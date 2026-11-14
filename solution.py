from __future__ import annotations

import csv
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from config import cfg
from pipeline import answer_question, ensure_kb_initialized


def find_questions_file() -> Path:
    """Ищет questions.csv в DATA_DIR или стандартных локациях платформы."""
    candidates = [
        cfg.DATA_DIR / "questions.csv",
        Path("data") / "questions.csv",
        Path("questions.csv"),
        Path(__file__).resolve().parent / "data" / "questions.csv",
        Path(__file__).resolve().parent / "questions.csv",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(f"Файл questions.csv не найден ни по одному из путей: {[str(p) for p in candidates]}")


def load_questions(path: Path) -> list[tuple[str, str]]:
    """Загружает список вопросов (id, question) с поддержкой BOM (utf-8-sig)."""
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not {"id", "question"}.issubset(reader.fieldnames):
            raise ValueError(f"В questions.csv обязательны колонки id и question, получено: {reader.fieldnames}")
        rows: list[tuple[str, str]] = []
        for r in reader:
            qid = str(r["id"]).strip()
            qtext = str(r["question"]).strip()
            if qid:
                rows.append((qid, qtext))

    if not rows:
        raise ValueError("Файл questions.csv пуст или не содержит валидных записей")
    return rows


def process_question_task(item: tuple[str, str], deadline_ts: float) -> tuple[str, str]:
    """Обрабатывает один вопрос и возвращает (qid, answer_text)."""
    qid, question = item
    try:
        res = answer_question(question, deadline_ts=deadline_ts)
        ans = (res.text or "").strip()
        if not ans:
            ans = "В базе знаний не найдено достаточных оснований для ответа на данный вопрос."
        return qid, ans
    except Exception as exc:
        sys.stderr.write(f"[solution] Error processing question id={qid}: {exc}\n")
        return qid, "В базе знаний не найдено достаточных оснований для ответа на данный вопрос."


def main() -> None:
    start_time = time.time()
    deadline_ts = start_time + cfg.TOTAL_BUDGET_SEC

    # 1. Поиск и чтение вопросов
    try:
        q_path = find_questions_file()
        questions = load_questions(q_path)
    except Exception as exc:
        sys.stderr.write(f"[solution] Fatal error loading questions: {exc}\n")
        sys.exit(1)

    print(f"[solution] Загружено {len(questions)} вопросов из {q_path}. Запуск обработки...")

    # 2. Однократная инициализация базы знаний
    ensure_kb_initialized()

    # 3. Параллельная обработка в ThreadPoolExecutor
    results_map: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=cfg.MAX_WORKERS) as executor:
        future_to_id = {
            executor.submit(process_question_task, item, deadline_ts): item[0] for item in questions
        }

        for future in as_completed(future_to_id):
            qid = future_to_id[future]
            try:
                out_id, answer = future.result()
                results_map[out_id] = answer
            except Exception as exc:
                sys.stderr.write(f"[solution] Worker failed for id={qid}: {exc}\n")
                results_map[qid] = "В базе знаний не найдено достаточных оснований для ответа на данный вопрос."

    # 4. Атомарная запись submission.csv с сохранением исходного порядка ID
    target_path = cfg.SUBMISSION_PATH
    tmp_path = target_path.with_suffix(".tmp")

    try:
        with tmp_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL, lineterminator="\n")
            writer.writerow(["id", "answer"])
            for qid, _ in questions:
                ans = results_map.get(
                    qid, "В базе знаний не найдено достаточных оснований для ответа на данный вопрос."
                )
                writer.writerow([qid, ans])

        # Атомарная замена
        if target_path.exists():
            target_path.unlink()
        tmp_path.rename(target_path)
    except Exception as exc:
        sys.stderr.write(f"[solution] Error writing submission.csv: {exc}\n")
        if tmp_path.exists():
            try:
                os.replace(tmp_path, target_path)
            except Exception:
                pass

    elapsed = round(time.time() - start_time, 2)
    print(f"[solution] Успешно сформирован {target_path}: {len(results_map)} ответов за {elapsed} сек.")


if __name__ == "__main__":
    main()
