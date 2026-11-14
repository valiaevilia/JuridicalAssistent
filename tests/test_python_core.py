from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import httpx
import pytest

from config import cfg
from llm_client import ResilientLLMClient, clean_think_tags, extract_json_str
from pipeline import answer_question, ensure_kb_initialized
from schemas import AnswerResult, Chunk, QueryInfo, RetrievalResult
from worker import ThreadingHTTPServer, InternalBridgeHandler


def test_schemas_serialization():
    chunk = Chunk(
        chunk_id="D1#3.1",
        doc_id="D1",
        doc_title="Договор аренды",
        doc_kind="contract",
        locator="п. 3.1",
        breadcrumbs=["Раздел 3", "п. 3.1"],
        text="450 000 руб.",
    )
    d = chunk.to_dict()
    assert d["chunk_id"] == "D1#3.1"
    assert d["breadcrumbs"] == ["Раздел 3", "п. 3.1"]

    ans = AnswerResult(
        text="Ответ",
        status="answered",
        claims=[{"doc_id": "D1", "chunk_id": "D1#3.1", "locator": "п. 3.1", "quote": "450 000"}],
    )
    ans_dict = ans.to_dict()
    assert ans_dict["status"] == "answered"
    assert len(ans_dict["claims"]) == 1


def test_clean_think_tags():
    raw = "<think>Некие внутренние рассуждения модели</think>Итоговый юридический ответ."
    assert clean_think_tags(raw) == "Итоговый юридический ответ."

    # Незакрытый тег
    unclosed = "Часть ответа.<think>Обрыв на рассуждениях"
    assert clean_think_tags(unclosed) == "Часть ответа."


def test_extract_json_str():
    # 1. В кодовом блоке markdown
    raw_md = '```json\n{"status": "answered", "text": "Пункт 3.1"}\n```'
    parsed = extract_json_str(raw_md)
    data = json.loads(parsed)
    assert data["status"] == "answered"

    # 2. Со скобками внутри строки
    raw_complex = 'Произвольный текст перед {"answer": "Аренда {450 000} руб.", "val": 123} текст после'
    parsed_complex = extract_json_str(raw_complex)
    data_complex = json.loads(parsed_complex)
    assert data_complex["answer"] == "Аренда {450 000} руб."


def test_llm_client_chat_retry_and_think():
    attempts = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            # Первая попытка - 429
            return httpx.Response(429, headers={"Retry-After": "0.01"})
        # Вторая попытка - успех
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "<think>Thinking...</think>Готовый ответ"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"total_tokens": 10},
            },
        )

    transport = httpx.MockTransport(mock_handler)
    client = ResilientLLMClient(transport=transport)
    try:
        res = client.chat([{"role": "user", "content": "Тест"}])
        assert res.text == "Готовый ответ"
        assert attempts == 2
    finally:
        client.close()


def test_llm_client_embeddings_cache():
    call_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        data = json.loads(request.content.decode("utf-8"))
        inputs = data["input"]
        return httpx.Response(
            200,
            json={"data": [{"index": i, "embedding": [0.1 * i, 0.2]} for i in range(len(inputs))]},
        )

    transport = httpx.MockTransport(mock_handler)
    client = ResilientLLMClient(transport=transport)
    try:
        texts = ["Текст 1", "Текст 2"]
        emb1 = client.embed(texts)
        assert len(emb1) == 2
        assert call_count == 1

        # Повторный вызов тех же текстов должен браться из кэша без HTTP запроса
        emb2 = client.embed(texts)
        assert len(emb2) == 2
        assert call_count == 1
    finally:
        client.close()


def test_llm_client_reranker_fallback_and_circuit_breaker():
    attempt = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempt
        attempt += 1
        # Обе модели реранкера возвращают 404
        return httpx.Response(404, text="Model not found")

    transport = httpx.MockTransport(mock_handler)
    client = ResilientLLMClient(transport=transport)
    try:
        docs = ["Фрагмент 1", "Фрагмент 2"]
        ranked = client.rerank("Вопрос", docs, top_n=2)
        # При падении реранкер не роняет процесс, а включает Circuit Breaker и отдает исходный порядок
        assert len(ranked) == 2
        assert ranked[0][0] == 0
        assert client._reranker_disabled is True

        # После включения Circuit Breaker повторный вызов не делает HTTP-запросов
        ranked_cached = client.rerank("Другой вопрос", docs, top_n=2)
        assert len(ranked_cached) == 2
    finally:
        client.close()


def test_pipeline_smart_stubs():
    ensure_kb_initialized()

    # 1. Вопрос по аренде
    res_lease = answer_question("Какова ставка арендной платы склада в Химках?")
    assert res_lease.status == "answered"
    assert "450 000" in res_lease.text
    assert len(res_lease.claims) >= 1
    assert res_lease.claims[0]["doc_id"] == "D1"

    # 2. Вопрос по гарантии
    res_warranty = answer_question("Какой гарантийный срок по договору с Альфа-Трейд?")
    assert res_warranty.status == "answered"
    assert "24 месяца" in res_warranty.text
    assert res_warranty.claims[0]["doc_id"] == "D2"

    # 3. Вопрос по оплате Альфа-Трейд
    res_pay = answer_question("Срок оплаты по договору с Альфа-Трейд")
    assert res_pay.status == "answered"
    assert "30 календарных дней" in res_pay.text

    # 4. Вопрос без ответа в стабе -> отказ
    res_none = answer_question("Каковы правила полета на Марс?")
    assert res_none.status == "refused"


def test_pipeline_budget_guard():
    # Симулируем ситуацию, когда до дедлайна осталось 100 секунд (< 150 с)
    now = time.time()
    res_s8_skip = answer_question("Вопрос про аренду", deadline_ts=now + 100.0)
    assert res_s8_skip.debug.get("skip_s8") is True

    # Экстренный останов: осталось 10 секунд (< 25 с)
    res_emergency = answer_question("Вопрос про аренду", deadline_ts=now + 10.0)
    assert res_emergency.status == "refused"
    assert "emergency_stop" in res_emergency.warnings


def test_python_worker_http():
    # Запускаем worker.py в отдельном потоке на свободном порту
    port = 8999
    server = ThreadingHTTPServer(("127.0.0.1", port), InternalBridgeHandler)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()

    try:
        # 1. Health check
        resp_h = httpx.get(f"http://127.0.0.1:{port}/internal/health", timeout=5.0)
        assert resp_h.status_code == 200
        assert resp_h.json()["status"] == "ok"

        # 2. Answer question
        resp_ans = httpx.post(
            f"http://127.0.0.1:{port}/internal/answer",
            json={"question": "Какова ставка арендной платы склада в Химках?"},
            timeout=10.0,
        )
        assert resp_ans.status_code == 200
        data = resp_ans.json()
        assert data["status"] == "answered"
        assert "450 000" in data["text"]
    finally:
        server.shutdown()
        server.server_close()
