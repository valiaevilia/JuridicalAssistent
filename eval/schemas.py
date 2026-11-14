from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EvalCase:
    id: str  # "q01".."q25"
    split: str  # "dev" | "holdout"
    category: str  # "simple_fact" | "date_edition" | "ambiguous_entity" | "prompt_injection" | "missing_data" | "wrong_premise" | "multi_turn"
    question: str
    expected_status: str  # "answered" | "partial" | "refused" | "out_of_scope"
    gold_docs: list[str]  # e.g. ["D1"], ["D2", "D4"], ["D6"], ["L2"]
    reference_answer: str
    must_mention: list[str] = field(default_factory=list)  # e.g. ["450 000|450000", "3.1"]
    forbidden_facts: list[str] = field(default_factory=list)  # e.g. ["90 календарных дней"]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalCase:
        return cls(
            id=str(data["id"]),
            split=str(data.get("split", "dev")),
            category=str(data.get("category", "simple_fact")),
            question=str(data.get("question", "")),
            expected_status=str(data.get("expected_status", "answered")),
            gold_docs=list(data.get("gold_docs", [])),
            reference_answer=str(data.get("reference_answer", "")),
            must_mention=list(data.get("must_mention", [])),
            forbidden_facts=list(data.get("forbidden_facts", [])),
        )


@dataclass
class JudgeRoundResult:
    score_for_candidate: float  # in {0.0, 0.25, 0.5, 0.75, 1.0}
    candidate_has_fabricated: bool = False
    candidate_fabricated_details: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CaseEvaluation:
    case_id: str
    category: str
    split: str
    question: str
    candidate_answer: str
    candidate_status: str
    baseline_answer: str
    round1_score: float
    round2_score: float
    final_score: float
    has_fabricated_fact: bool = False
    fabricated_reason: str = ""
    must_mention_hit_rate: float = 0.0
    doc_recall_hit: bool = False
    latency_sec: float = 0.0
    judge_mode: str = "heuristic"  # "llm" | "heuristic"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CategoryMetrics:
    category: str
    count: int
    score: float
    match_rate: float
    win_rate: float
    fabricated_rate: float
    must_mention_avg: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunSummary:
    tag: str
    split: str
    total_cases: int
    score: float  # 0.7 * match_rate + 0.3 * win_rate
    match_rate: float
    win_rate: float
    wins: int
    losses: int
    ties: int
    fabricated_rate: float
    fabricated_count: int
    false_refusal_rate: float
    must_mention_avg: float
    doc_recall_rate: float
    p50_latency_sec: float
    p95_latency_sec: float
    by_category: dict[str, CategoryMetrics] = field(default_factory=dict)
    evaluations: list[CaseEvaluation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d
