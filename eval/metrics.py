from __future__ import annotations

import math
from collections import defaultdict
from typing import Sequence

from eval.schemas import CaseEvaluation, CategoryMetrics, RunSummary


def percentile(values: Sequence[float], p: float) -> float:
    """Вычисляет p-й перцентиль (от 0 до 100) без внешних зависимостей."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    d0 = sorted_vals[f] * (c - k)
    d1 = sorted_vals[c] * (k - f)
    return round(d0 + d1, 3)


def compute_run_summary(
    evaluations: list[CaseEvaluation],
    tag: str = "latest",
    split: str = "dev",
) -> RunSummary:
    """Вычисляет официальные метрики хакатона ПСБ:

    - MatchRate: среднее арифметическое оценок
    - WinRate: W / (W + L) (ничьи исключаются!)
    - Score = 0.7 * MatchRate + 0.3 * WinRate
    - Метрики по категориям, перцентили латентности и частота выдумок
    """
    total = len(evaluations)
    if total == 0:
        return RunSummary(
            tag=tag,
            split=split,
            total_cases=0,
            score=0.0,
            match_rate=0.0,
            win_rate=0.5,
            wins=0,
            losses=0,
            ties=0,
            fabricated_rate=0.0,
            fabricated_count=0,
            false_refusal_rate=0.0,
            must_mention_avg=0.0,
            doc_recall_rate=0.0,
            p50_latency_sec=0.0,
            p95_latency_sec=0.0,
            by_category={},
            evaluations=[],
        )

    # 1. Победы, поражения, ничьи и MatchRate
    scores = [ev.final_score for ev in evaluations]
    match_rate = round(sum(scores) / total, 4)

    wins = sum(1 for s in scores if s > 0.5)
    losses = sum(1 for s in scores if s < 0.5)
    ties = sum(1 for s in scores if abs(s - 0.5) < 1e-4)

    decided = wins + losses
    win_rate = round(wins / decided, 4) if decided > 0 else 0.5000

    # Главная формула лидерборда ПСБ
    final_score = round(0.7 * match_rate + 0.3 * win_rate, 4)

    # 2. Выдуманные факты и ложные отказы
    fab_count = sum(1 for ev in evaluations if ev.has_fabricated_fact)
    fab_rate = round(fab_count / total, 4)

    # Ложный отказ: ожидался ответ, но система отказалась
    refusal_eligible = [ev for ev in evaluations if ev.category not in ("missing_data",)]
    false_refusals = sum(1 for ev in refusal_eligible if ev.candidate_status == "refused")
    false_refusal_rate = (
        round(false_refusals / len(refusal_eligible), 4) if refusal_eligible else 0.0
    )

    must_mentions = [ev.must_mention_hit_rate for ev in evaluations]
    must_mention_avg = round(sum(must_mentions) / total, 4)

    doc_recalls = sum(1 for ev in evaluations if ev.doc_recall_hit)
    doc_recall_rate = round(doc_recalls / total, 4)

    latencies = [ev.latency_sec for ev in evaluations if ev.latency_sec > 0]
    p50_lat = percentile(latencies, 50) if latencies else 0.0
    p95_lat = percentile(latencies, 95) if latencies else 0.0

    # 3. Метрики по категориям
    cat_groups: dict[str, list[CaseEvaluation]] = defaultdict(list)
    for ev in evaluations:
        cat_groups[ev.category].append(ev)

    by_category: dict[str, CategoryMetrics] = {}
    for cat_name, cat_evals in cat_groups.items():
        c_count = len(cat_evals)
        c_scores = [e.final_score for e in cat_evals]
        c_match = round(sum(c_scores) / c_count, 4)

        c_wins = sum(1 for s in c_scores if s > 0.5)
        c_losses = sum(1 for s in c_scores if s < 0.5)
        c_decided = c_wins + c_losses
        c_win = round(c_wins / c_decided, 4) if c_decided > 0 else 0.5000
        c_score = round(0.7 * c_match + 0.3 * c_win, 4)

        c_fab = sum(1 for e in cat_evals if e.has_fabricated_fact)
        c_must = sum(e.must_mention_hit_rate for e in cat_evals) / c_count

        by_category[cat_name] = CategoryMetrics(
            category=cat_name,
            count=c_count,
            score=c_score,
            match_rate=c_match,
            win_rate=c_win,
            fabricated_rate=round(c_fab / c_count, 4),
            must_mention_avg=round(c_must, 4),
        )

    return RunSummary(
        tag=tag,
        split=split,
        total_cases=total,
        score=final_score,
        match_rate=match_rate,
        win_rate=win_rate,
        wins=wins,
        losses=losses,
        ties=ties,
        fabricated_rate=fab_rate,
        fabricated_count=fab_count,
        false_refusal_rate=false_refusal_rate,
        must_mention_avg=must_mention_avg,
        doc_recall_rate=doc_recall_rate,
        p50_latency_sec=p50_lat,
        p95_latency_sec=p95_lat,
        by_category=by_category,
        evaluations=evaluations,
    )
