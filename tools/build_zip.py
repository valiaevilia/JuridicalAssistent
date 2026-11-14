#!/usr/bin/env python3
"""tools/build_zip.py

Собирает плоский ZIP-архив сабмита для платформы в папку dist/:
1. Запускает проверку импортов через check_imports.py.
2. Проверяет синтаксис всех .py файлов (py_compile).
3. Упаковывает только корневые .py файлы, requirements.txt, kb_meta.json, docs.json.
4. Проверяет отсутствие вложенных каталогов в корне архива.
5. Проверяет лимит размера архива (< 120 МБ).
"""

from __future__ import annotations

import hashlib
import py_compile
import subprocess
import sys
import time
import zipfile
from pathlib import Path

MAX_ZIP_BYTES = 120 * 1024 * 1024  # 120 MB (с запасом до 128 MB платформы)

REQUIRED_ROOT_FILES = [
    "solution.py",
    "pipeline.py",
    "schemas.py",
    "config.py",
    "llm_client.py",
    "requirements.txt",
]


def run_checks(root_dir: Path) -> None:
    # 1. Проверка check_imports.py
    check_script = root_dir / "tools" / "check_imports.py"
    if check_script.is_file():
        res = subprocess.run(
            [sys.executable, "-X", "utf8", str(check_script)], cwd=str(root_dir),
            capture_output=True, text=True, encoding="utf-8",
        )
        if res.returncode != 0:
            print(res.stderr, file=sys.stderr)
            raise RuntimeError("check_imports.py завершился с ошибкой. Сборка ZIP отменена.")

    # 2. Проверка обязательных файлов
    for req in REQUIRED_ROOT_FILES:
        p = root_dir / req
        if not p.is_file():
            raise FileNotFoundError(f"Отсутствует обязательный корневой файл: {req}")

    # 3. Синтаксическая компиляция корневых .py
    for py_file in root_dir.glob("*.py"):
        try:
            py_compile.compile(str(py_file), doraise=True)
        except py_compile.PyCompileError as exc:
            raise RuntimeError(f"Синтаксическая ошибка в {py_file.name}: {exc}") from exc


def build_zip() -> Path:
    root_dir = Path(__file__).resolve().parent.parent
    run_checks(root_dir)

    dist_dir = root_dir / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    ts = time.strftime("%Y%m%d_%H%M%S")
    zip_path = dist_dir / f"submission_{ts}.zip"

    # Сбор файлов для включения в корень ZIP
    files_to_pack: list[Path] = []

    # Все корневые .py файлы
    for py_file in root_dir.glob("*.py"):
        files_to_pack.append(py_file)

    # requirements.txt
    req_file = root_dir / "requirements.txt"
    if req_file.is_file():
        files_to_pack.append(req_file)

    # Опциональные вспомогательные файлы в корне
    for extra in ["kb_meta.json", "docs.json", "chunks.jsonl"]:
        p = root_dir / extra
        if p.is_file():
            files_to_pack.append(p)

    # Запись архива (строго плоский корень!)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files_to_pack:
            # arcname строго имя файла без путей
            zf.write(f, arcname=f.name)

    # Валидация созданного архива
    zip_size = zip_path.stat().st_size
    if zip_size > MAX_ZIP_BYTES:
        zip_path.unlink()
        raise ValueError(
            f"Размер архива ({zip_size / (1024*1024):.2f} МБ) превышает безопасный лимит 120 МБ!"
        )

    # Проверка структуры архива
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        for name in names:
            if "/" in name or "\\" in name:
                zip_path.unlink()
                raise ValueError(f"В архиве обнаружена вложенная папка: '{name}'! Корень должен быть плоским.")

    # Хэш-сумма
    sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()

    print(f"[OK] Собрано сабмит-архив: {zip_path.name}")
    print(f"     Путь: {zip_path}")
    print(f"     Размер: {zip_size / 1024:.1f} КБ ({zip_size} байт)")
    print(f"     SHA256: {sha256[:16]}...")
    print(f"     Файлов в архиве ({len(files_to_pack)}): {[f.name for f in files_to_pack]}")

    return zip_path


def main() -> int:
    try:
        build_zip()
        return 0
    except Exception as exc:
        print(f"[FAIL] tools/build_zip.py error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
