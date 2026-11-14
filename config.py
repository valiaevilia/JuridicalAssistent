"""Общие настройки backend и роли L; секреты остаются у сетевого клиента."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from math import isfinite

from schemas import ConfigurationError


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


@dataclass(frozen=True)
class LConfig:
    prompt_version: str = "L-1.0"
    s8_enabled: bool = True
    max_repairs: int = 1
    json_retries: int = 1
    max_llm_calls: int = 5
    answer_hard_limit: int = 9500
    max_input_chars: int = 60000
    max_context_chars: int = 24000
    max_tokens: int = 2500
    max_tokens_ceiling: int = 5000
    temperature: float = 0.0
    llm_timeout: float = 60.0
    q_budget_sec: float = 120.0
    s8_min_remaining_sec: float = 8.0

    def __post_init__(self):
        for name in ("s8_enabled",):
            if type(getattr(self, name)) is not bool:
                raise ConfigurationError(f"{name}: требуется bool")
        limits = {
            "max_repairs": (0, 1), "json_retries": (0, 1), "max_llm_calls": (1, 10),
            "answer_hard_limit": (500, 9500), "max_input_chars": (500, 200000),
            "max_context_chars": (500, 100000), "max_tokens": (1500, 16000),
            "max_tokens_ceiling": (1500, 16000),
        }
        for name, (lo, hi) in limits.items():
            value = getattr(self, name)
            if type(value) is not int or not lo <= value <= hi:
                raise ConfigurationError(f"{name}: ожидается целое от {lo} до {hi}")
        for name in ("llm_timeout", "q_budget_sec", "s8_min_remaining_sec", "temperature"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value) or value < 0:
                raise ConfigurationError(f"{name}: требуется конечное неотрицательное число")
        if not self.llm_timeout or not self.q_budget_sec:
            raise ConfigurationError("Таймаут и бюджет должны быть положительными")
        if self.max_tokens_ceiling < self.max_tokens or self.temperature > 0.2:
            raise ConfigurationError("Некорректны лимит токенов или температура (максимум 0.2)")
        if self.prompt_version != "L-1.0":
            raise ConfigurationError("Неизвестная версия промптов: требуется L-1.0")


ENV_NAMES = {
    "s8_enabled": "S8_ENABLED", "max_repairs": "MAX_REPAIRS",
    "json_retries": "L_JSON_RETRIES", "max_llm_calls": "L_MAX_LLM_CALLS",
    "answer_hard_limit": "ANSWER_HARD_LIMIT", "max_tokens": "MAX_TOKENS",
    "temperature": "TEMPERATURE", "llm_timeout": "LLM_TIMEOUT",
    "q_budget_sec": "Q_BUDGET_SEC", "s8_min_remaining_sec": "L_S8_MIN_REMAINING_SEC",
    "prompt_version": "L_PROMPT_VERSION", "max_input_chars": "L_MAX_INPUT_CHARS",
    "max_context_chars": "L_MAX_CONTEXT_CHARS", "max_tokens_ceiling": "L_MAX_TOKENS_CEILING",
}


def load_config(path: str | Path | None = None, *, environ=None) -> LConfig:
    """YAML → env. При отсутствии неявного YAML доступны платформенные defaults."""
    env = os.environ if environ is None else environ
    explicit = path is not None or bool(env.get("L_CONFIG_PATH"))
    config_path = Path(path or env.get("L_CONFIG_PATH") or Path(__file__).with_name("llm_config.yaml"))
    values = {}
    if config_path.is_file():
        try:
            import yaml
        except ImportError as exc:
            raise ConfigurationError("Для чтения YAML нужна разрешённая PyYAML; можно передать LConfig явно") from exc
        try:
            root = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
            if not isinstance(root, dict) or not isinstance(root.get("role_l"), dict):
                raise ValueError("нужен раздел role_l")
            values.update(root["role_l"])
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise ConfigurationError("Не удалось прочитать конфигурацию роли L") from exc
    elif explicit:
        raise ConfigurationError("Указанный YAML роли L не найден")
    defaults = LConfig()
    names = {f.name for f in fields(LConfig)}
    if values.keys() - names:
        raise ConfigurationError("Неизвестный параметр в разделе role_l")
    for name, env_name in ENV_NAMES.items():
        if env_name not in env:
            continue
        raw = env[env_name]
        default = getattr(defaults, name)
        try:
            if type(default) is bool:
                if raw.lower() not in ("1", "0", "true", "false"):
                    raise ValueError
                value = raw.lower() in ("1", "true")
            else:
                value = type(default)(raw)
            if name == "max_tokens":
                value = max(1500, value)
            values[name] = value
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(f"Некорректна переменная {env_name}") from exc
    return LConfig(**values)
