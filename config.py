"""Настройки только роли L; чтение файлов и окружения выполняется по вызову."""

import os
from dataclasses import dataclass, fields
from pathlib import Path
from math import isfinite

from schemas import ConfigurationError


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
