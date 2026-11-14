"""Индексация базы знаний: лексический поиск (BM25) и векторный поиск (BGE-M3).

Реализация BM25 на numpy/чистом Python без внешних зависимостей.
Поддерживает стемминг окончаний русского языка и нормализацию сущностей.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from schemas import Chunk

logger = logging.getLogger("index")

# Типовые русские окончания для быстрого стемминга без nltk/pymorphy
RU_SUFFIXES = sorted([
    "ами", "ями", "ого", "его", "ому", "ему", "ыми", "ими", "ах", "ях",
    "ов", "ев", "ей", "ой", "ий", "ый", "ая", "ое", "ые", "ие", "ую",
    "ом", "ем", "ам", "ям", "ы", "и", "а", "я", "у", "ю", "е", "о", "ь"
], key=len, reverse=True)

STOP_WORDS = {
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то", "все", "она", "так",
    "его", "но", "да", "ты", "к", "у", "же", "вы", "за", "бы", "по", "только", "ее", "мне", "было",
    "вот", "от", "меня", "еще", "нет", "о", "из", "ему", "теперь", "когда", "даже", "ну", "вдруг",
    "ли", "если", "уже", "или", "ни", "быть", "был", "него", "до", "вас", "нибудь", "опять", "уж",
    "вам", "ведь", "там", "потом", "себя", "ничего", "ей", "может", "они", "тут", "где", "есть",
    "надо", "ней", "для", "мы", "тебя", "их", "чем", "была", "сам", "чтоб", "без", "будто", "чего",
    "раз", "тоже", "себе", "под", "будет", "ж", "тогда", "кто", "этот", "того", "потому", "этого",
    "какой", "совсем", "ним", "здесь", "этом", "один", "почти", "мой", "тем", "чтобы", "нее", "кажется",
    "сейчас", "были", "куда", "зачем", "всех", "никогда", "можно", "при", "наконец", "два", "об",
    "другой", "хоть", "после", "над", "больше", "тот", "через", "эти", "нас", "про", "всего", "них",
    "какая", "много", "разве", "три", "эту", "моя", "впрочем", "хорошо", "свою", "этой", "перед",
    "иногда", "лучше", "чуть", "том", "нельзя", "такой", "им", "более", "всегда", "конечно", "всю",
    "между"
}


def stem_word(word: str) -> str:
    """Усечение типовых окончаний русских слов до основы."""
    w = word.lower().replace("ё", "е")
    if len(w) <= 4:
        return w
    for suf in RU_SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[:-len(suf)]
    return w


def tokenize(text: str) -> list[str]:
    """Токенизация с выделением номеров договоров, дат, чисел и основ слов."""
    t = text.lower().replace("ё", "е")
    # Извлекаем токены номеров (п-17/2024, а-08/2024, 152-фз)
    special_tokens = re.findall(r"\b[a-zа-я0-9]+[/-][a-zа-я0-9/-]+\b", t)

    # Стандартные буквенно-цифровые слова
    words = re.findall(r"\b[a-zа-я0-9]+\b", t)

    tokens: list[str] = []
    for st in special_tokens:
        clean_st = st.replace("/", "-")
        tokens.append(clean_st)

    for w in words:
        if w in STOP_WORDS or len(w) < 2:
            continue
        tokens.append(stem_word(w))

    return tokens


class BM25Index:
    """Векторизованный BM25 на чистом Python/numpy."""

    def __init__(self, chunks: list[Chunk], k1: float = 1.2, b: float = 0.75):
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.corpus_size = len(chunks)
        self.doc_lens = np.zeros(self.corpus_size, dtype=np.float32)
        self.doc_token_counts: list[Counter] = []
        self.df: dict[str, int] = Counter()
        self.idf: dict[str, float] = {}

        self._build_index()

    def _build_index(self):
        total_len = 0
        for i, c in enumerate(self.chunks):
            # Индексируем по index_text, который содержит крошки и нормализованные числа
            toks = tokenize(c.index_text or c.text)
            self.doc_lens[i] = len(toks)
            total_len += len(toks)
            counts = Counter(toks)
            self.doc_token_counts.append(counts)
            for t in counts.keys():
                self.df[t] += 1

        self.avg_doc_len = (total_len / self.corpus_size) if self.corpus_size > 0 else 1.0

        for term, freq in self.df.items():
            # Робустная формула IDF BM25 с защитой от отрицательных значений
            val = (self.corpus_size - freq + 0.5) / (freq + 0.5)
            self.idf[term] = math.log(max(val, 0.0001) + 1.0)

    def search(self, query: str, top_k: int = 40, allowed_indices: list[int] | None = None) -> list[tuple[int, float]]:
        """Возвращает список кортежей (индекс чанка, скор BM25)."""
        q_tokens = tokenize(query)
        if not q_tokens:
            return []

        scores = np.zeros(self.corpus_size, dtype=np.float32)

        for token in q_tokens:
            if token not in self.idf:
                continue
            idf_val = self.idf[token]
            for doc_idx, counts in enumerate(self.doc_token_counts):
                if allowed_indices is not None and doc_idx not in allowed_indices:
                    continue
                tf = counts.get(token, 0)
                if tf == 0:
                    continue
                doc_len = self.doc_lens[doc_idx]
                denom = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / self.avg_doc_len))
                scores[doc_idx] += idf_val * (tf * (self.k1 + 1.0) / denom)

        if allowed_indices is not None:
            candidate_indices = np.array(allowed_indices, dtype=np.int32)
            candidate_scores = scores[candidate_indices]
            top_order = np.argsort(candidate_scores)[::-1][:top_k]
            res = []
            for rank_idx in top_order:
                orig_idx = int(candidate_indices[rank_idx])
                s = float(candidate_scores[rank_idx])
                if s > 0:
                    res.append((orig_idx, s))
            return res
        else:
            top_indices = np.argsort(scores)[::-1][:top_k]
            res = []
            for idx in top_indices:
                s = float(scores[idx])
                if s > 0:
                    res.append((int(idx), s))
            return res


class KBIndex:
    """Общий фасад индексов базы знаний: BM25 + плотные векторы bge-m3."""

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.chunk_by_id = {c.chunk_id: c for c in chunks}
        self.bm25 = BM25Index(chunks)
        self.dense_vectors: np.ndarray | None = None
        self._init_dense_vectors_if_possible()

    def _init_dense_vectors_if_possible(self):
        """Пытается загрузить или рассчитать эмбеддинги через llm_client при старте."""
        # Проверяем наличие кэшированных эмбеддингов
        emb_path = Path("emb.npy")
        if emb_path.exists():
            try:
                self.dense_vectors = np.load(str(emb_path))
                if len(self.dense_vectors) == len(self.chunks):
                    logger.info("Loaded cached embeddings from %s", emb_path)
                    return
            except Exception as exc:
                logger.warning("Failed to load cached embeddings: %s", exc)

        # Если доступен реальный сервер эмбеддингов (проверяем быстрым тестом без долгих ретраев)
        try:
            from config import cfg
            if not cfg.LLM_BASE_URL or "dummy" in cfg.LLM_API_KEY.lower():
                # Локальный/тестовый режим без активного ключа -> чистый BM25
                self.dense_vectors = None
                return

            from llm_client import llm_client
            # Пробуем быстро получить эмбеддинг одного слова
            test_res = llm_client.embed("тест")
            if test_res and len(test_res) > 0:
                logger.info("llm_client.embed is available; precomputing dense index...")
                texts = [c.index_text[:800] for c in self.chunks]
                vecs = []
                batch_size = 32
                for i in range(0, len(texts), batch_size):
                    batch = texts[i:i + batch_size]
                    b_vecs = llm_client.embed_batch(batch) if hasattr(llm_client, "embed_batch") else [llm_client.embed(t) for t in batch]
                    vecs.extend(b_vecs)
                self.dense_vectors = np.array(vecs, dtype=np.float32)
                norms = np.linalg.norm(self.dense_vectors, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                self.dense_vectors = self.dense_vectors / norms
                logger.info("Dense vectors calculated for %d chunks", len(self.dense_vectors))
        except Exception as exc:
            logger.info("Dense embeddings skipped (fallback to BM25): %s", exc)
            self.dense_vectors = None

    def search_bm25(self, query: str, top_k: int = 40, allowed_indices: list[int] | None = None) -> list[tuple[int, float]]:
        return self.bm25.search(query, top_k=top_k, allowed_indices=allowed_indices)

    def search_dense(self, query: str, top_k: int = 40, allowed_indices: list[int] | None = None) -> list[tuple[int, float]]:
        if self.dense_vectors is None:
            return []
        try:
            from llm_client import llm_client
            q_vec = np.array(llm_client.embed(query), dtype=np.float32)
            q_norm = np.linalg.norm(q_vec)
            if q_norm > 0:
                q_vec = q_vec / q_norm
            scores = self.dense_vectors @ q_vec
            if allowed_indices is not None:
                cand_idx = np.array(allowed_indices, dtype=np.int32)
                cand_scores = scores[cand_idx]
                top_order = np.argsort(cand_scores)[::-1][:top_k]
                return [(int(cand_idx[i]), float(cand_scores[i])) for i in top_order]
            else:
                top_order = np.argsort(scores)[::-1][:top_k]
                return [(int(i), float(scores[i])) for i in top_order[:top_k]]
        except Exception:
            return []
