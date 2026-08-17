# Daily Info Free Source Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `daily_info` 在交易日 07:40 独立生成包含完整日期、现值、绝对变化、变化比例和来源状态的免费多源晨报。

**Architecture:** 保留现有 Observation/Verification/Pipeline/Report 边界，新增来源目录、纯解析器和批量预取缓存。明确日期来源进入主校验；TradingView 等无明确日期的响应进入 supplemental evidence。

**Tech Stack:** Python 3 标准库、curl subprocess、unittest、JSON 配置、launchd。

## Global Constraints

- 不引入收费、积分或新密钥依赖。
- 不从搜索结果补市场数字。
- 不改变交易日门和 07:40 launchd 调度。
- 所有输出数字由结构化对象确定性渲染。
- 本轮不创建 Git 提交。

---

### Task 1: 来源目录与配置契约

**Files:**
- Create: `config/source_catalog.json`
- Modify: `morning_brief/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `load_source_catalog(path) -> dict[str, dict]`
- Contract: top-level only `schema_version=1,sources`; each source only `status,roles,date_quality,endpoint_type,timeout_seconds,max_requests,url,ownership,limitations`.
- Endpoint types include `https_get_text` for structured quote text and `library_wrapper` for disabled wrapper records, in addition to the approved JSON/CSV/table/RSS types.
- Enums: `status=enabled|supplemental|on_demand|disabled`; `date_quality=explicit|derived_official_daily|session_only|not_applicable`.

- [ ] **Step 1: Write the failing catalog validation tests**

```python
def test_source_catalog_rejects_enabled_source_without_explicit_role(self):
    with self.assertRaises(ConfigError):
        load_source_catalog(path)

def test_source_catalog_loads_enabled_and_disabled_sources(self):
    catalog = load_source_catalog(path)
    self.assertEqual(catalog["tradingview"]["date_quality"], "session_only")
    self.assertEqual(catalog["twelve_data"]["status"], "disabled")
```

- [ ] **Step 2: Run the focused test and observe RED**

Run: `python3 -m unittest tests.test_config -v`  
Expected: FAIL because `load_source_catalog` and the catalog file do not exist.

- [ ] **Step 3: Implement strict catalog loading**

```python
def load_source_catalog(path):
    payload = _load_json_object(path, "source catalog")
    sources = payload.get("sources")
    if payload.get("schema_version") != 1 or not isinstance(sources, dict):
        raise ConfigError("source catalog schema is invalid")
    required = {
        "status", "roles", "date_quality", "endpoint_type",
        "timeout_seconds", "max_requests", "url", "ownership", "limitations",
    }
    for source_id, row in sources.items():
        if not isinstance(row, dict) or set(row) != required:
            raise ConfigError("source %s is incomplete" % source_id)
    return sources
```

- [ ] **Step 4: Populate every retained, supplemental and disabled source**

The JSON must include Tencent, Sina, TradingView, Cboe, BoC, BoE, ECB, LME, Eastmoney, SMM, Ganzhou, Mysteel, NBS, Fed, BLS, SEC, Yingmi and all explicitly disabled candidates from the design.

- [ ] **Step 5: Run focused tests**

Run: `python3 -m unittest tests.test_config -v`  
Expected: PASS.

### Task 2: HTTP POST、批量行情与官方外汇纯解析器

**Files:**
- Modify: `morning_brief/http.py`
- Create: `morning_brief/sources/free_market.py`
- Test: `tests/test_free_market_sources.py`
- Modify: `tests/test_sources.py`

**Interfaces:**
- Produces: `CurlClient.post_json(url, payload, headers=None) -> object`
- Produces: `parse_tradingview_scan(payload) -> dict[str, dict]`
- Produces: `parse_boc_cross_rates(payload, *, as_of, url) -> dict[str, Observation]`
- Produces: `parse_boe_cross_rates(text, *, as_of, url) -> dict[str, Observation]`
- Produces: `parse_cboe_history(text, *, instrument, as_of, url) -> Observation`
- Produces: `parse_sina_global_quote(text, ...) -> Observation`
- Produces: `parse_professional_price_history(text, *, source, instrument, contract, unit, as_of, url) -> Observation`
- Produces: `latest_completed_nyse_session(as_of) -> datetime.date`

- [ ] **Step 1: Add fixture-driven failing parser tests**

```python
def test_boc_cross_rates_compute_value_previous_and_change():
    rows = parse_boc_cross_rates(BOC_FIXTURE, as_of=AS_OF, url=URL)
    self.assertAlmostEqual(rows["usdcny"].value, 6.7731, places=4)
    self.assertIsNotNone(rows["usdcny"].previous_value)
    self.assertEqual(rows["usdcny"].market_date, "2026-07-22")

def test_tradingview_is_session_only_supplemental():
    row = parse_tradingview_scan(TV_FIXTURE)["NASDAQ:IXIC"]
    self.assertEqual(row["date_quality"], "session_only")
    self.assertNotIn("market_date", row)

def test_professional_price_history_keeps_contract_and_computes_change():
    row = parse_professional_price_history(
        SMM_MOLY_FIXTURE, source="smm", instrument="ferromolybdenum",
        contract="钼铁60%", unit="CNY/base-tonne", as_of=AS_OF, url=URL,
    )
    self.assertEqual(row.value, 333500.0)
    self.assertEqual(row.previous_value, 335500.0)
    self.assertEqual(row.change_pct, -0.60)
```

- [ ] **Step 2: Run parser tests and observe RED**

Run: `python3 -m unittest tests.test_free_market_sources -v`  
Expected: FAIL because the new module does not exist.

- [ ] **Step 3: Implement strict parsers**

Each parser must validate finite numeric values, two sequential dates where change is calculated, provider-stated changes where available, and reject future-dated rows. `latest_completed_nyse_session` must handle America/New_York DST plus all approved full-day NYSE holidays and the 16:15 ET cutoff. Professional-price parsing must keep SMM/Mysteel/Ganzhou contract and unit differences separate instead of forcing consensus.

- [ ] **Step 4: Add POST JSON without exposing payload in process arguments**

`CurlClient.post_json` must feed a curl config through stdin, set HTTPS-only/TLS/size/time limits, and parse JSON with the same `SourceError` boundary as `get_json`.

- [ ] **Step 5: Run focused source tests**

Run: `python3 -m unittest tests.test_free_market_sources tests.test_sources -v`  
Expected: PASS.

### Task 3: 行情批量预取、品种扩展与绝对变化展示

**Files:**
- Modify: `morning_brief/market.py`
- Modify: `config/instruments.json`
- Modify: `morning_brief/report.py`
- Modify: `tests/test_market_collect.py`
- Modify: `tests/test_report.py`

**Interfaces:**
- Produces: `MarketCollector.collect(...)[supplemental]`
- Consumes: Task 2 parsers.
- Output columns: `最新值`, `绝对变化`, `变化比例`, `数据日期`, `来源`.

- [ ] **Step 1: Add failing batch/cache/session tests**

```python
def test_boc_and_boe_are_each_fetched_once_for_four_pairs():
    result = collector.collect(config, as_of=AS_OF)
    self.assertEqual(client.url_count(BOC_URL), 1)
    self.assertEqual(client.url_count(BOE_URL), 1)
    self.assertEqual(result["quotes"]["usdjpy"].status, "verified")

def test_tradingview_value_does_not_replace_explicit_dated_sources():
    self.assertEqual(result["supplemental"]["NASDAQ:IXIC"]["date_quality"], "session_only")
    self.assertEqual(result["quotes"]["nasdaq"].consensus_value, 25690.9)

def test_each_batch_provider_stays_within_request_budget():
    collector.collect(config, as_of=AS_OF)
    self.assertEqual(client.calls_for("tradingview-america"), 1)
    self.assertEqual(client.calls_for("boc"), 1)
    self.assertEqual(client.calls_for("boe"), 1)
```

- [ ] **Step 2: Run focused tests and observe RED**

Run: `python3 -m unittest tests.test_market_collect tests.test_report -v`  
Expected: FAIL on missing adapters, instruments and absolute-change column.

- [ ] **Step 3: Implement one-run response caching**

Cache GET/POST payloads by `(kind, url, normalized request body)` for BoC, BoE, ECB and TradingView; do not cache across report runs. Enforce the request limits and timeout values from the approved design with fake-client call-count assertions.

- [ ] **Step 4: Replace failed default source order and expand instruments**

Add USD/CNY, USD/EUR, USD/JPY, USD/GBP; COMEX gold/silver/copper, WTI; LME copper/aluminum/zinc/lead/nickel/tin/cobalt; domestic gold/silver/copper/aluminum/zinc/lead/nickel/tin/oil/iron ore; tungsten and ferromolybdenum. Stooq/Yahoo remain disabled catalog entries and are removed from enabled instrument routes.

- [ ] **Step 5: Render absolute change deterministically**

```python
absolute = None if observation.previous_value is None else (
    observation.value - observation.previous_value
)
```

For verified results use the first agreed observation only after agreement; for conflicts show each source separately.

- [ ] **Step 6: Run focused tests**

Run: `python3 -m unittest tests.test_market_collect tests.test_report -v`  
Expected: PASS.

### Task 4: TradingView 沪深宽度与官方新闻源

**Files:**
- Modify: `morning_brief/breadth_collect.py`
- Create: `morning_brief/sources/official_feeds.py`
- Modify: `morning_brief/news_collect.py`
- Modify: `morning_brief/cli.py`
- Modify: `tests/test_breadth_collect.py`
- Modify: `tests/test_news_collect.py`

**Interfaces:**
- Produces: `parse_tradingview_china(payload) -> list[dict]`
- Produces: `OfficialFeedProvider.search(tool, query) -> list[dict]`
- Produces: `parse_bls_response(payload, *, series_ids) -> list[dict]`
- Produces: `parse_sec_submissions(payload, *, cik) -> list[dict]`
- Official provider IDs: `nbs_release`, `nbs_explain`, `fed_all`, `fed_monetary`, `ecb_press`.

- [ ] **Step 1: Add failing width tests**

Test the complete approved eligibility definition: security type, `XD/XR/DR` normalization, ST/delisting exclusion, suspension/missing prior-close exclusion, `venue:code` deduplication, three-venue counts, count invariant, pagination completeness, Shanghai/Shenzhen-only TradingView marker, and explicit refusal to treat TradingView as date-specific full-market breadth.

- [ ] **Step 2: Add failing RSS tests**

Use RSS/Atom fixtures to verify title, direct official HTTPS URL, UTC/offset timestamp, provider ID, category, response item limit and deduplication. Add BLS fixtures that reject non-month periods and SEC fixtures that keep 8-K/10-Q/10-K/6-K filings with accession links.

- [ ] **Step 3: Run focused tests and observe RED**

Run: `python3 -m unittest tests.test_breadth_collect tests.test_news_collect -v`  
Expected: FAIL on missing TradingView and official feed adapters.

- [ ] **Step 4: Implement supplemental width evidence**

Keep Sina×Eastmoney as the required full-market pair. Store TradingView Shanghai/Shenzhen counts under `supplemental`, with `coverage=["sh","sz"]`; do not pass it to `verify_breadth` as a complete source.

- [ ] **Step 5: Implement official feeds and validated fallback timing**

Official RSS rows enter `build_verified_news` as official single sources. BLS and SEC are bounded on-demand verification providers configured by series IDs/CIKs. Determine whether Codex fallback is needed after URL validation and after category counts are known, not from raw candidate count.

- [ ] **Step 6: Run focused tests**

Run: `python3 -m unittest tests.test_breadth_collect tests.test_news_collect -v`  
Expected: PASS.

### Task 5: 完整验证与现场探测

**Files:**
- Modify if required by tests: `tests/test_pipeline.py`, `tests/test_operations.py`
- Update: `progress.md`, `findings.md`

- [ ] **Step 1: Run full deterministic suite**

Run: `python3 -m unittest discover tests`  
Expected: all tests PASS.

- [ ] **Step 2: Run syntax and shell checks**

Run: `python3 -m py_compile morning_brief/*.py morning_brief/sources/*.py`  
Expected: exit 0.  
Run: `bash -n scripts/run_morning.sh`  
Expected: exit 0.

- [ ] **Step 3: Run controlled live source probes**

Run the CLI with an explicit Asia/Shanghai `--as-of`, capture only source IDs, dates, statuses, counts and error classes, and verify the report does not relabel an unopened US session.

- [ ] **Step 4: Confirm scheduler remains unchanged**

Run: `plutil -lint launchd/com.aviva.daily-info.plist`  
Expected: OK, with weekday 07:40 entries unchanged.

- [ ] **Step 5: Confirm independent runtime**

Run: `rg -n "/Users/aviva/Projects/stock|from scripts|import scripts" morning_brief config scripts`  
Expected: no runtime code dependency on `stock`; the existing Yingmi key-file path is configuration-only and no report/cache is imported.
