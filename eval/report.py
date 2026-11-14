from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

RUNS_DIR = Path(__file__).resolve().parent / "runs"


def load_run(tag_or_path: str) -> dict[str, Any]:
    p = Path(tag_or_path)
    if not p.is_file():
        p = RUNS_DIR / f"{tag_or_path}.json"
    if not p.is_file():
        raise FileNotFoundError(f"Файл прогона не найден: {p}")

    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def format_delta(old_val: float, new_val: float, is_pct: bool = False, invert_color: bool = False) -> str:
    diff = new_val - old_val
    sign = "+" if diff > 0 else ""
    if is_pct:
        return f"{sign}{diff * 100:.2f}%"
    return f"{sign}{diff:.4f}"


def generate_markdown_report(old: dict[str, Any], new: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Сравнительный отчёт оценки моделей ({old.get('tag')} -> {new.get('tag')})\n")
    lines.append("| Метрика | Бейзлайн / Старый | Новый прогон | Дельта |")
    lines.append("|---|---|---|---|")
    lines.append(f"| **Итоговый Score** | {old['score']:.4f} | **{new['score']:.4f}** | **{format_delta(old['score'], new['score'])}** |")
    lines.append(f"| Match Rate | {old['match_rate']:.4f} | {new['match_rate']:.4f} | {format_delta(old['match_rate'], new['match_rate'])} |")
    lines.append(f"| Win Rate | {old['win_rate']:.4f} | {new['win_rate']:.4f} | {format_delta(old['win_rate'], new['win_rate'])} |")
    lines.append(f"| Fabricated Rate | {old['fabricated_rate'] * 100:.1f}% | {new['fabricated_rate'] * 100:.1f}% | {format_delta(old['fabricated_rate'], new['fabricated_rate'], is_pct=True)} |")
    lines.append(f"| Must-Mention Avg | {old['must_mention_avg'] * 100:.1f}% | {new['must_mention_avg'] * 100:.1f}% | {format_delta(old['must_mention_avg'], new['must_mention_avg'], is_pct=True)} |")
    lines.append(f"| False Refusal Rate | {old['false_refusal_rate'] * 100:.1f}% | {new['false_refusal_rate'] * 100:.1f}% | {format_delta(old['false_refusal_rate'], new['false_refusal_rate'], is_pct=True)} |")
    lines.append(f"| Latency p50 | {old['p50_latency_sec']:.2f}s | {new['p50_latency_sec']:.2f}s | {new['p50_latency_sec'] - old['p50_latency_sec']:+.2f}s |")

    lines.append("\n### Динамика по категориям вопросов\n")
    lines.append("| Категория | Старый Score | Новый Score | Дельта | Fab Rate |")
    lines.append("|---|---|---|---|---|")

    old_cats = old.get("by_category", {})
    new_cats = new.get("by_category", {})
    all_cats = sorted(set(old_cats.keys()) | set(new_cats.keys()))

    for c in all_cats:
        o_s = old_cats.get(c, {}).get("score", 0.0)
        n_s = new_cats.get(c, {}).get("score", 0.0)
        n_fab = new_cats.get(c, {}).get("fabricated_rate", 0.0)
        lines.append(f"| {c} | {o_s:.4f} | {n_s:.4f} | {format_delta(o_s, n_s)} | {n_fab*100:.1f}% |")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Инструмент сравнения прогонов оценки")
    parser.add_argument("--old", required=True, help="Тег старого прогона (или путь к JSON)")
    parser.add_argument("--new", required=True, help="Тег нового прогона (или путь к JSON)")
    parser.add_argument("--markdown", type=Path, default=None, help="Файл для сохранения отчёта в Markdown")

    args = parser.parse_args()

    try:
        old_data = load_run(args.old)
        new_data = load_run(args.new)
    except Exception as exc:
        print(f"Ошибка загрузки отчётов: {exc}", file=sys.stderr)
        return 1

    sep = "=" * 80
    print("\n" + sep)
    print(f"  ДЕТАЛЬНОЕ СРАВНЕНИЕ ПРОГОНОВ: {old_data.get('tag')} ---> {new_data.get('tag')}")
    print(sep)
    print(f"  Score:            {old_data['score']:.4f} -> {new_data['score']:.4f} ({format_delta(old_data['score'], new_data['score'])})")
    print(f"  Match Rate:       {old_data['match_rate']:.4f} -> {new_data['match_rate']:.4f} ({format_delta(old_data['match_rate'], new_data['match_rate'])})")
    print(f"  Win Rate:         {old_data['win_rate']:.4f} -> {new_data['win_rate']:.4f} ({format_delta(old_data['win_rate'], new_data['win_rate'])})")
    print(f"  Fabricated Rate:  {old_data['fabricated_rate']*100:.1f}% -> {new_data['fabricated_rate']*100:.1f}% ({format_delta(old_data['fabricated_rate'], new_data['fabricated_rate'], is_pct=True)})")
    print(f"  Must-Mention:     {old_data['must_mention_avg']*100:.1f}% -> {new_data['must_mention_avg']*100:.1f}% ({format_delta(old_data['must_mention_avg'], new_data['must_mention_avg'], is_pct=True)})")
    print("-" * 80)

    # Поиск улучшений и регрессий по кейсам
    old_cases = {e["case_id"]: e for e in old_data.get("evaluations", [])}
    new_cases = {e["case_id"]: e for e in new_data.get("evaluations", [])}

    improved = []
    regressed = []

    for cid, n_case in new_cases.items():
        if cid in old_cases:
            o_score = old_cases[cid]["final_score"]
            n_score = n_case["final_score"]
            diff = n_score - o_score
            if diff > 0.05:
                improved.append((cid, o_score, n_score, n_case["question"]))
            elif diff < -0.05:
                regressed.append((cid, o_score, n_score, n_case["question"]))

    if improved:
        print(f"  Улучшений ({len(improved)}):")
        for cid, o_s, n_s, q in improved:
            print(f"    [+] {cid} ({o_s:.2f} -> {n_s:.2f}): {q[:60]}...")
    if regressed:
        print(f"  РЕГРЕССИЙ ({len(regressed)}):")
        for cid, o_s, n_s, q in regressed:
            print(f"    [-] {cid} ({o_s:.2f} -> {n_s:.2f}): {q[:60]}...")
    if not regressed and not improved:
        print("  Оценки по отдельным кейсам идентичны.")

    print(sep + "\n")

    md_report = generate_markdown_report(old_data, new_data)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(md_report, encoding="utf-8")
        print(f"Markdown-отчёт для презентации сохранён в: {args.markdown}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
