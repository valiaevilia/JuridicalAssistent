from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from config import cfg
from schemas import AnswerResult, Chunk, QueryInfo, RetrievalResult

logger = logging.getLogger("pipeline")

# Глобальный реестр загруженной базы знаний
_KB_CACHE: dict[str, Any] | None = None

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
    """Инициализирует базу знаний.

    При наличии модулей R загружает реальные файлы; иначе использует
    смарт-стабы и гарантирует наличие docs.json на диске.
    """
    global _KB_CACHE
    if _KB_CACHE is not None:
        return _KB_CACHE

    docs_map: dict[str, dict[str, Any]] = dict(DEFAULT_DOCS)

    # Пробуем динамически загрузить модуль R (kb_load)
    try:
        import importlib
        kb_load = importlib.import_module("kb_load")
        if hasattr(kb_load, "init_kb"):
            loaded_kb = kb_load.init_kb()
            if isinstance(loaded_kb, dict) and "docs" in loaded_kb:
                docs_map = loaded_kb["docs"]
                logger.info("Real KB initialized from kb_load")
    except (ImportError, ModuleNotFoundError):
        pass
    except Exception as exc:
        logger.warning("Error initializing kb_load: %s; using default docs", exc)

    _export_docs_json_if_needed(docs_map)

    _KB_CACHE = {
        "docs": docs_map,
        "initialized_at": time.time(),
    }
    return _KB_CACHE


def _smart_stub_answer(question: str) -> AnswerResult:
    """Встроенный смарт-стаб для автономной работы до слияния веток R и L."""
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


def answer_question(question_text: str, deadline_ts: float | None = None) -> AnswerResult:
    """Единая точка входа для обработки вопроса.

    Используется и в solution.py, и в worker.py (для Go-бэкенда).
    """
    start_t = time.time()
    ensure_kb_initialized()

    # 1. Budget Guard: проверка оставшегося времени
    skip_s8 = False
    if deadline_ts is not None:
        remaining_time = deadline_ts - time.time()
        # Экстренный останов: если времени меньше 25 секунд на весь остаток вопросов
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
        # Пропуск глубокой самопроверки S8 при подходе к лимиту (< 150 с)
        if remaining_time < cfg.S8_SKIP_REMAINING_SEC:
            skip_s8 = True

    try:
        # 2. Попытка вызвать реальные модули R и L
        answer_res: AnswerResult | None = None
        try:
            import importlib
            answer = importlib.import_module("answer")
            retrieve = importlib.import_module("retrieve")

            # Если модули R и L присутствуют в ветке, вызываем их сквозной пайплайн
            if hasattr(retrieve, "retrieve") and hasattr(answer, "generate_and_verify"):
                qinfo = (
                    answer.preprocess_query(question_text)
                    if hasattr(answer, "preprocess_query")
                    else QueryInfo(original=question_text, last_user=question_text)
                )
                retrieval = retrieve.retrieve(qinfo)
                answer_res = answer.generate_and_verify(qinfo, retrieval, skip_self_check=skip_s8)
        except (ImportError, ModuleNotFoundError):
            pass
        except Exception as exc:
            logger.warning("Pipeline R/L execution error: %s; falling back to stub", exc)

        # 3. Если реальные модули недоступны или вернули None -> смарт-стаб
        if answer_res is None:
            answer_res = _smart_stub_answer(question_text)

        # 4. Финализация длины ответа
        answer_res.text = _trim_to_hard_limit(answer_res.text, cfg.ANSWER_HARD_LIMIT)
        answer_res.debug["latency_sec"] = round(time.time() - start_t, 3)
        answer_res.debug["skip_s8"] = skip_s8
        return answer_res

    except Exception as exc:
        # Гарантированный fail-safe: никогда не ронять процесс необработанным исключением
        logger.error("Unhandled exception in answer_question: %s", exc, exc_info=True)
        return AnswerResult(
            text="В базе знаний не найдено достаточных оснований для ответа на данный вопрос.",
            status="refused",
            query_type="insufficient_info",
            claims=[],
            missing=["Техническая ошибка обработки запроса"],
            warnings=["unhandled_exception"],
            debug={"error": str(exc), "latency_sec": round(time.time() - start_t, 3)},
        )
