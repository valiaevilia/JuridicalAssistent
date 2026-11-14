"""Контроль 18 ручных сценариев демо, без подмены проверки настоящей модели."""

import socket
import unittest
from unittest.mock import patch

from answer import answer
from config import LConfig
from examples.offline_client import ScriptedLLM, review_ok
from examples.verify_materials import DEMO_EVIDENCE
from schemas import QueryInfo, RetrievalResult
from tests.fixtures import SAMPLES, draft_for


class DemoScenariosTests(unittest.TestCase):
    def test_eighteen_scripted_scenarios(self):
        cfg = LConfig(max_repairs=0)
        for question_id, names in DEMO_EVIDENCE.items():
            with self.subTest(demo=question_id), patch.object(socket.socket, 'connect', side_effect=AssertionError('offline')):
                chunks = [SAMPLES[n] for n in names]
                q = QueryInfo('Вопрос демо ' + question_id, 'Вопрос демо ' + question_id, rewritten='Вопрос демо ' + question_id)
                signals = {'topic_not_in_base': True} if question_id == '3' else {}
                if question_id == '13':
                    signals['explicit_ref_missing'] = '152-ФЗ, статьи 6, 10 и 11'
                r = RetrievalResult(chunks, signals=signals)
                client = ScriptedLLM([draft_for(chunks), review_ok(len(chunks))] if chunks else [])
                result = answer(q, r, client=client, config=cfg)
                expected = 'refused' if question_id == '3' else ('partial' if question_id == '13' else 'answered')
                self.assertEqual(result.status, expected, result.debug)
                self.assertEqual(len(result.claims), len(chunks))
                self.assertTrue(result.text)
                for claim in result.claims:
                    self.assertIn(claim['quote'], next(c.text for c in chunks if c.chunk_id == claim['chunk_id']))


if __name__ == '__main__':
    unittest.main()
