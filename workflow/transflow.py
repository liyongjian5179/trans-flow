#!/usr/bin/env python3
"""
Alfred workflow client for TransFlow / NLLW.

Modes:
  script-filter [query]  -> emits Alfred JSON
  action <json>          -> handles selected Alfred item

This workflow is a remote API client only. It never starts or calls a built-in
localhost translation service; set NLLW_API_URL to your backend endpoint.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, Optional

# Common aliases. nllw ultimately expects NLLB language identifiers.
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

PAIR_RE = re.compile(r"^\s*([\w\-\u4e00-\u9fff]+)\s*(?:>|->|=>|2|to)\s*([\w\-\u4e00-\u9fff]+)\s+(.+)$", re.I | re.S)
TO_RE = re.compile(r"^\s*(?:to|翻译成|译为)\s+([\w\-\u4e00-\u9fff]+)\s+(.+)$", re.I | re.S)
TARGET_PREFIX_RE = re.compile(r"^\s*(?:@|/)?([\w\-\u4e00-\u9fff]+)[:：]?\s+(.+)$", re.I | re.S)
QUICK_TARGET_TERMS = {
    "en", "eng", "english", "英文", "英语", "英",
    "zh", "cn", "中文", "汉语", "中",
    "ja", "jp", "japanese", "日语", "日文", "日",
    "ko", "kr", "korean", "韩语", "韩文", "韩",
    "fr", "french", "法语", "法文", "法",
    "de", "german", "德语", "德文", "德",
    "es", "spanish", "西语", "西班牙语", "西",
    "ru", "russian", "俄语", "俄文", "俄",
    "ar", "arabic", "阿语", "阿拉伯语", "阿",
    "it", "italian", "意大利语", "意",
    "pt", "portuguese", "葡语", "葡",
    "vi", "vietnamese", "越南语", "越",
    "th", "thai", "泰语", "泰",
}
LANG_DISPLAY_NAMES = {
    "eng_Latn": "英语", "zho_Hans": "中文", "zho_Hant": "繁中", "jpn_Jpan": "日语",
    "kor_Hang": "韩语", "fra_Latn": "法语", "deu_Latn": "德语", "spa_Latn": "西语",
    "ita_Latn": "意大利语", "por_Latn": "葡语", "rus_Cyrl": "俄语", "arb_Arab": "阿语",
    "vie_Latn": "越南语", "tha_Thai": "泰语",
}
LANG_SHORT_ALIASES = {
    "eng_Latn": "en", "zho_Hans": "zh", "zho_Hant": "tw", "jpn_Jpan": "ja", "kor_Hang": "ko",
    "fra_Latn": "fr", "deu_Latn": "de", "spa_Latn": "es", "ita_Latn": "it", "por_Latn": "pt",
    "rus_Cyrl": "ru", "arb_Arab": "ar", "vie_Latn": "vi", "tha_Thai": "th",
}


def api_base_url() -> str:
    raw = os.environ.get("NLLW_API_URL", "").strip()
    return raw.rstrip("/") if raw else ""


def api_key() -> str:
    return os.environ.get("NLLW_API_KEY", "").strip()


def endpoint(path: str) -> str:
    base = api_base_url()
    if not base:
        raise RuntimeError("NLLW_API_URL 未配置。请在 Alfred Workflow 环境变量中设置远程后端地址。")
    return f"{base}{path}"


def normalize_lang(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("empty language")
    key = value.lower()
    return LANG_ALIASES.get(key) or LANG_ALIASES.get(key.replace("_", "-")) or LANG_ALIASES.get(key.replace("-", "_")) or value


@dataclasses.dataclass
class ParsedQuery:
    src: str
    dst: str
    text: str
    display_pair: str


def default_src() -> str:
    return normalize_lang(os.environ.get("NLLW_SRC_LANG", os.environ.get("NLLW_SRC", "eng_Latn")))


def default_dst() -> str:
    return normalize_lang(os.environ.get("NLLW_DST_LANG", os.environ.get("NLLW_DST", "zho_Hans")))


def auto_primary_lang() -> str:
    # Translate non-primary languages into this language. Default: Chinese.
    return normalize_lang(os.environ.get("NLLW_AUTO_TARGET_LANG", os.environ.get("NLLW_DST_LANG", "zho_Hans")))


def auto_alt_lang() -> str:
    # If the detected source is already the primary language, translate into this.
    # Default: English.
    return normalize_lang(os.environ.get("NLLW_AUTO_ALT_TARGET_LANG", os.environ.get("NLLW_SRC_LANG", "eng_Latn")))


def _has_range(text: str, start: int, end: int) -> bool:
    return any(start <= ord(ch) <= end for ch in text)


def _count_range(text: str, start: int, end: int) -> int:
    return sum(1 for ch in text if start <= ord(ch) <= end)


def _latin_guess(text: str) -> str:
    lower = text.lower()
    # Lightweight heuristics for common Latin-script languages. Ambiguous Latin
    # text falls back to English; users can still force e.g. `fr>zh bonjour`.
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


def detect_source_lang(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return default_src()
    # Scripts with highly reliable Unicode ranges.
    if _has_range(text, 0x3040, 0x30FF):  # Hiragana + Katakana
        return "jpn_Jpan"
    if _has_range(text, 0xAC00, 0xD7AF) or _has_range(text, 0x1100, 0x11FF):
        return "kor_Hang"
    if _has_range(text, 0x4E00, 0x9FFF):
        # Han-only text is most often Chinese in Alfred translation use.
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


def choose_auto_dst(src: str) -> str:
    primary = auto_primary_lang()
    alt = auto_alt_lang()
    # Treat Simplified/Traditional Chinese as the same primary family.
    if src == primary or (src.startswith("zho_") and primary.startswith("zho_")):
        return alt
    return primary


def parse_translation_query(query: str) -> ParsedQuery:
    query = (query or "").strip()
    if not query:
        raise ValueError("empty query")
    m = PAIR_RE.match(query)
    if m:
        src_raw, dst_raw, text = m.groups()
        src = normalize_lang(src_raw)
        dst = normalize_lang(dst_raw)
        return ParsedQuery(src=src, dst=dst, text=text.strip(), display_pair=f"{src} → {dst}")
    m = TO_RE.match(query)
    if m:
        dst_raw, text = m.groups()
        src = detect_source_lang(text)
        dst = normalize_lang(dst_raw)
        return ParsedQuery(src=src, dst=dst, text=text.strip(), display_pair=f"auto:{src} → {dst}")
    # Ultra-short target override: `f ja 你好`, `f 日 how are you`,
    # `f @fr 你好`, `f /ko hello`, etc. Source remains auto-detected.
    m = TARGET_PREFIX_RE.match(query)
    if m and m.group(1).lower() in QUICK_TARGET_TERMS:
        dst_raw, text = m.groups()
        src = detect_source_lang(text)
        dst = normalize_lang(dst_raw)
        return ParsedQuery(src=src, dst=dst, text=text.strip(), display_pair=f"auto:{src} → {dst}")
    src = detect_source_lang(query)
    dst = choose_auto_dst(src)
    return ParsedQuery(src=src, dst=dst, text=query, display_pair=f"auto:{src} → {dst}")


def json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def stable_uid(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("\0".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


TIMED_TEXT_RE = re.compile(r"TimedText\(text=(['\"])(.*?)\1,\s*start=[^,)]*,\s*end=[^)]*\)")
LEADING_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*•]\s+)+")


def clean_api_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    matches = TIMED_TEXT_RE.findall(text)
    if matches:
        text = " ".join(part for _quote, part in matches if part).strip()
    return LEADING_LIST_MARKER_RE.sub("", text).strip()


def item(
    title: str,
    subtitle: str = "",
    arg: Optional[Dict[str, Any]] = None,
    valid: bool = True,
    icon: str = "icon.png",
    uid: Optional[str] = None,
    autocomplete: Optional[str] = None,
    copy_text: Optional[str] = None,
    mods: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    it: Dict[str, Any] = {
        "title": title,
        "subtitle": subtitle,
        "valid": valid,
        "icon": {"path": icon},
    }
    if uid:
        it["uid"] = uid
    if arg is not None:
        it["arg"] = json_dumps(arg)
    if autocomplete:
        it["autocomplete"] = autocomplete
    if copy_text:
        it["text"] = {"copy": copy_text, "largetype": copy_text}
    if mods:
        it["mods"] = mods
    return it


def emit_items(items: Iterable[Dict[str, Any]]) -> None:
    print(json_dumps({"items": list(items)}))


def lang_label(lang: str) -> str:
    return LANG_DISPLAY_NAMES.get(lang, lang)


def quick_target_items(parsed: ParsedQuery, current_translation: str = "") -> list[Dict[str, Any]]:
    # Alternative targets shown as Alfred options. Selecting them autocompletes
    # the query with a short target prefix; Alfred then translates on the next run.
    preferred = ["eng_Latn", "zho_Hans", "jpn_Jpan", "kor_Hang", "fra_Latn", "deu_Latn", "spa_Latn"]
    out: list[Dict[str, Any]] = []
    for lang in preferred:
        if lang == parsed.dst or lang == parsed.src:
            continue
        # Avoid offering Chinese as a target for Chinese-family input.
        if lang.startswith("zho_") and parsed.src.startswith("zho_"):
            continue
        alias = LANG_SHORT_ALIASES.get(lang, lang)
        out.append(item(
            f"翻译成{lang_label(lang)}",
            f"使用：{alias} {parsed.text[:60]}",
            valid=False,
            autocomplete=f"{alias} {parsed.text}",
            uid=f"target-{lang}",
        ))
    return out


def url_json(path: str, payload: Optional[Dict[str, Any]] = None, timeout: float = 1.5) -> Dict[str, Any]:
    url = endpoint(path)
    data = None
    headers = {"Accept": "application/json"}
    key = api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    method = "GET"
    if payload is not None:
        data = json_dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
        method = "POST"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def notify(title: str, message: str = "") -> None:
    # Works when run inside Alfred; silently ignore outside macOS GUI sessions.
    script = f'display notification {json.dumps(message)} with title {json.dumps(title)}'
    try:
        subprocess.run(["/usr/bin/osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    except Exception:
        pass


def copy_to_clipboard(text: str) -> None:
    subprocess.run(["/usr/bin/pbcopy"], input=text.encode("utf-8"), check=False)


def action(arg: str) -> None:
    try:
        payload = json.loads(arg)
    except Exception:
        payload = {"action": "copy", "text": arg}
    act = payload.get("action")
    if act == "copy":
        text = payload.get("text", "")
        copy_to_clipboard(text)
        notify("TransFlow", "译文已复制")
    else:
        notify("TransFlow", f"未知动作：{act}")


def script_filter(query: str) -> None:
    q = (query or "").strip()
    base = api_base_url()

    if not q:
        emit_items([
            item(
                "直接输入要翻译的内容",
                "默认：其他语言→中文，中文→英文；指定目标：f ja 你好 / f fr hello",
                valid=False,
                autocomplete="how are you",
            ),
            item(
                "远程后端：" + (base or "未配置"),
                "在 Environment Variables 中设置 NLLW_API_URL 和 NLLW_API_KEY" if not base else "仅请求远程 API，不使用本地服务",
                valid=False,
                uid="remote-backend-status",
            ),
        ])
        return

    try:
        parsed = parse_translation_query(q)
    except Exception as e:
        emit_items([item("无法解析翻译请求", str(e), valid=False)])
        return

    if not base:
        emit_items([
            item(
                "未配置远程后端",
                "请在 Alfred Workflow 的 Environment Variables 中设置 NLLW_API_URL，例如：https://translate.example.com",
                valid=False,
                uid="api-url-missing",
            ),
            item(f"待翻译：{parsed.text[:70]}", f"方向：{parsed.display_pair}", valid=False),
            *quick_target_items(parsed),
        ])
        return

    timeout = float(os.environ.get("NLLW_REQUEST_TIMEOUT", "25"))
    try:
        resp = url_json("/translate", payload=dataclasses.asdict(parsed), timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            detail = str(e)
        emit_items([item("翻译失败", detail[:220], valid=False)])
        return
    except Exception as e:
        emit_items([item("远程翻译服务不可用", f"{type(e).__name__}: {e}", valid=False)])
        return

    if not resp.get("ok"):
        err = resp.get("error", "unknown error")
        emit_items([item("翻译失败", str(err)[:220], valid=False)])
        return

    translated = clean_api_text(resp.get("translation"))
    validated = clean_api_text(resp.get("validated"))
    buffer = clean_api_text(resp.get("buffer"))
    if not translated:
        translated = validated or buffer or ""
    if not translated:
        emit_items([
            item(
                "远程后端返回空译文",
                "请重新部署后端；旧版本会返回空 TimedText 对象",
                valid=False,
                uid="empty-translation",
            ),
            item(f"待翻译：{parsed.text[:70]}", f"方向：{parsed.display_pair}", valid=False),
            *quick_target_items(parsed),
        ])
        return
    subtitle = f"{parsed.display_pair} · 回车复制译文"
    mods = {
        "cmd": {
            "valid": True,
            "arg": json_dumps({"action": "copy", "text": parsed.text}),
            "subtitle": "复制原文",
        }
    }
    items = [item(
        translated or "（空译文）",
        subtitle,
        arg={"action": "copy", "text": translated},
        uid=stable_uid("tr", parsed.src, parsed.dst, parsed.text, translated),
        copy_text=translated,
        mods=mods,
    )]
    if validated and buffer and translated != validated:
        items.append(item("稳定前缀 / 临时缓冲", f"validated: {validated} | buffer: {buffer}", valid=False))
    items.extend(quick_target_items(parsed, translated))
    emit_items(items)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Alfred workflow client for TransFlow")
    sub = parser.add_subparsers(dest="cmd")
    sf = sub.add_parser("script-filter")
    sf.add_argument("query", nargs="*", default=[])
    act = sub.add_parser("action")
    act.add_argument("arg", nargs="?", default="")
    args = parser.parse_args(argv)

    if args.cmd == "script-filter":
        script_filter(" ".join(args.query))
    elif args.cmd == "action":
        action(args.arg)
    else:
        parser.print_help()
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
