# Stock Market API Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 stock 仓库增加一份可被后续任务直接读取的通用市场接口配置，并提供发现入口和结构回归测试，不改变现有运行时行为。

**Architecture:** 新配置 `config/market_api_registry.json` 与现有严格生产目录 `config/source_catalog.json` 并列；前者是通用请求知识库，后者继续服务当前 pipeline。`AGENTS.md` 提醒后续任务优先读取新配置，独立 unittest 只校验配置结构、安全和核心接口覆盖。

**Tech Stack:** JSON、Python 3.9 标准库 unittest、Git worktree。

## Global Constraints

- 不修改抓取器、`fetch_astock.py`、provenance、FACT registry、报告、提示词或调度。
- 不新增第三方依赖或网络调用。
- 配置不得保存密钥值、本机私有路径或非 HTTPS 接口。
- 只收录已验证可访问或 stock 当前使用的接口；禁用来源继续留在 `config/source_catalog.json`。
- 不创建 commit、push、PR、merge、deploy 或 publish。

---

### Task 1: 通用接口配置契约

**Files:**
- Create: `tests/test_market_api_registry.py`
- Create: `config/market_api_registry.json`
- Modify: `AGENTS.md`

**Interfaces:**
- Produces: `config/market_api_registry.json`，顶层字段固定为 `schema_version/updated_at/purpose/defaults/interfaces`。
- Produces: 每个接口固定包含 `id/provider/name/status/categories/method/url_template/response_format/encoding/auth/required_headers/parameters/symbol_examples/request_body_template/date_semantics/contract/independence_group/rate_or_request_limit/limitations/verified_at/existing_consumers`。
- Consumes: 后续任务直接通过标准 JSON 读取，无运行时 Python API。

- [ ] **Step 1: 写结构契约失败测试**

创建 `tests/test_market_api_registry.py`，使用 `json`、`re`、`unittest` 和 `pathlib.Path`：

```python
import json
import re
import unittest
from pathlib import Path


REGISTRY = Path("config/market_api_registry.json")
TOP_LEVEL_KEYS = {
    "schema_version", "updated_at", "purpose", "defaults", "interfaces",
}
INTERFACE_KEYS = {
    "id", "provider", "name", "status", "categories", "method",
    "url_template", "response_format", "encoding", "auth",
    "required_headers", "parameters", "symbol_examples",
    "request_body_template", "date_semantics", "contract",
    "independence_group", "rate_or_request_limit", "limitations",
    "verified_at", "existing_consumers",
}
REQUIRED_IDS = {
    "tencent_batch_quotes", "tencent_europe_quotes", "sina_market_quotes",
    "sina_global_daily", "eastmoney_global_daily", "cboe_spx_history",
    "tradingview_america_scan", "tradingview_global_scan",
    "tradingview_china_scan", "boc_daily_fx", "boe_daily_fx",
    "ecb_daily_fx", "safe_rmb_central_parity", "sina_a_share_breadth",
    "eastmoney_a_share_breadth", "sina_domestic_futures_daily",
    "eastmoney_domestic_futures_daily", "smm_tungsten",
    "smm_ferromolybdenum", "ganzhou_tungsten_forecast",
    "mysteel_ferromolybdenum", "lme_official_price_context",
    "nbs_release_feed", "nbs_interpretation_feed", "fed_press_feed",
    "fed_monetary_feed", "ecb_press_feed", "bls_public_data",
    "sec_submissions", "yingmi_financial_news",
}


class MarketApiRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(REGISTRY.read_text(encoding="utf-8"))

    def test_registry_has_stable_schema_and_required_interfaces(self):
        self.assertEqual(set(self.payload), TOP_LEVEL_KEYS)
        self.assertEqual(self.payload["schema_version"], 1)
        rows = self.payload["interfaces"]
        self.assertIsInstance(rows, list)
        ids = [row["id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(REQUIRED_IDS.issubset(ids))
        for row in rows:
            self.assertEqual(set(row), INTERFACE_KEYS)
            self.assertIn(row["status"], {"active", "verified_catalog_only", "on_demand"})
            self.assertIn(row["method"], {"GET", "POST"})
            self.assertTrue(row["url_template"].startswith("https://"))
            self.assertTrue(row["categories"])
            self.assertTrue(row["verified_at"])

    def test_registry_contains_no_secret_values_or_private_paths(self):
        text = REGISTRY.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"/Users/|/private/|BEGIN [A-Z ]*PRIVATE KEY")
        for row in self.payload["interfaces"]:
            self.assertNotIn(row["auth"], {"api_key_value", "password_value", "token_value"})
            self.assertFalse(re.search(r"https?://[^/]*@", row["url_template"]))
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `python3 -m unittest tests.test_market_api_registry -v`  
Expected: ERROR，原因是 `config/market_api_registry.json` 不存在；不是导入、语法或测试拼写错误。

- [ ] **Step 3: 新增最小完整配置**

创建 `config/market_api_registry.json`：

- 顶层严格使用计划定义的五个字段。
- `defaults` 固定为连接超时5秒、总超时20秒、传输失败重试1次、HTTPS-only、不得存秘密、数值使用前验证日期/合同/单位。
- `interfaces` 至少包含 `REQUIRED_IDS` 的30项接口。
- 已由 stock 消费的接口标 `active` 并填写对应 `scripts/*.py`；新确认但未接线的新浪/东方财富历史日线、腾讯欧洲和SAFE标 `verified_catalog_only`；BLS、SEC、LME页面和盈米标 `on_demand`。
- URL、请求方法、响应格式、编码、认证类型、头部、参数、示例代码、日期语义、合同、独立来源组、预算限制、使用限制和最近核验日期全部使用已批准规格与现有代码中的实值。
- `auth` 只使用 `none` 或 `existing_local_key:.yingmi_api_key|env:YINGMI_API_KEY`，不保存密钥内容。

- [ ] **Step 4: 增加未来任务发现入口**

在 `AGENTS.md` 的 Non-negotiable rules 后增加：

```markdown
9. **Market API registry:** Before discovering or integrating external market, FX, commodity, breadth, macro-release, or filing data, read `config/market_api_registry.json`; reuse its verified request templates and preserve its date/contract limitations.
```

- [ ] **Step 5: 运行聚焦测试并确认 GREEN**

Run: `python3 -m unittest tests.test_market_api_registry -v`  
Expected: `Ran 2 tests`、`OK`。

- [ ] **Step 6: 验证配置与仓库回归**

Run: `python3 -m json.tool config/market_api_registry.json`  
Expected: exit 0。

Run: `python3 -m unittest discover tests`  
Expected: 全部测试通过，精确数量记录在交付日志。

Run: `python3 -m py_compile tests/test_market_api_registry.py`  
Expected: exit 0。

Run: `git diff --check`  
Expected: exit 0。

- [ ] **Step 7: 只读审查与主工作树同步**

审查三个文件的完整差异，检查接口真实性、请求模板、日期/合同口径、秘密和范围。阻断发现先补失败测试再修复。通过后生成只包含三个文件的补丁，应用到 `/Users/aviva/Projects/stock`，确认没有覆盖 `.planning` 或其他用户改动，并在主工作树重新运行聚焦测试、JSON校验和完整测试。
