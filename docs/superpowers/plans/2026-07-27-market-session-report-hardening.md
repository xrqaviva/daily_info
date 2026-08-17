# 盘前完整收盘口径固化实施计划

**目标：** 修复国际商品盘中值覆盖上一完整收盘的问题，并固化欧洲、现货贵金属、外汇与行业排名口径。

**原则：** 严格 TDD；每项先观察 RED，再写最小实现；不硬编码 2026-07-24 数值；不改正式 `latest`，直到隔离预览验证通过。

## Task 1：完整交易日锁

**文件：** `tests/test_free_market_sources.py`、`tests/test_market_collect.py`、`morning_brief/sources/free_market.py`、`morning_brief/market.py`

- [x] 添加 `latest_completed_international_session(as_of)` 的周末回退测试。
- [x] 添加 2026-07-27 08:42 拒绝 `market_date=2026-07-27` 实时连续报价的回归测试。
- [x] 为 `international_previous` 设置目标日期并传给统一校验。
- [x] 保证 `hf_*` 已滚动时结果为 `unexpected_market_date`，不返回盘中共识。

## Task 2：历史日线与新增品种

**文件：** `tests/test_free_market_sources.py`、`morning_brief/sources/free_market.py`、`morning_brief/market.py`、`config/instruments.json`

- [x] 用两条明确日期的 fixture 添加通用日线解析失败测试。
- [x] 实现日线 Observation 解析，精确选择目标完整交易日及相邻前一交易日。
- [x] 为 WTI、COMEX 金银铜、LME 六金属增加历史日线主源；已滚动的实时 `hf_*` 不再参与正式上一收盘值。
- [x] 增加富时 100、CAC 40、DAX、现货黄金、现货白银配置和合同标签。
- [x] 免费历史源不可稳定访问时保留完整交易日锁并明确不可用，禁止用实时值兜底。

## Task 3：报告语义与外汇

**文件：** `tests/test_report.py`、`morning_brief/report.py`、`config/instruments.json`

- [x] 添加行业后三为正时不出现“跌幅前三”的失败测试。
- [x] 添加外汇分组标题、欧洲与现货贵金属分组测试。
- [x] 报告改为“表现前三/表现后三”和“官方日度参考汇率”。
- [x] 检查各汇率来源日期、单位、合同一致性，拒绝混合基准。

## Task 4：国内期货摘要防错

**文件：** `tests/test_news.py` 或 `tests/test_report.py`、相关摘要构建模块

- [x] 添加“钯跌超5%，钯跌超4%”重复商品 fixture 的失败测试。
- [x] 实现标准化品种抽取与重复/矛盾检查；合法的“钯…铂…”通过。
- [x] 只允许带明确日期并符合新闻来源规则的摘要进入报告。

## Task 5：隔离预览与交付门

- [x] 运行聚焦测试并确认全部 GREEN。
- [x] 运行 `python3 -m unittest discover -s tests -v`（147/147 通过）。
- [x] 运行 `python3 -m py_compile morning_brief/*.py morning_brief/sources/*.py`、`bash -n scripts/run_morning.sh`、`plutil -lint launchd/com.aviva.daily-info.plist`。
- [x] 在 `reports/previews/2026-07-27-hardening/` 生成隔离预览，核对 2026-07-24 美股、欧洲、商品、LME 与汇率日期。
- [x] 完成 HTML 静态结构、内容与同日值泄漏检查；应用内浏览器无可用实例，未虚报可见页面验收。
- [x] 完成独立只读审查；结论为无剩余阻断级正确性或安全问题。
