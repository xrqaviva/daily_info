import json
import os
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

from .http import SourceError
from .news import (
    REQUIRED_MARKET_NEWS_CATEGORIES,
    _similar,
    build_verified_news,
)


DEFAULT_QUERIES = {
    "中国宏观与政策": "中国 央行 财政 统计 宏观 政策 监管",
    "美国与主要央行": "美联储 美国 CPI 非农 利率 ECB 央行",
    "全球市场风险": "全球 地缘 关税 制裁 原油 黄金 汇率 市场",
    "A股重要制度": "证监会 上交所 深交所 北交所 A股 政策",
    "隔夜美股与财报": "美股收盘 大型科技股 费城半导体 中概股 财报 业绩",
    "国内商品期货": "国内商品期货收盘 原油 黄金 白银 有色金属",
}


class _MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.in_title = False
        self.title_text = []

    def handle_starttag(self, tag, attrs):
        values = {str(key).lower(): value for key, value in attrs}
        if tag.lower() == "meta":
            key = str(values.get("property") or values.get("name") or "").lower()
            content = values.get("content")
            if key and content and key not in self.meta:
                self.meta[key] = content.strip()
        elif tag.lower() == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title_text.append(data)


def parse_article_metadata(html):
    parser = _MetadataParser()
    try:
        parser.feed(str(html or ""))
    except (TypeError, ValueError):
        raise SourceError("article HTML is invalid")
    title = (
        parser.meta.get("og:title")
        or parser.meta.get("twitter:title")
        or " ".join(parser.title_text).strip()
    )
    published = (
        parser.meta.get("article:published_time")
        or parser.meta.get("datepublished")
        or parser.meta.get("publishdate")
        or parser.meta.get("pubdate")
    )
    raw = str(html or "")
    if not published:
        match = re.search(
            r'"datePublished"\s*:\s*"([^"]+)"', raw, re.IGNORECASE
        )
        published = match.group(1).strip() if match else None
    if not published:
        match = re.search(
            r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日", raw
        )
        if match:
            year, month, day = (int(value) for value in match.groups())
            published = "%04d-%02d-%02dT00:00:00+08:00" % (
                year, month, day
            )
    return {"title": title or None, "published_at": published or None}


def _first(item, names):
    for name in names:
        value = item.get(name)
        if value:
            return value
    return None


def parse_yingmi_result(payload, *, provider):
    candidates = []
    try:
        content = (payload.get("result") or {}).get("content") or []
    except AttributeError:
        return candidates
    for block in content:
        text = block.get("text") if isinstance(block, dict) else None
        if not text:
            continue
        try:
            inner = json.loads(text)
        except (TypeError, ValueError):
            continue
        data = inner.get("data") if isinstance(inner, dict) else None
        items = (data or {}).get("items") if isinstance(data, dict) else None
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            title = _first(item, ("title", "headline"))
            url = _first(item, ("url", "link", "newsUrl", "sourceUrl"))
            publisher = _first(item, ("sourceName", "publisher", "source", "sources"))
            if isinstance(publisher, list):
                publisher = ", ".join(str(value) for value in publisher)
            if isinstance(publisher, dict):
                publisher = _first(publisher, ("name", "title", "source"))
            if not title or not url:
                continue
            candidates.append({
                "title": str(title),
                "summary": str(_first(item, ("summary", "content", "description")) or ""),
                "publisher": str(publisher or "unknown"),
                "published_at": str(_first(item, ("publishDate", "publishedAt", "reportDate", "date")) or ""),
                "event_time": _first(item, ("eventTime", "eventDate")),
                "url": str(url),
                "provider": provider,
            })
    return candidates


def _curl_config_value(value):
    text = str(value)
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise SourceError("curl config value contains control characters")
    return text.replace("\\", "\\\\").replace('"', '\\"')


class YingmiClient:
    ENDPOINT = "https://stargate.yingmi.com/mcp/v2"

    def __init__(self, *, key_file, runner=subprocess.run, timeout=30):
        self.key_file = Path(key_file)
        self.runner = runner
        self.timeout = int(timeout)

    def _key(self):
        key = os.environ.get("YINGMI_API_KEY", "").strip()
        if not key:
            try:
                key = self.key_file.read_text(encoding="utf-8").strip()
            except OSError:
                key = ""
        if not key:
            raise SourceError("Yingmi API key is unavailable")
        return key

    def _post(self, payload):
        config = "\n".join([
            'url = "%s"' % self.ENDPOINT,
            'request = "POST"',
            'header = "Content-Type: application/json"',
            'header = "Accept: application/json, text/event-stream"',
            'header = "X-API-Key: %s"' % _curl_config_value(self._key()),
            'data = "%s"' % _curl_config_value(json.dumps(payload, ensure_ascii=False)),
        ])
        command = [
            "curl", "--silent", "--show-error", "--location",
            "--proto", "=https", "--tlsv1.2", "--connect-timeout", "5",
            "--max-time", str(self.timeout), "--config", "-",
        ]
        try:
            result = self.runner(
                command,
                input=config.encode("utf-8"),
                capture_output=True,
                timeout=self.timeout + 5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SourceError("Yingmi curl failed: %s" % type(exc).__name__)
        if result.returncode != 0:
            raise SourceError("Yingmi curl rc=%s" % result.returncode)
        text = result.stdout.decode("utf-8", "ignore")
        if "data:" in text and not text.lstrip().startswith(("{", "[")):
            text = next(
                (line[5:].strip() for line in text.splitlines() if line.startswith("data:")),
                "",
            )
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            raise SourceError("Yingmi response is not JSON")

    def search(self, tool, query):
        self._post({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "daily-info", "version": "1"},
            },
        })
        result = self._post({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": tool, "arguments": {"query": query}},
        })
        return parse_yingmi_result(result, provider="yingmi:%s" % tool)


class CodexNewsProvider:
    tools = ("codex_web_search",)

    def __init__(
        self, project_root, *, runner=subprocess.run, timeout=180,
        executable="codex"
    ):
        self.project_root = Path(project_root).resolve()
        self.runner = runner
        self.timeout = int(timeout)
        self.executable = str(executable)

    def _execute(self, prompt, *, max_items, allowed_categories=None):
        schema_path = self.project_root / "config" / "news_candidates.schema.json"
        command = [
            self.executable, "exec", "--skip-git-repo-check", "--ephemeral",
            "--output-schema", str(schema_path),
            "-c", 'web_search="live"', "-s", "read-only",
            "-C", str(self.project_root), prompt,
        ]
        try:
            result = self.runner(
                command, capture_output=True, timeout=self.timeout
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SourceError("Codex news fallback failed: %s" % type(exc).__name__)
        if result.returncode != 0:
            raise SourceError("Codex news fallback rc=%s" % result.returncode)
        text = result.stdout.decode("utf-8", "ignore") if isinstance(result.stdout, bytes) else str(result.stdout)
        start, end = text.find("["), text.rfind("]")
        if start < 0 or end <= start:
            raise SourceError("Codex news fallback returned no JSON array")
        try:
            payload = json.loads(text[start:end + 1])
        except (TypeError, ValueError):
            raise SourceError("Codex news fallback JSON is invalid")
        rows = []
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict):
                continue
            if not item.get("title") or not item.get("url"):
                continue
            category = str(item.get("category") or "")
            if allowed_categories and category not in allowed_categories:
                continue
            row = {
                "event_key": str(item.get("event_key") or ""),
                "title": str(item["title"]),
                "summary": str(item.get("summary") or ""),
                "publisher": str(item.get("publisher") or "unknown"),
                "published_at": str(item.get("published_at") or ""),
                "event_time": item.get("event_time"),
                "url": str(item["url"]),
                "provider": "codex_web_search",
            }
            if category:
                row["category"] = category
            rows.append(row)
        return rows[:max(0, int(max_items))]

    def search(self, tool, query):
        if tool != "codex_web_search":
            return []
        prompt = (
            "Search the live web for important macro/market events matching this Chinese query: %s. "
            "Return only a JSON object with a candidates array of source pages. Every candidate "
            "must use category general and contain title, "
            "summary, publisher, published_at (ISO 8601 with timezone), a direct https URL, and "
            "event_key (a short stable ASCII identifier; use exactly the same event_key for pages "
            "covering the same event). For a non-official event, include direct article pages from "
            "at least two distinct publisher domains whenever available. Do not claim that a "
            "candidate is verified; the caller will fetch every URL. Maximum 10."
            % query
        )
        return self._execute(prompt, max_items=10)

    def search_many(self, queries):
        selected = {
            str(category): str(query)
            for category, query in dict(queries or {}).items()
            if str(category).strip() and str(query).strip()
        }
        if not selected:
            return []
        prompt = (
            "Search the live web for important events for these exact Chinese report categories "
            "and queries: %s. Return only a JSON object with a candidates array containing at "
            "most 20 direct source pages. "
            "Each object must contain category (exactly one supplied category), event_key (a short "
            "stable ASCII identifier shared by every page for the same event), title, summary, "
            "publisher, published_at (ISO 8601 with timezone), and a direct https URL. For every "
            "non-official event include at least two accessible article pages from distinct "
            "publisher domains; exclude homepages, search pages, HTTP URLs and paywalled pages. "
            "Do not claim verification because the caller fetches and validates every page."
            % json.dumps(selected, ensure_ascii=False, sort_keys=True)
        )
        return self._execute(
            prompt, max_items=20, allowed_categories=set(selected)
        )


class NewsCollector:
    def __init__(
        self, providers, article_client, *, queries=None, tools=None,
        fallback_providers=None, fallback_threshold=4, official_providers=None
    ):
        self.providers = list(providers or [])
        self.fallback_providers = list(fallback_providers or [])
        self.fallback_threshold = max(0, int(fallback_threshold))
        self.official_providers = list(official_providers or [])
        self.article_client = article_client
        self.queries = dict(queries or DEFAULT_QUERIES)
        self.tools = tuple(tools or ("SearchFinancialNews", "searchRealtimeAiAnalysis"))

    def collect(self, *, since, as_of, max_items=20):
        candidates = []
        errors = []
        def search(providers, categories=None):
            selected_queries = tuple(
                self.queries.items()
                if categories is None
                else tuple(
                    (category, self.queries[category])
                    for category in categories if category in self.queries
                )
            )
            for provider in providers:
                search_many = getattr(provider, "search_many", None)
                if callable(search_many):
                    query_map = dict(selected_queries)
                    try:
                        rows = search_many(query_map)
                    except Exception as exc:
                        errors.append({
                            "provider": type(provider).__name__,
                            "tool": "batch_search",
                            "category": " / ".join(query_map),
                            "error": type(exc).__name__,
                        })
                        continue
                    for item in rows or []:
                        row = dict(item)
                        category = str(row.get("category") or "")
                        if category not in query_map:
                            continue
                        row["category"] = category
                        candidates.append(row)
                    continue
                provider_tools = tuple(getattr(provider, "tools", self.tools))
                for tool in provider_tools:
                    for category, query in selected_queries:
                        try:
                            rows = provider.search(tool, query)
                        except Exception as exc:
                            errors.append({
                                "provider": type(provider).__name__,
                                "tool": tool,
                                "category": category,
                                "error": type(exc).__name__,
                            })
                            continue
                        for item in rows or []:
                            row = dict(item)
                            row["category"] = category
                            candidates.append(row)

        search(self.providers)
        validated = []
        rejected = []
        seen_urls = set()

        for provider in self.official_providers:
            try:
                rows, provider_errors = provider.collect_official()
                candidates.extend(rows or [])
                errors.extend(provider_errors or [])
            except Exception as exc:
                errors.append({"provider": type(provider).__name__, "tool": "official_feed", "category": "official", "error": type(exc).__name__})

        def validate_pending():
            for item in candidates:
                url = str(item.get("url") or "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                if str(item.get("provider") or "").startswith("official:"):
                    if item.get("title") and item.get("published_at") and url.startswith("https://"):
                        validated.append(dict(item))
                    else:
                        rejected.append({"url": url, "error": "SourceError"})
                    continue
                try:
                    metadata = parse_article_metadata(self.article_client.get_text(url))
                    if not metadata.get("title") or not _similar(item.get("title"), metadata["title"]):
                        raise SourceError("article title does not match candidate")
                    if not metadata.get("published_at"):
                        raise SourceError("article publish time is unavailable")
                    row = dict(item)
                    row["title"] = metadata["title"]
                    row["published_at"] = metadata["published_at"]
                    validated.append(row)
                except Exception as exc:
                    rejected.append({"url": url, "error": type(exc).__name__})

        validate_pending()
        publishable = build_verified_news(
            validated, since=since, as_of=as_of, max_items=max_items
        )
        required_categories = tuple(
            category for category in REQUIRED_MARKET_NEWS_CATEGORIES
            if category in self.queries
        )
        published_categories = {
            item.get("category") for item in publishable
        }
        missing_categories = tuple(
            category for category in required_categories
            if category not in published_categories
        )
        fallback_categories = (
            None if len(publishable) < self.fallback_threshold
            else missing_categories
        )
        if self.fallback_providers and (
            len(publishable) < self.fallback_threshold or missing_categories
        ):
            search(self.fallback_providers, fallback_categories)
            validate_pending()
            publishable = build_verified_news(
                validated, since=since, as_of=as_of, max_items=max_items
            )

        final_categories = {item.get("category") for item in publishable}
        missing_required_categories = [
            category for category in required_categories
            if category not in final_categories
        ]

        return {
            "items": publishable,
            "candidate_count": len(seen_urls),
            "validated_count": len(validated),
            "rejected": rejected,
            "errors": errors,
            "missing_required_categories": missing_required_categories,
        }
