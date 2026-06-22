#!/usr/bin/env python3
"""
Alfred workflow bridge for NoLanguageLeftWaiting (nllw).

Modes:
  script-filter [query]  -> emits Alfred JSON
  action <json>          -> handles selected Alfred item
  serve                  -> starts local HTTP translation service
  status                 -> CLI status helper

The Alfred UI should not load a 600M/1.3B model on every keystroke, so this
workflow keeps nllw in a small localhost daemon and the Script Filter only calls
that daemon.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import errno
import http.client
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

BUNDLE_ID = "com.codex.alfred.transflow"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

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
QUICK_TARGET_TOKENS = {
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


def workflow_dir() -> Path:
    return Path(__file__).resolve().parent


def cache_dir() -> Path:
    raw = os.environ.get("alfred_workflow_cache")
    if raw:
        p = Path(raw)
    else:
        p = Path.home() / "Library" / "Caches" / BUNDLE_ID
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_dir() -> Path:
    raw = os.environ.get("alfred_workflow_data")
    if raw:
        p = Path(raw)
    else:
        p = Path.home() / "Library" / "Application Support" / BUNDLE_ID
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_path() -> Path:
    return cache_dir() / "server.log"


def pid_path() -> Path:
    return cache_dir() / "server.pid"


def python_executable() -> str:
    # Prefer the workflow venv created by install_deps.sh.
    venv_py = workflow_dir() / ".venv" / "bin" / "python3"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable or "/usr/bin/python3"


def port() -> int:
    raw = os.environ.get("NLLW_PORT", str(DEFAULT_PORT)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_PORT
    if not (1 <= value <= 65535):
        return DEFAULT_PORT
    return value


def host() -> str:
    return os.environ.get("NLLW_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST


def api_base_url() -> str:
    # If set, Alfred calls an external/local backend service directly.
    # Example: http://127.0.0.1:8765 or https://translate.example.com
    raw = os.environ.get("NLLW_API_URL", "").strip()
    if raw:
        return raw.rstrip("/")
    return f"http://{host()}:{port()}"


def api_token() -> str:
    return os.environ.get("NLLW_API_TOKEN", "").strip()


def using_external_api() -> bool:
    return bool(os.environ.get("NLLW_API_URL", "").strip())


def endpoint(path: str) -> str:
    return f"{api_base_url()}{path}"


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
    if m and m.group(1).lower() in QUICK_TARGET_TOKENS:
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
    token = api_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    method = "GET"
    if payload is not None:
        data = json_dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
        method = "POST"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def is_server_running(timeout: float = 0.35) -> bool:
    try:
        health = url_json("/health", timeout=timeout)
        return bool(health.get("ok"))
    except Exception:
        return False


def read_pid() -> Optional[int]:
    try:
        raw = pid_path().read_text().strip()
        return int(raw) if raw else None
    except Exception:
        return None


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError as e:
        return e.errno == errno.EPERM


def start_server() -> str:
    if is_server_running():
        return "TransFlow 服务已经在运行"
    py = python_executable()
    log = log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    with log.open("ab", buffering=0) as fh:
        subprocess.Popen(
            [py, str(Path(__file__).resolve()), "serve"],
            cwd=str(workflow_dir()),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=fh,
            stderr=fh,
            start_new_session=True,
            close_fds=True,
        )
    for _ in range(30):
        if is_server_running(timeout=0.2):
            return "TransFlow 服务已启动"
        time.sleep(0.1)
    return f"已尝试启动，模型可能仍在初始化；日志：{log}"


def stop_server() -> str:
    # Prefer graceful HTTP shutdown.
    try:
        url_json("/shutdown", payload={}, timeout=0.8)
        time.sleep(0.2)
    except Exception:
        pass
    pid = read_pid()
    if pid and process_exists(pid):
        with contextlib.suppress(Exception):
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.2)
    with contextlib.suppress(FileNotFoundError):
        pid_path().unlink()
    return "TransFlow 服务已停止"


def notify(title: str, message: str = "") -> None:
    # Works when run inside Alfred; silently ignore outside macOS GUI sessions.
    script = f'display notification {json.dumps(message)} with title {json.dumps(title)}'
    with contextlib.suppress(Exception):
        subprocess.run(["/usr/bin/osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)


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
    elif act == "start":
        msg = start_server()
        notify("TransFlow", msg)
    elif act == "stop":
        msg = stop_server()
        notify("TransFlow", msg)
    elif act == "copy_install":
        cmd = f'cd {str(workflow_dir()).replace(chr(39), chr(39)+"\\"+chr(39)+chr(39))} && ./install_deps.sh'
        copy_to_clipboard(cmd)
        notify("TransFlow", "安装命令已复制到剪贴板")
    elif act == "copy_log_path":
        copy_to_clipboard(str(log_path()))
        notify("TransFlow", "日志路径已复制")
    else:
        notify("TransFlow", f"未知动作：{act}")


def script_filter(query: str) -> None:
    q = (query or "").strip()
    if not q:
        running = is_server_running()
        emit_items([
            item(
                "直接输入要翻译的内容",
                "默认：其他语言→中文，中文→英文；指定目标：f ja 你好 / f fr hello",
                valid=False,
                autocomplete="how are you",
            ),
            item(
                "服务状态：" + ("运行中" if running else "未运行"),
                (f"后端：{api_base_url()}" if using_external_api() else "回车" + ("停止后台翻译服务" if running else "启动后台翻译服务，首次加载/下载模型会较慢")),
                arg=None if using_external_api() else {"action": "stop" if running else "start"},
                valid=not using_external_api(),
                uid="status",
            ),
            item(
                "安装依赖：pip install nllw",
                "回车复制安装命令；建议先在终端运行，首次会下载模型",
                arg={"action": "copy_install"},
                uid="install",
            ),
        ])
        return

    if q in {":start", "start", "启动"}:
        emit_items([item("启动 TransFlow 后台服务", "回车启动；首次加载/下载模型会较慢", arg={"action": "start"}, uid="start")])
        return
    if q in {":stop", "stop", "停止"}:
        emit_items([item("停止 TransFlow 后台服务", "回车停止后台模型进程", arg={"action": "stop"}, uid="stop")])
        return
    if q in {":log", "log", "日志"}:
        emit_items([item("复制日志路径", str(log_path()), arg={"action": "copy_log_path"}, uid="log")])
        return
    if q in {":install", "install", "安装"}:
        emit_items([item("复制依赖安装命令", "在终端执行该命令安装 nllw 依赖", arg={"action": "copy_install"}, uid="install")])
        return

    try:
        parsed = parse_translation_query(q)
    except Exception as e:
        emit_items([item("无法解析翻译请求", str(e), valid=False)])
        return

    if not is_server_running(timeout=0.3):
        if using_external_api():
            emit_items([
                item(
                    "后端翻译服务不可用",
                    f"请检查 NLLW_API_URL={api_base_url()}",
                    valid=False,
                    uid="api-not-running",
                ),
                item(f"待翻译：{parsed.text[:70]}", f"方向：{parsed.display_pair}", valid=False),
                *quick_target_items(parsed),
            ])
        else:
            emit_items([
                item(
                    "TransFlow 服务未启动",
                    "回车启动后台服务，然后再次输入翻译内容",
                    arg={"action": "start"},
                    uid="server-not-running",
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
        emit_items([item("翻译失败", detail[:220], valid=False), item("复制日志路径", str(log_path()), arg={"action": "copy_log_path"})])
        return
    except Exception as e:
        emit_items([
            item("翻译服务暂时不可用", f"{type(e).__name__}: {e}", valid=False),
            item("重启 NLLW 服务", "回车重启后台服务", arg={"action": "stop"}, uid="restart-stop"),
        ])
        return

    if not resp.get("ok"):
        err = resp.get("error", "unknown error")
        emit_items([item("翻译失败", err[:220], valid=False), item("复制日志路径", str(log_path()), arg={"action": "copy_log_path"})])
        return

    translated = (resp.get("translation") or "").strip()
    validated = (resp.get("validated") or "").strip()
    buffer = (resp.get("buffer") or "").strip()
    if not translated:
        translated = validated or buffer or ""
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


class NLLWEngine:
    def __init__(self) -> None:
        self._nllw = None
        self._models: Dict[Tuple[str, str, str], Any] = {}
        self._lock = threading.RLock()
        self.backend = os.environ.get("NLLW_BACKEND", "transformers")
        self.size = os.environ.get("NLLW_MODEL_SIZE", "600M")

    def _import_nllw(self):
        with self._lock:
            if self._nllw is None:
                try:
                    import nllw  # type: ignore
                except ImportError as e:
                    raise RuntimeError(
                        "未安装 nllw。请在 workflow 目录运行 ./install_deps.sh，或执行：python3 -m pip install nllw"
                    ) from e
                self._nllw = nllw
        return self._nllw

    def _model(self, src: str):
        key = (self.backend, self.size, src)
        with self._lock:
            if key not in self._models:
                nllw = self._import_nllw()
                print(f"[transflow] loading model backend={self.backend} size={self.size} src={src}", flush=True)
                self._models[key] = nllw.load_model(src_langs=[src], nllb_backend=self.backend, nllb_size=self.size)
                print(f"[transflow] model loaded for src={src}", flush=True)
            return self._models[key]

    def translate(self, src: str, dst: str, text: str) -> Dict[str, Any]:
        text = text.strip()
        if not text:
            return {"ok": True, "translation": "", "validated": "", "buffer": ""}
        nllw = self._import_nllw()
        model = self._model(src)
        translator = nllw.OnlineTranslation(model, input_languages=[src], output_languages=[dst])
        tokens = [nllw.timed_text.TimedText(text)]
        translator.insert_tokens(tokens)
        validated, buffer = translator.process()
        validated_s = str(validated or "").strip()
        buffer_s = str(buffer or "").strip()
        translation = (validated_s + (" " if validated_s and buffer_s else "") + buffer_s).strip()
        return {"ok": True, "translation": translation, "validated": validated_s, "buffer": buffer_s}


_ENGINE = NLLWEngine()
_SHOULD_SHUTDOWN = False


class Handler(BaseHTTPRequestHandler):
    server_version = "NLLWAlfred/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {self.address_string()} {fmt % args}", flush=True)

    def _send_json(self, obj: Dict[str, Any], status: int = 200) -> None:
        raw = json_dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError as e:
            raise ValueError("invalid Content-Length") from e
        if length > 1024 * 1024:
            raise ValueError("request body too large")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        return json.loads(raw or "{}")

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/health"):
            self._send_json({"ok": True, "backend": _ENGINE.backend, "size": _ENGINE.size, "pid": os.getpid()})
        else:
            self._send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        global _SHOULD_SHUTDOWN
        if self.path.startswith("/shutdown"):
            self._send_json({"ok": True})
            _SHOULD_SHUTDOWN = True
            # Shutdown from another thread after response is flushed.
            import threading
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if self.path.startswith("/translate"):
            try:
                payload = self._read_json()
                src = normalize_lang(payload.get("src", default_src()))
                dst = normalize_lang(payload.get("dst", default_dst()))
                text = str(payload.get("text", ""))
                result = _ENGINE.translate(src, dst, text)
                self._send_json(result)
            except Exception as e:
                traceback.print_exc()
                self._send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, status=500)
            return
        self._send_json({"ok": False, "error": "not found"}, status=404)


def serve() -> None:
    cache_dir().mkdir(parents=True, exist_ok=True)
    pid_path().write_text(str(os.getpid()))
    print(f"[transflow] serving on {host()}:{port()} pid={os.getpid()}", flush=True)
    try:
        httpd = ThreadingHTTPServer((host(), port()), Handler)
        httpd.serve_forever(poll_interval=0.2)
    finally:
        with contextlib.suppress(FileNotFoundError):
            if read_pid() == os.getpid():
                pid_path().unlink()
        print("[transflow] stopped", flush=True)


def status_cli() -> None:
    if is_server_running(timeout=1):
        print("running", json_dumps(url_json("/health", timeout=1)))
    else:
        pid = read_pid()
        if pid and process_exists(pid):
            print(f"pid {pid} exists but health check failed")
        else:
            print("stopped")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Alfred workflow bridge for nllw")
    sub = parser.add_subparsers(dest="cmd")
    sf = sub.add_parser("script-filter")
    sf.add_argument("query", nargs="*", default=[])
    act = sub.add_parser("action")
    act.add_argument("arg", nargs="?", default="")
    sub.add_parser("serve")
    sub.add_parser("status")
    sub.add_parser("start")
    sub.add_parser("stop")
    args = parser.parse_args(argv)

    if args.cmd == "script-filter":
        script_filter(" ".join(args.query))
    elif args.cmd == "action":
        action(args.arg)
    elif args.cmd == "serve":
        serve()
    elif args.cmd == "status":
        status_cli()
    elif args.cmd == "start":
        print(start_server())
    elif args.cmd == "stop":
        print(stop_server())
    else:
        parser.print_help()
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
