"""Роль L: S0/S1 → интерфейс R → S6/S7/S8/S9/S10. Сеть реализует B."""

import json
import math
import re
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field

from config import LConfig, load_config
from guard import (CONTRACT_PATTERN, FormatError, build_context, normalize, numeric_facts,
                   parse_dialogue, parse_draft, parse_json_object, parse_review,
                   required_mentions, string_list, validate_answer, validated_dates,
                   QUERY_TYPES)
from prompts import (EXTRACTIVE_NOTE, ILLEGAL_INTENT, NO_EVIDENCE, OUT_OF_SCOPE,
                     PROMPT_VERSION, TECHNICAL_FAILURE, answer_messages,
                     query_messages, review_messages)
from schemas import AnswerResult, ConfigurationError, LLMClient, LLMResult, QueryInfo, RetrievalResult


class BudgetExceeded(TimeoutError):
    """Остатка общего бюджета недостаточно для нового этапа."""


class ModelFailure(RuntimeError):
    """Техническая ошибка клиента; исходный текст исключения не раскрывается."""


class Calls:
    def __init__(self, client, config, deadline=None, *, previous=0, inherited_deadline=None):
        now = time.monotonic()
        self.client, self.config, self.count = client, config, previous
        self.deadline = now + config.q_budget_sec
        for bound in (deadline, inherited_deadline):
            if bound is not None:
                if type(bound) not in (int, float) or not math.isfinite(bound):
                    raise ConfigurationError("deadline — конечное абсолютное значение time.monotonic()")
                self.deadline = min(self.deadline, bound)
        self.stages = []

    def remaining(self):
        return max(0.0, self.deadline - time.monotonic())

    def available(self, minimum=0.0):
        return self.count < self.config.max_llm_calls and self.remaining() > minimum

    def call(self, stage, messages, *, tokens=None):
        if self.client is None or not callable(getattr(self.client, "chat", None)):
            raise ConfigurationError("Передайте client= с методом chat клиента B. Тестовый клиент включается только явно.")
        if not self.available():
            raise BudgetExceeded("llm_budget_exhausted")
        timeout = min(self.config.llm_timeout, self.remaining())
        self.count += 1
        self.stages.append(stage)
        try:
            result = self.client.chat(messages, json_mode=True, temperature=0.0 if stage in ("S1", "S8") else self.config.temperature,
                                      max_tokens=tokens or self.config.max_tokens, timeout=timeout)
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ModelFailure(type(exc).__name__) from None
        if not self.remaining():
            raise BudgetExceeded("deadline_exhausted_during_call")
        if not isinstance(result, LLMResult) or not isinstance(result.text, str):
            raise ModelFailure("invalid_client_result")
        return result


def prepare_query(text, *, client: LLMClient | None = None, config: LConfig | None = None,
                  deadline: float | None = None, entity_detector=None, date_extractor=None) -> QueryInfo:
    """S0/S1. Сбой S1 сохраняет last_user; функции извлечения R внедряются явно."""
    cfg = config or load_config()
    q = parse_dialogue(text, cfg.max_input_chars)
    calls = Calls(client, cfg, deadline)
    user_context = "\n".join(content for role, content in q.history if role == "user")
    date_hints = []
    if q.query_type != "off_topic" and client is not None:
        try:
            result = calls.call("S1", query_messages(q))
            if result.finish_reason in ("length", "content_filter"):
                raise FormatError("incomplete_s1")
            data = parse_json_object(result.text)
            rewritten = data.get("last_question")
            if not isinstance(rewritten, str) or not rewritten.strip() or len(rewritten) > cfg.max_input_chars:
                raise FormatError("schema_last_question")
            if data.get("query_type") not in QUERY_TYPES:
                raise FormatError("schema_query_type")
            for name in ("date_matters", "compare_editions"):
                if type(data.get(name)) is not bool:
                    raise FormatError("schema_" + name)
            input_values = {v for v, _ in numeric_facts(q.original)}
            if any(v not in input_values for v, _ in numeric_facts(rewritten)):
                raise FormatError("rewrite_invented_number")
            for company in re.findall(r'(?:ООО|АО|ПАО)\s*[«"“][^»"”]+[»"”]', rewritten):
                if normalize(company) not in normalize(q.original):
                    raise FormatError("rewrite_invented_entity")
            # Явное последнее уточнение нельзя заменить старым кандидатом из
            # истории. Это ограничение переписывания, не роутинг документов R.
            latest_refs = [m[0] for m in CONTRACT_PATTERN.finditer(q.last_user)]
            latest_refs += re.findall(r'«[А-ЯЁ][^»\n]{0,80}»|\b[А-ЯЁ][а-яё]+(?:-[А-ЯЁа-яё]+)+', q.last_user)
            for reference in latest_refs:
                if normalize(reference).strip('"') not in normalize(rewritten):
                    raise FormatError("rewrite_dropped_latest_entity")
            date_hints = validated_dates(data.get("dates", []), user_context)
            subquestions = string_list(data.get("subquestions", []), "subquestions")
            injection = data.get("injection", {})
            if not isinstance(injection, dict):
                raise FormatError("schema_injection")
            q.rewritten = rewritten.strip()
            q.query_type = data["query_type"]
            q.date_matters, q.compare_editions = data["date_matters"], data["compare_editions"]
            q.subquestions = subquestions
            q.injection = {"detected": bool(q.injection.get("detected") or injection.get("detected"))}
            # Идентификаторы документов назначает R. Подсказки S1 без R не становятся doc_id.
        except (FormatError, ModelFailure, BudgetExceeded) as exc:
            q.warnings.append("s1_fallback:" + type(exc).__name__)
    elif q.query_type != "off_topic":
        q.warnings.append("s1_skipped:no_client")
    if entity_detector is not None:
        try:
            entities = entity_detector(q.rewritten)
            if not isinstance(entities, dict):
                raise ValueError
            q.entities = entities
        except Exception:
            q.warnings.append("entity_detector_failed")
    if date_extractor is not None:
        try:
            date_hints = validated_dates(date_extractor(user_context), user_context)
        except Exception:
            q.warnings.append("date_extractor_failed")
    q.dates = date_hints
    preferred_role = "signing" if re.search(r"одобр|согласован", q.rewritten, re.I) else "event"
    preferred = [d for d in date_hints if d["role"] == preferred_role]
    if not preferred:
        preferred = [d for d in date_hints if d["role"] == "event"]
    if not preferred and len(date_hints) == 1 and date_hints[0]["role"] != "other":
        preferred = date_hints
    if len(preferred) == 1:
        d = preferred[0]
        if d["iso_from"] == d["iso_to"]:
            q.as_of = d["iso_from"]
        else:
            q.as_of_range = (d["iso_from"], d["iso_to"])
    q.debug.update(llm_calls=calls.count, stages=calls.stages, operation_deadline=calls.deadline,
                   prompt_version=PROMPT_VERSION)
    return q


def decide(model_status, verified_claims, signals, s8=None, *, missing=(), query_type="normal"):
    """Политика статуса. Непроверенные утверждения сюда передавать нельзя."""
    if query_type in ("off_topic", "manipulation"):
        return "out_of_scope"
    if query_type == "illegal_intent" or signals.get("entity_unknown"):
        return "refused"
    if not verified_claims:
        return "refused"
    if missing or model_status in ("partial", "refused", "out_of_scope") or (s8 and s8.get("verdict") != "ok"):
        return "partial"
    return "answered"


def to_api_response(result: AnswerResult) -> dict:
    """Адаптер к существующему openapi.yaml; бизнес-статус result не изменяется.

    В HTTP-контракте пока нет partial: передаём answered и непустой missing_info.
    Изменение самого HTTP-контракта остаётся у B/F по командному плану.
    """
    allowed_types = {"normal", "insufficient_info", "wrong_premise", "date_edition",
                     "illegal_intent", "manipulation", "off_topic", "needs_clarification"}
    return {
        "answer": result.text,
        "status": "answered" if result.status == "partial" else result.status,
        "query_type": result.query_type if result.query_type in allowed_types else "manipulation" if result.query_type == "mixed" else "normal",
        "citations": [{"id": i, "doc_id": c["doc_id"], "fragment_id": c["chunk_id"],
                       "doc_title": c["doc_title"], "locator": c["locator"], "quote": c["quote"]}
                      for i, c in enumerate(result.claims, 1)],
        "missing_info": list(result.missing),
        "latency_ms": round(result.debug.get("elapsed_sec", 0) * 1000),
    }


def _canonical_claim(claim, chunk, *, text, quote):
    return {"text": text, "doc_id": chunk.doc_id, "chunk_id": chunk.chunk_id,
            "doc_title": chunk.doc_title, "locator": chunk.locator, "quote": quote}


def _reference(chunk):
    title = chunk.doc_title
    if chunk.edition and normalize(chunk.edition) not in normalize(title):
        title += " (" + chunk.edition + ")"
    return title + ", " + chunk.locator


def _render(claims, context, *, extractive=False):
    by_id = {c.chunk_id: c for c in context.labels.values()}
    lines = []
    for claim in claims:
        text = f'«{claim["quote"]}»' if extractive else claim["text"].rstrip(" .")
        lines.append(text + " (" + _reference(by_id[claim["chunk_id"]]) + ").")
    return "\n\n".join(lines)


def _pack(text, claims, context, notes, limit, *, extractive=False):
    """Убирает целые утверждения; никогда не обрезает цитату или оговорку посередине."""
    notes = list(dict.fromkeys(n for n in notes if n))
    suffix = "\n\n".join(notes)
    kept = list(claims)
    while kept:
        body = _render(kept, context, extractive=extractive)
        limited_note = "Часть подтверждений не поместилась в лимит ответа." if len(kept) != len(claims) else ""
        candidate = "\n\n".join(p for p in (body, suffix, limited_note) if p)
        if len(candidate) <= limit:
            return candidate, kept, len(kept) != len(claims)
        kept.pop()
    suffix = "\n\n".join(n for n in notes if n != EXTRACTIVE_NOTE)
    candidate = "\n\n".join(p for p in (text, suffix) if p)
    if len(candidate) <= limit:
        return candidate, [], bool(claims)
    # У очень большого набора сигналов нельзя молча терять нужные оговорки.
    return "Не удалось вместить подтверждённый ответ и обязательные оговорки в допустимый объём.", [], True


def answer(qinfo: QueryInfo, retrieval: RetrievalResult, deadline: float | None = None, *,
           client: LLMClient | None = None, config: LConfig | None = None) -> AnswerResult:
    """deadline — абсолютный time.monotonic(), общий с prepare_query и pipeline B."""
    cfg = config or load_config()
    started = time.monotonic()
    calls = Calls(client, cfg, deadline, previous=qinfo.debug.get("llm_calls", 0),
                  inherited_deadline=qinfo.debug.get("operation_deadline"))
    context = build_context(retrieval, cfg.max_context_chars)
    mentions = required_mentions(qinfo, retrieval, context)
    warnings = list(dict.fromkeys(qinfo.warnings + retrieval.warnings + context.warnings))
    debug = {"prompt_version": PROMPT_VERSION, "repairs": 0, "json_retries": 0,
             "safe_mode": False, "checks": [], "violations": [], "s8": "not_run",
             "label_map": {k: v.chunk_id for k, v in context.labels.items()}}
    mandatory_missing = [m.missing for m in mentions if m.missing]

    def finish(text, status, claims=None, missing=None):
        debug.update(llm_calls=calls.count, stages=qinfo.debug.get("stages", []) + calls.stages,
                     elapsed_sec=round(time.monotonic() - started, 4))
        return AnswerResult(text, status, qinfo.query_type, claims or [], list(dict.fromkeys(missing or [])),
                            list(dict.fromkeys(warnings)), debug)

    if qinfo.query_type in ("off_topic", "manipulation"):
        return finish(OUT_OF_SCOPE, "out_of_scope")
    if qinfo.query_type == "illegal_intent":
        return finish(ILLEGAL_INTENT, "refused", missing=["Законная постановка вопроса"])
    if retrieval.signals.get("entity_unknown"):
        text = "\n\n".join(m.text for m in mentions if m.code == "entity_unknown")
        text, _, _ = _pack(text or NO_EVIDENCE, [], context, [], cfg.answer_hard_limit)
        return finish(text, "refused", missing=mandatory_missing or ["Документы по указанной сущности"])
    if not context.labels:
        notes = [m.text for m in mentions]
        text, _, _ = _pack(NO_EVIDENCE, [], context, notes, cfg.answer_hard_limit)
        return finish(text, "refused", missing=mandatory_missing or ["Релевантные положения документов"])
    # Нет неявной подмены настоящей LLM тестовым клиентом.
    if client is None:
        raise ConfigurationError("Для генерации передайте client= с методом chat клиента B; для offline-примера используйте examples.offline_demo")

    draft, report, review = None, None, None
    technical = None
    try:
        messages = answer_messages(qinfo, context, mentions, cfg.answer_hard_limit)
        for attempt in range(cfg.json_retries + 1):
            result = calls.call("S6", messages, tokens=min(cfg.max_tokens_ceiling, cfg.max_tokens * (attempt + 1)))
            try:
                if result.finish_reason in ("length", "content_filter"):
                    raise FormatError("generation_" + result.finish_reason)
                draft = parse_draft(result.text)
                break
            except FormatError as exc:
                warnings.append("invalid_model_json")
                debug["parse_error"] = str(exc)
                if attempt == cfg.json_retries:
                    raise
                debug["json_retries"] += 1
                messages = answer_messages(qinfo, context, mentions, cfg.answer_hard_limit,
                                           issues=[{"code": "FORMAT", "reason": str(exc), "instruction": "Верни полный JSON по схеме"}])
        for repair_round in range(cfg.max_repairs + 1):
            report = validate_answer(draft, qinfo, context, mentions, hard_limit=cfg.answer_hard_limit)
            debug["checks"] = [asdict(c) for c in report.checks]
            issues = report.issues()
            debug["violations"].extend(c["code"] for c in issues)
            # Оговорки C7 добавляются кодом при финализации. Не тратим S9 только
            # ради отсутствующего шаблона, если остальной ответ подтверждён.
            issues = [issue for issue in issues if issue["code"] != "C7"]
            if any(i["code"] == "C5" for i in issues):
                debug["injection_leak"] = True
            # S8 не может ослабить программные проверки. При C1–C6/C9 нет смысла
            # тратить вызов на оценку заведомо испорченного кандидата.
            structural_ok = not any(i["code"] in ("C1", "C2", "C3", "C4", "C5", "C6", "C9") for i in issues)
            review = None
            if cfg.s8_enabled and structural_ok and draft["claims"] and calls.available(cfg.s8_min_remaining_sec):
                result = calls.call("S8", review_messages(qinfo, context, draft, mentions))
                if result.finish_reason in ("length", "content_filter"):
                    raise FormatError("incomplete_review")
                review = parse_review(result.text, len(draft["claims"]))
                debug["s8"] = review["verdict"]
                if review["verdict"] != "ok":
                    issues.append({"code": "S8", "details": review})
            elif not cfg.s8_enabled:
                debug["s8"] = "disabled"
            else:
                debug["s8"] = "skipped_budget_or_invalid_draft"
            if not issues or repair_round == cfg.max_repairs or not calls.available():
                break
            debug["repairs"] += 1
            result = calls.call("S9", answer_messages(qinfo, context, mentions, cfg.answer_hard_limit,
                                                      draft=draft, issues=issues))
            if result.finish_reason in ("length", "content_filter"):
                raise FormatError("incomplete_repair")
            # После неудачного исправления остаётся последний проверенный snapshot.
            repaired = parse_draft(result.text)
            draft, report, review = repaired, None, None
    except (ModelFailure, BudgetExceeded, FormatError) as exc:
        technical = type(exc).__name__
        warnings.append("technical_failure:" + technical)
        debug["technical_failure"] = technical

    # Нельзя использовать старую оценку S8 для исправленного ответа.
    if draft is not None and report is None:
        report = validate_answer(draft, qinfo, context, mentions, hard_limit=cfg.answer_hard_limit)
        debug["checks"] = [asdict(c) for c in report.checks]
    if draft is None or report is None:
        debug["safe_mode"] = True
        text, _, _ = _pack(TECHNICAL_FAILURE, [], context, [m.text for m in mentions], cfg.answer_hard_limit)
        return finish(text, "refused", missing=mandatory_missing)

    # При полном отказе модель не может спрятать нормы в answer/missing.
    if not draft["claims"]:
        debug["safe_mode"] = True
        base = TECHNICAL_FAILURE if technical else NO_EVIDENCE
        text, _, _ = _pack(base, [], context, [m.text for m in mentions], cfg.answer_hard_limit)
        return finish(text, "refused", missing=mandatory_missing or ["Подтверждение ответа в найденных фрагментах"])

    bad_codes = {c.code for c in report.checks if not c.passed}
    semantic_ok = bool(review and review["verdict"] == "ok" and not technical)
    # C7 исправляется шаблонами кода. Остальные нарушения — только выдержки.
    extractive = not semantic_ok or bool(bad_codes - {"C7"})
    debug["safe_mode"] = extractive
    if extractive:
        warnings.append("extractive_fallback")
    selected = []
    for i in report.verified:
        claim = draft["claims"][i]
        chunk = context.labels[claim["chunk"]]
        # В режиме выдержек показываем весь нормативный фрагмент R: короткая
        # подстрока модели могла не включить соседнее условие или исключение.
        quote = chunk.text if extractive else report.quotes[i]
        # Fallback не выводит свободный claim.text, даже с настоящей цитатой.
        selected.append(_canonical_claim(claim, chunk, text=quote if extractive else claim["text"], quote=quote))
    missing = list(mandatory_missing)
    notes = [m.text for m in mentions]
    if extractive and selected:
        notes.append(EXTRACTIVE_NOTE)
        missing.append("Проверенный вывод по всем условиям и частям вопроса")
    elif draft["missing"]:
        # Текст missing тоже недоверенный: факт отсутствия нормы сообщает R или S8.
        if review and review["unanswered_parts"]:
            notes.append("Часть вопроса не подтверждена найденными фрагментами.")
        else:
            notes.append("Для полного ответа недостаточно подтверждений в найденных фрагментах.")
        missing.append("Подтверждения для оставшейся части вопроса")
    if "context_truncated" in context.warnings or "input_truncated" in qinfo.warnings:
        notes.append("Объём входа ограничен; полнота рассмотрения не подтверждена.")
        missing.append("Полный контекст вопроса и документов")
    # Неоднозначность требует доказательств по каждому кандидату, а не только имён.
    ambiguous = retrieval.signals.get("ambiguous")
    if isinstance(ambiguous, list):
        covered = {c["doc_id"] for c in selected}
        ids = [v if isinstance(v, str) else v.get("doc_id") for v in ambiguous if isinstance(v, (str, dict))]
        if any(v not in covered for v in ids):
            missing.append("Подтверждения по каждому неоднозначному кандидату")
            notes.append("Не по каждому кандидату удалось подтвердить ответ.")
    if technical:
        notes.append(TECHNICAL_FAILURE)
    text, selected, truncated = _pack(TECHNICAL_FAILURE if technical else NO_EVIDENCE,
                                      selected, context, notes, cfg.answer_hard_limit, extractive=extractive)
    if truncated:
        warnings.append("output_limited")
        missing.append("Часть подтверждений не поместилась в лимит ответа")
    if not selected:
        status = "refused"
        missing = missing or ["Проверенный ответ на вопрос"]
    else:
        status = decide(draft["status"], selected, retrieval.signals, review,
                        missing=missing, query_type=qinfo.query_type)
    return finish(text, status, selected, missing)


@dataclass
class Metrics:
    """B может собирать агрегаты без текстов вопросов, ответов, цитат и ключей."""
    count: int = 0
    statuses: Counter = field(default_factory=Counter)
    violations: Counter = field(default_factory=Counter)
    llm_calls: int = 0
    repairs: int = 0
    safe_mode: int = 0
    invalid_json: int = 0
    elapsed_sec: float = 0.0

    def add(self, result: AnswerResult):
        self.count += 1
        self.statuses[result.status] += 1
        debug = result.debug
        self.violations.update(debug.get("violations", []))
        self.llm_calls += debug.get("llm_calls", 0)
        self.repairs += bool(debug.get("repairs"))
        self.safe_mode += bool(debug.get("safe_mode"))
        self.invalid_json += bool(debug.get("parse_error"))
        self.elapsed_sec += debug.get("elapsed_sec", 0)

    def summary(self):
        n = self.count or 1
        return {"questions": self.count, "status": dict(self.statuses), "violations": dict(self.violations),
                "repair_rate": self.repairs/n, "safe_mode_rate": self.safe_mode/n,
                "invalid_json_rate": self.invalid_json/n, "mean_llm_calls": self.llm_calls/n,
                "mean_answer_sec": self.elapsed_sec/n}

    def emit(self, stream=None):
        print(json.dumps(self.summary(), ensure_ascii=False), file=stream or sys.stderr)
