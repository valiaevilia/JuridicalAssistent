"""Тесты для модуля Retrieval (Роль R).

Проверяет:
1. Загрузку и парсинг всех 21 документов
2. Карантин инъекций (D8)
3. Извлечение дат (dates.py)
4. Распознавание сущностей и разрешение коллизий ('Альфа')
5. Выбор редакций на дату события (resolve_editions)
6. Сквозной поиск retrieve() на 25 вопросах из eval/dataset.jsonl
"""

import json
import os
import sys
from pathlib import Path

# Добавляем корень репозитория в sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dates import extract_dates
from kb_load import load_meta, load_raw_docs
from kb_parse import parse_all_documents
from retrieve import detect_entities, get_global_index, resolve_editions, retrieve
from schemas import QueryInfo


def test_kb_meta_and_load():
    meta = load_meta()
    assert "documents" in meta
    assert len(meta["documents"]) == 21
    docs = load_raw_docs()
    assert len(docs) == 21


def test_quarantine_integrity():
    chunks = parse_all_documents()
    for c in chunks:
        assert "90 календарных" not in c.text, f"Leak in text of {c.chunk_id}"
        assert "90 календарных" not in c.index_text, f"Leak in index_text of {c.chunk_id}"
        if c.quarantined:
            assert c.text == ""
            assert c.index_text == ""


def test_dates_extraction():
    cases = [
        ("договор заключали 15.10.2024", "2024-10-15", "day"),
        ("в августе 2024 года", "2024-08-01", "month"),
        ("в апреле 2025 года", "2025-04-01", "month"),
        ("в июне 2026 года", "2026-06-01", "month"),
        ("в 2025 году", "2025-01-01", "year"),
        ("с 1 января 2026 г.", "2026-01-01", "day"),
        ("на текущий момент", None, "current"),
    ]
    for text, expected_as_of, expected_prec in cases:
        res = extract_dates(text)
        assert res.as_of == expected_as_of, f"Failed for '{text}': got {res.as_of}"
        assert res.precision == expected_prec, f"Failed prec for '{text}': got {res.precision}"


def test_entity_detection_and_ambiguity():
    # Голая Альфа -> неоднозначность
    ent = detect_entities("какой срок оплаты по договору с Альфой?")
    assert "D2" in ent["ambiguous"] and "D3" in ent["ambiguous"]

    # Альфа-Трейдинг -> D3
    ent_trading = detect_entities("срок поставки по договору с Альфа-Трейдинг")
    assert "D3" in ent_trading["docs"]
    assert "D2" not in ent_trading["docs"]

    # Альфа-Трейд -> D2
    ent_trade = detect_entities("гарантийный срок по договору с Альфа-Трейд")
    assert "D2" in ent_trade["docs"]
    assert "D3" not in ent_trade["docs"]

    # Аренда склада Химки -> D1
    ent_rent = detect_entities("размер арендной платы склада в Химках")
    assert "D1" in ent_rent["docs"]

    # Тема вне базы
    ent_maternity = detect_entities("размер пособия по беременности и родам")
    assert ent_maternity["topic_not_in_base"] is True


def test_resolve_editions():
    # Регламент 2024 -> D6
    docs, ed, warn = resolve_editions(["REG"], as_of="2024-08-15")
    assert "D6" in docs
    assert "D7" not in docs
    assert "10.01.2023" in ed.get("Регламент", "")

    # Регламент 2025 -> D7
    docs, ed, warn = resolve_editions(["REG"], as_of="2025-04-10")
    assert "D7" in docs
    assert "D6" not in docs
    assert "01.03.2025" in ed.get("Регламент", "")

    # ТК ст. 70 до сентября 2026 -> предупреждение older_edition_missing
    docs, ed, warn = resolve_editions(["L2"], as_of="2026-06-01")
    assert any("older_edition_missing" in w for w in warn)

    # МРОТ до 2026 -> предупреждение older_edition_missing
    docs, ed, warn = resolve_editions(["L5"], as_of="2025-06-01")
    assert any("older_edition_missing" in w for w in warn)


def test_retrieve_smoke_on_dataset():
    with open("eval/dataset.jsonl", "r", encoding="utf-8") as f:
        dataset = [json.loads(line) for line in f]

    hit_count = 0
    for item in dataset:
        qid = item["id"]
        q_text = item["question"]
        gold_docs = item["gold_docs"]

        qinfo = QueryInfo(original=q_text, last_user=q_text)
        res = retrieve(qinfo)

        retrieved_doc_ids = {c.doc_id for c in res.chunks}

        # Если вопрос требует конкретный gold_doc, он должен быть среди найденных
        if gold_docs:
            has_gold = any(gd in retrieved_doc_ids for gd in gold_docs)
            assert has_gold, f"Question {qid} failed: gold {gold_docs} not in {retrieved_doc_ids}"
            hit_count += 1

    print(f"Dataset recall: {hit_count}/{len(dataset)} questions covered!")


if __name__ == "__main__":
    test_kb_meta_and_load()
    print("test_kb_meta_and_load OK")
    test_quarantine_integrity()
    print("test_quarantine_integrity OK")
    test_dates_extraction()
    print("test_dates_extraction OK")
    test_entity_detection_and_ambiguity()
    print("test_entity_detection_and_ambiguity OK")
    test_resolve_editions()
    print("test_resolve_editions OK")
    test_retrieve_smoke_on_dataset()
    print("ALL TESTS PASSED!")
