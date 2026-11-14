"""Загрузка базы знаний (zip-архив или директория)."""

from __future__ import annotations

import json
import logging
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import cfg

logger = logging.getLogger("kb_load")

META_PATH = Path(__file__).parent / "kb_meta.json"


@dataclass
class RawDoc:
    file_key: str
    file_name: str
    text: str
    meta: dict[str, Any]


def normalize_file_key(name: str) -> str:
    """Приводит имя файла к нормализованному ключу для устойчивого сопоставления.

    Нижний регистр, ё->е, замена разделителей на пробелы, удаление расширения.
    """
    clean = name.strip()
    if "." in clean:
        clean = clean.rsplit(".", 1)[0]
    clean = clean.lower().replace("ё", "е")
    clean = re.sub(r"[\s_\-]+", " ", clean)
    return clean.strip()


def load_meta() -> dict[str, Any]:
    if not META_PATH.exists():
        logger.warning("kb_meta.json not found at %s", META_PATH)
        return {"documents": {}, "kb_asof": "2026-10-10"}
    with open(META_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_kb_source() -> tuple[str, Path] | None:
    """Находит источник базы знаний: zip архив или директорию."""
    candidates_zip = [
        cfg.DATA_DIR / "knowledge-base.zip",
        cfg.DATA_DIR / "kb.zip",
        cfg.DATA_DIR / "knowledge_base.zip",
        Path("knowledge-base.zip"),
        Path("data/knowledge-base.zip"),
    ]
    for p in candidates_zip:
        if p.exists() and p.is_file():
            return ("zip", p)

    candidates_dir = [
        cfg.DATA_DIR / "knowledge-base",
        cfg.DATA_DIR / "kb",
        cfg.DATA_DIR,
    ]
    for d in candidates_dir:
        if d.exists() and d.is_dir():
            # Проверим, есть ли внутри txt файлы базы знаний
            txts = list(d.glob("*.txt"))
            if len(txts) >= 5:
                return ("dir", d)

    return None


def load_raw_docs() -> list[RawDoc]:
    """Загружает исходные файлы документов из zip или папки и связывает с метаданными."""
    meta_info = load_meta()
    docs_meta = meta_info.get("documents", {})

    # Индексируем метаданные по нормализованному имени файла
    meta_by_norm: dict[str, tuple[str, dict[str, Any]]] = {}
    for doc_id, dmeta in docs_meta.items():
        fname = dmeta.get("file_name", "")
        if fname:
            meta_by_norm[normalize_file_key(fname)] = (doc_id, dmeta)

    src = _find_kb_source()
    raw_docs: list[RawDoc] = []

    if not src:
        logger.warning("No knowledge base source found in data dir or root")
        return raw_docs

    src_type, src_path = src
    logger.info("Loading KB from %s: %s", src_type, src_path)

    if src_type == "zip":
        with zipfile.ZipFile(src_path, "r") as z:
            for name in z.namelist():
                if name.endswith("/") or name.startswith("__MACOSX"):
                    continue
                if not any(name.endswith(ext) for ext in (".txt", ".md", ".docx")):
                    continue
                norm_k = normalize_file_key(Path(name).name)
                content = z.read(name).decode("utf-8-sig", errors="ignore")

                doc_meta = {}
                if norm_k in meta_by_norm:
                    _, doc_meta = meta_by_norm[norm_k]
                else:
                    # Попробуем нечёткое вхождение
                    for mk, (did, dm) in meta_by_norm.items():
                        if norm_k in mk or mk in norm_k:
                            doc_meta = dm
                            break

                raw_docs.append(RawDoc(
                    file_key=norm_k,
                    file_name=name,
                    text=content,
                    meta=doc_meta,
                ))
    else:
        for file_p in src_path.glob("*"):
            if not file_p.is_file():
                continue
            if not any(file_p.name.endswith(ext) for ext in (".txt", ".md", ".docx")):
                continue
            norm_k = normalize_file_key(file_p.name)
            try:
                content = file_p.read_text(encoding="utf-8-sig", errors="ignore")
            except Exception:
                continue

            doc_meta = {}
            if norm_k in meta_by_norm:
                _, doc_meta = meta_by_norm[norm_k]
            else:
                for mk, (did, dm) in meta_by_norm.items():
                    if norm_k in mk or mk in norm_k:
                        doc_meta = dm
                        break

            raw_docs.append(RawDoc(
                file_key=norm_k,
                file_name=file_p.name,
                text=content,
                meta=doc_meta,
            ))

    logger.info("Loaded %d raw documents", len(raw_docs))
    return raw_docs


def init_kb() -> dict[str, Any]:
    """Точка входа для pipeline.py.

    Загружает базу, парсит чанки и возвращает словарь для Go-бэкенда и кэша.
    """
    from kb_parse import parse_all_documents, build_docs_json
    raw_docs = load_raw_docs()
    chunks = parse_all_documents(raw_docs)
    docs_map = build_docs_json(chunks, raw_docs)
    return {
        "raw_docs": raw_docs,
        "chunks": chunks,
        "docs": docs_map,
    }
