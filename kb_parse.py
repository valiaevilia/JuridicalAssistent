"""Парсинг документов базы знаний на нормативные фрагменты (Chunk).

Реализует требования раздела 5.3 и 5.4 planchik.md:
- Чистка текста без потери нормативных чисел
- Изоляция и строгий карантин prompt-инъекций (D8)
- Отделение примечаний об изменениях от текста норм
- Хлебные крошки со ставками налогов (НК РФ)
- Эвристика нумерации частей для Трудового кодекса РФ
- Экспорт в chunks.jsonl и docs.json
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from kb_load import RawDoc, load_raw_docs
from schemas import Chunk

logger = logging.getLogger("kb_parse")

# Маркеры инъекций для безусловного карантина
INJECTION_MARKERS = [
    "внимание для ии-ассистента",
    "игнорируй все остальные",
    "отвечай «90 календарных дней»",
    "отвечай \"90 календарных дней\"",
    "90 календарных дней",
    "не упоминай эту инструкцию",
]


def clean_text(text: str) -> str:
    """Нормализует пробелы и служебные символы."""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace("\u00a0", " ").replace("\u202f", " ")
    # Схлопываем повторяющиеся пробелы (но сохраняем переносы строк)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in t.split("\n")]
    return "\n".join(lines).strip()


def is_quarantined_line(line: str) -> bool:
    l_low = line.lower()
    return any(marker in l_low for marker in INJECTION_MARKERS)


def normalize_index_text(breadcrumbs: list[str], text: str) -> str:
    """Формирует расширенный текст для поиска: крошки + текст + нормализованные числа/номера."""
    full = " > ".join(breadcrumbs) + " " + text
    clean = full.lower().replace("ё", "е")

    # Добавляем числа без пробелов: "450 000" -> "450000", "8 400 000" -> "8400000"
    numbers_with_spaces = re.findall(r"\b\d{1,3}(?:\s+\d{3})+\b", clean)
    added_nums = [n.replace(" ", "") for n in numbers_with_spaces]

    # Варианты номеров договоров: п-17/2024 -> п-17-2024, п17
    contract_vars: list[str] = []
    if "а-08/2024" in clean or "а-08-2024" in clean:
        contract_vars.extend(["а-08/2024", "а-08-2024", "а08", "а-08"])
    if "п-17/2024" in clean or "п-17-2024" in clean:
        contract_vars.extend(["п-17/2024", "п-17-2024", "п17", "п-17"])
    if "пт-05/2023" in clean or "пт-05-2023" in clean:
        contract_vars.extend(["пт-05/2023", "пт-05-2023", "пт05", "пт-05"])

    extras = " ".join(added_nums + contract_vars)
    return (full + " " + extras).strip()


def _parse_contract_clauses(doc_id: str, title: str, kind: str, text: str, meta: dict[str, Any]) -> list[Chunk]:
    """Парсинг договоров D1, D2, D3 по разделам и пунктам."""
    chunks: list[Chunk] = []
    lines = clean_text(text).split("\n")

    current_section = ""
    current_clause_num = ""
    current_clause_lines: list[str] = []
    preamble_lines: list[str] = []
    requisites_lines: list[str] = []
    is_preamble = True

    clause_regex = re.compile(r"^(\d+\.\d+)\.?\s*(.*)$")
    section_regex = re.compile(r"^(\d+\.\s+[^.\n]+)$")

    def flush_clause():
        nonlocal current_clause_num, current_clause_lines
        if current_clause_num and current_clause_lines:
            c_text = "\n".join(current_clause_lines).strip()
            locator = f"п. {current_clause_num}"
            bcs = [title]
            if current_section:
                bcs.append(current_section)
            bcs.append(locator)
            cid = f"{doc_id}#{current_clause_num}"

            chunks.append(Chunk(
                chunk_id=cid,
                doc_id=doc_id,
                doc_title=title,
                doc_kind=kind,
                locator=locator,
                breadcrumbs=bcs,
                text=c_text,
                index_text=normalize_index_text(bcs, c_text),
                edition=meta.get("edition"),
                valid_from=meta.get("valid_from"),
                valid_to=meta.get("valid_to"),
                quarantined=False,
            ))
            current_clause_lines = []
            current_clause_num = ""

    for line in lines:
        if not line:
            continue
        sec_match = section_regex.match(line)
        if sec_match:
            flush_clause()
            is_preamble = False
            current_section = sec_match.group(1).strip()
            continue

        c_match = clause_regex.match(line)
        if c_match:
            flush_clause()
            is_preamble = False
            current_clause_num = c_match.group(1)
            rest = c_match.group(2).strip()
            current_clause_lines = [f"{current_clause_num}. {rest}" if rest else f"{current_clause_num}."]
            continue

        if is_preamble:
            preamble_lines.append(line)
        elif current_clause_num:
            current_clause_lines.append(line)
        elif current_section and "подписи" in current_section.lower():
            # Реквизиты и подписи
            requisites_lines.append(line)

    flush_clause()

    if requisites_lines:
        r_text = "\n".join(requisites_lines)
        chunks.append(Chunk(
            chunk_id=f"{doc_id}#requisites", doc_id=doc_id, doc_title=title,
            doc_kind=kind, locator="Реквизиты и подписи сторон",
            breadcrumbs=[title, "Реквизиты и подписи сторон"], text=r_text,
            index_text=normalize_index_text([title, "Реквизиты"], r_text),
            edition=meta.get("edition"), valid_from=meta.get("valid_from"), valid_to=meta.get("valid_to"),
        ))

    # Добавляем преамбулу как отдельный чанк
    if preamble_lines:
        p_text = "\n".join(preamble_lines).strip()
        bcs = [title, "Преамбула"]
        chunks.insert(0, Chunk(
            chunk_id=f"{doc_id}#preamble",
            doc_id=doc_id,
            doc_title=title,
            doc_kind=kind,
            locator="Преамбула",
            breadcrumbs=bcs,
            text=p_text,
            index_text=normalize_index_text(bcs, p_text),
            edition=meta.get("edition"),
            valid_from=meta.get("valid_from"),
            valid_to=meta.get("valid_to"),
        ))

    return chunks


def _parse_amendment(doc_id: str, title: str, text: str, meta: dict[str, Any]) -> list[Chunk]:
    """Парсинг Дополнительного соглашения D4."""
    chunks: list[Chunk] = []
    lines = [l for l in clean_text(text).split("\n") if l]

    p_lines = []
    for i, line in enumerate(lines):
        if "изложить пункт 3.2" in line.lower() or "пункт 3.2" in line.lower():
            # Это пункт об изменении адреса
            c_text = line
            # Захватываем последующие строки условия (например, про партии после 01.10.2024)
            for j in range(i + 1, min(i + 4, len(lines))):
                if any(kw in lines[j].lower() for kw in ("парти", "вступает в силу", "спецификац")):
                    c_text += "\n" + lines[j]

            bcs = [title, "изложение п. 3.2", "доставка Химки склад № 3"]
            chunks.append(Chunk(
                chunk_id=f"{doc_id}#3.2",
                doc_id=doc_id,
                doc_title=title,
                doc_kind="amendment",
                locator="изложение п. 3.2",
                breadcrumbs=bcs,
                text=c_text,
                index_text=normalize_index_text(bcs, c_text),
                valid_from=meta.get("valid_from"),
            ))
        else:
            p_lines.append(line)

    # Весь документ целиком как общий чанк D4
    full_text = "\n".join(lines).strip()
    bcs = [title, "полный текст"]
    chunks.insert(0, Chunk(
        chunk_id=f"{doc_id}#all",
        doc_id=doc_id,
        doc_title=title,
        doc_kind="amendment",
        locator="Доп. соглашение № 1",
        breadcrumbs=bcs,
        text=full_text,
        index_text=normalize_index_text(bcs, full_text),
        valid_from=meta.get("valid_from"),
    ))
    return chunks


def _parse_regulations(doc_id: str, title: str, text: str, meta: dict[str, Any]) -> list[Chunk]:
    """Парсинг регламентов D6 и D7 по пунктам с указанием редакции."""
    chunks: list[Chunk] = []
    lines = clean_text(text).split("\n")

    current_section = ""
    current_clause_num = ""
    current_clause_lines: list[str] = []
    header_lines: list[str] = []
    is_header = True

    clause_regex = re.compile(r"^(\d+\.\d+)\.?\s*(.*)$")
    section_regex = re.compile(r"^(\d+\.\s+[^.\n]+)$")

    edition_str = meta.get("edition") or ("ред. 01.03.2025" if doc_id == "D7" else "ред. 10.01.2023")

    def flush():
        nonlocal current_clause_num, current_clause_lines
        if current_clause_num and current_clause_lines:
            c_text = "\n".join(current_clause_lines).strip()
            locator = f"п. {current_clause_num}"
            bcs = [f"{title} ({edition_str})"]
            if current_section:
                bcs.append(current_section)
            bcs.append(locator)

            cid = f"{doc_id}#{current_clause_num}"
            chunks.append(Chunk(
                chunk_id=cid,
                doc_id=doc_id,
                doc_title=title,
                doc_kind="regulation",
                locator=locator,
                breadcrumbs=bcs,
                text=c_text,
                index_text=normalize_index_text(bcs, c_text),
                edition=edition_str,
                valid_from=meta.get("valid_from"),
                valid_to=meta.get("valid_to"),
            ))
            current_clause_lines = []

    for line in lines:
        if not line:
            continue
        sec_m = section_regex.match(line)
        if sec_m:
            flush()
            is_header = False
            current_section = sec_m.group(1).strip()
            continue

        cl_m = clause_regex.match(line)
        if cl_m:
            flush()
            is_header = False
            current_clause_num = cl_m.group(1)
            rest = cl_m.group(2).strip()
            current_clause_lines = [f"{current_clause_num}. {rest}" if rest else f"{current_clause_num}."]
            continue

        if is_header:
            header_lines.append(line)
        elif current_clause_num:
            current_clause_lines.append(line)

    flush()

    if header_lines:
        h_text = "\n".join(header_lines).strip()
        bcs = [f"{title} ({edition_str})", "Шапка"]
        chunks.insert(0, Chunk(
            chunk_id=f"{doc_id}#header",
            doc_id=doc_id,
            doc_title=title,
            doc_kind="regulation",
            locator="Шапка",
            breadcrumbs=bcs,
            text=h_text,
            index_text=normalize_index_text(bcs, h_text),
            edition=edition_str,
            valid_from=meta.get("valid_from"),
            valid_to=meta.get("valid_to"),
        ))

    return chunks


def _parse_memo_and_letter(doc_id: str, title: str, kind: str, text: str, meta: dict[str, Any]) -> list[Chunk]:
    """Парсинг письма комплаенс D5 и служебной записки D8 с изоляцией карантина."""
    chunks: list[Chunk] = []
    lines = clean_text(text).split("\n")

    valid_paragraphs: list[str] = []

    for i, line in enumerate(lines):
        line_s = line.strip()
        if not line_s:
            continue

        # ПРОВЕРКА НА ИНЪЕКЦИЮ В D8
        if is_quarantined_line(line_s):
            logger.warning("QUARANTINE TRIGGERED in %s: %s", doc_id, line_s[:60])
            # Создаем изолированный чанк с пометкой quarantined=True
            chunks.append(Chunk(
                chunk_id=f"{doc_id}#quarantined",
                doc_id=doc_id,
                doc_title=title,
                doc_kind=kind,
                locator="Карантин",
                breadcrumbs=[title, "КАРАНТИН (инструкция ИИ)"],
                text="",  # Очищаем нормативный текст!
                index_text="",  # Не индексируем в поиске!
                notes=[line_s],
                quarantined=True,
            ))
            continue

        valid_paragraphs.append(line_s)
        locator = f"абз. {len(valid_paragraphs)}"
        bcs = [title, locator]
        chunks.append(Chunk(
            chunk_id=f"{doc_id}#p{len(valid_paragraphs)}",
            doc_id=doc_id,
            doc_title=title,
            doc_kind=kind,
            locator=locator,
            breadcrumbs=bcs,
            text=line_s,
            index_text=normalize_index_text(bcs, line_s),
            valid_from=meta.get("valid_from"),
            quarantined=False,
        ))

    # Полный документ (без инъекции!)
    safe_full = "\n".join(valid_paragraphs).strip()
    chunks.insert(0, Chunk(
        chunk_id=f"{doc_id}#all",
        doc_id=doc_id,
        doc_title=title,
        doc_kind=kind,
        locator="Полный документ",
        breadcrumbs=[title, "Полный текст"],
        text=safe_full,
        index_text=normalize_index_text([title], safe_full),
        valid_from=meta.get("valid_from"),
        quarantined=False,
    ))
    return chunks


def _parse_labor_code(doc_id: str, title: str, text: str, meta: dict[str, Any]) -> list[Chunk]:
    """Парсинг статей Трудового кодекса РФ (ст. 59, 70, 99, 152) с эвристикой частей."""
    chunks: list[Chunk] = []
    lines = clean_text(text).split("\n")

    article_num = meta.get("article", "")
    code_name = "ТК РФ"
    changed_on = meta.get("changed_on", [])

    body_lines: list[str] = []
    notes: list[str] = []
    in_body = False

    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue
        if line_s.startswith("Источник:") or line_s.startswith("URL:") or line_s.startswith("Дата выгрузки:"):
            continue
        if "изменена с" in line_s or "изменен с" in line_s:
            notes.append(line_s)
            continue
        if f"Статья {article_num}." in line_s or f"Статья {article_num}" in line_s:
            in_body = True
            continue
        if in_body:
            body_lines.append(line_s)

    # Разбивка на части
    parts: list[str] = []
    current_part: list[str] = []

    for line in body_lines:
        if line.endswith(":") or not line.endswith("."):
            current_part.append(line)
        else:
            current_part.append(line)
            parts.append("\n".join(current_part).strip())
            current_part = []
    if current_part:
        parts.append("\n".join(current_part).strip())

    for idx, part_text in enumerate(parts, 1):
        locator = f"ст. {article_num}, ч. {idx}"
        bcs = [code_name, f"ст. {article_num}", f"ч. {idx}"]
        chunks.append(Chunk(
            chunk_id=f"{doc_id}#ч{idx}",
            doc_id=doc_id,
            doc_title=title,
            doc_kind="law",
            locator=locator,
            breadcrumbs=bcs,
            text=part_text,
            index_text=normalize_index_text(bcs, part_text),
            changed_on=changed_on,
            notes=notes,
        ))

    return chunks


def _parse_tax_code_164(doc_id: str, title: str, text: str, meta: dict[str, Any]) -> list[Chunk]:
    """Специальный парсинг НК РФ ст. 164 со ставками в крошках и заглушкой п. 11."""
    chunks: list[Chunk] = []
    lines = clean_text(text).split("\n")

    current_item = ""
    current_item_header = ""
    current_item_lines: list[str] = []
    current_subitem = ""
    current_subitem_lines: list[str] = []

    item_rates = {
        "1": "ставка 0 процентов",
        "2": "ставка 10 процентов (продовольственные товары, молоко, книги)",
        "3": "ставка 22 процента (с 01.01.2026, ранее 20 процентов)",
        "4": "расчетные ставки",
        "8": "ставки 5% и 7% на УСН",
    }

    item_regex = re.compile(r"^(\d+)\.\s+(.*)$")
    subitem_regex = re.compile(r"^(\d+)\)\s+(.*)$")

    def flush_subitem():
        nonlocal current_subitem, current_subitem_lines
        if current_subitem and current_subitem_lines:
            c_text = "\n".join(current_subitem_lines).strip()
            locator = f"ст. 164, п. {current_item}, пп. {current_subitem})"
            rate_info = item_rates.get(current_item, "")
            bcs = ["НК РФ", "ст. 164", f"п. {current_item} ({rate_info})" if rate_info else f"п. {current_item}", f"пп. {current_subitem})"]

            cid = f"{doc_id}#{current_item}#{current_subitem}"
            chunks.append(Chunk(
                chunk_id=cid,
                doc_id=doc_id,
                doc_title=title,
                doc_kind="law",
                locator=locator,
                breadcrumbs=bcs,
                text=c_text,
                index_text=normalize_index_text(bcs, c_text),
                changed_on=meta.get("changed_on", []),
            ))
            current_subitem_lines = []

    def flush_item():
        nonlocal current_item, current_item_header, current_item_lines
        flush_subitem()
        if current_item and current_item_lines:
            c_text = "\n".join(current_item_lines).strip()
            locator = f"ст. 164, п. {current_item}"
            rate_info = item_rates.get(current_item, "")
            bcs = ["НК РФ", "ст. 164", f"п. {current_item} ({rate_info})" if rate_info else f"п. {current_item}"]

            cid = f"{doc_id}#{current_item}"
            chunks.append(Chunk(
                chunk_id=cid,
                doc_id=doc_id,
                doc_title=title,
                doc_kind="law",
                locator=locator,
                breadcrumbs=bcs,
                text=c_text,
                index_text=normalize_index_text(bcs, c_text),
                changed_on=meta.get("changed_on", []),
            ))
            current_item_lines = []

    for line in lines:
        line_s = line.strip()
        if not line_s or line_s.startswith("Источник:") or line_s.startswith("URL:") or line_s.startswith("Дата выгрузки:"):
            continue

        im = item_regex.match(line_s)
        if im and int(im.group(1)) <= 15:
            flush_item()
            current_item = im.group(1)
            current_item_header = im.group(2)
            current_item_lines = [line_s]
            current_subitem = ""
            continue

        sm = subitem_regex.match(line_s)
        if sm and current_item:
            flush_subitem()
            current_subitem = sm.group(1)
            current_subitem_lines = [line_s]
            continue

        if current_subitem:
            current_subitem_lines.append(line_s)
        elif current_item:
            current_item_lines.append(line_s)

    flush_item()

    # Пункт 11 заглушка (в файле нет текста пункта 11, только примечание)
    chunks.append(Chunk(
        chunk_id=f"{doc_id}#11",
        doc_id=doc_id,
        doc_title=title,
        doc_kind="law",
        locator="ст. 164, п. 11",
        breadcrumbs=["НК РФ", "ст. 164", "п. 11 (текст отсутствует)"],
        text="В файле статьи 164 НК РФ базы знаний указано примечание о дополнении статьи пунктом 11 с 01.10.2026, однако нормативный текст пункта 11 в документе отсутствует.",
        index_text=normalize_index_text(["НК РФ", "ст. 164", "п. 11"], "текст пункта 11 статьи 164 отсутствует нормативный текст не представлен"),
        notes=["Статья 164 дополнена пунктом 11 с 1 октября 2026 г."],
    ))

    return chunks


def _parse_generic_law(doc_id: str, title: str, text: str, meta: dict[str, Any]) -> list[Chunk]:
    """Парсинг остальных законов (МРОТ, КоАП 13.11, 152-ФЗ ст. 9, НК 112, 114, 145, 224, 284)."""
    chunks: list[Chunk] = []
    lines = clean_text(text).split("\n")

    code_name = meta.get("code", "Закон")
    art_num = meta.get("article", "")
    changed_on = meta.get("changed_on", [])

    current_item_num = ""
    current_lines: list[str] = []

    # Различаем пункты 1. или части 1.
    is_part_numbering = doc_id in ("L6", "L7")  # 152-ФЗ ст. 9, КоАП 13.11
    item_regex = re.compile(r"^(\d+(?:\.\d+)*)\.?\s*(.*)$")

    def flush():
        nonlocal current_item_num, current_lines
        if current_item_num and current_lines:
            c_text = "\n".join(current_lines).strip()
            prefix = "ч." if is_part_numbering else "п."
            locator = f"ст. {art_num}, {prefix} {current_item_num}"
            bcs = [code_name, f"ст. {art_num}", f"{prefix} {current_item_num}"]

            cid = f"{doc_id}#{current_item_num}"
            chunks.append(Chunk(
                chunk_id=cid,
                doc_id=doc_id,
                doc_title=title,
                doc_kind="law",
                locator=locator,
                breadcrumbs=bcs,
                text=c_text,
                index_text=normalize_index_text(bcs, c_text),
                changed_on=changed_on,
            ))
            current_lines = []

    for line in lines:
        line_s = line.strip()
        if not line_s or line_s.startswith("Источник:") or line_s.startswith("URL:") or line_s.startswith("Дата выгрузки:"):
            continue
        if "изменена с" in line_s or "изменен с" in line_s or "дополнена" in line_s:
            continue

        im = item_regex.match(line_s)
        if im and float(im.group(1).split(".")[0]) <= 50:
            flush()
            current_item_num = im.group(1)
            rest = im.group(2).strip()
            current_lines = [f"{current_item_num}. {rest}" if rest else f"{current_item_num}."]
            continue

        if current_item_num:
            current_lines.append(line_s)
        elif not chunks:
            # Преамбула/первый абзац (например, ст. 1 МРОТ)
            current_lines.append(line_s)

    flush()

    if not chunks and current_lines:
        c_text = "\n".join(current_lines).strip()
        locator = f"ст. {art_num}"
        bcs = [code_name, f"ст. {art_num}"]
        chunks.append(Chunk(
            chunk_id=f"{doc_id}#1",
            doc_id=doc_id,
            doc_title=title,
            doc_kind="law",
            locator=locator,
            breadcrumbs=bcs,
            text=c_text,
            index_text=normalize_index_text(bcs, c_text),
            changed_on=changed_on,
        ))

    return chunks


def parse_document(raw_doc: RawDoc) -> list[Chunk]:
    """Маршрутизирует документ на соответствующее семейство парсеров."""
    meta = raw_doc.meta
    doc_id = meta.get("doc_id", "UNK")
    title = meta.get("title", raw_doc.file_name)
    kind = meta.get("kind", "other")
    text = raw_doc.text

    if doc_id in ("D1", "D2", "D3"):
        return _parse_contract_clauses(doc_id, title, kind, text, meta)
    elif doc_id == "D4":
        return _parse_amendment(doc_id, title, text, meta)
    elif doc_id in ("D6", "D7"):
        return _parse_regulations(doc_id, title, text, meta)
    elif doc_id in ("D5", "D8"):
        return _parse_memo_and_letter(doc_id, title, kind, text, meta)
    elif doc_id in ("L1", "L2", "L3", "L4"):
        return _parse_labor_code(doc_id, title, text, meta)
    elif doc_id == "L11":
        return _parse_tax_code_164(doc_id, title, text, meta)
    elif doc_id.startswith("L"):
        return _parse_generic_law(doc_id, title, text, meta)
    else:
        # Универсальный парсер по абзацам
        paragraphs = [p.strip() for p in clean_text(text).split("\n\n") if p.strip()]
        chunks = []
        for i, p in enumerate(paragraphs, 1):
            chunks.append(Chunk(
                chunk_id=f"{doc_id}#{i}",
                doc_id=doc_id,
                doc_title=title,
                doc_kind=kind,
                locator=f"фрагмент {i}",
                breadcrumbs=[title, f"фрагмент {i}"],
                text=p,
                index_text=normalize_index_text([title], p),
            ))
        return chunks


def unique_chunk_ids(chunks: list[Chunk]) -> list[Chunk]:
    """Повторная нумерация вложенных частей не должна затирать источник по ID.

    Первый идентификатор сохраняется, последующие получают стабильный суффикс
    по порядку исходного документа. Тексты и нормативные локаторы не меняются.
    """
    used = set()
    output = []
    for chunk in chunks:
        base, candidate, occurrence = chunk.chunk_id, chunk.chunk_id, 1
        while candidate in used:
            occurrence += 1
            candidate = f"{base}~{occurrence}"
        output.append(replace(chunk, chunk_id=candidate) if candidate != base else chunk)
        used.add(candidate)
    return output


def parse_all_documents(raw_docs: list[RawDoc] | None = None) -> list[Chunk]:
    """Парсит все документы, сохраняет chunks.jsonl и возвращает список Chunk."""
    if raw_docs is None:
        raw_docs = load_raw_docs()

    all_chunks: list[Chunk] = []
    for doc in raw_docs:
        doc_chunks = parse_document(doc)
        all_chunks.extend(doc_chunks)

    all_chunks = unique_chunk_ids(all_chunks)

    # Запись в chunks.jsonl в корень репозитория
    out_path = Path("chunks.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")

    logger.info("Parsed %d chunks written to %s", len(all_chunks), out_path)
    return all_chunks


def build_docs_json(chunks: list[Chunk], raw_docs: list[RawDoc]) -> dict[str, dict[str, Any]]:
    """Формирует и сохраняет docs.json для Go-бэкенда и веб-интерфейса."""
    docs_map: dict[str, dict[str, Any]] = {}

    meta_by_doc_id = {d.meta.get("doc_id"): d.meta for d in raw_docs if d.meta.get("doc_id")}

    for c in chunks:
        did = c.doc_id
        if did not in docs_map:
            dmeta = meta_by_doc_id.get(did, {})
            docs_map[did] = {
                "doc_id": did,
                "title": c.doc_title,
                "doc_type": c.doc_kind,
                "edition_date": c.edition or dmeta.get("valid_from", ""),
                "fragments": [],
            }
        docs_map[did]["fragments"].append({
            "fragment_id": c.chunk_id,
            "doc_id": c.doc_id,
            "locator": c.locator,
            "breadcrumbs": c.breadcrumbs,
            "text": c.text,
            "quarantined": c.quarantined,
        })

    docs_json_path = Path("docs.json")
    with open(docs_json_path, "w", encoding="utf-8") as f:
        json.dump(list(docs_map.values()), f, ensure_ascii=False, indent=2)

    logger.info("Exported %d docs to %s", len(docs_map), docs_json_path)
    return docs_map


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    docs = load_raw_docs()
    parsed_chunks = parse_all_documents(docs)
    build_docs_json(parsed_chunks, docs)
    print(f"Total chunks: {len(parsed_chunks)}")
