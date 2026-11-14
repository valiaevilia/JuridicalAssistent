from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from eval.judge import TwoRoundJudge
from eval.metrics import compute_run_summary
from eval.schemas import CaseEvaluation, EvalCase
from pipeline import answer_question, ensure_kb_initialized

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("eval.run")

DATASET_PATH = Path(__file__).resolve().parent / "dataset.jsonl"
BASELINE_PATH = Path(__file__).resolve().parent / "baseline_answers.json"
RUNS_DIR = Path(__file__).resolve().parent / "runs"


def load_dataset(dataset_path: Path, split: str = "dev") -> list[EvalCase]:
    cases: list[EvalCase] = []
    if not dataset_path.is_file():
        raise FileNotFoundError(f"Датасет не найден: {dataset_path}")

    with dataset_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            case = EvalCase.from_dict(item)
            if split == "all" or case.split == split:
                cases.append(case)
    return cases


def load_baseline_answers(baseline_path: Path) -> dict[str, str]:
    if not baseline_path.is_file():
        return {}
    with baseline_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_single_case(
    case: EvalCase,
    baseline_ans: str,
    judge: TwoRoundJudge,
) -> CaseEvaluation:
    t0 = time.time()
    try:
        ans_res = answer_question(case.question)
        cand_text = ans_res.text or ""
        cand_status = ans_res.status or "answered"
    except Exception as exc:
        cand_text = f"Ошибка генерации: {exc}"
        cand_status = "refused"

    latency = round(time.time() - t0, 3)

    return judge.evaluate_case(
        case=case,
        candidate_ans=cand_text,
        candidate_status=cand_status,
        baseline_ans=baseline_ans,
        latency_sec=latency,
    )


def print_summary_table(summary) -> None:
    sep = "=" * 78
    print("\n" + sep)
    print(f"  ОФИЦИАЛЬНЫЕ РЕЗУЛЬТАТЫ СУДЕЙСТВА ХАКАТОНА ПСБ (Tag: {summary.tag}, Split: {summary.split})")
    print(sep)
    print(f"  ИТОГОВЫЙ SCORE:      {summary.score:.4f}  (0.7 * MatchRate + 0.3 * WinRate)")
    print(f"  Match Rate:          {summary.match_rate:.4f}")
    print(f"  Win Rate:            {summary.win_rate:.4f}  (Побед: {summary.wins}, Поражений: {summary.losses}, Ничьих: {summary.ties})")
    print(f"  Fabricated Rate:     {summary.fabricated_rate:.4f}  ({summary.fabricated_count} выдуманных фактов)")
    print(f"  Must-Mention Avg:    {summary.must_mention_avg * 100:.1f}%")
    print(f"  Doc Recall Rate:     {summary.doc_recall_rate * 100:.1f}%")
    print(f"  False Refusal Rate:  {summary.false_refusal_rate * 100:.1f}%")
    print(f"  Latency p50 / p95:   {summary.p50_latency_sec:.2f}s / {summary.p95_latency_sec:.2f}s")
    print("-" * 78)
    print(f"  {'Категория':<20} | {'Кейсов':<6} | {'Score':<8} | {'Match':<8} | {'WinRate':<8} | {'FabRate':<8}")
    print("-" * 78)
    for cat, m in sorted(summary.by_category.items()):
        print(f"  {cat:<20} | {m.count:<6} | {m.score:<8.4f} | {m.match_rate:<8.4f} | {m.win_rate:<8.4f} | {m.fabricated_rate:<8.4f}")
    print(sep + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Eval Runner по методике ПСБ")
    parser.add_argument("--split", choices=["dev", "holdout", "all"], default="dev", help="Подвыборка кейсов")
    parser.add_argument("--tag", default="latest", help="Имя тега прогона")
    parser.add_argument("--workers", type=int, default=4, help="Число параллельных воркеров")
    parser.add_argument("--use-llm", action="store_true", help="Включить реального LLM-судью вместо эвристики")
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH, help="Путь к dataset.jsonl")
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH, help="Путь к baseline_answers.json")

    args = parser.parse_args()

    ensure_kb_initialized()

    cases = load_dataset(args.dataset, split=args.split)
    baselines = load_baseline_answers(args.baseline)
    judge = TwoRoundJudge(use_llm=args.use_llm)

    print(f"Запуск оценки {len(cases)} кейсов (split: {args.split}, judge: {'LLM' if args.use_llm else 'Heuristic'})...")

    evaluations: list[CaseEvaluation] = []
    start_all = time.time()

    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(evaluate_single_case, c, baselines.get(c.id, ""), judge): c
                for c in cases
            }
            for fut in as_completed(futures):
                evaluations.append(fut.result())
    else:
        for c in cases:
            evaluations.append(evaluate_single_case(c, baselines.get(c.id, ""), judge))

    # Сортировка по ID кейса для детерминированности
    evaluations.sort(key=lambda e: e.case_id)

    summary = compute_run_summary(evaluations, tag=args.tag, split=args.split)
    print_summary_table(summary)

    # Сохранение артефакта прогона
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RUNS_DIR / f"{args.tag}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(summary.to_dict(), f, ensure_ascii=False, indent=2)

    print(f"Артефакт оценки сохранён в: {out_path} (всего времени: {round(time.time() - start_all, 2)}с)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
