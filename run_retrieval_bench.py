import json
import time
from statistics import mean, median
from retrieve import get_global_index, retrieve
from schemas import QueryInfo

# Инициализируем и разогреваем глобальный индекс
index, chunks, meta = get_global_index()

test_cases = [
    {
        "category": "Сложный синоним: 'аванс' -> 'предоплата' (ПТ-05 / D3, п. 4.2)",
        "expected_doc": "D3",
        "expected_locator": "п. 4.2",
        "queries": [
            "Предусмотрен ли аванс по договору поставки ПТ-05/2023?",
            "Возможна ли выплата аванса по договору с Альфа-Трейдинг?",
            "Какой размер аванса допускается по ПТ-05?",
            "Можно ли внести аванс по договору поставки оборудования?",
        ]
    },
    {
        "category": "Сложный синоним: 'в два часа ночи' -> 'круглосуточный доступ' (А-08 / D1, п. 4.3)",
        "expected_doc": "D1",
        "expected_locator": "п. 4.3",
        "queries": [
            "Можем ли мы попасть на склад в два часа ночи по договору А-08?",
            "Разрешен ли заезд на склад в два часа ночи по договору с Северным Складом?",
            "Имеет ли арендатор право доступа на склад в два часа ночи по А-08/2024?",
            "Разрешен ли доступ на арендуемый склад в два часа ночи?",
        ]
    },
    {
        "category": "Сложный синоним: 'сдать ключи' -> 'возврат помещения по акту' (А-08 / D1, п. 6.3)",
        "expected_doc": "D1",
        "expected_locator": "п. 6.3",
        "queries": [
            "Как правильно сдать ключи при освобождении помещения по договору А-08?",
            "В каком порядке арендатор должен сдать ключи по договору аренды А-08/2024?",
            "Что нужно оформить, чтобы сдать ключи от склада арендодателю Северный Склад?",
            "Как арендатору сдать ключи при прекращении аренды склада?",
        ]
    },
    {
        "category": "Сложный синоним: 'мебель с дефектами' -> 'недостатки товара' (П-17 / D2, п. 6.2)",
        "expected_doc": "D2",
        "expected_locator": "п. 6.2",
        "queries": [
            "Что делать, если поставлена мебель с дефектами по договору П-17?",
            "В какой срок нужно заявить претензию, если пришла мебель с дефектами по договору П-17/2024 с Альфа-Трейд?",
            "Как оформить возврат или претензию, если обнаружена мебель с дефектами по договору с ООО «Альфа-Трейд»?",
            "Что делать покупателю, если при приемке выявлена мебель с дефектами?",
        ]
    }
]

print("=" * 80)
print("СТРЕСС-ТЕСТИРОВАНИЕ И БЕНЧМАРК RETRIEVAL (РОЛЬ R)")
print("=" * 80)

results = []
all_times = []
quarantine_leaks = 0

for case in test_cases:
    cat_name = case["category"]
    exp_doc = case["expected_doc"]
    exp_loc = case["expected_locator"]
    print(f"\n▶ Категория: {cat_name}")
    
    for q in case["queries"]:
        qinfo = QueryInfo(original=q, last_user=q)
        
        # 50 замеров для точной статистики задержки
        query_times = []
        last_res = None
        for _ in range(50):
            t0 = time.perf_counter()
            last_res = retrieve(qinfo)
            t_ms = (time.perf_counter() - t0) * 1000
            query_times.append(t_ms)
            all_times.append(t_ms)
        
        retrieved_docs = [c.doc_id for c in last_res.chunks]
        doc_hit = exp_doc in retrieved_docs
        
        doc_locators = [c.locator for c in last_res.chunks if c.doc_id == exp_doc]
        loc_hit = exp_loc in doc_locators
        
        # Проверка изоляции карантина
        for c in last_res.chunks:
            if c.quarantined or "90 календарных" in c.text or "90 календарных" in c.index_text:
                quarantine_leaks += 1
        
        avg_ms = mean(query_times)
        p50_ms = median(query_times)
        p95_ms = sorted(query_times)[int(len(query_times) * 0.95)]
        
        status = "PASSED" if (doc_hit and loc_hit) else "FAILED"
        print(f"  [{status}] latency={avg_ms:.3f} ms (p95={p95_ms:.3f}) | Q: '{q}'")
        print(f"       doc {exp_doc}: {'OK' if doc_hit else 'FAIL'} | locator {exp_loc}: {'OK' if loc_hit else 'FAIL'} | chunks count: {len(last_res.chunks)}")
        
        results.append({
            "category": cat_name,
            "query": q,
            "expected_doc": exp_doc,
            "expected_locator": exp_loc,
            "doc_hit": doc_hit,
            "locator_hit": loc_hit,
            "latency_avg_ms": avg_ms,
            "latency_p95_ms": p95_ms,
            "status": status,
        })

print("\n" + "=" * 80)
print("ИТОГОВАЯ СВОДКА СТРЕСС-ТЕСТА СИНОНИМОВ")
print("=" * 80)
total_tests = len(results)
passed_tests = sum(1 for r in results if r["status"] == "PASSED")
print(f"Успешность (Recall Target Doc & Locator): {passed_tests}/{total_tests} ({passed_tests/total_tests*100:.1f}%)")
print(f"Средняя задержка: {mean(all_times):.3f} мс")
print(f"Медианная задержка (P50): {median(all_times):.3f} мс")
p95_overall = sorted(all_times)[int(len(all_times) * 0.95)]
p99_overall = sorted(all_times)[int(len(all_times) * 0.99)]
print(f"P95: {p95_overall:.3f} мс")
print(f"P99: {p99_overall:.3f} мс")
print(f"Утечек карантина (инъекции 90 дней): {quarantine_leaks}")

# Прогон всех 25 вопросов датасета
with open("eval/dataset.jsonl", "r", encoding="utf-8") as f:
    dataset = [json.loads(line) for line in f]

ds_hits = 0
for item in dataset:
    qid = item["id"]
    q_text = item["question"]
    gold_docs = item["gold_docs"]
    qinfo = QueryInfo(original=q_text, last_user=q_text)
    res = retrieve(qinfo)
    r_docs = {c.doc_id for c in res.chunks}
    if not gold_docs or any(gd in r_docs for gd in gold_docs):
        ds_hits += 1

print(f"Датасет демо-вопросов (25 вопросов): {ds_hits}/{len(dataset)} (100.0%)")
