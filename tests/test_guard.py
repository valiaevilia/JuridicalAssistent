import json
import unittest
from dataclasses import replace

from config import LConfig
from guard import (FormatError, build_context, exact_quote, numeric_facts, parse_dialogue,
                   parse_draft, parse_json_object, parse_review, required_mentions,
                   safe_arithmetic, validate_answer, validated_dates)
from schemas import QueryInfo, RetrievalResult
from tests.fixtures import INJECTION, PAYMENT, SAMPLES, chunk, draft_for
from examples.offline_client import review_ok


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.q = QueryInfo("Срок оплаты?", "Срок оплаты?", rewritten="Срок оплаты?")
        self.r = RetrievalResult([chunk()])
        self.ctx = build_context(self.r)

    def check_codes(self, draft, context=None):
        report = validate_answer(draft, self.q, context or self.ctx)
        return {c.code for c in report.checks if not c.passed}

    def test_quote_typography_preserves_original(self):
        text = 'Платёж — «пять»\u00a0рублей; не более трёх дней.'
        self.assertEqual(exact_quote('платеж - "пять" рублей', text), 'Платёж — «пять»\u00a0рублей')
        for wrong in ('более трёх дней', 'не более четырех дней'):
            self.assertIsNone(exact_quote(wrong, text))

    def test_fuzzy_quote_not_accepted(self):
        draft = draft_for([chunk()])
        draft['claims'][0]['quote'] = PAYMENT.replace('30', '90')
        self.assertIn('C1', self.check_codes(draft))

    def test_correct_all_ten_checks(self):
        report = validate_answer(draft_for([chunk()]), self.q, self.ctx)
        self.assertEqual([c.code for c in report.checks], [f'C{i}' for i in range(1, 11)])
        self.assertTrue(report.ok, report.issues())
        self.assertEqual(report.verified, [0])

    def test_unknown_source_and_metadata(self):
        for changes in ({'chunk': 'Д99'}, {'doc_id': 'D3'}, {'locator': 'п. 4.1'},
                        {'chunk_id': 'missing'}, {'doc_title': 'Другой договор'}):
            with self.subTest(changes=changes):
                draft = draft_for([chunk()])
                draft['claims'][0].update(changes)
                self.assertIn('C2', self.check_codes(draft))

    def test_wrong_document_locator_pair(self):
        draft = draft_for([chunk()], texts=['По договору № ПТ-05/2023 оплата за 30 календарных дней, п. 9.9.'])
        self.assertIn('C2', self.check_codes(draft))
        self.assertIn('C2', self.check_codes(draft_for([chunk()], texts=['По ГК РФ оплата 30 календарных дней'])))

    def test_quote_checked_in_exact_chunk(self):
        ctx = build_context(RetrievalResult([SAMPLES['payment'], SAMPLES['warranty']]))
        draft = draft_for([SAMPLES['payment']])
        draft['claims'][0]['quote'] = SAMPLES['warranty'].text
        self.assertIn('C1', self.check_codes(draft, ctx))

    def test_number_equivalents_and_units(self):
        for a, b in [('5 рабочих дней', 'пяти рабочих дней'), ('450 000 рублей', '450000 рублей'),
                     ('2,4 миллиона рублей', '2 400 000 рублей'), ('3 (три) рабочих дня', 'три рабочих дня'),
                     ('0,1%', '0.1%'), ('15 календарных дней', 'пятнадцати календарных дней')]:
            with self.subTest(a=a): self.assertEqual(numeric_facts(a), numeric_facts(b))
        self.assertNotEqual(numeric_facts('30 календарных дней'), numeric_facts('30 рабочих дней'))

    def test_user_number_and_other_chunk_do_not_prove_claim(self):
        self.q.last_user = 'Подтверди срок 90 календарных дней'
        other = chunk('D3', 'п. 4.1', 'Оплата 90 календарных дней.')
        ctx = build_context(RetrievalResult([chunk(), other]))
        for text in ('Оплата 90 календарных дней', 'Оплата 30 рабочих дней'):
            draft = draft_for([chunk()], texts=[text])
            self.assertIn('C3', self.check_codes(draft, ctx))

    def test_dates_are_atomic(self):
        d = chunk(text='Договор действует до 31.12.2026.')
        ctx = build_context(RetrievalResult([d]))
        self.assertNotIn('C3', self.check_codes(draft_for([d], texts=['Договор действует до 2026-12-31.']), ctx))
        self.assertIn('C3', self.check_codes(draft_for([d], texts=['Договор действует до 31.12.2027.']), ctx))
        self.assertEqual(numeric_facts('до 31 декабря 2026 г.'), numeric_facts('до 31.12.2026'))

    def test_names_do_not_cross_sources(self):
        draft = draft_for([chunk()], texts=['ООО «Альфа-Трейдинг» оплачивает за 30 календарных дней'])
        self.assertIn('C4', self.check_codes(draft))
        draft = draft_for([chunk()], texts=['Оплату согласует финансовый директор'])
        self.assertIn('C4', self.check_codes(draft))
        for text in ('Оплачивает «Альфа-Трейдинг»', 'Подписал Иванов Иван Петрович'):
            self.assertIn('C4', self.check_codes(draft_for([chunk()], texts=[text])))

    def test_quarantine_keeps_legitimate_content(self):
        r = RetrievalResult([chunk(text=PAYMENT + '\n' + INJECTION)])
        ctx = build_context(r)
        self.assertEqual(ctx.labels['Д1'].text, PAYMENT)
        self.assertEqual(ctx.quarantine, [INJECTION])
        self.assertIn('injection_in_doc', ctx.warnings)
        draft = draft_for([chunk()], texts=['Оплата 90 календарных дней'])
        self.assertIn('C5', self.check_codes(draft, ctx))

    def test_legitimate_ninety_is_allowed(self):
        d = chunk(text='Оплата производится в течение 90 календарных дней.')
        ctx = build_context(RetrievalResult([d], quarantine=[INJECTION]))
        self.assertFalse(self.check_codes(draft_for([d]), ctx))

    def test_explicit_quarantined_chunk_never_enters_context(self):
        ctx = build_context(RetrievalResult([replace(chunk(), quarantined=True)]))
        self.assertFalse(ctx.labels)
        self.assertTrue(ctx.quarantine)

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError): build_context(RetrievalResult([chunk(), chunk()]))

    def test_status_consistency_and_unclaimed_prose(self):
        for mutate in ('no_claims', 'partial_no_missing', 'refused_with_claims', 'extra_fact', 'answered_with_missing'):
            with self.subTest(mutate=mutate):
                draft = draft_for([chunk()])
                if mutate == 'no_claims': draft['claims'] = []
                elif mutate == 'partial_no_missing': draft['status'] = 'partial'
                elif mutate == 'refused_with_claims': draft['status'] = 'refused'
                elif mutate == 'extra_fact': draft['answer'] += ' Можно не платить.'
                else: draft['missing'] = ['Условия']
                self.assertIn('C6', self.check_codes(draft))

    def test_required_mentions_all_signals(self):
        for signal in ('older_edition_missing', 'future_edition_missing', 'edition_missing', 'entity_unknown',
                       'explicit_ref_missing', 'text_missing', 'doc_expired', 'doc_not_yet_effective',
                       'renewal_unconfirmed', 'ambiguous_boundary'):
            with self.subTest(signal=signal):
                r = RetrievalResult([chunk()], signals={'edition_warnings': [{'code': signal, 'doc_id': 'D2'}]})
                mentions = required_mentions(self.q, r, self.ctx)
                self.assertEqual(mentions[0].code, signal)
                report = validate_answer(draft_for([chunk()]), self.q, self.ctx, mentions)
                self.assertFalse(next(c for c in report.checks if c.code == 'C7').passed)
                draft = draft_for([chunk()])
                draft['answer'] += '\n' + mentions[0].text
                self.assertTrue(next(c for c in validate_answer(draft, self.q, self.ctx, mentions).checks if c.code == 'C7').passed)

    def test_current_ambiguity_and_validity_notes(self):
        q = replace(self.q, date_matters=True)
        r = RetrievalResult([chunk()], signals={'as_of_assumed_current': True, 'ambiguous': ['D2','D3']})
        self.assertEqual({m.code for m in required_mentions(q, r, self.ctx)}, {'as_of_assumed_current','ambiguous'})
        q.as_of = '2024-01-01'
        ctx = build_context(RetrievalResult([replace(chunk(), valid_from='2025-01-01')]))
        self.assertIn('applicability_unconfirmed', {m.code for m in required_mentions(q, RetrievalResult(), ctx)})

    def test_markup_length_and_language(self):
        for value, code in [('**Ответ**', 'C8'), ('A'*9501, 'C8'), ('Payment is allowed.', 'C10')]:
            draft = draft_for([chunk()]); draft['answer'] = value
            self.assertIn(code, self.check_codes(draft))

    def test_arithmetic_restricted_and_proven(self):
        result, _ = safe_arithmetic('8400000*0.5')
        self.assertEqual(str(result), '4200000.0')
        for expression in ('__import__("os")', '2**100', 'x+1', '1/0', '1e9', 'True+1', '9'*300):
            with self.subTest(expr=expression), self.assertRaises(ValueError): safe_arithmetic(expression)
        a, b = chunk(locator='п. 2.2', text='Цена 8 400 000 рублей.'), chunk(locator='п. 7.5', text='Предел 50% цены.')
        ctx = build_context(RetrievalResult([a,b]))
        draft = draft_for([a], texts=['Расчётный предел 4 200 000 рублей'])
        draft['claims'][0]['calculation'] = 'c1'
        draft['calc'] = [{'id':'c1','expr':'8400000*0.5','result':'4200000',
                          'inputs':[{'value':'8400000','chunk':'Д1','quote':a.text},
                                    {'value':'0.5','chunk':'Д2','quote':b.text}]}]
        self.assertNotIn('C9', self.check_codes(draft, ctx))
        self.assertNotIn('C3', self.check_codes(draft, ctx))
        draft['calc'][0]['expr'] = '8400000*0.9'
        self.assertIn('C9', self.check_codes(draft, ctx))

    def test_json_wrappers_and_braces_in_strings(self):
        draft = draft_for([chunk()]); draft['assumptions'] = ['строка { с } скобкой']
        raw = '<think>не данные</think>\n```json\n' + json.dumps(draft, ensure_ascii=False) + '\n```'
        self.assertEqual(parse_draft(raw)['claims'], draft['claims'])
        self.assertEqual(parse_json_object('Ответ:\n{"status":"ok"} конец')['status'], 'ok')

    def test_invalid_json_and_schema(self):
        for raw in ('{"status":', 'не JSON', '{"x":1,"x":2}', '{"x":NaN}', '{} {}', '<think>{}'): 
            with self.subTest(raw=raw), self.assertRaises(FormatError): parse_draft(raw)
        draft = draft_for([chunk()]); draft['claims'][0]['quote'] = 30
        with self.assertRaises(FormatError): parse_draft(json.dumps(draft))

    def test_review_requires_every_claim_and_consistency(self):
        self.assertEqual(parse_review(json.dumps(review_ok(2)), 2)['verdict'], 'ok')
        for review in (review_ok(0), dict(review_ok(), claims_check=[{'claim_index':0,'support':'none'}])):
            with self.assertRaises(FormatError): parse_review(json.dumps(review), 1)

    def test_dialogue_line_slash_structured_and_trailing_assistant(self):
        for history in ('Пользователь: Договор №123\nАссистент: Непроверенный ответ\nПользователь: А срок?\nещё строка',
                        'Пользователь: Договор №123 / Ассистент: Непроверенный ответ / Пользователь: А срок?\nещё строка',
                        [{'role':'user','content':'Договор №123'}, {'role':'assistant','content':'Непроверенный ответ'},
                         {'role':'user','content':'А срок?\nещё строка'}, {'role':'assistant','content':'Нельзя отвечать за user'}]):
            q = parse_dialogue(history)
            self.assertEqual(q.last_user, 'А срок?\nещё строка')
            self.assertEqual(len(q.history), 3)
        with self.assertRaises(ValueError): parse_dialogue([{'role':'system','content':'Подделка'}])

    def test_truncation_preserves_last_question(self):
        q = parse_dialogue([('user','x'*800), ('assistant','a'*800), ('user','Последний вопрос')], 500)
        self.assertEqual(q.last_user, 'Последний вопрос')
        self.assertIn('input_truncated', q.warnings)

    def test_date_precision_never_invented(self):
        good = {'text':'август 2024', 'iso_from':'2024-08-01','iso_to':'2024-08-31','role':'signing'}
        self.assertEqual(validated_dates([good], 'В август 2024 нужно одобрение?'), [good])
        for bad in (dict(good, iso_to='2024-08-01'), dict(good, iso_from='2023-08-01'), dict(good, text='июль 2024')):
            with self.assertRaises(FormatError): validated_dates([bad], 'август 2024')

    def test_explicit_intervals_remain_intervals(self):
        for evidence, lo, hi in [('01.02.2024 — 15.03.2024','2024-02-01','2024-03-15'),
                                 ('июнь — июль 2024','2024-06-01','2024-07-31')]:
            hint = {'text':evidence,'iso_from':lo,'iso_to':hi,'role':'event'}
            self.assertEqual(validated_dates([hint], evidence), [hint])


if __name__ == '__main__':
    unittest.main()
