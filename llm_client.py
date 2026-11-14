from __future__ import annotations

import email.utils
import hashlib
import json
import logging
import random
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from config import cfg

logger = logging.getLogger("llm_client")


@dataclass
class LLMResult:
    text: str
    finish_reason: str = "stop"
    usage: dict[str, Any] = field(default_factory=dict)
    raw_response: dict[str, Any] = field(default_factory=dict)


def clean_think_tags(text: str) -> str:
    """Очищает блоки рассуждений <think>...</think> DeepSeek V4.1 Flash,

    включая незакрытые теги.
    """
    if not text:
        return ""
    # Полные закрытые блоки
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Если остался незакрытый тег <think>
    if "<think>" in cleaned:
        cleaned = cleaned.split("<think>")[0]
    return cleaned.strip()


def extract_json_str(raw: str) -> str:
    """Извлекает валидную JSON-строку: срез markdown-ограждений и

    скобочный автомат для поиска сбалансированного {...}.
    """
    if not raw:
        return "{}"

    text = raw.strip()
    # Срез кодовых блоков markdown ```json ... ```
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

    # Поиск первого открывающего '{'
    start_idx = text.find("{")
    if start_idx == -1:
        return text

    depth = 0
    in_string = False
    escape = False

    for i in range(start_idx, len(text)):
        char = text[i]

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start_idx : i + 1]

    return text[start_idx:]


class ResilientLLMClient:
    """Потокобезопасный HTTP-клиент для DeepSeek V4.1 Flash,

    bge-m3 и реранкеров с ретраями, пулом соединений и Circuit Breaker.
    """

    RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(
            timeout=cfg.HTTP_TIMEOUT_SEC,
            limits=httpx.Limits(max_keepalive_connections=16, max_connections=32),
            transport=transport,
        )
        self._sem = threading.BoundedSemaphore(cfg.MAX_WORKERS * 2)
        self._embed_cache: dict[str, list[float]] = {}
        self._cache_lock = threading.Lock()
        self._reranker_disabled: bool = False
        self._reranker_model: str = cfg.RERANKER_MODEL

    def close(self) -> None:
        self._client.close()

    def _parse_retry_after(self, response: httpx.Response | None) -> float:
        if not response:
            return 0.0
        header = response.headers.get("Retry-After", "").strip()
        if not header:
            return 0.0
        try:
            return max(0.0, min(10.0, float(header)))
        except ValueError:
            pass
        try:
            dt = email.utils.parsedate_to_datetime(header)
            delay = dt.timestamp() - time.time()
            return max(0.0, min(10.0, delay))
        except Exception:
            return 0.0

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
        timeout: float | None = None,
    ) -> LLMResult:
        temp = cfg.TEMPERATURE if temperature is None else temperature
        tokens = cfg.MAX_TOKENS if max_tokens is None else max_tokens
        req_timeout = cfg.HTTP_TIMEOUT_SEC if timeout is None else timeout

        payload: dict[str, Any] = {
            "model": cfg.LLM_MODEL,
            "messages": messages,
            "temperature": temp,
            "max_tokens": tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {cfg.LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        url = f"{cfg.LLM_BASE_URL}/chat/completions"

        for attempt in range(cfg.MAX_RETRIES + 1):
            try:
                with self._sem:
                    resp = self._client.post(url, json=payload, headers=headers, timeout=req_timeout)

                if resp.status_code == 400 and json_mode and "response_format" in resp.text:
                    # Некоторые прокси не поддерживают response_format -> повторяем без него
                    del payload["response_format"]
                    continue

                if resp.status_code in self.RETRYABLE_STATUSES:
                    if attempt < cfg.MAX_RETRIES:
                        wait = self._parse_retry_after(resp) or (0.5 * (2**attempt) + random.uniform(0.1, 0.4))
                        time.sleep(wait)
                        continue
                    resp.raise_for_status()

                resp.raise_for_status()
                data = resp.json()
                choice = data.get("choices", [{}])[0]
                content = choice.get("message", {}).get("content", "") or ""
                finish_reason = choice.get("finish_reason", "stop")

                # Проверка на обрезку длины: при finish_reason == "length" удваиваем max_tokens (до 8192)
                if finish_reason == "length" and tokens < 8192 and attempt < cfg.MAX_RETRIES:
                    tokens = min(8192, tokens * 2)
                    payload["max_tokens"] = tokens
                    continue

                cleaned_text = clean_think_tags(content)
                return LLMResult(
                    text=cleaned_text,
                    finish_reason=finish_reason,
                    usage=data.get("usage", {}),
                    raw_response=data,
                )

            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                if attempt < cfg.MAX_RETRIES:
                    wait = 0.5 * (2**attempt) + random.uniform(0.1, 0.4)
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"Chat completion failed after {attempt} retries: {exc}") from exc

        raise RuntimeError(f"Chat completion exceeded max retries ({cfg.MAX_RETRIES})")

    def embed(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        missing_indices: list[int] = []
        missing_texts: list[str] = []

        with self._cache_lock:
            for i, text in enumerate(texts):
                key = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if key in self._embed_cache:
                    results[i] = self._embed_cache[key]
                else:
                    missing_indices.append(i)
                    missing_texts.append(text)

        if not missing_texts:
            return [res for res in results if res is not None]

        url = f"{cfg.LLM_BASE_URL}/embeddings"
        headers = {
            "Authorization": f"Bearer {cfg.EMBEDDER_API_KEY}",
            "Content-Type": "application/json",
        }

        for start in range(0, len(missing_texts), batch_size):
            batch_slice = missing_texts[start : start + batch_size]
            batch_orig_indices = missing_indices[start : start + batch_size]
            payload = {
                "model": cfg.EMB_MODEL,
                "input": batch_slice,
                "encoding_format": "float",
            }

            batch_succeeded = False
            for attempt in range(cfg.MAX_RETRIES + 1):
                try:
                    with self._sem:
                        resp = self._client.post(url, json=payload, headers=headers)
                    if resp.status_code in self.RETRYABLE_STATUSES and attempt < cfg.MAX_RETRIES:
                        wait = self._parse_retry_after(resp) or (0.5 * (2**attempt) + random.uniform(0.1, 0.4))
                        time.sleep(wait)
                        continue
                    resp.raise_for_status()
                    data = resp.json().get("data", [])
                    # Сортировка по index внутри data
                    sorted_data = sorted(data, key=lambda x: x.get("index", 0))

                    with self._cache_lock:
                        for idx_in_batch, item in enumerate(sorted_data):
                            emb = item.get("embedding", [])
                            orig_idx = batch_orig_indices[idx_in_batch]
                            results[orig_idx] = emb
                            text_key = hashlib.sha256(batch_slice[idx_in_batch].encode("utf-8")).hexdigest()
                            self._embed_cache[text_key] = emb

                    batch_succeeded = True
                    break
                except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                    if attempt < cfg.MAX_RETRIES:
                        wait = 0.5 * (2**attempt) + random.uniform(0.1, 0.4)
                        time.sleep(wait)
                        continue
                    logger.warning("Embeddings call failed on batch: %s", exc)
                    break

            if not batch_succeeded:
                # В крайнем случае заполняем нулями чтобы не ронять пайплайн
                zero_emb = [0.0] * 1024
                for orig_idx in batch_orig_indices:
                    if results[orig_idx] is None:
                        results[orig_idx] = zero_emb

        return [res if res is not None else [0.0] * 1024 for res in results]

    def rerank(self, query: str, documents: list[str], top_n: int | None = None) -> list[tuple[int, float]]:
        if not documents:
            return []

        limit = min(len(documents), top_n or cfg.RERANKER_TOP_N)

        if self._reranker_disabled:
            return [(i, 1.0 / (i + 1)) for i in range(len(documents))[:limit]]

        url = f"{cfg.LLM_BASE_URL}/rerank"
        headers = {
            "Authorization": f"Bearer {cfg.RERANKER_API_KEY}",
            "Content-Type": "application/json",
        }

        models_to_try = [self._reranker_model]
        if cfg.RERANKER_FALLBACK_MODEL and cfg.RERANKER_FALLBACK_MODEL != self._reranker_model:
            models_to_try.append(cfg.RERANKER_FALLBACK_MODEL)

        for model in models_to_try:
            payload = {
                "model": model,
                "query": query,
                "documents": documents,
                "top_n": limit,
            }

            for attempt in range(cfg.MAX_RETRIES + 1):
                try:
                    with self._sem:
                        resp = self._client.post(url, json=payload, headers=headers)
                    if resp.status_code in (404, 400) and model != models_to_try[-1]:
                        # Модель не найдена на прокси -> пробуем fallback модель
                        break

                    if resp.status_code in self.RETRYABLE_STATUSES and attempt < cfg.MAX_RETRIES:
                        wait = self._parse_retry_after(resp) or (0.5 * (2**attempt) + random.uniform(0.1, 0.4))
                        time.sleep(wait)
                        continue

                    if resp.is_error:
                        break

                    data = resp.json()
                    raw_results = data.get("results", [])
                    ranked: list[tuple[int, float]] = []
                    for item in raw_results:
                        idx = item.get("index", 0)
                        score = float(item.get("relevance_score", 0.0))
                        ranked.append((idx, score))

                    self._reranker_model = model
                    return ranked[:limit]

                except Exception as exc:
                    if attempt < cfg.MAX_RETRIES:
                        time.sleep(0.5 * (2**attempt))
                        continue
                    logger.warning("Rerank error with model %s: %s", model, exc)
                    break

        # Если ни одна модель не ответила — включаем Circuit Breaker
        self._reranker_disabled = True
        sys.stderr.write(
            f"[llm_client] Reranker unavailable at {url}. Circuit breaker opened; using fallback ranking.\n"
        )
        return [(i, 1.0 / (i + 1)) for i in range(len(documents))[:limit]]


# Глобальный синглтон клиента
llm_client = ResilientLLMClient()
