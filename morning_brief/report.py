import dataclasses
import html
import json
import os
import re
import tempfile
from pathlib import Path

from .templates import CSS_VERSION, HTML_SHELL, REPORT_CSS, md_to_html


STATUS_LABELS = {
    "verified": "已双源核验",
    "conflict": "待核验（双源冲突）",
    "single_source": "待核验（仅单源）",
    "unavailable": "不可用",
}

INSTRUMENT_LABELS = {
    "sp500": "标普500",
    "nasdaq": "纳斯达克综合",
    "dow": "道琼斯工业",
    "ftse100": "英国富时100",
    "cac40": "法国CAC40",
    "dax": "德国DAX",
    "dxy": "美元指数",
    "usdcnh": "美元/离岸人民币",
    "usdcny": "美元/在岸人民币",
    "usdeur": "美元/欧元",
    "usdjpy": "美元/日元",
    "usdgbp": "美元/英镑",
    "gold": "COMEX黄金",
    "silver": "COMEX白银",
    "spot_gold": "现货黄金",
    "spot_silver": "现货白银",
    "btc_usd": "比特币",
    "brent": "布伦特原油",
    "natgas": "美国天然气",
    "platinum": "纽约铂金",
    "palladium": "纽约钯金",
    "copper": "COMEX铜",
    "aluminum": "上期所铝",
    "tungsten": "钨精矿参考价",
    "iron_ore": "大商所铁矿石",
    "brent": "布伦特原油",
    "wti": "WTI原油",
    "lme_copper": "铜",
    "lme_aluminum": "铝",
    "lme_zinc": "锌",
    "lme_lead": "铅",
    "lme_nickel": "镍",
    "lme_tin": "锡",
    "shfe_gold": "上期所黄金",
    "shfe_silver": "上期所白银",
    "shfe_copper": "上期所铜",
    "shfe_zinc": "上期所锌",
    "shfe_lead": "上期所铅",
    "shfe_nickel": "上期所镍",
    "shfe_tin": "上期所锡",
    "ine_crude": "上海原油",
    "ferromolybdenum_smm": "钼铁60%（SMM）",
    "antimony": "1#锑锭（SMM）",
    "bismuth": "精铋（SMM）",
    "gallium": "镓（SMM）",
    "germanium": "锗锭（SMM）",
    "indium": "精铟（SMM）",
    "magnesium": "上海镁锭（SMM）",
    "selenium": "99.99%硒锭（SMM）",
}

def _monthly_cell(market, key, default=None):
    """取品种月序列并输出月趋势单元格内容。

    Markdown/HTML 双轨（2026-08-27 新增列）：
    - 有数据：输出 "SPARK|<date,close;date,close;…"，HTML 渲染为 SVG 迷你折线。
    - 无数据：返回 "—"（不伪造）。
    """
    series = ((market or {}).get("monthly_series") or {}).get(key) or []
    pairs = ["%s,%s" % (date, close) for date, close in series if close is not None]
    if len(pairs) < 2:
        return "—"
    return "SPARK:" + ";".join(pairs)


SECTION_KEYS = (
    ("美股三大指数", ("sp500", "nasdaq", "dow")),
    ("欧洲市场", ("ftse100", "cac40", "dax")),
    ("美元指数", ("dxy",)),
    ("官方日度参考汇率", ("usdcny", "usdeur", "usdjpy", "usdgbp")),
    ("现货价格", ("spot_gold", "spot_silver", "btc_usd", "lme_copper", "lme_aluminum", "lme_zinc", "lme_lead", "lme_nickel", "lme_tin", "tungsten", "ferromolybdenum_smm", "antimony", "bismuth", "gallium", "germanium", "indium", "magnesium", "selenium")),
    ("期货价格", ("gold", "silver", "copper", "platinum", "palladium", "wti", "brent", "natgas", "shfe_gold", "shfe_silver", "shfe_copper", "aluminum", "shfe_zinc", "shfe_lead", "shfe_nickel", "shfe_tin", "ine_crude", "iron_ore")),
)


def _plain(value):
    if dataclasses.is_dataclass(value):
        return _plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    return value


def _number(value):
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    precision = 4 if abs(number) < 100 else 2
    return ("{:%s,.%sf}" % ("", precision)).format(number)


def _pct(value):
    if value is None:
        return "—"
    return "%+.2f%%" % float(value)


def _signed_number(value):
    if value is None:
        return "—"
    number = float(value)
    precision = 4 if abs(number) < 100 else 2
    return ("{:+,.%sf}" % precision).format(number)


def _md_text(value):
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"([\\`*_{}\[\]<>#|])", r"\\\1", text)


def _md_url(value):
    text = re.sub(r"[\x00-\x20\x7f]+", "", str(value or ""))
    return (
        text.replace("<", "%3C").replace(">", "%3E")
        .replace("(", "%28").replace(")", "%29")
    )


def _result_parts(result):
    observations = list(getattr(result, "observations", ()) or [])
    status = getattr(result, "status", "unavailable")
    reason = getattr(result, "reason", None)
    hides_out_of_session_value = status == "conflict" and reason in {
        "unexpected_market_date",
        "future_market_date",
        "market_date_mismatch",
        "invalid_market_date",
        "invalid_collection_timestamp",
    }
    if hides_out_of_session_value:
        value, absolute, change = "—", "—", "—"
    elif status == "verified":
        value = _number(getattr(result, "consensus_value", None))
        change = _pct(getattr(result, "consensus_change_pct", None))
        first = observations[0] if observations else None
        absolute = _signed_number(
            first.value - first.previous_value
            if first is not None and first.previous_value is not None else None
        )
    elif observations:
        value = " / ".join(
            "%s %s" % (item.source, _number(item.value)) for item in observations
        )
        absolute = " / ".join(
            "%s %s" % (
                item.source,
                _signed_number(
                    item.value - item.previous_value
                    if item.previous_value is not None else None
                ),
            ) for item in observations
        )
        change = " / ".join(
            "%s %s" % (item.source, _pct(item.change_pct)) for item in observations
        )
    else:
        value, absolute, change = "—", "—", "—"
    dates = sorted({item.market_date for item in observations if item.market_date})
    date = " / ".join(dates) if dates else "—"
    return status, value, absolute, change, date, observations


def _md_sources(observations):
    return "；".join(
        "[%s](%s)" % (_md_text(item.source), _md_url(item.url))
        for item in observations
    )


def _md_quote_table(market, keys):
    lines = ["| 品种 | 最新值 | 绝对变化 | 变化比例 | 月趋势 | 数据日期 | 来源 |",
             "|---|---:|---:|---:|---|---:|---|"]
    quotes = (market or {}).get("quotes") or {}
    for key in keys:
        result = quotes.get(key)
        if result is None:
            continue
        _status, value, absolute, change, date, observations = _result_parts(result)
        label = _md_text(INSTRUMENT_LABELS.get(key, key))
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            label, value, absolute, change, _monthly_cell(market, key),
            date, _md_sources(observations),
        ))
    if len(lines) == 2:
        lines.append("| — | — | — | — | — | — | — |")
    return "\n".join(lines)


def _rank_label(direction, index):
    if direction == "top":
        return "第{}名".format("一二三四五"[index])
    return "倒数第{}名".format("一二三四五"[index])


def _synthetic_sources(obs, member_stocks):
    members = []
    for symbol in sorted(member_stocks):
        result = member_stocks[symbol]
        member_obs = getattr(result, "observations", None)
        member_obs = member_obs[0] if member_obs else None
        if not member_obs or not getattr(member_obs, "url", ""):
            continue
        members.append("[%s](%s)" % (
            _md_text(member_obs.instrument or symbol), _md_url(member_obs.url),
        ))
    if not members:
        return "合成·等权"
    return "合成·等权（%s）" % " ".join(members)


def _render_stock_groups_markdown(market):
    groups = market.get("stock_groups") or {}
    if not groups:
        return "| 分类 | 状态 |\n|---|---|\n| — | 暂无美股核心股票行情 |"
    lines = ["| 分类 | 名称 | 最新值 | 变化比例 | 月趋势 | 数据日期 | 来源 |",
             "|---|---|---:|---:|---|---:|---|"]
    for group_key, group in groups.items():
        category = _md_text(group.get("name") or group_key)
        stocks = group.get("stocks") or {}
        group_index = group.get("index")
        rows = []
        if group_index is not None:
            series_key = "us_group:%s:index" % group_key
            row = _stock_group_row(
                group_index, symbol="index", member_stocks=stocks,
                trend=_monthly_cell(market, series_key),
            )
            if row:
                rows.append((category, row))
                category = ""
        for symbol in sorted(stocks):
            series_key = "us_group:%s:%s" % (group_key, symbol)
            row = _stock_group_row(
                stocks[symbol], symbol=symbol,
                trend=_monthly_cell(market, series_key),
            )
            if row:
                rows.append((category, row))
                category = ""
        if not rows:
            lines.append("| %s | — | — | — | — | — | — |" % category)
            continue
        for cat, row in rows:
            lines.append("| %s | %s |" % (cat, row))

    return "\n".join(lines)


def _stock_group_row(result, *, symbol, member_stocks=None, trend=None):
    observations = getattr(result, "observations", None) or ()
    obs = observations[0] if observations else None
    value = getattr(result, "consensus_value", None)
    change = getattr(result, "consensus_change_pct", None)
    if value is None and obs is not None:
        value = getattr(obs, "value", None)
        change = getattr(obs, "change_pct", None)
    label = str(getattr(obs, "instrument", "") or symbol)
    date = str(getattr(obs, "market_date", "") or "")
    source = str(getattr(obs, "source", "") or "—")
    url = str(getattr(obs, "url", "") or "")
    if value is None:
        return "%s | — | — | %s | %s | %s" % (
            _md_text(label), trend or "—", _md_text(date), _md_text(source))

    if source == "synthetic":
        sources = _synthetic_sources(obs, member_stocks or {})
    elif url.startswith("http"):
        sources = "[%s](%s)" % (_md_text(source), _md_url(url))
    else:
        sources = _md_text(source)
    return "%s | %s | %s | %s | %s | %s" % (
        _md_text(label),
        _number(value),
        _pct(change) if change is not None else "—",
        trend or "—",
        _md_text(date),
        sources,
    )


def _render_sector_markdown(market):
    extremes = market.get("sector_extremes") or {}
    lines = ["| 排名 | 板块 | 变化比例 |", "|---|---|---:|"]
    for direction, key in (("top", "top"), ("bottom", "bottom")):
        for index, (name, change) in enumerate(extremes.get(key) or []):
            lines.append("| %s | %s | %s |" % (
                _rank_label(direction, index), _md_text(name), _pct(change),
            ))
    if len(lines) == 2:
        for direction, key in (
            ("top", "single_source_top"),
            ("bottom", "single_source_bottom"),
        ):
            for index, (name, change) in enumerate(extremes.get(key) or []):
                lines.append("| %s | %s | %s |" % (
                    _rank_label(direction, index), _md_text(name), _pct(change),
                ))
    if len(lines) == 2:
        lines.append("| — | 暂无可用板块行情 | — |")
    return "\n".join(lines)


def _breadth_hides_values(breadth, expected_market_date=None):
    verification = breadth.get("verification")
    reason = getattr(verification, "reason", None)
    if reason in {
        "unexpected_market_date", "market_date_mismatch", "market_date_missing",
        "future_market_date", "invalid_market_date",
    }:
        return True
    if expected_market_date:
        return any(
            not row.market_date or row.market_date != str(expected_market_date)
            for row in (breadth.get("sources") or {}).values()
        )
    return False


def _render_breadth_markdown(breadth, expected_market_date=None):
    verification = breadth.get("verification")
    status = getattr(verification, "status", "unavailable")
    reason = getattr(verification, "reason", None)
    hidden = _breadth_hides_values(breadth, expected_market_date)
    lines = ["核验状态：%s" % STATUS_LABELS.get(status, status)]
    if reason:
        lines.append("核验原因：%s" % _md_text(reason))
    lines.extend(["", "| 来源 | 数据日期 | 有效样本 | 上涨 | 下跌 | 平盘 | 上涨率 | 下跌率 |", "|---|---|---:|---:|---:|---:|---:|---:|"])
    sources = breadth.get("sources") or {}
    for source, row in sources.items():
        values = ("—",) * 6 if hidden else (
            _number(row.sample_size), _number(row.up), _number(row.down),
            _number(row.flat),
            _pct(row.up_rate * 100 if row.up_rate is not None else None),
            _pct(row.down_rate * 100 if row.down_rate is not None else None),
        )
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            _md_text(source), _md_text(row.market_date or "—"), *values,
        ))
    if not sources:
        lines.append("| — | — | — | — | — | — | — | — |")
    return "\n".join(lines)


def _render_news_markdown(news):
    items = (news or {}).get("items") or []
    if not items:
        return "本时间窗内没有通过严格来源规则的宏观新闻。"
    lines = []
    for index, item in enumerate(items[:20], 1):
        status = "官方一手单源" if item.get("verification_status") == "official_single_source" else "媒体双源"
        sources = "；".join(
            "[%s](%s)" % (
                _md_text(source.get("publisher") or source.get("domain")),
                _md_url(source.get("url")),
            )
            for source in item.get("sources") or []
        )
        lines.extend([
            "%s. **%s**" % (index, _md_text(item.get("title"))),
            "   - 摘要：%s" % _md_text(item.get("summary") or "—"),
            "   - 事件时间：%s；发布时间：%s；核验：%s" % (
                _md_text(item.get("event_time") or "未单独提供"),
                _md_text(item.get("published_at") or "—"), status,
            ),
            "   - 来源：%s" % (sources or "—"),
        ])
    return "\n".join(lines)


def _status_lines(model):
    lines = []
    for key, result in ((model.get("market") or {}).get("quotes") or {}).items():
        status = getattr(result, "status", "unavailable")
        lines.append("- %s：%s" % (
            _md_text(INSTRUMENT_LABELS.get(key, key)),
            STATUS_LABELS.get(status, status),
        ))
    extremes = ((model.get("market") or {}).get("sector_extremes")) or {}
    if extremes.get("single_source_top") or extremes.get("single_source_bottom"):
        lines.append("- 标普500行业ETF板块行情：单源参考")
        lines.append("- 美股核心股票行情（Mag7/存储/光模块CPO/AI应用/中国金龙）：腾讯单源")
    breadth_status = getattr(
        ((model.get("breadth") or {}).get("verification")),
        "status", "unavailable",
    )
    lines.append("- A股涨跌家数：%s" % STATUS_LABELS.get(breadth_status, breadth_status))
    missing_news = (model.get("news") or {}).get("missing_required_categories") or []
    if missing_news:
        lines.append("- 新闻核验缺口：%s" % "、".join(str(item) for item in missing_news))
    return lines


def render_markdown(model):
    market = model.get("market") or {}
    quotes = market.get("quotes") or {}
    lines = [
        "# A股盘前双源晨报｜%s" % model.get("report_date"),
        "",
        "采集截止：中国时间 %s  " % model.get("as_of"),
        "上一A股交易日：%s" % ((model.get("calendar") or {}).get("previous_trading_day") or "待确认"),
        "",
        "> 规则：只有同口径、同日期的两个独立来源在容差内才显示共识值；普通冲突或单源会列原值，交易日不符的盘中值仅保留日期与来源证据、不进入主表。",
    ]
    for heading, keys in SECTION_KEYS:
        lines.extend(["", "## %s" % heading, "", _md_quote_table(market, keys)])
        if heading == "美股三大指数":
            lines.extend(["", "### 标普500行业ETF表现前五/后五", "", _render_sector_markdown(market)])
            lines.extend(["", "### 美股核心股票行情（Mag7/存储/光模块CPO/AI应用/中国金龙）", "", _render_stock_groups_markdown(market)])
    lines.extend([
        "", "## 上一交易日A股非ST涨跌家数", "",
        _render_breadth_markdown(
            model.get("breadth") or {},
            (model.get("calendar") or {}).get("previous_trading_day"),
        ),
        "", "## 重要宏观新闻", "",
        _render_news_markdown(model.get("news") or {}),
    ])
    status_lines = _status_lines(model)
    if status_lines:
        lines.extend(["", "## 核验状态", "", *status_lines])
    lines.extend(["", "---", "本报告仅作信息整理，不构成投资建议。"])
    return "\n".join(lines) + "\n"


def render_html(model):
    body = md_to_html(render_markdown(model))
    return HTML_SHELL.replace(
        "{date}", html.escape(str(model.get("report_date")))
    ).replace("{css_version}", CSS_VERSION).replace("{body}", body)


def _write_atomic(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".%s." % path.name, dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_symlink(path, target):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".%s." % path.name, dir=str(path.parent)
    )
    os.close(descriptor)
    os.unlink(temporary)
    try:
        os.symlink(str(target), temporary)
        os.replace(temporary, path)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


class ReportWriter:
    def __init__(self, output_root):
        self.output_root = Path(output_root)
        self.warnings = []

    def write(self, model):
        self.warnings = []
        report_date = str(model["report_date"])
        self.output_root.mkdir(parents=True, exist_ok=True)
        runs_root = self.output_root / ".runs"
        runs_root.mkdir(parents=True, exist_ok=True)
        run_directory = Path(tempfile.mkdtemp(
            prefix="%s-" % report_date, dir=str(runs_root)
        ))
        directory = self.output_root / report_date
        markdown = render_markdown(model)
        rendered_html = render_html(model)
        evidence = json.dumps(_plain(model), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        state = json.dumps({
            "last_successful_as_of": str(model["as_of"]),
            "last_report_date": report_date,
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        run_paths = {
            "markdown": run_directory / "A股盘前晨报.md",
            "html": run_directory / "A股盘前晨报.html",
            "evidence": run_directory / "evidence.json",
            "state": run_directory / "state.json",
        }
        _write_atomic(run_paths["markdown"], markdown)
        _write_atomic(run_paths["html"], rendered_html)
        _write_atomic(run_paths["evidence"], evidence)
        _write_atomic(run_paths["state"], state)
        _write_atomic(self.output_root / "report.css", REPORT_CSS)

        run_target = Path(".runs") / run_directory.name
        _atomic_symlink(self.output_root / "index.md", Path("index") / "A股盘前晨报.md")
        _atomic_symlink(self.output_root / "index.html", Path("index") / "A股盘前晨报.html")
        _atomic_symlink(self.output_root / "index.json", Path("index") / "evidence.json")
        _atomic_symlink(self.output_root / "index", run_target)
        published_directory = self.output_root / "index"
        if not directory.is_symlink() and not directory.exists():
            try:
                _atomic_symlink(directory, run_target)
                published_directory = directory
            except OSError as exc:
                self.warnings.append({
                    "component": "dated_alias",
                    "error": type(exc).__name__,
                })
                published_directory = self.output_root / "index"

        return {
            "markdown": published_directory / "A股盘前晨报.md",
            "html": published_directory / "A股盘前晨报.html",
            "evidence": published_directory / "evidence.json",
        }
