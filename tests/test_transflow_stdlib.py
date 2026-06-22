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

    def test_bad_port_falls_back_to_default(self):
        old = os.environ.get("NLLW_PORT")
        try:
            for value in ["bad", "0", "70000", ""]:
                with self.subTest(value=value):
                    os.environ["NLLW_PORT"] = value
                    self.assertEqual(self.workflow.port(), self.workflow.DEFAULT_PORT)
            os.environ["NLLW_PORT"] = "12345"
            self.assertEqual(self.workflow.port(), 12345)
        finally:
            if old is None:
                os.environ.pop("NLLW_PORT", None)
            else:
                os.environ["NLLW_PORT"] = old

    def test_stable_uid_is_deterministic(self):
        a = self.workflow.stable_uid("tr", "en", "zh", "hello")
        b = self.workflow.stable_uid("tr", "en", "zh", "hello")
        c = self.workflow.stable_uid("tr", "en", "zh", "world")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


if __name__ == "__main__":
    unittest.main()
