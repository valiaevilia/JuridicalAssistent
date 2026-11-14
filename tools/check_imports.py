#!/usr/bin/env python3
"""tools/check_imports.py

AST-валидатор импортов в корневых .py файлах репозитория.
Проверяет:
1. Запрет импортов из поддиректорий (backend, backend-go, eval, tools, tests).
2. Запрет неразрешённых библиотек (nltk, pymorphy3, sentence_transformers, scipy, spacy, torch, faiss, tiktoken).
3. Соответствие разрешённым пакетам из requirements.txt и стандартной библиотеке Python 3.11+.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

FORBIDDEN_PACKAGES = {
    "pymorphy3",
    "nltk",
    "sentence_transformers",
    "scipy",
    "spacy",
    "torch",
    "faiss",
    "tiktoken",
}

FORBIDDEN_SUBDIRS = {
    "backend",
    "backend-go",
    "backend_go",
    "eval",
    "tools",
    "tests",
    "frontend",
    "dist",
}

# Плановые корневые модули команды (R, L, B)
PLANNED_ROOT_MODULES = {
    "solution",
    "pipeline",
    "schemas",
    "config",
    "llm_client",
    "worker",
    "kb_load",
    "kb_parse",
    "index",
    "retrieve",
    "dates",
    "prompts",
    "guard",
    "answer",
}
STDLIB_MODULES = set(sys.stdlib_module_names) | {
    "dataclasses",
    "typing",
    "pathlib",
    "json",
    "csv",
    "os",
    "sys",
    "re",
    "time",
    "math",
    "random",
    "threading",
    "hashlib",
    "concurrent",
    "email",
    "http",
    "logging",
    "xml",
    "zipfile",
    "io",
    "collections",
    "itertools",
    "functools",
    "copy",
    "traceback",
    "uuid",
    "datetime",
    "contextlib",
    "abc",
    "enum",
    "ast",
    "shutil",
    "tempfile",
}


def load_allowed_from_requirements(req_path: Path) -> set[str]:
    """Считывает имена разрешённых библиотек из requirements.txt."""
    allowed = set()
    if not req_path.is_file():
        return allowed

    with req_path.open("r", encoding="utf-8") as f:
        for line in f:
            clean = line.strip().split("#")[0].strip()
            if not clean:
                continue
            pkg = clean.split("==")[0].split(">=")[0].split("<=")[0].strip().lower().replace("-", "_")
            if pkg:
                allowed.add(pkg)

    # Нормализация известных маппингов имен пакетов к импортам
    mappings = {
        "beautifulsoup4": "bs4",
        "pyyaml": "yaml",
        "faiss_cpu": "faiss",
        "python_docx": "docx",
        "python_dotenv": "dotenv",
        "python_multipart": "multipart",
    }
    for k, v in mappings.items():
        if k in allowed:
            allowed.add(v)

    return allowed


def check_file(file_path: Path, allowed_pkgs: set[str], root_py_modules: set[str]) -> list[str]:
    """Проверяет один файл .py через AST."""
    errors = []
    try:
        with file_path.open("r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
    except Exception as exc:
        return [f"Не удалось распарсить {file_path.name}: {exc}"]

    for node in ast.walk(tree):
        imported_names: list[str] = []
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)

        for imp in imported_names:
            top_level = imp.split(".")[0].lower()

            # 1. Проверка на запрет импорта из подпапок
            if top_level in FORBIDDEN_SUBDIRS:
                errors.append(
                    f"{file_path.name}:{getattr(node, 'lineno', '?')} Запрещён импорт из подпапки: '{imp}'"
                )

            # 2. Проверка на строго запрещённые пакеты
            if top_level in FORBIDDEN_PACKAGES:
                errors.append(
                    f"{file_path.name}:{getattr(node, 'lineno', '?')} Строго запрещённый пакет для платформы: '{imp}'"
                )

            # 3. Проверка разрешён ли пакет (stdlib, requirements или локальный корневой .py)
            is_stdlib = top_level in STDLIB_MODULES
            is_local = top_level in root_py_modules or top_level in PLANNED_ROOT_MODULES
            is_req = top_level in allowed_pkgs
            if not (is_stdlib or is_local or is_req):
                errors.append(
                    f"{file_path.name}:{getattr(node, 'lineno', '?')} Пакет '{top_level}' отсутствует в requirements.txt или stdlib"
                )

    return errors


def main() -> int:
    root_dir = Path(__file__).resolve().parent.parent
    req_file = root_dir / "requirements.txt"
    allowed_pkgs = load_allowed_from_requirements(req_file)

    # Имена локальных корневых .py файлов
    root_py_files = [p for p in root_dir.glob("*.py") if p.is_file()]
    root_py_modules = {p.stem for p in root_py_files}

    total_errors: list[str] = []
    for py_file in root_py_files:
        errs = check_file(py_file, allowed_pkgs, root_py_modules)
        total_errors.extend(errs)

    if total_errors:
        print("[FAIL] tools/check_imports.py обнаружил нарушения правил платформы:", file=sys.stderr)
        for err in total_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"[OK] tools/check_imports.py: Проверено {len(root_py_files)} корневых файлов. Все импорты валидны.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
