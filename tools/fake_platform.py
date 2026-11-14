#!/usr/bin/env python3
"""tools/fake_platform.py

Локальный эмулятор среды проверки платформы хакатона.
1. Распаковывает собранный ZIP в изолированную временную песочницу (sandbox/).
2. Подкладывает data/questions.csv.
3. Запускает 'python solution.py' в песочнице с замером времени.
4. Проверяет сгенерированный submission.csv по 7 строгим критериям платформы.
"""

from __future__ import annotations

import csv
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path


def get_or_build_zip(root_dir: Path) -> Path:
    dist_dir = root_dir / "dist"
    zips = sorted(dist_dir.glob("submission_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if zips:
        return zips[0]

    # Если архивов ещё нет, собираем свежий
    build_script = root_dir / "tools" / "build_zip.py"
    res = subprocess.run([sys.executable, str(build_script)], cwd=str(root_dir), capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stderr, file=sys.stderr)
        raise RuntimeError("Не удалось собрать ZIP-архив перед запуском эмулятора.")

    zips = sorted(dist_dir.glob("submission_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        raise FileNotFoundError("Собранный ZIP-архив не найден в dist/")
    return zips[0]


def prepare_test_questions(sandbox_data: Path, root_dir: Path) -> list[str]:
    """Копирует или генерирует тестовые questions.csv."""
    sandbox_data.mkdir(parents=True, exist_ok=True)
    target_q = sandbox_data / "questions.csv"

    # Пробуем взять реальные вопросы из data/questions.csv в корне
    src_q = root_dir / "data" / "questions.csv"
    if src_q.is_file():
        shutil.copy2(src_q, target_q)
    else:
        # Генерируем 3 базовых вопроса для теста
        with target_q.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "question"])
            writer.writerow(["1", "Какова ставка арендной платы и срок внесения по договору склада в Химках?"])
            writer.writerow(["2", "Какой гарантийный срок установлен по договору поставки с Альфа-Трейд?"])
            writer.writerow(["3", "В какой срок производится оплата по договору с Альфа-Трейд?"])

    # Читаем список ID
    ids = []
    with target_q.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if "id" in r and r["id"]:
                ids.append(str(r["id"]).strip())
    return ids


def validate_submission_csv(csv_path: Path, expected_ids: list[str]) -> list[str]:
    """Проверяет submission.csv по 7 строгим критериям платформы."""
    errors: list[str] = []

    # 1. Существование и непустота
    if not csv_path.is_file():
        return ["Критерий 1: Файл submission.csv не создан!"]
    if csv_path.stat().st_size == 0:
        return ["Критерий 1: Файл submission.csv пустой (0 байт)!"]

    # 2. Корректный UTF-8
    try:
        raw_bytes = csv_path.read_bytes()
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"Критерий 2: Ошибка кодировки UTF-8 в submission.csv: {exc}"]

    # 3. Заголовок id,answer
    lines = raw_text.splitlines()
    if not lines:
        return ["Критерий 3: submission.csv пустой"]
    header = lines[0].replace('"', "").strip()
    if header != "id,answer":
        errors.append(f"Критерий 3: Неверный заголовок CSV: '{lines[0]}', ожидается 'id,answer'")

    # Чтение строк через csv.reader
    rows: list[dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    # 4. Совпадение ID и количества
    actual_ids = [r.get("id", "").strip() for r in rows]
    if len(actual_ids) != len(expected_ids):
        errors.append(
            f"Критерий 4: Число строк ({len(actual_ids)}) не совпадает с числом входных вопросов ({len(expected_ids)})"
        )
    if set(actual_ids) != set(expected_ids):
        missing = set(expected_ids) - set(actual_ids)
        extra = set(actual_ids) - set(expected_ids)
        if missing:
            errors.append(f"Критерий 4: Пропущены ID: {list(missing)[:5]}")
        if extra:
            errors.append(f"Критерий 4: Лишние неизвестные ID: {list(extra)[:5]}")

    # 5, 6, 7. Проверка ответов
    for i, row in enumerate(rows):
        qid = row.get("id", f"row_{i}")
        ans = row.get("answer", "")

        # 5. Непустой ответ
        if not ans or not ans.strip():
            errors.append(f"Критерий 5: Пустой ответ для ID '{qid}'")

        # 6. Длина <= 10000
        if len(ans) > 10000:
            errors.append(f"Критерий 6: Длина ответа для ID '{qid}' ({len(ans)} симв.) превышает лимит 10 000!")

        # 7. Отсутствие сырого JSON и тегов <think>
        if "<think>" in ans or "</think>" in ans:
            errors.append(f"Критерий 7: Утечка тегов <think> в ответе для ID '{qid}'")
        if ans.strip().startswith('{"answer"') or ans.strip().startswith('{"status"'):
            errors.append(f"Критерий 7: Утечка нераспарсенного JSON в ответе для ID '{qid}'")

    return errors


def run_fake_platform() -> int:
    root_dir = Path(__file__).resolve().parent.parent
    zip_path = get_or_build_zip(root_dir)

    print(f"=== [fake_platform] Тестирование сабмита: {zip_path.name} ===")

    temp_dir = Path(tempfile.mkdtemp(prefix="psb_sandbox_"))
    try:
        # Распаковываем ZIP
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(temp_dir)

        # Подготавливаем тестовые вопросы
        sandbox_data = temp_dir / "data"
        expected_ids = prepare_test_questions(sandbox_data, root_dir)

        # Копируем knowledge-base.zip если есть
        src_kb = root_dir / "data" / "knowledge-base.zip"
        if src_kb.is_file():
            shutil.copy2(src_kb, sandbox_data / "knowledge-base.zip")

        solution_script = temp_dir / "solution.py"
        if not solution_script.is_file():
            print("[FAIL] В архиве отсутствует solution.py!", file=sys.stderr)
            return 1

        print(f"[fake_platform] Запуск solution.py на {len(expected_ids)} вопросах...")
        start_t = time.time()

        # Запуск процесса в песочнице
        res = subprocess.run(
            [sys.executable, str(solution_script)],
            cwd=str(temp_dir),
            capture_output=True,
            text=True,
            timeout=180.0,
        )

        elapsed = round(time.time() - start_t, 2)
        print(f"[fake_platform] Время выполнения: {elapsed} с. Exit code: {res.returncode}")

        if res.stdout:
            print("[stdout]:", res.stdout.strip())
        if res.stderr:
            print("[stderr]:", res.stderr.strip(), file=sys.stderr)

        if res.returncode != 0:
            print(f"[FAIL] solution.py упал с кодом {res.returncode}!", file=sys.stderr)
            return 1

        # Валидация submission.csv
        submission_csv = temp_dir / "submission.csv"
        errors = validate_submission_csv(submission_csv, expected_ids)

        if errors:
            print(f"[FAIL] Обнаружено {len(errors)} нарушений формата платформы:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 1

        print(
            f"[SUCCESS] Платформенный эмулятор: Все 7 критериев пройдены на 100%! "
            f"Ответов: {len(expected_ids)}/{len(expected_ids)}, время: {elapsed}с."
        )
        return 0

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(run_fake_platform())
