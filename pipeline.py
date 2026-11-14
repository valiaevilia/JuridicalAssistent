from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import replace
from typing import Any

from config import LConfig, cfg, load_config
from schemas import AnswerResult, ConfigurationError

logger = logging.getLogger("pipeline")

# Глобальный реестр загруженной базы знаний
_KB_CACHE: dict[str, Any] | None = None
_KB_LOCK = threading.Lock()

# Встроенные дефолтные документы для автономной работы и экспорта в docs.json
DEFAULT_DOCS: dict[str, dict[str, Any]] = {
    "D1": {
        "doc_id": "D1",
        "title": "Договор аренды нежилого помещения № А-08/2024 (ООО «Северный Склад»)",
        "doc_type": "contract",
        "edition_date": "2024-08-01",
        "fragments": [
            {
                "fragment_id": "D1#3.1",
                "doc_id": "D1",
                "locator": "п. 3.1",
                "breadcrumbs": ["Раздел 3. Арендная плата и порядок расчётов", "п. 3.1"],
                "text": "3.1. Арендная плата устанавливается в размере 450 000 (четыреста пятьдесят тысяч) рублей в месяц, включая НДС.",
            },
            {
                "fragment_id": "D1#3.2",
                "doc_id": "D1",
                "locator": "п. 3.2",
                "breadcrumbs": ["Раздел 3. Арендная плата и порядок расчётов", "п. 3.2"],
                "text": "3.2. Арендная плата вносится Арендатором ежемесячно не позднее 5-го числа оплачиваемого месяца путем перечисления денежных средств на расчетный счет Арендодателя.",
            },
            {
                "fragment_id": "D1#3.3",
                "doc_id": "D1",
                "locator": "п. 3.3",
                "breadcrumbs": ["Раздел 3. Арендная плата и порядок расчётов", "п. 3.3"],
                "text": "3.3. Коммунальные услуги и эксплуатационные расходы не входят в сумму арендной платы и оплачиваются Арендатором отдельно на основании счетов эксплуатирующей организации.",
            },
        ],
    },
    "D2": {
        "doc_id": "D2",
        "title": "Договор поставки № П-17/2024 (ООО «Альфа-Трейд»)",
        "doc_type": "contract",
        "edition_date": "2024-02-12",
        "fragments": [
            {
                "fragment_id": "D2#4.2",
                "doc_id": "D2",
                "locator": "п. 4.2",
                "breadcrumbs": ["Раздел 4. Порядок расчетов", "п. 4.2"],
                "text": "4.2. Оплата товара производится Покупателем в течение 30 (тридцати) календарных дней с даты подписания универсального передаточного документа (УПД).",
            },
            {
                "fragment_id": "D2#5.2",
                "doc_id": "D2",
                "locator": "п. 5.2",
                "breadcrumbs": ["Раздел 5. Качество и гарантийные обязательства", "п. 5.2"],
                "text": "5.2. Гарантийный срок на поставляемое оборудование и мебель составляет 24 (двадцать четыре) месяца с даты подписания УПД обеими Сторонами.",
            },
        ],
    },
}


def _export_docs_json_if_needed(docs_map: dict[str, dict[str, Any]]) -> None:
    """Экспортирует базу документов в docs.json для Go-бэкенда,

    если файла ещё нет на диске.
    """
    path = cfg.DOCS_JSON_PATH
    if not path.exists():
        try:
            doc_list = list(docs_map.values())
            with path.open("w", encoding="utf-8") as f:
                json.dump(doc_list, f, ensure_ascii=False, indent=2)
            logger.info("Exported default docs to %s", path)
        except Exception as exc:
            logger.warning("Could not export docs.json: %s", exc)


def ensure_kb_initialized() -> dict[str, Any]:
    """Загружает исходную базу R один раз; образцы разрешены только в DEMO_MODE."""
    global _KB_CACHE
    if _KB_CACHE is not None and (not _KB_CACHE.get("demo") or cfg.DEMO_MODE):
        return _KB_CACHE
    with _KB_LOCK:
        if _KB_CACHE is not None and (not _KB_CACHE.get("demo") or cfg.DEMO_MODE):
            return _KB_CACHE
        from kb_load import init_kb
        loaded = init_kb()
        if not loaded.get("docs"):
            if not cfg.DEMO_MODE:
                raise FileNotFoundError("База знаний не найдена; задайте DATA_DIR")
            loaded = {"docs": dict(DEFAULT_DOCS), "chunks": [], "demo": True}
        _export_docs_json_if_needed(loaded["docs"])
        _KB_CACHE = {**loaded, "initialized_at": time.time()}
        return _KB_CACHE


def _smart_stub_answer(question: str) -> AnswerResult:
    """Предзаданные примеры, доступные только при явном DEMO_MODE=true."""
    q_lower = question.lower()

    # 1. Аренда склада в Химках (D1)
    if any(w in q_lower for w in ("аренд", "склад", "химк")):
        claims = [
            {
                "text": "Арендная плата составляет 450 000 рублей в месяц, включая НДС",
                "doc_id": "D1",
                "chunk_id": "D1#3.1",
                "locator": "п. 3.1",
                "quote": "3.1. Арендная плата устанавливается в размере 450 000 (четыреста пятьдесят тысяч) рублей в месяц, включая НДС.",
            },
            {
                "text": "Арендная плата вносится ежемесячно не позднее 5-го числа оплачиваемого месяца",
                "doc_id": "D1",
                "chunk_id": "D1#3.2",
                "locator": "п. 3.2",
                "quote": "3.2. Арендная плата вносится Арендатором ежемесячно не позднее 5-го числа оплачиваемого месяца",
            },
        ]
        text = (
            "Арендная плата по договору аренды склада № А-08/2024 составляет 450 000 рублей в месяц, включая НДС (п. 3.1). "
            "Оплата вносится ежемесячно не позднее 5-го числа оплачиваемого месяца (п. 3.2)."
        )
        return AnswerResult(
            text=text,
            status="answered",
            query_type="normal",
            claims=claims,
            missing=[],
            warnings=[],
            debug={"stub": True, "category": "lease_warehouse"},
        )

    # 2. Гарантия по договору поставки Альфа-Трейд (D2)
    if "гарант" in q_lower and ("альфа" in q_lower or "трейд" in q_lower or "п-17" in q_lower):
        claims = [
            {
                "text": "Гарантийный срок составляет 24 месяца с даты подписания УПД",
                "doc_id": "D2",
                "chunk_id": "D2#5.2",
                "locator": "п. 5.2",
                "quote": "5.2. Гарантийный срок на поставляемое оборудование и мебель составляет 24 (двадцать четыре) месяца с даты подписания УПД",
            }
        ]
        text = (
            "Гарантийный срок на поставляемое оборудование и мебель по договору поставки № П-17/2024 с ООО «Альфа-Трейд» "
            "составляет 24 месяца с даты подписания УПД обеими Сторонами (п. 5.2)."
        )
        return AnswerResult(
            text=text,
            status="answered",
            query_type="normal",
            claims=claims,
            missing=[],
            warnings=[],
            debug={"stub": True, "category": "warranty_alpha"},
        )

    # 3. Срок оплаты по договору поставки Альфа-Трейд (D2)
    if "оплат" in q_lower and ("альфа" in q_lower or "трейд" in q_lower or "п-17" in q_lower):
        claims = [
            {
                "text": "Оплата производится в течение 30 календарных дней с даты подписания УПД",
                "doc_id": "D2",
                "chunk_id": "D2#4.2",
                "locator": "п. 4.2",
                "quote": "4.2. Оплата товара производится Покупателем в течение 30 (тридцати) календарных дней с даты подписания универсального передаточного документа (УПД).",
            }
        ]
        text = (
            "Покупатель оплачивает товар по договору поставки № П-17/2024 в течение 30 календарных дней "
            "с даты подписания универсального передаточного документа (УПД) (договор поставки № П-17/2024, п. 4.2)."
        )
        return AnswerResult(
            text=text,
            status="answered",
            query_type="normal",
            claims=claims,
            missing=[],
            warnings=[],
            debug={"stub": True, "category": "payment_terms"},
        )

    # 4. Общий безопасный отказ при отсутствии точных совпадений в стабе
    return AnswerResult(
        text="В предоставленной базе знаний недостаточно данных для однозначного ответа на данный вопрос.",
        status="refused",
        query_type="insufficient_info",
        claims=[],
        missing=["Необходимый нормативный документ или пункт договора отсутствует в базе"],
        warnings=[],
        debug={"stub": True, "category": "refused_fallback"},
    )


def _trim_to_hard_limit(text: str, limit: int) -> str:
    """Обрезает ответ по лимиту символов с сохранением целостности

    предложения/слова.
    """
    if len(text) <= limit:
        return text
    truncated = text[:limit]
    # Пытаемся обрезать по последней точке или переводу строки
    last_stop = max(truncated.rfind(". "), truncated.rfind(".\n"), truncated.rfind("\n"))
    if last_stop > limit // 2:
        return truncated[: last_stop + 1].strip()
    # Иначе по пробелу
    last_space = truncated.rfind(" ")
    if last_space > limit // 2:
        return truncated[:last_space].strip() + "..."
    return truncated.strip() + "..."


def _extract_date_hints(text: str) -> list[dict]:
    """Адаптирует DateExtractionResult роли R к контракту S1 без потери точности."""
    from dates import extract_dates
    from guard import CONTRACT_PATTERN
    # Год внутри номера договора не является датой события.
    extracted = extract_dates(CONTRACT_PATTERN.sub("", text))
    if extracted.precision in ("none", "current") or not extracted.raw_match:
        return []
    lo, hi = extracted.as_of_range or (extracted.as_of, extracted.as_of)
    return [{"text": extracted.raw_match.strip(), "iso_from": lo, "iso_to": hi,
             "role": "signing" if any(w in text.lower() for w in ("одобр", "согласован")) else "event"}]


def answer_question(question_text: str, deadline_ts: float | None = None, *,
                    client=None, config: LConfig | None = None) -> AnswerResult:
    """Единый R→L pipeline для CSV и worker. deadline_ts — Unix-время B.

    На границе L оно переводится в time.monotonic(); client/config внедряются
    для offline-проверок того же пути без сетевых запросов.
    """
    start_t = time.time()
    skip_s8 = False
    if deadline_ts is not None:
        remaining_time = deadline_ts - time.time()
        if remaining_time < cfg.EMERGENCY_STOP_REMAINING_SEC:
            return AnswerResult(
                text="Время обработки ограничено тайм-бюджетом платформы. Сформировать ответ не удалось.",
                status="refused",
                query_type="insufficient_info",
                claims=[],
                missing=["Превышен тайм-бюджет выполнения"],
                warnings=["emergency_stop"],
                debug={"latency_sec": round(time.time() - start_t, 3)},
            )
        if remaining_time < cfg.S8_SKIP_REMAINING_SEC:
            skip_s8 = True

    try:
        limits = config or load_config()
        limits = replace(limits, s8_enabled=limits.s8_enabled and not skip_s8,
                         answer_hard_limit=min(limits.answer_hard_limit, cfg.ANSWER_HARD_LIMIT))
        remaining = min(limits.q_budget_sec, cfg.PER_QUESTION_TIMEOUT_SEC)
        if deadline_ts is not None:
            remaining = min(remaining, deadline_ts - time.time())
        deadline = time.monotonic() + remaining
        ensure_kb_initialized()
        if cfg.DEMO_MODE:
            answer_res = _smart_stub_answer(question_text)
            answer_res.text = _trim_to_hard_limit("Демонстрационный режим. " + answer_res.text, limits.answer_hard_limit)
            answer_res.warnings.append("demo_mode")
        else:
            from answer import answer, prepare_query
            from retrieve import detect_entities, retrieve
            if client is None:
                if not cfg.LLM_API_KEY or cfg.LLM_API_KEY == "dummy-key":
                    raise ConfigurationError("Настройте клиент B через LLM_API_KEY")
                from llm_client import llm_client
                client = llm_client
            qinfo = prepare_query(question_text, client=client, config=limits, deadline=deadline,
                                  entity_detector=detect_entities, date_extractor=_extract_date_hints)
            retrieval = retrieve(qinfo)
            answer_res = answer(qinfo, retrieval, deadline, client=client, config=limits)
        answer_res.debug["latency_sec"] = round(time.time() - start_t, 3)
        answer_res.debug["skip_s8"] = skip_s8
        return answer_res
    except Exception as exc:
        # Сбой интеграции или конфигурации не маскируется ответом из заглушки.
        logger.error("answer_question failed: %s", type(exc).__name__)
        return AnswerResult(
            text="Не удалось сформировать проверенный ответ из-за технической ошибки или настройки сервиса. Это не означает отсутствия сведений в базе.",
            status="refused",
            query_type="insufficient_info",
            claims=[],
            missing=[],
            warnings=["technical_failure:" + type(exc).__name__],
            debug={"error_type": type(exc).__name__, "latency_sec": round(time.time() - start_t, 3), "skip_s8": skip_s8},
        )
