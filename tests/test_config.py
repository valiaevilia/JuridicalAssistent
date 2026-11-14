import unittest

from config import LConfig, load_config
from schemas import ConfigurationError


class ConfigTests(unittest.TestCase):
    def test_repository_yaml_and_env(self):
        try:
            cfg = load_config(environ={'S8_ENABLED':'false','MAX_TOKENS':'1024','MAX_REPAIRS':'0'})
        except ConfigurationError as exc:
            if 'PyYAML' in str(exc): self.skipTest('PyYAML не установлена; core работает с явным LConfig')
            raise
        self.assertFalse(cfg.s8_enabled)
        self.assertEqual(cfg.max_tokens, 1500)
        self.assertEqual(cfg.max_repairs, 0)

    def test_invalid_settings_rejected_without_values_in_error(self):
        for kwargs in ({'max_repairs':2}, {'llm_timeout':0}, {'temperature':0.9},
                       {'q_budget_sec':float('nan')}, {'s8_enabled':'false'}, {'answer_hard_limit':10001}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ConfigurationError): LConfig(**kwargs)
        for env in ({'S8_ENABLED':'secret'}, {'MAX_TOKENS':'secret'}, {'LLM_TIMEOUT':'secret'}):
            with self.subTest(env=env), self.assertRaises(ConfigurationError) as caught:
                load_config(environ=env)
            self.assertNotIn('secret', str(caught.exception))

    def test_explicit_missing_yaml_is_not_ignored(self):
        with self.assertRaises(ConfigurationError): load_config('definitely-missing.yaml', environ={})

    def test_imports_do_not_read_config_or_need_keys(self):
        import answer, guard, prompts, schemas
        self.assertTrue(callable(answer.answer))


if __name__ == '__main__':
    unittest.main()
