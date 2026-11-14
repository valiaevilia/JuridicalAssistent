from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def env(name: str, default: str = "") -> str:
    val = os.getenv(name, "").strip()
    if not val or val == name:
        return default
    return val


def env_int(name: str, default: int, low: int = 1, high: int = 65535) -> int:
    raw = env(name, "")
    if not raw:
        return default
    try:
        parsed = int(raw)
        return max(low, min(high, parsed))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    raw = env(name, "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    # Директории и файлы
    DATA_DIR: Path = Path(env("DATA_DIR", "data"))
    SUBMISSION_PATH: Path = Path(env("SUBMISSION_PATH", "submission.csv"))
    DOCS_JSON_PATH: Path = Path(env("DOCS_JSON_PATH", "docs.json"))

    # Сетевые адреса и ключи
    LLM_BASE_URL: str = (
        env("LLM_BASE_URL") or env("BASE_URL") or env("OPENAI_BASE_URL") or "http://localhost:8001/v1"
    ).rstrip("/")
    LLM_API_KEY: str = env("LLM_API_KEY") or env("OPENAI_API_KEY") or "dummy-key"
    EMBEDDER_API_KEY: str = env("EMBEDDER_API_KEY") or LLM_API_KEY
    RERANKER_API_KEY: str = env("RERANKER_API_KEY") or LLM_API_KEY

    # Имена моделей
    LLM_MODEL: str = (
        env("LLM_MODEL") or env("GEN_MODEL") or env("OPENAI_MODEL") or "deepseek/deepseek-v4.1-flash"
    )
    EMB_MODEL: str = env("EMB_MODEL") or env("EMBEDDER_MODEL") or "baai/bge-m3"
    RERANKER_MODEL: str = env("RERANKER_MODEL") or "cohere/rerank-5-fast"
    RERANKER_FALLBACK_MODEL: str = "Qwen/Qwen3-Reranker-8B"

    # Параметры выполнения и инференса
    MAX_WORKERS: int = env_int("MAX_WORKERS", 5, 1, 8)
    MAX_TOKENS: int = max(1500, env_int("MAX_TOKENS", 2048, 256, 8192))
    TEMPERATURE: float = env_float("TEMPERATURE", 0.0)
    TOP_K: int = env_int("TOP_K", 8, 1, 30)
    RERANKER_TOP_N: int = env_int("RERANKER_TOP_N", 4, 1, 10)

    # Тайм-бюджеты и отказоустойчивость
    TOTAL_BUDGET_SEC: float = env_float("TOTAL_BUDGET_SEC", 1110.0)  # 18.5 мин из 20 мин платформы
    S8_SKIP_REMAINING_SEC: float = env_float("S8_SKIP_REMAINING_SEC", 150.0)
    EMERGENCY_STOP_REMAINING_SEC: float = env_float("EMERGENCY_STOP_REMAINING_SEC", 25.0)
    PER_QUESTION_TIMEOUT_SEC: float = env_float("PER_QUESTION_TIMEOUT_SEC", 45.0)
    HTTP_TIMEOUT_SEC: float = env_float("HTTP_TIMEOUT_SEC", 40.0)
    MAX_RETRIES: int = env_int("MAX_RETRIES", 3, 0, 10)
    ANSWER_HARD_LIMIT: int = env_int("ANSWER_HARD_LIMIT", 9500, 1000, 10000)
    WORKER_PORT: int = env_int("WORKER_PORT", 8001, 1024, 65535)


cfg = Config()
