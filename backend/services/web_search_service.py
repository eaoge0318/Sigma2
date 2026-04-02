"""
Simple web search integration for finding public pages related to a topic.

Default provider uses DuckDuckGo's HTML results page so the feature can work
without an API key. The provider can be swapped later without changing the UI.
"""

from __future__ import annotations

import html
import json
import re
import urllib.request
from typing import Dict, List, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import config

SEARCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36 Sigma2/1.0"
    )
}

# Matches Yahoo search results (h3 title containing an anchor)
_YAHOO_RESULT_RE = re.compile(
    r'<h3[^>]*>.*?<a[^>]+href="(?P<href>https?://[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r'<[^>]+>')


class WebSearchError(ValueError):
    """Raised when search provider returns no usable results."""


class WebSearchNoWhitelistMatch(WebSearchError):
    """Raised when search results exist but none match the whitelist."""


def _clean_html_text(value: str) -> str:
    value = html.unescape(_TAG_RE.sub(" ", value or ""))
    return re.sub(r"\s+", " ", value).strip()


def _extract_result_url(href: str) -> Optional[str]:
    if not href:
        return None
    href = html.unescape(href.strip())
    # Yahoo redirect URLs embed the real URL as RU= in path segments or query string
    # e.g. https://r.search.yahoo.com/_ylt=.../RU=https%3A%2F%2Fexample.com/RK=.../
    if "yahoo.com" in href or "yimg.com" in href:
        # Check query string first
        qs = parse_qs(urlparse(href).query)
        if qs.get("RU"):
            return unquote(qs["RU"][0])
        # Check path segments: /RU=<encoded-url>/
        path = urlparse(href).path
        m = re.search(r'/RU=([^/]+)', path)
        if m:
            return unquote(m.group(1))
        return None
    return href



def _normalize_domain(domain: str) -> str:
    value = (domain or "").strip().lower()
    if not value:
        return ""
    if "://" in value:
        value = urlparse(value).hostname or value
    value = value.split("/", 1)[0]
    return value[4:] if value.startswith("www.") else value


def _match_domain(url: str, allowed_domains: List[str]) -> bool:
    if not allowed_domains:
        return True
    host = _normalize_domain(urlparse(url).hostname or "")
    if not host:
        return False
    return any(host == dom or host.endswith("." + dom) for dom in allowed_domains)


def _collect_matches(page_html: str) -> List[tuple[str, str]]:
    # Matches Yahoo h3>a structure
    return _YAHOO_RESULT_RE.findall(page_html)


def _guess_result_type(url: str) -> str:
    path = (urlparse(url).path or "").lower()
    if path.endswith(".pdf") or ".pdf?" in url.lower():
        return "pdf"
    if path.endswith(".doc") or path.endswith(".docx"):
        return "word"
    if path.endswith(".ppt") or path.endswith(".pptx"):
        return "ppt"
    if path.endswith(".xls") or path.endswith(".xlsx") or path.endswith(".csv"):
        return "sheet"
    return "web"


def search_web(query: str, max_results: Optional[int] = None, allowed_domains: Optional[List[str]] = None) -> List[Dict[str, str]]:
    query = (query or "").strip()
    if not query:
        raise WebSearchError("搜尋主題不可為空")

    max_results = max_results or config.WEB_SEARCH_DEFAULT_MAX_RESULTS
    max_results = max(1, min(max_results, config.WEB_SEARCH_MAX_RESULTS_LIMIT))
    domain_list = [_normalize_domain(d) for d in (allowed_domains or config.WEB_SEARCH_ALLOWED_DOMAINS) if d]
    domain_list = [d for d in domain_list if d]

    search_query = query
    if domain_list:
        site_clause = " OR ".join(f"site:{domain}" for domain in domain_list)
        search_query = f"{query} ({site_clause})"

    search_url = f"{config.WEB_SEARCH_ENDPOINT}?p={quote_plus(search_query)}"
    try:
        req = urllib.request.Request(search_url, headers=SEARCH_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html_text = resp.read().decode('utf-8', errors='ignore')
    except Exception as exc:
        raise WebSearchError(f"搜尋服務連線失敗: {exc}") from exc

    matches = _collect_matches(html_text)
    results: List[Dict[str, str]] = []
    seen = set()
    filtered_out = 0
    _GARBAGE_TITLES = {"here", "click here", "this", "link", "more", "read more", "source", "visit"}

    for href, title_html in matches:
        url = _extract_result_url(href)
        if not url or url in seen:
            continue
        if not _match_domain(url, domain_list):
            filtered_out += 1
            continue
        seen.add(url)
        title = _clean_html_text(title_html) or ""
        # If garbage anchor text, fall back to URL as title instead of skipping
        if not title or title.lower() in _GARBAGE_TITLES or len(title) < 4:
            title = url
        results.append({
            "title": title[:200],
            "url": url,
            "result_type": _guess_result_type(url),
        })
        if len(results) >= max_results:
            break

    if not results:
        if not matches:
            raise WebSearchError("搜尋頁沒有解析出結果，可能是搜尋引擎頁面格式已變更")
        if domain_list:
            raise WebSearchNoWhitelistMatch(
                f"搜尋結果沒有符合白名單網址。可先清空白名單測試，或調整主題。"
                f" 目前白名單 {len(domain_list)} 個，已過濾 {filtered_out} 筆結果。"
            )
        raise WebSearchError("找不到可匯入的公開搜尋結果")
    return results


# ── Bilingual helpers ──────────────────────────────────────────────────────────

def _detect_has_cjk(text: str) -> bool:
    """Return True if text contains CJK (Chinese/Japanese/Korean) characters."""
    return bool(re.search(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', text))


def _translate_query(text: str, target_lang: str) -> Optional[str]:
    """
    Use local LLM to translate *text* to target_lang ("en" or "zh-TW").
    Returns translated string, or None on any failure (graceful degradation).
    """
    try:
        if target_lang == "en":
            prompt = f"Translate the following query to English. Reply with ONLY the translated text, no explanation:\n{text}"
        else:
            prompt = f"將以下查詢翻譯成繁體中文，只回覆翻譯結果，不要有任何說明：\n{text}"

        payload = {
            "model": config.LLM_MODEL or "default",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 100,
            "temperature": 0,
        }
        req = urllib.request.Request(
            config.LLM_API_URL, 
            data=json.dumps(payload).encode('utf-8'),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            translated = data["choices"][0]["message"]["content"].strip()
            
        # Sanity check: reject if too long or unchanged
        if translated and translated.lower() != text.lower() and len(translated) < 300:
            return translated
    except Exception:
        pass
    return None


def search_web_bilingual(
    query: str,
    max_results: Optional[int] = None,
    allowed_domains: Optional[List[str]] = None,
) -> Dict:
    """
    Run search in the original language AND the translated language concurrently.
    Returns:
      {
        "results": [...merged, deduplicated...],
        "translated_query": "..." or None,
        "fallback_used": bool,
      }
    """
    import concurrent.futures as _cf

    query = (query or "").strip()
    max_results = max_results or config.WEB_SEARCH_DEFAULT_MAX_RESULTS
    max_results = max(1, min(max_results, config.WEB_SEARCH_MAX_RESULTS_LIMIT))
    allowed_domains = allowed_domains or []

    # Detect language and build translated query
    is_cjk = _detect_has_cjk(query)
    target_lang = "en" if is_cjk else "zh-TW"
    translated_query: Optional[str] = None

    # Translate in background while primary search runs
    with _cf.ThreadPoolExecutor(max_workers=2) as pool:
        # Start translation first (non-blocking)
        translate_future = pool.submit(_translate_query, query, target_lang)

        # Primary search with original query
        orig_results: List[Dict] = []
        orig_error: Optional[Exception] = None
        fallback_used = False

        def _search_with_fallback(q: str) -> List[Dict]:
            nonlocal fallback_used
            try:
                return search_web(q, max_results, allowed_domains)
            except WebSearchNoWhitelistMatch:
                fallback_used = True
                return search_web(q, max_results, [])

        orig_future = pool.submit(_search_with_fallback, query)

        # Wait for translation result
        try:
            translated_query = translate_future.result(timeout=12)
        except Exception:
            translated_query = None

        # Secondary search with translated query (if translation succeeded)
        trans_future = None
        if translated_query:
            trans_future = pool.submit(_search_with_fallback, translated_query)

        # Collect primary results
        try:
            orig_results = orig_future.result(timeout=35)
        except Exception as e:
            orig_error = e

        # Collect secondary results
        trans_results: List[Dict] = []
        if trans_future:
            try:
                trans_results = trans_future.result(timeout=35)
            except Exception:
                pass  # Secondary failure is non-fatal

    if not orig_results and not trans_results:
        raise orig_error or WebSearchError("找不到可匯入的公開搜尋結果")

    # Merge & deduplicate by URL (original results take priority)
    seen_urls: set = set()
    merged: List[Dict] = []
    for item in orig_results + trans_results:
        if item["url"] not in seen_urls:
            seen_urls.add(item["url"])
            merged.append(item)

    return {
        "results": merged,
        "translated_query": translated_query,
        "fallback_used": fallback_used,
    }

