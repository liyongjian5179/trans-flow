from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_workflow_module():
    spec = importlib.util.spec_from_file_location("transflow_workflow", ROOT / "workflow" / "transflow.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BackendLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT))
        cls.lang = importlib.import_module("backend.lang")

    def test_normalize_lang_aliases(self):
        cases = {
            "en": "eng_Latn",
            "zh-cn": "zho_Hans",
            "zh_hant": "zho_Hant",
            "日": "jpn_Jpan",
            "韩语": "kor_Hang",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(self.lang.normalize_lang(raw), expected)

    def test_detect_source_lang_common_scripts(self):
        cases = {
            "你好": "zho_Hans",
            "臺灣天氣很好": "zho_Hant",
            "こんにちは": "jpn_Jpan",
            "안녕하세요": "kor_Hang",
            "привет": "rus_Cyrl",
            "مرحبا": "arb_Arab",
            "bonjour tout le monde": "fra_Latn",
            "hola buenos dias": "spa_Latn",
            "hallo danke": "deu_Latn",
            "how are you": "eng_Latn",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.lang.detect_source_lang(text), expected)

    def test_choose_auto_dst(self):
        self.assertEqual(self.lang.choose_auto_dst("eng_Latn"), "zho_Hans")
        self.assertEqual(self.lang.choose_auto_dst("zho_Hans"), "eng_Latn")
        self.assertEqual(self.lang.choose_auto_dst("zho_Hant"), "eng_Latn")


class BackendTranslatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT))
        cls.translator_mod = importlib.import_module("backend.translator")

    def test_text_part_extracts_timed_text_text(self):
        class FakeTimedText:
            def __init__(self, text):
                self.text = text

            def __str__(self):
                return f"TimedText(text={self.text!r}, start=0.0, end=0)"

        tr = self.translator_mod.NLLWTranslator
        self.assertEqual(tr._text_part(FakeTimedText("你好")), "你好")
        self.assertEqual(tr._text_part([FakeTimedText("你"), FakeTimedText("好")]), "你好")
        self.assertEqual(tr._text_part(FakeTimedText("")), "")
        self.assertEqual(tr._join_parts(FakeTimedText("你"), FakeTimedText("好")), ("你", "好", "你 好"))

    def test_direct_translation_extracts_backend_result(self):
        class FakeBackend:
            def simple_translation(self, text):
                return ["ignored"], f"translated:{text}"

        class FakeTranslator:
            backend = FakeBackend()

        tr = self.translator_mod.NLLWTranslator
        self.assertEqual(tr._direct_translation(FakeTranslator(), "hello"), "translated:hello")


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = load_workflow_module()

    def test_parse_query_auto_and_overrides(self):
        parsed = self.workflow.parse_translation_query("how are you")
        self.assertEqual((parsed.src, parsed.dst, parsed.text), ("eng_Latn", "zho_Hans", "how are you"))

        parsed = self.workflow.parse_translation_query("zh_hant>en 臺灣天氣很好")
        self.assertEqual((parsed.src, parsed.dst, parsed.text), ("zho_Hant", "eng_Latn", "臺灣天氣很好"))

        parsed = self.workflow.parse_translation_query("ja 你好")
        self.assertEqual((parsed.src, parsed.dst, parsed.text), ("zho_Hans", "jpn_Jpan", "你好"))

        parsed = self.workflow.parse_translation_query("en>ja how are you")
        self.assertEqual((parsed.src, parsed.dst, parsed.text), ("eng_Latn", "jpn_Jpan", "how are you"))

        parsed = self.workflow.parse_translation_query("to fr hello")
        self.assertEqual((parsed.src, parsed.dst, parsed.text), ("eng_Latn", "fra_Latn", "hello"))

    def test_remote_api_url_is_required(self):
        old_api_url = os.environ.get("NLLW_API_URL")
        try:
            os.environ.pop("NLLW_API_URL", None)
            self.assertEqual(self.workflow.api_base_url(), "")
            with self.assertRaises(RuntimeError):
                self.workflow.endpoint("/health")

            os.environ["NLLW_API_URL"] = "https://translate.example.com/"
            self.assertEqual(self.workflow.api_base_url(), "https://translate.example.com")
            self.assertEqual(self.workflow.endpoint("/health"), "https://translate.example.com/health")
        finally:
            if old_api_url is None:
                os.environ.pop("NLLW_API_URL", None)
            else:
                os.environ["NLLW_API_URL"] = old_api_url

    def test_api_key(self):
        old_key = os.environ.get("NLLW_API_KEY")
        try:
            os.environ.pop("NLLW_API_KEY", None)
            self.assertEqual(self.workflow.api_key(), "")

            os.environ["NLLW_API_KEY"] = "new-key"
            self.assertEqual(self.workflow.api_key(), "new-key")
        finally:
            if old_key is None:
                os.environ.pop("NLLW_API_KEY", None)
            else:
                os.environ["NLLW_API_KEY"] = old_key

    def test_stable_uid_is_deterministic(self):
        a = self.workflow.stable_uid("tr", "en", "zh", "hello")
        b = self.workflow.stable_uid("tr", "en", "zh", "hello")
        c = self.workflow.stable_uid("tr", "en", "zh", "world")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_clean_api_text_removes_timed_text_repr(self):
        self.assertEqual(
            self.workflow.clean_api_text("TimedText(text='hello', start=0.0, end=1)"),
            "hello",
        )
        self.assertEqual(
            self.workflow.clean_api_text("TimedText(text='', start=0.0, end=0) TimedText(text='', start=0.0, end=0)"),
            "",
        )


if __name__ == "__main__":
    unittest.main()
