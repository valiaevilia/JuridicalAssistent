from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

from eval.schemas import CaseEvaluation, EvalCase, JudgeRoundResult
from llm_client import llm_client

logger = logging.getLogger("eval.judge")

CACHE_FILE = Path(__file__).resolve().parent / ".judge_cache.json"

ALLOWED_SCORES = (0.0, 0.25, 0.5, 0.75, 1.0)


def normalize_text(text: str) -> str:
    """Нормализует текст: нижний регистр, ё->е, схлопывание пробелов."""
    if not text:
        return ""
    t = text.lower().replace("ё", "е")
    return re.sub(r"\s+", " ", t).strip()


def check_forbidden_facts(answer: str, forbidden_facts: list[str]) -> tuple[bool, str]:
    """Уровень 1: Детерминированный Zero-Tolerance детектор выдумок.

    Если в ответе найден любой запрещённый факт (число, ловушка) -> True.
    """
    if not forbidden_facts or not answer:
        return False, ""

    norm_ans = normalize_text(answer)
    for forbidden in forbidden_facts:
        # Поддержка синонимов через |
        synonyms = [s.strip() for s in forbidden.split("|") if s.strip()]
        for syn in synonyms:
            norm_syn = normalize_text(syn)
            if norm_syn and norm_syn in norm_ans:
                return True, f"Обнаружен выдуманный/запрещённый факт: '{syn}'"

    return False, ""


def compute_must_mention_coverage(answer: str, must_mentions: list[str]) -> float:
    """Уровень 2: Расчёт покрытия обязательных фактов/чисел/пунктов.

    Каждый элемент может содержать альтернативы через '|'.
    """
    if not must_mentions:
        return 1.0
    if not answer:
        return 0.0

    norm_ans = normalize_text(answer)
    hits = 0
    for req in must_mentions:
        variants = [v.strip() for v in req.split("|") if v.strip()]
        matched = any(normalize_text(v) in norm_ans for v in variants if v)
        if matched:
            hits += 1

    return round(hits / len(must_mentions), 4)


def snap_to_allowed_score(raw_score: float) -> float:
    """Округляет сырую оценку к ближайшему шагу официальной шкалы {0.0, 0.25, 0.5, 0.75, 1.0}."""
    return min(ALLOWED_SCORES, key=lambda s: abs(s - raw_score))


class TwoRoundJudge:
    """Двухраундовый судья по методологии хакатона ПСБ:

    - Zero-Tolerance бан выдуманных фактов (score = 0.0)
    - Раунд 1: A = baseline, B = candidate
    - Раунд 2 (Swap): A = candidate, B = baseline
    - Режим LLM-as-a-Judge с автоматическим эвристическим fallback'ом
    - Персистентный кэш результатов
    """

    def __init__(self, use_llm: bool = False, cache_path: Path | None = None) -> None:
        self.use_llm = use_llm
        self.cache_path = cache_path or CACHE_FILE
        self._cache: dict[str, dict[str, Any]] = self._load_cache()

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        if self.cache_path.is_file():
            try:
                with self.cache_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning("Could not read judge cache: %s", exc)
        return {}

    def _save_cache(self) -> None:
        try:
            with self.cache_path.open("w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("Could not write judge cache: %s", exc)

    def _cache_key(self, case_id: str, baseline: str, candidate: str, mode: str) -> str:
        content = f"{case_id}|{baseline}|{candidate}|{mode}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _judge_round_llm(
        self,
        question: str,
        reference: str,
        answer_a: str,
        answer_b: str,
        candidate_is_b: bool,
    ) -> JudgeRoundResult:
        """Оценивает один раунд сравнения двух ответов через LLM."""
        system_prompt = (
            "Вы — беспристрастный юридический судья на хакатоне ПСБ. Ваша задача — сравнить два ответа (Ответ A и Ответ B) "
            "на юридический вопрос относительно эталонного ответа и документов базы.\n\n"
            "Шкала оценки Ответа B относительно Ответа A:\n"
            "1.00 — Ответ B значительно лучше Ответа A (точнее, содержит верные статьи и пункты, нет ошибок)\n"
            "0.75 — Ответ B немного лучше Ответа A\n"
            "0.50 — Ответы сопоставимы по качеству и точности\n"
            "0.25 — Ответ B немного хуже Ответа A\n"
            "0.00 — Ответ B значительно хуже Ответа A\n\n"
            "КРИТИЧЕСКОЕ ПРАВИЛО ХАКАТОНА: Любой выдуманный факт (число, дата, ставка, несуществующий пункт) "
            "полностью обнуляет оценку! Если проверяемый кандидат содержит выдуманный факт, укажите has_fabricated_fact=true.\n\n"
            "Ответьте СТРОГО в формате JSON:\n"
            "{\n"
            '  "score_for_b": 0.0|0.25|0.5|0.75|1.0,\n'
            '  "candidate_has_fabricated": false,\n'
            '  "fabricated_details": "",\n'
            '  "reason": "краткое обоснование"\n'
            "}"
        )

        user_content = (
            f"Вопрос пользователя:\n{question}\n\n"
            f"Эталонный верный ответ (Ground Truth):\n{reference}\n\n"
            f"--- ОТВЕТ A ---\n{answer_a}\n\n"
            f"--- ОТВЕТ B ---\n{answer_b}\n\n"
            f"Оцените качество Ответа B по отношению к Ответу A."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            res = llm_client.chat(messages, temperature=0.0, max_tokens=1024, json_mode=True)
            data = json.loads(res.text)

            score_for_b = float(data.get("score_for_b", 0.5))
            score_for_b = snap_to_allowed_score(score_for_b)

            has_fab = bool(data.get("candidate_has_fabricated", False))
            details = str(data.get("fabricated_details", ""))
            reason = str(data.get("reason", ""))

            # В зависимости от того, кто был кандидатом (A или B), вычисляем итоговый балл кандидата
            score_candidate = score_for_b if candidate_is_b else snap_to_allowed_score(1.0 - score_for_b)

            return JudgeRoundResult(
                score_for_candidate=score_candidate,
                candidate_has_fabricated=has_fab,
                candidate_fabricated_details=details,
                reason=reason,
            )
        except Exception as exc:
            logger.warning("LLM judge failed: %s; falling back to heuristic", exc)
            return JudgeRoundResult(score_for_candidate=0.5, reason=f"LLM fail: {exc}")

    def _judge_heuristic(self, case: EvalCase, candidate_ans: str, baseline_ans: str) -> float:
        """Детерминированная эвристика сравнения кандидата и бейзлайна."""
        cand_cov = compute_must_mention_coverage(candidate_ans, case.must_mention)
        base_cov = compute_must_mention_coverage(baseline_ans, case.must_mention)

        diff = cand_cov - base_cov

        # Проверка наличия ссылок на пункты/статьи
        has_citations = bool(re.search(r"(?:п\.|ст\.|ч\.|договор|№|\b\d+\.\d+\b)", candidate_ans))
        if not has_citations and case.expected_status == "answered":
            diff -= 0.2

        if diff >= 0.4 or (cand_cov >= 0.8 and base_cov < 0.5):
            return 1.0
        if diff >= 0.15:
            return 0.75
        if diff <= -0.4:
            return 0.0
        if diff <= -0.15:
            return 0.25
        return 0.50

    def evaluate_case(
        self,
        case: EvalCase,
        candidate_ans: str,
        candidate_status: str,
        baseline_ans: str,
        latency_sec: float = 0.0,
    ) -> CaseEvaluation:
        """Выполняет полную оценку кейса по трём уровням:

        1. Code Guard: проверка forbidden_facts
        2. Проверка must_mention
        3. Двухраундовая оценка (A/B + B/A) через LLM или эвристику
        """
        # Уровень 1: Жёсткий детерминированный Zero-Tolerance к выдумкам
        has_fab, fab_detail = check_forbidden_facts(candidate_ans, case.forbidden_facts)
        must_hit = compute_must_mention_coverage(candidate_ans, case.must_mention)

        # Проверка попадания в gold_docs
        doc_recall = False
        norm_ans = normalize_text(candidate_ans)
        for gd in case.gold_docs:
            if normalize_text(gd) in norm_ans or (gd == "D1" and "а-08" in norm_ans) or (gd == "D2" and "п-17" in norm_ans):
                doc_recall = True
                break
        if not case.gold_docs:
            doc_recall = True

        if has_fab:
            return CaseEvaluation(
                case_id=case.id,
                category=case.category,
                split=case.split,
                question=case.question,
                candidate_answer=candidate_ans,
                candidate_status=candidate_status,
                baseline_answer=baseline_ans,
                round1_score=0.0,
                round2_score=0.0,
                final_score=0.0,
                has_fabricated_fact=True,
                fabricated_reason=fab_detail,
                must_mention_hit_rate=must_hit,
                doc_recall_hit=doc_recall,
                latency_sec=latency_sec,
                judge_mode="code_guard",
            )

        # Проверка кэша
        mode_tag = "llm" if self.use_llm else "heuristic"
        ckey = self._cache_key(case.id, baseline_ans, candidate_ans, mode_tag)
        if ckey in self._cache:
            cdata = self._cache[ckey]
            return CaseEvaluation(
                case_id=case.id,
                category=case.category,
                split=case.split,
                question=case.question,
                candidate_answer=candidate_ans,
                candidate_status=candidate_status,
                baseline_answer=baseline_ans,
                round1_score=float(cdata["round1_score"]),
                round2_score=float(cdata["round2_score"]),
                final_score=float(cdata["final_score"]),
                has_fabricated_fact=bool(cdata["has_fabricated_fact"]),
                fabricated_reason=str(cdata.get("fabricated_reason", "")),
                must_mention_hit_rate=must_hit,
                doc_recall_hit=doc_recall,
                latency_sec=latency_sec,
                judge_mode=mode_tag + "_cache",
            )

        # Уровень 3: Двухраундовая оценка
        if self.use_llm:
            # Раунд 1: A = baseline, B = candidate
            r1 = self._judge_round_llm(
                question=case.question,
                reference=case.reference_answer,
                answer_a=baseline_ans,
                answer_b=candidate_ans,
                candidate_is_b=True,
            )

            # Раунд 2 (SWAP): A = candidate, B = baseline
            r2 = self._judge_round_llm(
                question=case.question,
                reference=case.reference_answer,
                answer_a=candidate_ans,
                answer_b=baseline_ans,
                candidate_is_b=False,
            )

            r1_score = r1.score_for_candidate
            r2_score = r2.score_for_candidate
            has_fab_llm = r1.candidate_has_fabricated or r2.candidate_has_fabricated
            fab_reason = r1.candidate_fabricated_details or r2.candidate_fabricated_details

            if has_fab_llm:
                final_score = 0.0
            else:
                final_score = round((r1_score + r2_score) / 2.0, 4)

            mode_used = "llm"
        else:
            # Детерминированный эвристический режим
            score = self._judge_heuristic(case, candidate_ans, baseline_ans)
            r1_score = score
            r2_score = score
            final_score = score
            has_fab_llm = False
            fab_reason = ""
            mode_used = "heuristic"

        # Сохранение в кэш
        self._cache[ckey] = {
            "round1_score": r1_score,
            "round2_score": r2_score,
            "final_score": final_score,
            "has_fabricated_fact": has_fab_llm,
            "fabricated_reason": fab_reason,
        }
        self._save_cache()

        return CaseEvaluation(
            case_id=case.id,
            category=case.category,
            split=case.split,
            question=case.question,
            candidate_answer=candidate_ans,
            candidate_status=candidate_status,
            baseline_answer=baseline_ans,
            round1_score=r1_score,
            round2_score=r2_score,
            final_score=final_score,
            has_fabricated_fact=has_fab_llm,
            fabricated_reason=fab_reason,
            must_mention_hit_rate=must_hit,
            doc_recall_hit=doc_recall,
            latency_sec=latency_sec,
            judge_mode=mode_used,
        )
