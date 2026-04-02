"""
Web ingestion helpers for importing public web pages into the RAG knowledge base.
"""

from __future__ import annotations

import html
import ipaddress
import re
import socket
from pathlib import Path
from typing import Dict
from urllib.parse import urlparse

import requests


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 Sigma2/1.0"
)

MAX_HTML_BYTES = 3 * 1024 * 1024
MAX_TEXT_CHARS = 50000

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript|svg|canvas)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[ \t]{2,}")
_BLANK_RE = re.compile(r"\n{3,}")


class WebImportError(ValueError):
    """Raised when a web page cannot be safely imported."""


def _validate_public_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise WebImportError("只支援 http 或 https 網址")
    if not parsed.netloc:
        raise WebImportError("網址格式不完整")

    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise WebImportError("找不到網址主機")
    if host in {"localhost", "127.0.0.1", "::1"}:
        raise WebImportError("不允許抓取 localhost")
    if host.endswith(".local") or host.endswith(".internal"):
        raise WebImportError("不允許抓取內部網域")

    try:
        direct_ip = ipaddress.ip_address(host)
    except ValueError:
        direct_ip = None

    if direct_ip is not None:
        if not direct_ip.is_global:
            raise WebImportError("不允許抓取私人或保留 IP")
    else:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise WebImportError(f"無法解析網域: {host}") from exc
        for info in infos:
            addr = info[4][0]
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                continue
            if not ip.is_global:
                raise WebImportError("不允許抓取私人或保留 IP")

    return parsed.geturl()


def _detect_encoding(resp: requests.Response) -> str:
    if resp.encoding:
        return resp.encoding
    apparent = getattr(resp, "apparent_encoding", None)
    return apparent or "utf-8"


def _extract_title(raw_html: str, parsed_url) -> str:
    match = _TITLE_RE.search(raw_html)
    if match:
        title = html.unescape(match.group(1)).strip()
        title = re.sub(r"\s+", " ", title)
        if title:
            return title[:180]
    return parsed_url.netloc


def _html_to_text(raw_html: str) -> str:
    body = _SCRIPT_STYLE_RE.sub(" ", raw_html)
    body = re.sub(r"</(p|div|section|article|li|h[1-6]|tr|blockquote)>", "\n", body, flags=re.IGNORECASE)
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.IGNORECASE)
    body = _TAG_RE.sub(" ", body)
    body = html.unescape(body)
    body = body.replace("\r", "\n")
    body = _SPACE_RE.sub(" ", body)
    body = re.sub(r" *\n *", "\n", body)
    body = _BLANK_RE.sub("\n\n", body)
    text = body.strip()
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS].rsplit("\n", 1)[0].strip()
    return text


def _safe_slug(text: str, fallback: str = "web_page") -> str:
    value = re.sub(r"[^\w\-]+", "_", text.strip(), flags=re.UNICODE).strip("._")
    return (value or fallback)[:80]


def fetch_web_document(url: str, workspace_dir: str, folder: str = "") -> Dict[str, str]:
    safe_url = _validate_public_url(url)
    parsed = urlparse(safe_url)

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
    }
    resp = requests.get(safe_url, headers=headers, timeout=(10, 30), allow_redirects=True, stream=True)
    resp.raise_for_status()

    content_type = (resp.headers.get("Content-Type") or "").lower()
    if "text/html" not in content_type and "text/plain" not in content_type:
        raise WebImportError(f"目前只支援 HTML 或純文字頁面，收到: {content_type or 'unknown'}")

    raw_bytes = resp.raw.read(MAX_HTML_BYTES + 1, decode_content=True)
    if len(raw_bytes) > MAX_HTML_BYTES:
        raise WebImportError("網頁內容過大，暫不匯入")

    text_encoding = _detect_encoding(resp)
    raw_text = raw_bytes.decode(text_encoding, errors="replace")
    title = _extract_title(raw_text, parsed)
    text = raw_text if "text/plain" in content_type else _html_to_text(raw_text)

    if not text or len(text.strip()) < 80:
        raise WebImportError("抓到的網頁文字太少，可能是動態網站或無法解析")

    snapshot_name = f"{_safe_slug(title)}.web.txt"
    docs_dir = Path(workspace_dir) / "docs"
    if folder:
        docs_dir = docs_dir / Path(folder)
    docs_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = docs_dir / snapshot_name
    snapshot_path.write_text(
        f"URL: {resp.url}\nTitle: {title}\n\n{text}\n",
        encoding="utf-8",
    )

    return {
        "title": title,
        "text": text,
        "filename": snapshot_name,
        "final_url": resp.url,
        "content_type": content_type,
    }
