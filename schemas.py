"""Общие контракты R → L → B. Поля плана сохранены, расширения имеют defaults."""

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, Sequence


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    doc_title: str
    doc_kind: str = "contract"
    locator: str = ""
    breadcrumbs: list[str] = field(default_factory=list)
    text: str = ""
    index_text: str = ""
    edition: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    changed_on: list[str] = field(default_factory=list)
    future_changes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    quarantined: bool = False
    parent_id: str | None = None
    prev_id: str | None = None
    next_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QueryInfo:
    original: str
    last_user: str
    history: list[tuple[str, str]] = field(default_factory=list)
    rewritten: str = ""
    entities: dict = field(default_factory=dict)
    as_of: str | None = None
    as_of_range: tuple[str, str] | None = None
    compare_editions: bool = False
    query_type: str = "normal"
    dates: list[dict] = field(default_factory=list)
    date_matters: bool = False
    subquestions: list[str] = field(default_factory=list)
    injection: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    debug: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalResult:
    chunks: list[Chunk] = field(default_factory=list)
    signals: dict = field(default_factory=dict)
    as_of: str | None = None
    editions_used: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    # R передаёт kb.quarantine явно; эти тексты никогда не идут в промпт.
    quarantine: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnswerResult:
    text: str
    status: str
    query_type: str = "normal"
    claims: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    debug: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LLMResult:
    text: str
    finish_reason: str = "stop"
    usage: dict = field(default_factory=dict)
    raw_response: dict = field(default_factory=dict)


class LLMClient(Protocol):
    def chat(
        self, messages: Sequence[dict[str, str]], *, json_mode: bool = False,
        temperature: float = 0.0, max_tokens: int | None = None,
        timeout: float = 60.0,
    ) -> LLMResult:
        """B соблюдает timeout ВМЕСТЕ с транспортными повторами; ключи остаются у B."""
        ...


class ConfigurationError(ValueError):
    """Нельзя запустить генерацию без явно переданного клиента/настроек."""
