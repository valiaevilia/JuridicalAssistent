"""Проверка реальных стыков B/R/L; модель отвечает через MockTransport."""

import json
from dataclasses import replace
from unittest.mock import patch

import httpx

import pipeline
from config import LConfig, cfg
from examples.offline_client import review_ok
from llm_client import ResilientLLMClient
from schemas import LLMResult


def test_real_pipeline_calls_r_l_and_b_without_stub(monkeypatch):
    # HTTP-клиент B, реальная выдача R, реальные S1/S6/S7/S8 роли L.
    stages = []
    quarantine_seen = []
    actual_retrieve = __import__('retrieve').retrieve

    def inspect_retrieval(qinfo):
        result = actual_retrieve(qinfo)
        quarantine_seen.extend(result.quarantine)
        assert qinfo.as_of is None  # 2024 в номере договора не дата события
        assert result.as_of is None
        return result

    def respond(request):
        payload = json.loads(request.content)
        data = json.loads(payload['messages'][1]['content'])
        if 'last_user' in data and 'fragments' not in data:
            stages.append('S1')
            text = {'last_question': data['last_user'], 'query_type': 'normal',
                    'injection': {'detected': False}, 'dates': [], 'date_matters': False,
                    'compare_editions': False, 'subquestions': [], 'entities': {}}
        elif 'draft' in data:
            stages.append('S8')
            text = review_ok(len(data['draft']['claims']))
        else:
            stages.append('S6')
            c = next(c for c in data['fragments'] if c['doc_id'] == 'D2' and c['locator'] == 'п. 4.2')
            claim = {'text': c['text'], 'chunk': c['label'], 'quote': c['text']}
            text = {'status': 'answered', 'answer': c['text'], 'claims': [claim],
                    'missing': [], 'assumptions': [], 'calc': []}
            assert all('90 календарных дней' not in c['text'] for c in data['fragments'])
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(text, ensure_ascii=False)},
                                                      'finish_reason': 'stop'}]})

    monkeypatch.setattr(pipeline, 'cfg', replace(cfg, DEMO_MODE=False))
    monkeypatch.setattr(__import__('retrieve'), 'retrieve', inspect_retrieval)
    client = ResilientLLMClient(transport=httpx.MockTransport(respond))
    try:
        result = pipeline.answer_question('Какой срок оплаты по договору № П-17/2024?',
                                          client=client, config=LConfig())
    finally:
        client.close()
    assert result.status == 'answered', result.debug
    assert stages == ['S1', 'S6', 'S8']
    assert result.claims[0]['doc_id'] == 'D2'
    assert result.claims[0]['locator'] == 'п. 4.2'
    fragments = pipeline.ensure_kb_initialized()['docs']['D2']['fragments']
    source = next(f['text'] for f in fragments if f['fragment_id'] == result.claims[0]['chunk_id'])
    assert result.claims[0]['quote'] in source
    assert '30' in result.text and '90' not in result.text
    assert not result.debug.get('stub')
    assert quarantine_seen
    assert result.to_dict()['claims'] == result.claims


def test_missing_model_configuration_is_not_a_successful_stub(monkeypatch):
    monkeypatch.setattr(pipeline, 'cfg', replace(cfg, DEMO_MODE=False, LLM_API_KEY='dummy-key'))
    result = pipeline.answer_question('Какова арендная плата за склад?', config=LConfig())
    assert result.status == 'refused'
    assert result.claims == []
    assert 'technical_failure:ConfigurationError' in result.warnings
    assert '450 000' not in result.text
    assert 'технической' in result.text


def test_b_client_uses_shared_result_and_l_controls_length_retries():
    count = []

    def respond(request):
        count.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"status":'}, 'finish_reason': 'length'}]})

    client = ResilientLLMClient(transport=httpx.MockTransport(respond))
    try:
        result = client.chat([{'role': 'user', 'content': 'Тест'}], timeout=1)
    finally:
        client.close()
    assert isinstance(result, LLMResult)
    assert result.finish_reason == 'length'
    assert len(count) == 1


def test_b_client_retries_share_one_total_timeout():
    now, calls = [100.0], []

    def respond(request):
        calls.append(request)
        now[0] += 0.8
        return httpx.Response(429, headers={'Retry-After': '0.5'})

    client = ResilientLLMClient(transport=httpx.MockTransport(respond))
    try:
        with patch('llm_client.time.monotonic', side_effect=lambda: now[0]):
            try:
                client.chat([{'role': 'user', 'content': 'Тест'}], timeout=1)
            except TimeoutError:
                pass
            else:
                raise AssertionError('Общий timeout не соблюдён')
    finally:
        client.close()
    assert len(calls) == 1


def test_r_date_adapter_preserves_interval_and_ignores_contract_year():
    assert pipeline._extract_date_hints('Договор № П-17/2024. Какой срок оплаты?') == []
    dates = pipeline._extract_date_hints('Нужно одобрение договора в августе 2024 года')
    assert dates[0]['role'] == 'signing'
    assert (dates[0]['iso_from'], dates[0]['iso_to']) == ('2024-08-01', '2024-08-31')


def test_all_source_ids_are_unique_and_resolve_in_document_export():
    kb = pipeline.ensure_kb_initialized()
    chunks = kb['chunks']
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    by_id = {f['fragment_id']: f for doc in kb['docs'].values() for f in doc['fragments']}
    for c in chunks:
        assert by_id[c.chunk_id]['text'] == c.text
        assert by_id[c.chunk_id]['doc_id'] == c.doc_id


def test_contract_requisites_do_not_change_last_normative_clause():
    chunks = pipeline.ensure_kb_initialized()['chunks']
    payment_contract = [c for c in chunks if c.doc_id == 'D2']
    last_clause = next(c for c in payment_contract if c.locator == 'п. 9.2')
    assert 'Поставщик: ООО' not in last_clause.text
    requisites = next(c for c in payment_contract if c.chunk_id == 'D2#requisites')
    assert 'Альфа-Трейд' in requisites.text
