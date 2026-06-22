"""Fast local language normalization/detection helpers for NLLB/NLLW."""
from __future__ import annotations

import re

LANG_ALIASES = {
    "en": "eng_Latn", "eng": "eng_Latn", "english": "eng_Latn", "英文": "eng_Latn", "英语": "eng_Latn", "英": "eng_Latn",
    "zh": "zho_Hans", "cn": "zho_Hans", "zh-cn": "zho_Hans", "zh_hans": "zho_Hans", "chinese": "zho_Hans", "中文": "zho_Hans", "汉语": "zho_Hans", "中": "zho_Hans",
    "zh-tw": "zho_Hant", "zh_hant": "zho_Hant", "tw": "zho_Hant", "繁中": "zho_Hant", "繁体": "zho_Hant",
    "ja": "jpn_Jpan", "jp": "jpn_Jpan", "japanese": "jpn_Jpan", "日语": "jpn_Jpan", "日文": "jpn_Jpan", "日": "jpn_Jpan",
    "ko": "kor_Hang", "kr": "kor_Hang", "korean": "kor_Hang", "韩语": "kor_Hang", "韩文": "kor_Hang", "韩": "kor_Hang",
    "fr": "fra_Latn", "fra": "fra_Latn", "french": "fra_Latn", "法语": "fra_Latn", "法文": "fra_Latn", "法": "fra_Latn",
    "de": "deu_Latn", "ger": "deu_Latn", "deu": "deu_Latn", "german": "deu_Latn", "德语": "deu_Latn", "德文": "deu_Latn", "德": "deu_Latn",
    "es": "spa_Latn", "spa": "spa_Latn", "spanish": "spa_Latn", "西语": "spa_Latn", "西班牙语": "spa_Latn", "西": "spa_Latn",
    "it": "ita_Latn", "ita": "ita_Latn", "italian": "ita_Latn", "意大利语": "ita_Latn", "意": "ita_Latn",
    "pt": "por_Latn", "por": "por_Latn", "portuguese": "por_Latn", "葡语": "por_Latn", "葡": "por_Latn",
    "ru": "rus_Cyrl", "rus": "rus_Cyrl", "russian": "rus_Cyrl", "俄语": "rus_Cyrl", "俄文": "rus_Cyrl", "俄": "rus_Cyrl",
    "ar": "arb_Arab", "ara": "arb_Arab", "arabic": "arb_Arab", "阿语": "arb_Arab", "阿拉伯语": "arb_Arab", "阿": "arb_Arab",
    "hi": "hin_Deva", "hin": "hin_Deva", "hindi": "hin_Deva", "印地语": "hin_Deva",
    "id": "ind_Latn", "ind": "ind_Latn", "indonesian": "ind_Latn", "印尼语": "ind_Latn",
    "vi": "vie_Latn", "vie": "vie_Latn", "vietnamese": "vie_Latn", "越南语": "vie_Latn", "越": "vie_Latn",
    "th": "tha_Thai", "tha": "tha_Thai", "thai": "tha_Thai", "泰语": "tha_Thai", "泰": "tha_Thai",
    "tr": "tur_Latn", "tur": "tur_Latn", "turkish": "tur_Latn", "土耳其语": "tur_Latn", "土": "tur_Latn",
    "nl": "nld_Latn", "nld": "nld_Latn", "dutch": "nld_Latn", "荷兰语": "nld_Latn",
    "pl": "pol_Latn", "pol": "pol_Latn", "polish": "pol_Latn", "波兰语": "pol_Latn",
    "uk": "ukr_Cyrl", "ua": "ukr_Cyrl", "ukr": "ukr_Cyrl", "ukrainian": "ukr_Cyrl", "乌克兰语": "ukr_Cyrl",
}

LANG_DISPLAY_NAMES = {
    "eng_Latn": "英语", "zho_Hans": "中文", "zho_Hant": "繁中", "jpn_Jpan": "日语",
    "kor_Hang": "韩语", "fra_Latn": "法语", "deu_Latn": "德语", "spa_Latn": "西语",
    "ita_Latn": "意大利语", "por_Latn": "葡语", "rus_Cyrl": "俄语", "arb_Arab": "阿语",
    "vie_Latn": "越南语", "tha_Thai": "泰语", "hin_Deva": "印地语", "ind_Latn": "印尼语",
}


def normalize_lang(value: str | None, fallback: str | None = None) -> str:
    raw = (value or fallback or "").strip()
    if not raw:
        raise ValueError("empty language")
    key = raw.lower()
    return LANG_ALIASES.get(key) or LANG_ALIASES.get(key.replace("_", "-")) or LANG_ALIASES.get(key.replace("-", "_")) or raw


def _has_range(text: str, start: int, end: int) -> bool:
    return any(start <= ord(ch) <= end for ch in text)


def _latin_guess(text: str) -> str:
    lower = text.lower()
    if re.search(r"[ăâêôơưđạảấầẩẫậắằẳẵặẹẻẽếềểễệịỉĩọỏốồổỗộớờởỡợụủứừửữựỳỷỹ]", lower):
        return "vie_Latn"
    if "ß" in lower or re.search(r"[äöü]", lower):
        return "deu_Latn"
    if "ñ" in lower or "¿" in text or "¡" in text:
        return "spa_Latn"
    if re.search(r"(?:ção|ções| não | você| obrigado)", f" {lower} ") or re.search(r"[ãõ]", lower):
        return "por_Latn"
    if re.search(r"[çœ]", lower) or re.search(r"\b(?:bonjour|merci|avec|pour|est|une|vous|nous)\b", lower):
        return "fra_Latn"
    if re.search(r"\b(?:hola|gracias|usted|para|como|qué|buenos|buenas)\b", lower):
        return "spa_Latn"
    if re.search(r"\b(?:hallo|danke|nicht|und|ich|sie|der|die|das)\b", lower):
        return "deu_Latn"
    return "eng_Latn"


def detect_source_lang(text: str, fallback: str = "eng_Latn") -> str:
    text = (text or "").strip()
    if not text:
        return fallback
    if _has_range(text, 0x3040, 0x30FF):
        return "jpn_Jpan"
    if _has_range(text, 0xAC00, 0xD7AF) or _has_range(text, 0x1100, 0x11FF):
        return "kor_Hang"
    if _has_range(text, 0x4E00, 0x9FFF):
        trad_markers = set("臺灣萬與專業東絲兩嚴喪個豐臨為麗舉麼義烏樂喬習鄉書買亂爭於虧雲亞產畝親褻褲貝貞負財責賢敗帳貨質販貪貧貼貴貸費貿賀賁資賈賊賑賓賜賞賠賢賣賤賦質賬賭賴賺購賽贊贈贏趙趕趨趲跡踐輕載輝輩輪輯輸轄辦辭辯農這連週進遊運過達違遙遜遞遠適遷選遺遼邁還邇邊邏鄧鄭鄰醫釋釐鈔鐘鋼錄錢錦鍵鎖長門開間關闆隊陽陰陣階際陸隻難電霧靈頁頂項順須預頓領頭顧風飛飯飲館馬駐駕驗體髮鬥魚鳥鳴麗麥黃點齊齒龍")
        return "zho_Hant" if any(ch in trad_markers for ch in text) else "zho_Hans"
    if _has_range(text, 0x0400, 0x04FF):
        return "rus_Cyrl"
    if _has_range(text, 0x0600, 0x06FF):
        return "arb_Arab"
    if _has_range(text, 0x0590, 0x05FF):
        return "heb_Hebr"
    if _has_range(text, 0x0900, 0x097F):
        return "hin_Deva"
    if _has_range(text, 0x0E00, 0x0E7F):
        return "tha_Thai"
    if _has_range(text, 0x0370, 0x03FF):
        return "ell_Grek"
    if _has_range(text, 0x0B80, 0x0BFF):
        return "tam_Taml"
    if _has_range(text, 0x0C00, 0x0C7F):
        return "tel_Telu"
    if _has_range(text, 0x1780, 0x17FF):
        return "khm_Khmr"
    if _has_range(text, 0x1000, 0x109F):
        return "mya_Mymr"
    return _latin_guess(text)


def choose_auto_dst(src: str, primary: str = "zho_Hans", alt: str = "eng_Latn") -> str:
    if src == primary or (src.startswith("zho_") and primary.startswith("zho_")):
        return alt
    return primary
