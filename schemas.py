from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    doc_title: str
    doc_kind: str
    locator: str
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
    entities: dict[str, Any] = field(default_factory=dict)
    as_of: str | None = None
    as_of_range: tuple[str, str] | None = None
    compare_editions: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalResult:
    chunks: list[Chunk] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)
    as_of: str | None = None
    editions_used: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnswerResult:
    text: str
    status: str  # answered | partial | refused | out_of_scope | needs_clarification
    query_type: str = "normal"
    claims: list[dict[str, Any]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
