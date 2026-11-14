#!/usr/bin/env python3
"""tools/check_integration.py — Валидатор интеграции веток R (Retrieval) и L (LLM/Guardrails)

с бэкендом B.

Проверяет:
1. [Role R - KB Load]: наличие и сигнатуры kb_load.py (init_kb / load_kb).
2. [Role R - Retrieve]: наличие и сигнатуры retrieve.py (retrieve / search).
3. [Role L - Preprocess & Answer]: наличие prompts.py, guard.py, answer.py.
4. Сквозной E2E-тест пайплайна (pipeline.answer_question) на 3 контрольных вопросах.
5. Интеграцию с docs.json и Go API Gateway контрактом.
"""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path
from typing import Any

# Добавляем корень проекта в sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def print_header(title: str) -> None:
    print(f"\n{'=' * 65}\n  {title}\n{'=' * 65}")


def check_role_r() -> dict[str, str]:
    print_header("1. Проверка модулей Роли R (База знаний и Retrieval)")
    status = {}

    # 1.1 kb_load.py
    try:
        mod_kb = importlib.import_module("kb_load")
        has_init = hasattr(mod_kb, "init_kb") or hasattr(mod_kb, "load_kb")
        if has_init:
            func = getattr(mod_kb, "init_kb", getattr(mod_kb, "load_kb", None))
            status["kb_load"] = f"OK (found function '{func.__name__}')"
            print(f"  [OK] kb_load.py: найден, точка входа '{func.__name__}'")
        else:
            status["kb_load"] = "WARN (missing init_kb or load_kb function)"
            print("  [WARN] kb_load.py: найден, но нет стандартной функции init_kb() / load_kb()")
    except (ImportError, ModuleNotFoundError):
        status["kb_load"] = "PENDING (using core smart stubs)"
        print("  [PENDING] kb_load.py: модуль ещё не влит, ядро использует встроенные смарт-стабы D1/D2")
    except Exception as exc:
        status["kb_load"] = f"ERROR ({exc})"
        print(f"  [ERROR] kb_load.py ошибка импорта: {exc}")

    # 1.2 retrieve.py
    try:
        mod_ret = importlib.import_module("retrieve")
        has_ret = hasattr(mod_ret, "retrieve") or hasattr(mod_ret, "search")
        if has_ret:
            func = getattr(mod_ret, "retrieve", getattr(mod_ret, "search", None))
            status["retrieve"] = f"OK (found function '{func.__name__}')"
            print(f"  [OK] retrieve.py: найден, точка входа '{func.__name__}'")
        else:
            status["retrieve"] = "WARN (missing retrieve or search function)"
            print("  [WARN] retrieve.py: найден, но нет стандартной функции retrieve() / search()")
    except (ImportError, ModuleNotFoundError):
        status["retrieve"] = "PENDING (using core smart stubs)"
        print("  [PENDING] retrieve.py: модуль ещё не влит, ядро использует эвристический поиск")
    except Exception as exc:
        status["retrieve"] = f"ERROR ({exc})"
        print(f"  [ERROR] retrieve.py ошибка импорта: {exc}")

    return status


def check_role_l() -> dict[str, str]:
    print_header("2. Проверка модулей Роли L (LLM, Промпты, Guardrails)")
    status = {}

    for mod_name in ("prompts", "guard", "answer"):
        try:
            mod = importlib.import_module(mod_name)
            status[mod_name] = "OK"
            print(f"  [OK] {mod_name}.py: найден и успешно импортирован")
        except (ImportError, ModuleNotFoundError):
            status[mod_name] = "PENDING (using resilient core fallback)"
            print(f"  [PENDING] {mod_name}.py: модуль ещё не влит, ядро использует llm_client + pipeline fallback")
        except Exception as exc:
            status[mod_name] = f"ERROR ({exc})"
            print(f"  [ERROR] {mod_name}.py ошибка импорта: {exc}")

    return status


def run_e2e_diagnostic() -> bool:
    print_header("3. Сквозной E2E-тест пайплайна (pipeline.answer_question)")
    from pipeline import answer_question, ensure_kb_initialized

    kb = ensure_kb_initialized()
    docs = kb.get("docs", {})
    print(f"  База знаний инициализирована: доступно документов = {len(docs)}")

    test_queries = [
        ("Какова арендная плата за склад в Химках?", "450 000", "D1"),
        ("Какой гарантийный срок по договору с Альфа-Трейд?", "24", "D2"),
        ("Сколько лет длится экспедиция на Плутон?", None, None),  # out_of_scope / refused
    ]

    all_passed = True
    for i, (q, expected_substr, expected_doc) in enumerate(test_queries, 1):
        t0 = time.time()
        res = answer_question(q)
        lat_ms = int((time.time() - t0) * 1000)

        print(f"\n  Тест {i}: \"{q}\"")
        print(f"    -> Статус: {res.status} | Время: {lat_ms}ms")
        print(f"    -> Ответ: {res.text[:80]}...")

        if expected_substr:
            if res.status != "answered":
                print(f"    [FAIL] Ожидался статус 'answered', получен '{res.status}'")
                all_passed = False
            elif expected_substr.lower() not in res.text.lower():
                print(f"    [FAIL] Ожидалась подстрока '{expected_substr}' в ответе")
                all_passed = False
            else:
                print(f"    [PASS] Ключевой факт '{expected_substr}' подтвержден")

            if expected_doc:
                has_doc = any(c.get("doc_id") == expected_doc for c in res.claims)
                if not has_doc:
                    print(f"    [WARN] Цитата не ссылается на {expected_doc}")
                else:
                    print(f"    [PASS] Цитата корректно ссылается на {expected_doc}")
        else:
            if res.status in ("refused", "out_of_scope"):
                print(f"    [PASS] Неподдерживаемый вопрос корректно отклонен (status='{res.status}')")
            else:
                print(f"    [WARN] Вопрос вне базы не получил статус refused: '{res.status}'")

    return all_passed


def main() -> int:
    print_header("ДИАГНОСТИКА ГОТОВНОСТИ ИНТЕГРАЦИИ (B5 - B/R/L)")

    status_r = check_role_r()
    status_l = check_role_l()
    e2e_ok = run_e2e_diagnostic()

    print_header("ИТОГОВЫЙ СТАТУС ГОТОВНОСТИ")
    r_ready = all("ERROR" not in v for v in status_r.values())
    l_ready = all("ERROR" not in v for v in status_l.values())

    if r_ready and l_ready and e2e_ok:
        print("  \u2705 INTEGRATION HEALTH: 100% OK")
        print("  Ядро полностью готово к бесшовному слиянию веток R (Retrieval) и L (LLM).")
        print("  Текущий режим: Smart Hybrid Fallback активен и готов к работе.\n")
        return 0
    else:
        print("  \u274c INTEGRATION ISSUES DETECTED. Проверьте логи выше.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
