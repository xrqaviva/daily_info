import datetime
import email.utils
import xml.etree.ElementTree as ET

from morning_brief.http import SourceError


def parse_bls_response(payload, limit=25):
    if not isinstance(payload, dict) or payload.get("status") != "REQUEST_SUCCEEDED":
        raise SourceError("BLS response did not succeed")
    series = ((payload.get("Results") or {}).get("series") or [])
    rows = []
    for item in series[:25]:
        series_id = str(item.get("seriesID") or "").strip()
        if not series_id:
            continue
        for value in item.get("data") or []:
            period = str(value.get("period") or "")
            if len(period) != 3 or not period.startswith("M") or period == "M13":
                continue
            try:
                month = int(period[1:])
                number = float(value.get("value"))
                year = int(value.get("year"))
                normalized_period = datetime.date(year, month, 1).strftime("%Y-%m")
            except (TypeError, ValueError):
                continue
            rows.append({
                "series_id": series_id,
                "period": normalized_period,
                "period_name": str(value.get("periodName") or ""),
                "value": number,
                "provider": "official:bls",
            })
            if len(rows) >= min(100, max(0, int(limit))):
                return rows
    return rows


def parse_sec_submissions(payload, cik, limit=20):
    recent = (((payload or {}).get("filings") or {}).get("recent") or {})
    if not isinstance(recent, dict):
        raise SourceError("SEC submissions response is invalid")
    cik_number = str(cik or "").lstrip("0")
    if not cik_number.isdigit():
        raise SourceError("SEC CIK is invalid")
    allowed_forms = {"8-K", "10-K", "10-Q", "20-F", "40-F", "6-K"}
    accessions = recent.get("accessionNumber") or []
    rows = []
    for index, accession in enumerate(accessions):
        def field(name):
            values = recent.get(name) or []
            return values[index] if index < len(values) else ""

        form = str(field("form") or "").strip().upper()
        document = str(field("primaryDocument") or "").strip()
        accession_text = str(accession or "").strip()
        compact_accession = accession_text.replace("-", "")
        if form not in allowed_forms or not compact_accession.isdigit() or not document:
            continue
        rows.append({
            "cik": cik_number,
            "accession_number": accession_text,
            "form": form,
            "filing_date": str(field("filingDate") or ""),
            "report_date": str(field("reportDate") or ""),
            "url": (
                "https://www.sec.gov/Archives/edgar/data/%s/%s/%s"
                % (cik_number, compact_accession, document)
            ),
            "provider": "official:sec",
        })
        if len(rows) >= min(20, max(0, int(limit))):
            break
    return rows


def _local_name(tag):
    return str(tag or "").split("}")[-1].lower()


def _child_text(node, names):
    names = set(names)
    for child in list(node):
        if _local_name(child.tag) in names:
            if _local_name(child.tag) == "link" and child.attrib.get("href"):
                return child.attrib["href"].strip()
            return " ".join("".join(child.itertext()).split())
    return ""


def _published(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
            parsed = datetime.datetime.fromisoformat(normalized)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.isoformat()


def parse_official_feed(text, provider_id, category, limit=10):
    try:
        root = ET.fromstring(str(text or ""))
    except ET.ParseError:
        raise SourceError("official feed XML is invalid")
    rows = []
    for node in root.iter():
        if _local_name(node.tag) not in ("item", "entry"):
            continue
        title = _child_text(node, ("title",))
        url = _child_text(node, ("link", "id"))
        published = _published(_child_text(node, ("pubdate", "published", "updated", "date")))
        summary = _child_text(node, ("description", "summary", "content"))
        if not title or not url.startswith("https://") or not published:
            continue
        rows.append({
            "title": title,
            "summary": summary,
            "publisher": provider_id,
            "published_at": published,
            "event_time": None,
            "url": url,
            "provider": "official:%s" % provider_id,
            "category": category,
        })
        if len(rows) >= min(10, max(0, int(limit))):
            break
    return rows


class OfficialFeedProvider:
    FEEDS = (
        ("nbs_release", "中国宏观与政策", "https://www.stats.gov.cn/sj/zxfb/rss.xml"),
        ("nbs_explain", "中国宏观与政策", "https://www.stats.gov.cn/sj/sjjd/rss.xml"),
        ("fed_all", "美国与主要央行", "https://www.federalreserve.gov/feeds/press_all.xml"),
        ("fed_monetary", "美国与主要央行", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
        ("ecb_press", "美国与主要央行", "https://www.ecb.europa.eu/rss/press.html"),
    )

    def __init__(self, client):
        self.client = client

    def collect_official(self):
        rows = []
        errors = []
        for provider_id, category, url in self.FEEDS:
            try:
                rows.extend(parse_official_feed(
                    self.client.get_text(url), provider_id, category, limit=10
                ))
            except Exception as exc:
                errors.append({
                    "provider": provider_id,
                    "error": type(exc).__name__,
                })
        return rows, errors
