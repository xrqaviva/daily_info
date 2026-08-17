import datetime
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from .breadth import calculate_breadth, verify_breadth
from .http import SourceError
from .models import VerificationResult
from .sources.eastmoney import parse_eastmoney_snapshot
from .sources.sina import parse_sina_snapshot
from .sources.free_market import parse_tradingview_china


class BreadthCollector:
    PAGE_WORKERS = 8
    SINA_BASE = (
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "Market_Center.getHQNodeData"
    )
    EASTMONEY_URL = (
        "https://push2delay.eastmoney.com/api/qt/clist/get?pn={page}&pz={page_size}&po=1"
        "&np=1&fltt=2&invt=2&fid=f3"
        "&fs=m%3A0%2Bt%3A6%2Cm%3A0%2Bt%3A80%2Cm%3A1%2Bt%3A2%2Cm%3A1%2Bt%3A23%2Cm%3A0%2Bt%3A81%2Bs%3A2048"
        "&fields=f12%2Cf14%2Cf3%2Cf2%2Cf124"
    )

    def __init__(
        self, client, *, page_size=100, max_pages=70, min_sample_size=1000
    ):
        self.client = client
        self.page_size = int(page_size)
        self.max_pages = int(max_pages)
        self.min_sample_size = int(min_sample_size)
        if self.page_size <= 0 or self.max_pages <= 0 or self.min_sample_size <= 0:
            raise ValueError("breadth collection limits must be positive")

    def _page_batches(self, start=1, stop=None):
        stop = self.max_pages + 1 if stop is None else min(
            self.max_pages + 1, int(stop)
        )
        for batch_start in range(int(start), stop, self.PAGE_WORKERS):
            yield range(batch_start, min(stop, batch_start + self.PAGE_WORKERS))

    def _fetch_batch(self, pages, fetcher):
        page_numbers = list(pages)

        def fetch(page):
            try:
                return page, fetcher(page), None
            except Exception as exc:
                return page, None, exc

        with ThreadPoolExecutor(
            max_workers=min(self.PAGE_WORKERS, len(page_numbers))
        ) as executor:
            return list(executor.map(fetch, page_numbers))

    def _sina_market_date(self):
        date_url = "https://hq.sinajs.cn/list=sh000001,sz399001,bj899050"
        date_text = self.client.get_text(
            date_url, headers={"Referer": "https://finance.sina.com.cn"}
        )
        required_symbols = {"sh000001", "sz399001", "bj899050"}
        dates = {}
        for symbol, payload in re.findall(
            r'var\s+hq_str_([a-z0-9]+)="([^"]*)"', str(date_text)
        ):
            if symbol not in required_symbols:
                continue
            date = next(
                (field for field in payload.split(",")
                 if re.fullmatch(r"\d{4}-\d{2}-\d{2}", field)),
                None,
            )
            if date:
                dates[symbol] = date
        if set(dates) != required_symbols or len(set(dates.values())) != 1:
            raise SourceError("Sina three-venue snapshot date is unavailable")
        return next(iter(dates.values()))

    @staticmethod
    def _normalize_stamp(stamped, expected_market_date, as_of=None):
        """Pre-market/weekend providers stamp today's calendar date while a
        snapshot still holds the last completed session (the strict source
        check would otherwise discard the whole venue). When the stamp is at
        most 3 days ahead of the expected session date and the as-of moment
        is outside the A-share trading window, accept it as the expected
        date; live intraday stamps and far-future stamps still fail."""
        if not stamped or not expected_market_date:
            return stamped
        expected = str(expected_market_date)
        if str(stamped) == expected:
            return stamped
        try:
            stamped_date = datetime.date.fromisoformat(str(stamped))
            expected_date = datetime.date.fromisoformat(expected)
        except ValueError:
            return stamped
        if not (
            stamped_date > expected_date
            and (stamped_date - expected_date).days <= 3
        ):
            return stamped
        if not as_of:
            return stamped
        try:
            moment = datetime.datetime.fromisoformat(str(as_of))
            if moment.tzinfo is None or moment.utcoffset() is None:
                moment = moment.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            sh_time = moment.astimezone(ZoneInfo("Asia/Shanghai"))
        except ValueError:
            return stamped
        in_trading = (
            sh_time.weekday() < 5
            and datetime.time(9, 15) <= sh_time.time() < datetime.time(15, 0)
        )
        return expected if not in_trading else stamped

    def _sina(self, expected_market_date, as_of=None):
        market_date = self._normalize_stamp(
            self._sina_market_date(), expected_market_date, as_of
        )
        if market_date != str(expected_market_date):
            raise SourceError("Sina snapshot date is not the expected market date")

        rows = []
        def fetch_page(page):
            query = urlencode({
                "page": page,
                "num": self.page_size,
                "sort": "changepercent",
                "asc": 0,
                "node": "hs_a",
                "symbol": "",
                "_s_r_a": "page",
            })
            return self.client.get_json(
                "%s?%s" % (self.SINA_BASE, query),
                headers={"Referer": "https://finance.sina.com.cn"},
            )

        def finish():
            if self._normalize_stamp(
                self._sina_market_date(), expected_market_date, as_of
            ) != market_date:
                raise SourceError("Sina snapshot date changed during pagination")
            return calculate_breadth(rows)

        for pages in self._page_batches():
            outcomes = self._fetch_batch(pages, fetch_page)
            for index, (_page, payload, error) in enumerate(outcomes):
                if error is not None:
                    raise error
                if not isinstance(payload, list):
                    raise SourceError("Sina snapshot response is not a list")
                if len(payload) < self.page_size:
                    for _tail_page, tail_payload, tail_error in outcomes[index + 1:]:
                        if tail_error is not None:
                            continue
                        if not isinstance(tail_payload, list) or tail_payload:
                            raise SourceError("Sina pagination is inconsistent")
                    if payload:
                        page_rows = parse_sina_snapshot(payload)
                        for row in page_rows:
                            if row.get("market_date") not in (None, market_date):
                                raise SourceError("Sina snapshot dates disagree")
                            row["market_date"] = market_date
                        rows.extend(page_rows)
                    return finish()
                page_rows = parse_sina_snapshot(payload)
                for row in page_rows:
                    if row.get("market_date") not in (None, market_date):
                        raise SourceError("Sina snapshot dates disagree")
                    row["market_date"] = market_date
                rows.extend(page_rows)
        raise SourceError("Sina pagination did not terminate before the page limit")

    def _eastmoney(self):
        rows = []
        def fetch_page(page):
            url = self.EASTMONEY_URL.format(
                page=page, page_size=self.page_size
            )
            return self.client.get_json(
                url,
                headers={"Referer": "https://quote.eastmoney.com"},
            )

        first_payload = fetch_page(1)
        first_data = (
            first_payload.get("data")
            if isinstance(first_payload, dict) else None
        )
        first_raw_rows = (
            first_data.get("diff") if isinstance(first_data, dict) else None
        )
        total = first_data.get("total") if isinstance(first_data, dict) else None
        if isinstance(total, bool) or not isinstance(total, int):
            raise SourceError("Eastmoney snapshot total is invalid")
        if total <= 0 or not isinstance(first_raw_rows, list):
            raise SourceError("Eastmoney snapshot is empty or malformed")
        total_pages = (total + self.page_size - 1) // self.page_size
        if total_pages > self.max_pages:
            raise SourceError("Eastmoney snapshot exceeds the page limit")
        expected_first = min(self.page_size, total)
        if len(first_raw_rows) != expected_first:
            raise SourceError("Eastmoney first page size disagrees with total")
        rows.extend(parse_eastmoney_snapshot(first_payload))
        raw_count = len(first_raw_rows)
        if total_pages == 1:
            return calculate_breadth(rows)

        for pages in self._page_batches(2, total_pages + 1):
            for page, payload, error in self._fetch_batch(pages, fetch_page):
                if error is not None:
                    raise error
                data = payload.get("data") if isinstance(payload, dict) else None
                raw_rows = data.get("diff") if isinstance(data, dict) else None
                page_total = data.get("total") if isinstance(data, dict) else None
                if isinstance(page_total, bool) or not isinstance(page_total, int):
                    raise SourceError("Eastmoney page total is invalid")
                if page_total != total or not isinstance(raw_rows, list):
                    raise SourceError("Eastmoney pagination total drifted")
                expected_rows = (
                    total - self.page_size * (total_pages - 1)
                    if page == total_pages else self.page_size
                )
                if len(raw_rows) != expected_rows:
                    raise SourceError("Eastmoney page size disagrees with total")
                page_rows = parse_eastmoney_snapshot(payload)
                rows.extend(page_rows)
                raw_count += len(raw_rows)
        if raw_count != total:
            raise SourceError("Eastmoney pagination is incomplete")
        return calculate_breadth(rows)

    @staticmethod
    def _verify_single(result, expected_market_date):
        if result.sample_size == 0:
            reason = "empty_breadth"
            status = "unavailable"
        elif not result.market_date:
            reason = "market_date_missing"
            status = "conflict"
        elif expected_market_date and result.market_date != str(expected_market_date):
            reason = "unexpected_market_date"
            status = "conflict"
        elif not {"sh", "sz", "bj"}.issubset(
            {code.split(":", 1)[0] for code in result.codes}
        ):
            reason = "incomplete_market_coverage"
            status = "conflict"
        else:
            reason = "only_one_independent_source"
            status = "single_source"
        return VerificationResult(status, None, None, (), reason, None)

    def collect(self, *, expected_market_date=None, as_of=None):
        try:
            expected_date = datetime.date.fromisoformat(str(expected_market_date))
        except (TypeError, ValueError):
            raise ValueError("expected_market_date is required")
        if as_of:
            try:
                collection_date = datetime.datetime.fromisoformat(str(as_of)).date()
            except ValueError:
                raise ValueError("as_of is invalid")
            if expected_date > collection_date:
                raise ValueError("expected_market_date cannot be in the future")
        sources = {}
        errors = []
        fetchers = (
            ("sina", lambda: self._sina(expected_date.isoformat(), as_of=as_of)),
            ("eastmoney", self._eastmoney),
        )
        for name, fetcher in fetchers:
            try:
                result = fetcher()
                if result.sample_size < self.min_sample_size:
                    raise SourceError("breadth sample is below the minimum")
                result = replace(
                    result,
                    market_date=self._normalize_stamp(
                        result.market_date, expected_market_date, as_of
                    ),
                )
                sources[name] = result
            except Exception as exc:
                errors.append({"source": name, "error": type(exc).__name__})
        if len(sources) == 2:
            verification = verify_breadth(
                sources["sina"], sources["eastmoney"],
                expected_market_date=expected_market_date,
            )
        elif len(sources) == 1:
            verification = self._verify_single(
                next(iter(sources.values())), expected_market_date
            )
        else:
            verification = VerificationResult(
                "unavailable", None, None, (), "no_sources", None
            )
        supplemental = {}
        try:
            url = "https://scanner.tradingview.com/china/scan"
            payload = {
                "filter": [{"left": "type", "operation": "equal", "right": "stock"}],
                "symbols": {"query": {"types": []}, "tickers": []},
                "columns": ["name", "close", "change", "exchange", "current_session", "update_mode"],
                "range": [0, 6000],
            }
            tv = calculate_breadth(parse_tradingview_china(
                self.client.post_json(url, payload)
            ))
            supplemental["tradingview_china"] = {
                "coverage": ["sh", "sz"],
                "sample_size": tv.sample_size,
                "up": tv.up,
                "down": tv.down,
                "flat": tv.flat,
                "market_date": None,
                "date_quality": "session_only",
            }
        except Exception as exc:
            errors.append({"source": "tradingview", "error": type(exc).__name__})
        return {
            "sources": sources,
            "verification": verification,
            "supplemental": supplemental,
            "errors": errors,
        }
