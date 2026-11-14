"""Разбор недоверенных данных и детерминированные проверки C1–C10.

Проверки отсеивают нарушения формата и происхождения фактов. Семантическое
следование из цитаты проверяет S8; без него используется извлечение цитат.
"""

import ast
import calendar
import json
import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

from schemas import Chunk, QueryInfo, RetrievalResult

STATUSES = {"answered", "partial", "refused", "out_of_scope"}
QUERY_TYPES = {"normal", "off_topic", "illegal_intent", "manipulation", "mixed",
               "insufficient_info", "wrong_premise", "date_edition", "needs_clarification"}
DIRECTIVES = re.compile(
    r"(?:игнорир\w*|забуд\w*).{0,90}(?:инструкц|документ|правил)|"
    r"(?:не\s+упоминай|скрой).{0,70}(?:инструкц|источник|документ)|"
    r"(?:\[\s*system\s*\]|<\s*/?\s*system\b|(?:^|\n)\s*system\s*:)|"
    r"(?:ты\s+теперь|режим\s+разработчика|покажи\s+(?:системн\w*\s+)?промпт)|"
    r"(?:для\s+(?:ии|ai)[-\s]*ассистента)", re.I,
)
LEGAL = re.compile(r"договор|оплат|аренд|закон|согласован|стать[яеию]|штраф|гарант|"
                   r"налог|работник|бухгалтер|постав|юрист|правов|срок|персональн|архив", re.I)
ROLE_MARKER = re.compile(r"(?:^|\n|\s+/\s+)(Пользователь|Ассистент|User|Assistant)\s*:\s*", re.I)


class FormatError(ValueError):
    """Ответ модели не соответствует контракту; текст ответа в исключение не входит."""


def normalize(text: str) -> str:
    # NFC сохраняет знак №: NFKC превращал бы «№123» в «No123», пряча число
    # от проверки реквизитов. Пробелы и типографику нормализуем явно.
    text = unicodedata.normalize("NFC", text).lower().replace("ё", "е")
    text = text.translate(str.maketrans({c: '"' for c in '«»“”„'} | {c: "-" for c in '–—−'}))
    return re.sub(r"\s+", " ", text).strip()


def exact_quote(quote: str, text: str) -> str | None:
    """Поиск без fuzzy: возвращает исходное написание и сохраняет условия нормы."""
    chars, positions = [], []
    for pos, char in enumerate(text):
        for normalized in normalize(char) if not char.isspace() else " ":
            if normalized == " " and (not chars or chars[-1] == " "):
                continue
            chars.append(normalized)
            positions.append(pos)
    needle = normalize(quote)
    if not needle:
        return None
    haystack = "".join(chars)
    start = haystack.find(needle)
    while start >= 0:
        end = start + len(needle)
        inside_word = ((start > 0 and haystack[start-1].isalnum() and needle[0].isalnum()) or
                       (end < len(haystack) and haystack[end].isalnum() and needle[-1].isalnum()))
        lost_qualifier = re.search(r"\b(?:не(?:\s+(?:более|менее))?|ни|только|кроме|без)\s*$", haystack[:start])
        if not inside_word and not lost_qualifier:
            return text[positions[start]:positions[end - 1] + 1]
        start = haystack.find(needle, start + 1)
    return None


def parse_dialogue(text, max_chars: int = 60000) -> QueryInfo:
    if isinstance(text, str):
        original = text
        markers = list(ROLE_MARKER.finditer(text))
        history = []
        if markers:
            for i, marker in enumerate(markers):
                role = "user" if marker[1].lower() in ("пользователь", "user") else "assistant"
                end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
                history.append((role, text[marker.end():end].strip()))
        else:
            history = [("user", text.strip())]
    elif isinstance(text, (list, tuple)):
        history = []
        for item in text:
            if isinstance(item, dict):
                role, content = item.get("role"), item.get("content")
            elif isinstance(item, (tuple, list)) and len(item) == 2:
                role, content = item
            else:
                raise ValueError("История: ожидаются role/content или пары role, content")
            if role not in ("user", "assistant") or not isinstance(content, str):
                raise ValueError("В пользовательской истории допустимы только user и assistant")
            history.append((role, content.strip()))
        original = "\n".join(f"{'Пользователь' if r == 'user' else 'Ассистент'}: {c}" for r, c in history)
    else:
        raise TypeError("Нужен текст вопроса или структурированная история")
    users = [i for i, (role, _) in enumerate(history) if role == "user"]
    history = history[:users[-1] + 1] if users else []
    last_user = history[-1][1] if history else ""
    warnings = []
    # Сохраняем последнюю реплику, сокращая сначала старую историю.
    if len(original) > max_chars:
        warnings.append("input_truncated")
        remaining, kept = max_chars, []
        for role, content in reversed(history):
            if remaining <= 0:
                break
            part = content[:remaining]
            kept.append((role, part))
            remaining -= len(part)
        history = list(reversed(kept))
        last_user = history[-1][1] if history else ""
    detected = bool(DIRECTIVES.search(original))
    query_type = "mixed" if detected and LEGAL.search(last_user) else "normal"
    if not last_user or (detected and not LEGAL.search(last_user)):
        query_type = "off_topic"
    return QueryInfo(original, last_user, history, last_user, query_type=query_type,
                     injection={"detected": detected}, warnings=warnings)


def parse_json_object(text: str, max_chars: int = 100000) -> dict:
    """Без eval. Разрешён один JSON-объект, ограждения, преамбула и завершённый think."""
    if not isinstance(text, str) or len(text) > max_chars:
        raise FormatError("json_size_or_type")
    text = text.strip().lstrip("\ufeff")
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I).strip()
    if re.search(r"</?think>", text, re.I):
        raise FormatError("truncated_thinking")
    def unique_keys(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise FormatError("duplicate_json_key")
            out[k] = v
        return out
    def no_constant(_):
        raise FormatError("nonfinite_json_number")
    decoder = json.JSONDecoder(object_pairs_hook=unique_keys, parse_constant=no_constant)
    start = text.find("{")
    if start < 0:
        raise FormatError("json_object_missing")
    try:
        obj, end = decoder.raw_decode(text, start)
    except (ValueError, RecursionError) as exc:
        raise FormatError("invalid_or_truncated_json") from exc
    if not isinstance(obj, dict) or re.search(r"[\[{]", text[end:]):
        raise FormatError("multiple_json_values")
    return obj


def string_list(value, field_name: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 64 or any(not isinstance(v, str) or not v.strip() for v in value):
        raise FormatError(f"schema_{field_name}")
    return value


def parse_draft(raw: str) -> dict:
    draft = parse_json_object(raw)
    if draft.get("status") not in STATUSES or not isinstance(draft.get("answer"), str) or not draft["answer"].strip():
        raise FormatError("schema_status_answer")
    claims = draft.get("claims")
    if not isinstance(claims, list) or len(claims) > 40:
        raise FormatError("schema_claims")
    for claim in claims:
        if not isinstance(claim, dict) or any(not isinstance(claim.get(k), str) or not claim[k].strip()
                                               for k in ("text", "chunk", "quote")):
            raise FormatError("schema_claim")
        if claim.get("calculation") is not None and not isinstance(claim["calculation"], str):
            raise FormatError("schema_calculation_ref")
        for name in ("doc_id", "chunk_id", "locator", "doc_title"):
            if name in claim and not isinstance(claim[name], str):
                raise FormatError("schema_source_metadata")
    for name in ("missing", "assumptions"):
        draft[name] = string_list(draft.get(name, []), name)
    calc = draft.setdefault("calc", [])
    if not isinstance(calc, list) or len(calc) > 8:
        raise FormatError("schema_calc")
    for item in calc:
        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) for k in ("id", "expr", "result")):
            raise FormatError("schema_calc_item")
        inputs = item.get("inputs")
        if not isinstance(inputs, list) or not 1 <= len(inputs) <= 12:
            raise FormatError("schema_calc_inputs")
        for operand in inputs:
            if not isinstance(operand, dict) or any(not isinstance(operand.get(k), str) for k in ("value", "chunk", "quote")):
                raise FormatError("schema_calc_input")
    return draft


def parse_review(raw: str, n_claims: int) -> dict:
    review = parse_json_object(raw)
    if review.get("verdict") not in ("ok", "fix", "refuse"):
        raise FormatError("schema_review_verdict")
    checks = review.get("claims_check")
    if not isinstance(checks, list) or len(checks) != n_claims:
        raise FormatError("schema_review_coverage")
    indexes = []
    for item in checks:
        if not isinstance(item, dict) or type(item.get("claim_index")) is not int or item.get("support") not in ("full", "partial", "none"):
            raise FormatError("schema_review_claim")
        indexes.append(item["claim_index"])
    if sorted(indexes) != list(range(n_claims)):
        raise FormatError("schema_review_indexes")
    for name in ("fabricated", "unanswered_parts"):
        review[name] = string_list(review.get(name), name)
    for name in ("premise_issue", "edition_issue"):
        if not isinstance(review.get(name), str):
            raise FormatError("schema_review_issue")
    if review["verdict"] == "ok" and (any(c["support"] != "full" for c in checks) or any(
        review[k] for k in ("fabricated", "unanswered_parts", "premise_issue", "edition_issue")
    )):
        raise FormatError("contradictory_review")
    return review


@dataclass
class Context:
    labels: dict[str, Chunk] = field(default_factory=dict)
    quarantine: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def build_context(retrieval: RetrievalResult, max_chars: int = 24000) -> Context:
    context = Context(quarantine=list(retrieval.quarantine))
    seen, size = set(), 0
    for chunk in retrieval.chunks:
        if chunk.chunk_id in seen:
            raise ValueError("Повтор chunk_id в результатах R")
        seen.add(chunk.chunk_id)
        if not chunk.chunk_id or not chunk.doc_id or not chunk.doc_title or not chunk.locator:
            raise ValueError("R должен передать идентификатор, название и локатор каждого фрагмента")
        if chunk.quarantined or DIRECTIVES.search(chunk.doc_title + " " + chunk.locator):
            context.quarantine.append(chunk.text)
            continue
        clean = []
        for line in chunk.text.splitlines():
            # Строка с командами уходит целиком. Удаление частей нормативной фразы
            # могло бы убрать отрицание; R должен разделять смешанные строки.
            if DIRECTIVES.search(line):
                context.quarantine.append(line)
            else:
                clean.append(line)
        text = "\n".join(clean).strip()
        if not text:
            continue
        if size + len(text) + len(chunk.doc_title) + 150 > max_chars:
            context.warnings.append("context_truncated")
            continue
        size += len(text) + len(chunk.doc_title) + 150
        context.labels[f"Д{len(context.labels) + 1}"] = replace(chunk, text=text)
    if context.quarantine:
        context.warnings.append("injection_in_doc")
    return context


@dataclass(frozen=True)
class Mention:
    code: str
    text: str
    missing: str = ""


def required_mentions(qinfo: QueryInfo, retrieval: RetrievalResult, context: Context) -> list[Mention]:
    """Явные шаблоны из метаданных R. Ни один срок или реквизит не придумывается."""
    signals = dict(retrieval.signals)
    events = []
    for name, value in signals.items():
        if value and name not in ("edition_warnings",):
            events.append((name, value))
    for warning in list(signals.get("edition_warnings") or []) + retrieval.warnings:
        if isinstance(warning, dict):
            events.append((warning.get("code", ""), warning))
        elif isinstance(warning, str):
            code, _, detail = warning.partition(":")
            events.append((code, detail or True))
    if qinfo.as_of or qinfo.as_of_range or retrieval.as_of:
        lo, hi = qinfo.as_of_range or (qinfo.as_of or retrieval.as_of, qinfo.as_of or retrieval.as_of)
        for c in context.labels.values():
            if not qinfo.compare_editions and ((c.valid_from and lo and lo < c.valid_from) or
                                               (c.valid_to and hi and hi > c.valid_to)):
                events.append(("applicability_unconfirmed", c.doc_id))
    output = []
    def detail(value):
        if isinstance(value, dict):
            parts = [str(value[k]) for k in ("doc_id", "reference", "before", "after", "date") if value.get(k)]
            value = "; ".join(parts)
        if isinstance(value, (list, tuple)):
            value = "; ".join(detail(v) for v in value)
        if value is True or not value:
            return "указанного документа"
        result = str(value)
        for c in context.labels.values():
            result = re.sub(rf"(?<!\w){re.escape(c.doc_id)}(?!\w)", lambda _: c.doc_title, result)
        if DIRECTIVES.search(result):
            return "указанного документа"
        return re.sub(r"[<>\r\n]", " ", result)[:500]
    templates = {
        "older_edition_missing": "В базе нет прежней редакции: {d}. Вывод по отсутствующей редакции сделать нельзя.",
        "future_edition_missing": "В базе нет будущей редакции: {d}. Её содержание не подтверждено.",
        "edition_missing": "В базе нет нужной редакции: {d}. Вывод по ней сделать нельзя.",
        "entity_unknown": "Указанная организация или договор отсутствует в базе: {d}. Подмена похожим контрагентом недопустима.",
        "explicit_ref_missing": "В базе нет указанной нормы: {d}. Для полного вывода нужен её текст.",
        "text_missing": "В базе отсутствует текст положения: {d}. Его содержание установить нельзя.",
        "doc_expired": "Срок действия документа истёк: {d}. Сведений о продлении в базе нет.",
        "doc_not_yet_effective": "Документ ещё не действовал на дату события: {d}. Его применение к этой дате не подтверждено.",
        "renewal_unconfirmed": "Продление договора не подтверждено: {d}. Нужны сведения об уведомлении о прекращении и выполнении условий продления.",
        "ambiguous_boundary": "Дата события неточна и затрагивает границу редакций: {d}. Применимость следует проверить по обеим редакциям.",
        "applicability_unconfirmed": "Применимость приведённого фрагмента к дате события не подтверждена: {d}.",
    }
    seen = set()
    for code, value in events:
        if code in templates:
            d = detail(value)
            text = templates[code].format(d=d)
            if text not in seen:
                output.append(Mention(code, text, text))
                seen.add(text)
        elif code == "as_of_assumed_current" and (qinfo.date_matters or signals.get("date_matters") or
                                                  any(c.edition or c.changed_on for c in context.labels.values())):
            text = "Дата события не указана. Вывод дан по текущей редакции."
            if text not in seen:
                output.append(Mention(code, text))
                seen.add(text)
        elif code == "ambiguous":
            text = "Неоднозначность: требуется учитывать каждого кандидата: " + detail(value) + "."
            if text not in seen:
                output.append(Mention(code, text))
                seen.add(text)
    return output


# Небольшой словарь числительных — это проверка написаний, а не морфология R.
NUMBER_WORDS = {}
for forms, value in [
    ("ноль нуля", 0), ("один одна одно одного одной одному", 1),
    ("два две двух двум", 2), ("три трех трем трёх", 3), ("четыре четырех четырёх", 4),
    ("пять пяти", 5), ("шесть шести", 6), ("семь семи", 7), ("восемь восьми", 8),
    ("девять девяти", 9), ("десять десяти", 10), ("одиннадцать одиннадцати", 11),
    ("двенадцать двенадцати", 12), ("тринадцать тринадцати", 13), ("четырнадцать четырнадцати", 14),
    ("пятнадцать пятнадцати", 15), ("шестнадцать шестнадцати", 16), ("семнадцать семнадцати", 17),
    ("восемнадцать восемнадцати", 18), ("девятнадцать девятнадцати", 19),
    ("двадцать двадцати", 20), ("тридцать тридцати", 30), ("сорок сорока", 40),
    ("пятьдесят пятидесяти", 50), ("шестьдесят шестидесяти", 60), ("семьдесят семидесяти", 70),
    ("восемьдесят восьмидесяти", 80), ("девяносто девяноста", 90), ("сто ста", 100),
    ("двести двухсот", 200), ("триста трехсот", 300), ("четыреста четырехсот", 400),
    ("пятьсот пятисот", 500), ("шестьсот шестисот", 600), ("семьсот семисот", 700),
    ("восемьсот восьмисот", 800), ("девятьсот девятисот", 900),
]:
    for form in forms.split():
        NUMBER_WORDS[normalize(form)] = value
SCALES = {"тысяч": 1000, "тысяча": 1000, "тысячи": 1000, "тысячу": 1000, "тыс": 1000,
          "миллион": 1000000, "миллиона": 1000000, "миллионов": 1000000, "млн": 1000000,
          "миллиард": 1000000000, "миллиарда": 1000000000, "миллиардов": 1000000000, "млрд": 1000000000}
NUMERIC_TOKEN = r"\d+(?: \d{3})*(?:[.,]\d+)?"
WORD_TOKEN = "(?:" + "|".join(sorted(NUMBER_WORDS.keys() | SCALES.keys(), key=len, reverse=True)) + ")"
NUMBER_RUN = re.compile(rf"(?<![\w])(?:{NUMERIC_TOKEN}|{WORD_TOKEN})(?:\s+{WORD_TOKEN})*(?![\w])")
MONTHS = {m: n for n, m in enumerate(("январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр"), 1)}


def number_value(raw: str) -> Decimal:
    tokens = raw.replace(",", ".").split()
    # Цифры с группировкой тысяч не являются суммой отдельных токенов.
    raw_number = re.match(NUMERIC_TOKEN, raw)
    if raw_number:
        current = Decimal(raw_number[0].replace(" ", "").replace(",", "."))
        tokens = raw[len(raw_number[0]):].split()
    else:
        current = Decimal(0)
    total = Decimal(0)
    for token in tokens:
        if token in SCALES:
            total += (current or 1) * SCALES[token]
            current = Decimal(0)
        else:
            current += NUMBER_WORDS[token]
    return total + current


def numeric_facts(text: str) -> set[tuple[str, str]]:
    text = normalize(text)
    facts = set()
    # Даты — отдельные факты: случайное совпадение дня и года недостаточно.
    def keep_date(match):
        raw = match[0]
        try:
            if "." in raw:
                d, m, y = map(int, raw.split("."))
                value = date(y, m, d).isoformat()
            else:
                value = date.fromisoformat(raw).isoformat()
            facts.add((value, "date"))
        except ValueError:
            facts.add((raw, "invalid_date"))
        return " " * len(raw)
    text = re.sub(r"\b(?:\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2})\b", keep_date, text)
    month_names = {name: n for n, name in enumerate(("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"), 1)}
    def keep_verbal_date(match):
        try:
            value = date(int(match[3]), month_names[match[2]], int(match[1])).isoformat()
            facts.add((value, "date"))
        except ValueError:
            facts.add((match[0], "invalid_date"))
        return " " * len(match[0])
    text = re.sub(r"\b(\d{1,2})\s+(" + "|".join(month_names) + r")\s+(\d{4})(?:\s*г\.?)?\b", keep_verbal_date, text)
    # Повтор числительного в скобках не меняет единицу следующего числа.
    text = re.sub(r"\(([^()]*)\)", lambda m: " " if re.fullmatch(
        rf"(?:{NUMERIC_TOKEN}|{WORD_TOKEN})(?:\s+{WORD_TOKEN})*", m[1].strip()) else m[0], text)
    for match in NUMBER_RUN.finditer(text):
        try:
            value = number_value(match[0])
        except (KeyError, InvalidOperation):
            continue
        tail = text[match.end():].lstrip()
        unit = "number"
        for pattern, name in [
            (r"^%|^процент", "%"), (r"^(?:₽|руб|р\.)", "rub"),
            (r"^календарн\w*\s+д", "calendar_day"), (r"^рабоч\w*\s+д", "work_day"),
            (r"^месяц", "month"), (r"^недел", "week"), (r"^час", "hour"),
            (r"^лет|^год", "year"), (r"^дн|^день", "day"), (r"^-го\s+числа|^числа", "day_of_month"),
            (r"^кв\.?\s*м", "sqm"),
        ]:
            if re.search(pattern, tail):
                unit = name
                break
        facts.add((str(value.normalize()), unit))
    return facts


REF_PATTERN = re.compile(r"\b(п\.|ст\.|ч\.|абз\.)\s*(\d+(?:\.\d+)*)", re.I)
CONTRACT_PATTERN = re.compile(r"\b[А-ЯA-Z]{1,3}[-–]\d{1,4}/\d{4}\b", re.I)
LAW_PATTERN = re.compile(r"\b(?:ТК|НК|ГК|УК|КоАП|СК)\s+РФ\b|\b\d+[-–]ФЗ\b", re.I)


def without_source_refs(text: str, chunk: Chunk) -> str:
    # Удаляем только проверенные ссылки; произвольные числа остаются под C3.
    text = text.replace(chunk.doc_title, "")
    text = REF_PATTERN.sub("", text)
    text = CONTRACT_PATTERN.sub("", text)
    return text


def unsupported_numbers(text: str, quote: str, *, extra=()) -> set[tuple[str, str]]:
    available = numeric_facts(quote) | set(extra)
    result = set()
    for value, unit in numeric_facts(text):
        if (value, unit) not in available:
            # Число без единицы допустимо, если в цитате оно имеет явную единицу.
            if unit != "number" or not any(v == value for v, _ in available):
                result.add((value, unit))
    return result


def names_unsupported(text: str, quote: str, chunk: Chunk) -> bool:
    evidence = normalize(quote + " " + chunk.doc_title)
    for pattern in (r'(?:ООО|АО|ПАО|ОАО|ЗАО)\s*[«"“][^»"”]+[»"”]',
                    r'«[А-ЯЁ][^»\n]{0,80}»',
                    r"\b[А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё]*(?:вич|вна|чна)[а-яё]*\b",
                    r"\bИНН\s*\d{10,12}\b", r"\b(?:ул\.|улица|г\.|город|наб\.)\s+[А-ЯЁ][\w-]+"):
        for match in re.finditer(pattern, text):
            if normalize(match[0]) not in evidence:
                return True
    for root in (r"генеральн\w*\s+директор", r"финансов\w*\s+директор",
                 r"главн\w*\s+бухгалтер", r"юридическ\w*\s+отдел"):
        if re.search(root, normalize(text)) and not re.search(root, evidence):
            return True
    return False


def safe_arithmetic(expression: str) -> tuple[Decimal, list[Decimal]]:
    """Только ограниченное дерево чисел и +-*/(); без eval, имён и вызовов."""
    if not isinstance(expression, str) or len(expression) > 200 or not re.fullmatch(r"[0-9. +*/()\-]+", expression):
        raise ValueError("Недопустимое выражение")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("Недопустимое выражение") from exc
    if len(list(ast.walk(tree))) > 60:
        raise ValueError("Слишком сложное выражение")
    operands = []
    def walk(node, depth=0):
        if depth > 20:
            raise ValueError("Слишком глубокое выражение")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = Decimal(ast.get_source_segment(expression, node))
            operands.append(value)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = walk(node.operand, depth+1) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = walk(node.left, depth+1), walk(node.right, depth+1)
            if isinstance(node.op, ast.Add): value = a + b
            elif isinstance(node.op, ast.Sub): value = a - b
            elif isinstance(node.op, ast.Mult): value = a * b
            else:
                if not b: raise ValueError("Деление на ноль")
                value = a / b
        else:
            raise ValueError("Недопустимая операция")
        if not value.is_finite() or abs(value) > Decimal("1e15"):
            raise ValueError("Результат вне допустимого диапазона")
        return value
    with localcontext() as ctx:
        ctx.prec = 28
        return walk(tree.body), operands


def validate_calculations(calc, context: Context):
    valid, problems = {}, []
    for index, item in enumerate(calc):
        try:
            if not item["id"] or item["id"] in valid:
                raise ValueError("duplicate_id")
            proven = set()
            for operand in item["inputs"]:
                chunk = context.labels.get(operand["chunk"])
                if chunk is None or exact_quote(operand["quote"], chunk.text) is None:
                    raise ValueError("unproven_input_quote")
                value = Decimal(operand["value"])
                facts = numeric_facts(operand["quote"])
                possible = {Decimal(v) for v, u in facts if u not in ("date", "invalid_date")}
                possible.update(Decimal(v)/100 for v, u in facts if u == "%")
                if not value.is_finite() or value not in possible:
                    raise ValueError("unproven_input_value")
                proven.add(value)
            result, leaves = safe_arithmetic(item["expr"])
            if any(v not in proven for v in leaves) or result != Decimal(item["result"]):
                raise ValueError("unproven_operand_or_wrong_result")
            valid[item["id"]] = result
        except (ValueError, InvalidOperation, KeyError) as exc:
            problems.append(f"calc[{index}]: {type(exc).__name__}")
    return valid, problems


@dataclass
class Check:
    code: str
    passed: bool
    reasons: list[str] = field(default_factory=list)
    claim_indexes: list[int] = field(default_factory=list)


@dataclass
class ValidationReport:
    checks: list[Check]
    verified: list[int]
    quotes: dict[int, str]
    calculations: dict[str, Decimal]

    @property
    def ok(self):
        return all(c.passed for c in self.checks)

    def issues(self):
        return [{"code": c.code, "reasons": c.reasons, "claim_indexes": c.claim_indexes}
                for c in self.checks if not c.passed]


def validate_answer(draft: dict, qinfo: QueryInfo, context: Context, mentions=(), *, hard_limit=9500) -> ValidationReport:
    failures = {f"C{i}": [] for i in range(1, 11)}
    bad = {f"C{i}": [] for i in range(1, 11)}
    valid_quotes, verified = {}, []
    calculations, calc_errors = validate_calculations(draft["calc"], context)
    failures["C9"].extend(calc_errors)
    def fail(code, reason, index=None):
        failures[code].append(reason)
        if index is not None:
            bad[code].append(index)
    for i, claim in enumerate(draft["claims"]):
        chunk = context.labels.get(claim["chunk"])
        if chunk is None:
            fail("C2", "unknown_source", i)
            continue
        source = chunk.doc_title + " " + chunk.locator + " " + claim["quote"]
        for key in ("doc_id", "chunk_id", "locator", "doc_title"):
            if key in claim and normalize(claim[key]) != normalize(getattr(chunk, key)):
                fail("C2", "source_metadata_mismatch:" + key, i)
        allowed_refs = {(normalize(m[1]), m[2]) for m in REF_PATTERN.finditer(source)}
        if any((normalize(m[1]), m[2]) not in allowed_refs for m in REF_PATTERN.finditer(claim["text"])):
            fail("C2", "unknown_locator_in_claim", i)
        if any(normalize(m[0]) not in normalize(source) for m in CONTRACT_PATTERN.finditer(claim["text"])):
            fail("C2", "wrong_contract_in_claim", i)
        if any(normalize(m[0]) not in normalize(source) for m in LAW_PATTERN.finditer(claim["text"])):
            fail("C2", "wrong_law_in_claim", i)
        quote = exact_quote(claim["quote"], chunk.text)
        if quote is None:
            fail("C1", "quote_not_in_designated_chunk", i)
        else:
            valid_quotes[i] = quote
        calc_id = claim.get("calculation")
        extra = []
        if calc_id:
            if calc_id not in calculations:
                fail("C9", "unknown_or_invalid_calculation", i)
            else:
                value = str(calculations[calc_id].normalize())
                extra = [(value, unit) for unit in ("number", "rub")]
        if unsupported_numbers(without_source_refs(claim["text"], chunk), claim["quote"], extra=extra):
            fail("C3", "number_date_or_unit_not_supported_by_this_quote", i)
        if names_unsupported(claim["text"], claim["quote"], chunk):
            fail("C4", "name_details_or_position_not_in_this_source", i)
        if DIRECTIVES.search(claim["text"]):
            fail("C5", "directive_in_output", i)
        q_facts = set().union(*(numeric_facts(q) for q in context.quarantine)) if context.quarantine else set()
        source_facts = numeric_facts(claim["quote"])
        if (numeric_facts(claim["text"]) & q_facts) - source_facts - set(extra):
            fail("C5", "quarantine_only_number_or_unit", i)
        if not any(i in bad[c] for c in bad):
            verified.append(i)
    status, claims = draft["status"], draft["claims"]
    if status in ("answered", "partial") and not verified:
        fail("C6", "substantive_status_without_verified_claim")
    if status == "answered" and draft["missing"]:
        fail("C6", "answered_with_missing")
    if status == "partial" and not draft["missing"]:
        fail("C6", "partial_without_missing")
    if status in ("refused", "out_of_scope") and claims:
        fail("C6", "refusal_with_legal_claims")
    # Свободный answer не должен содержать дополнительные утверждения.
    remainder = draft["answer"]
    for mention in mentions:
        remainder = remainder.replace(mention.text, "")
    for claim in sorted(claims, key=lambda c: len(c["text"]), reverse=True):
        remainder = remainder.replace(claim["text"], "")
    if claims and re.search(r"[\w]", remainder):
        fail("C6", "unmapped_text_in_answer")
    for mention in mentions:
        if normalize(mention.text) not in normalize(draft["answer"]):
            fail("C7", "required_mention_missing:" + mention.code)
    if not draft["answer"].strip() or len(draft["answer"]) > hard_limit or re.search(
        r"`|\*\*|^\s*(?:#{1,6}\s|[-*>]\s|\|)|\n\s*\n\s*\n|\"(?:claims|status)\"\s*:|\[[^\]]+\]\(", draft["answer"], re.M
    ):
        fail("C8", "length_or_markup")
    if re.search(r"[а-яё]", qinfo.last_user, re.I):
        cyrillic = len(re.findall(r"[а-яё]", draft["answer"], re.I))
        latin = len(re.findall(r"[a-z]", draft["answer"], re.I))
        if cyrillic < 3 or cyrillic < latin:
            fail("C10", "russian_answer_required")
    if DIRECTIVES.search(draft["answer"]):
        fail("C5", "directive_in_answer")
    return ValidationReport([Check(c, not reasons, reasons, sorted(set(bad[c])))
                             for c, reasons in failures.items()], verified, valid_quotes, calculations)


def validated_dates(hints, original: str) -> list[dict]:
    """Проверяет подсказки S1/R, не заменяя извлечение и выбор редакций R."""
    if not isinstance(hints, list):
        raise FormatError("schema_dates")
    output = []
    for hint in hints:
        if not isinstance(hint, dict) or hint.get("role") not in ("event", "signing", "delivery", "spec", "other"):
            raise FormatError("schema_date_role")
        evidence = hint.get("text")
        if not isinstance(evidence, str) or normalize(evidence) not in normalize(original) or not evidence.strip():
            raise FormatError("date_without_input_evidence")
        try:
            lo, hi = date.fromisoformat(hint["iso_from"]), date.fromisoformat(hint["iso_to"])
        except (ValueError, KeyError, TypeError) as exc:
            raise FormatError("invalid_iso_date") from exc
        if lo > hi:
            raise FormatError("reversed_date_range")
        ev = normalize(evidence)
        exact = re.findall(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\.\d{1,2}\.\d{4}\b", ev)
        if exact:
            try:
                parsed = [date.fromisoformat(raw) if "-" in raw else date(*reversed(list(map(int, raw.split("."))))) for raw in exact]
            except ValueError as exc:
                raise FormatError("invalid_input_date") from exc
            if len(parsed) > 2 or lo != parsed[0] or hi != parsed[-1]:
                raise FormatError("date_precision_or_value_changed")
        else:
            years = re.findall(r"\b(?:19|20)\d{2}\b", ev)
            if not years or lo.year != int(years[0]) or hi.year != int(years[-1]):
                raise FormatError("date_year_invented")
            month_tokens = []
            for root, n in MONTHS.items():
                pattern = r"\bма[йяею]\b" if n == 5 else rf"\b{root}[а-я]*\b"
                month_tokens.extend((m.start(), n) for m in re.finditer(pattern, ev))
            months = [n for _, n in sorted(month_tokens)]
            month = months[0] if months else None
            day_number = re.match(r"\s*(\d{1,2})\s+[а-я]", ev)
            if month and day_number:
                if lo != hi or (lo.day, lo.month) != (int(day_number[1]), month):
                    raise FormatError("input_day_changed")
            elif month:
                last_month = months[-1]
                if (lo.month, hi.month, lo.day, hi.day) != (month, last_month, 1, calendar.monthrange(hi.year, last_month)[1]):
                    raise FormatError("month_precision_invented")
            elif (lo.month, lo.day, hi.month, hi.day) != (1, 1, 12, 31):
                raise FormatError("year_precision_invented")
        output.append(dict(hint))
    return output
