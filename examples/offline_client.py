"""Только тестовый клиент с заранее заданным сценарием; сети здесь нет."""

import json
from copy import deepcopy

from schemas import LLMResult


class ScriptedLLM:
    is_test_client = True

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, *, json_mode=False, temperature=0.0, max_tokens=None, timeout=60.0):
        self.calls.append({"messages": deepcopy(messages), "json_mode": json_mode,
                           "temperature": temperature, "max_tokens": max_tokens, "timeout": timeout})
        if not self.responses:
            raise AssertionError("Сценарий тестового клиента исчерпан")
        response = self.responses.pop(0)
        if callable(response):
            response = response()
        if isinstance(response, Exception):
            raise response
        if isinstance(response, LLMResult):
            return response
        if isinstance(response, dict):
            return LLMResult(json.dumps(response, ensure_ascii=False))
        return LLMResult(response)


def review_ok(count=1):
    return {"claims_check": [{"claim_index": i, "support": "full"} for i in range(count)],
            "fabricated": [], "unanswered_parts": [], "premise_issue": "", "edition_issue": "", "verdict": "ok"}


def query_response(question, **overrides):
    response = {"last_question": question, "query_type": "normal", "injection": {"detected": False},
                "dates": [], "date_matters": False, "compare_editions": False,
                "subquestions": [], "entities": {}}
    response.update(overrides)
    return response
