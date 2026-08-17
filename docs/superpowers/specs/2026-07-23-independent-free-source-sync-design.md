# 双项目独立免费数据源接入设计

**批准日期：** 2026-07-23  
**批准结论：** `daily_info` 与 `stock` 分别取数、分别运行、分别生成报告；当前仅同步来源能力、字段口径和校验规则，不建立跨项目运行时依赖。

## 目标

1. `daily_info` 在每个中国 A 股交易日 07:40 独立收集并生成盘前晨报。
2. `stock` 保留自己的调度与报告流水线，把同一批免费来源接入现有 preflight、provenance 和 FACT registry。
3. 两边都展示可复算的现值、前值、绝对变化和变化比例，并保留数据日期、采集时间、单位、合约与来源。
4. 市场数值只来自结构化接口；权威新闻允许官方单源，非权威新闻继续双源核验。

## 非目标

- 本次不让任一项目导入另一个项目的 Python 包、读取对方缓存或依赖对方先运行。
- 本次不合并两套报告，也不改变 `stock` 已有运行时点。
- 不接入收费、积分计量、必须注册密钥、明确禁止脚本抓取或现场不稳定的来源。

## 方案选择

采用“同一来源契约、两套独立适配器”：

- 两个项目各保存一份 schema_version 相同的 `config/source_catalog.json`。
- 目录记录来源 ID、状态、用途、权威级别、日期能力、接口地址、超时预算和限制说明。
- 两边各自实现标准库解析器和各自编排接线；不使用软链接或共享本地包。
- 后续根据长期运行质量再选择一个项目成为公共数据提供方。

## 来源分级

### 启用：生产市场来源

| 数据域 | 主校验来源 | 补充来源 |
|---|---|---|
| 美股三大指数 | 腾讯、新浪 | Cboe SPX 官方历史 CSV；TradingView 延迟扫描 |
| 美股 11 行业 ETF | 腾讯、新浪 | TradingView America Scanner |
| 官方日度外汇 | 加拿大央行 Valet、英格兰银行 IADB | ECB 参考汇率；新浪用于盘中补充 |
| COMEX/NYMEX 与 LME | 腾讯、新浪海外期货 | TradingView Global Scanner；LME 官方收盘说明/页面 |
| 国内期货 | 新浪、东方财富日 K | 交易所公开日线经独立适配后使用 |
| 钨、钼与小金属 | SMM、赣州钨协、Mysteel 已验证公开报价 | 口径不同的报价只并列，不强制合并 |
| 非 ST A 股涨跌家数 | 新浪、东方财富 | TradingView China 仅复核沪深；北交所单独合并 |

### 启用：权威信息来源

- 国家统计局最新发布与数据解读 RSS。
- 美联储全部新闻与货币政策 RSS。
- 欧洲央行新闻 RSS。
- BLS Public Data API v1，用于美国宏观数据核验。
- SEC EDGAR submissions/XBRL JSON，用于财报与申报事件核验。
- 盈米继续用于综合新闻候选；官方原文优先。

### 登记但不启用

- Alpha Vantage、FMP、Finnhub：需要注册密钥或免费权限不清晰。
- Twelve Data：积分计量。
- CME 内部结算 JSON：明确限制自动抓取。
- Nasdaq 内部网页接口、Stooq、Yahoo：现场不稳定或失败。
- FRED/EIA：对 07:40 日度行情过旧或批量包过重。
- Baostock、mootdx：效率、用途或协议稳定性不足。
- 生意社：触发 JavaScript 安全检查，仅保留人工网页兜底。

## 统一事实契约

每个市场观察值至少包含：

```text
source, instrument, value, previous_value, absolute_change, change_pct,
market_date, previous_market_date, collected_at, unit, contract, url,
date_quality, attempted_sources, unavailable_sources
```

`date_quality` 取值：

- `explicit`：来源明确给出市场日期，可参与主校验。
- `derived_official_daily`：由同一官方日度序列的共同基准交叉计算，可参与同口径校验。
- `session_only`：只有会话状态或延迟信息，不能单独证明日期，只能进入 supplemental evidence。

校验结果状态与日期质量分开：`fresh/stale/conflict/missing/unknown_as_of` 是事实状态；`explicit/derived_official_daily/session_only` 是来源日期质量。`session_only` 永远映射为 `unknown_as_of`，不进入可发布共识。

## 字段所有权矩阵

| 字段/品种 | 主所有者 | 可选复核 | 日期质量 | 单位/合约 | 容差 | 缺主源状态 |
|---|---|---|---|---|---|---|
| 美股三大指数现值/涨跌额/涨跌幅 | Tencent + Sina | Cboe 仅 SPX | explicit | points / cash index close | 相对 0.20%，涨幅绝对 0.10pct | 单源仅展示原值，`single_source` |
| 11 行业 ETF | Tencent + Sina | TradingView | explicit；TV=session_only | USD / ETF close | 相对 0.30%，涨幅 0.10pct | `single_source` |
| USD/CNY、USD/EUR、USD/JPY、USD/GBP | BoC + BoE | ECB 可支持交叉 | derived_official_daily | quote currency per USD / official daily reference | 相对 0.35%，涨幅 0.10pct | `single_source` |
| DXY、COMEX、NYMEX、LME | Tencent + Sina | TradingView；LME 页面只作口径证据 | explicit；TV=session_only | 配置逐品种固定 | 相对 0.50%，涨幅 0.15pct | `single_source` |
| 国内主连期货 | Sina Futures + Eastmoney | 交易所公开日线同合同才可加入 | explicit | CNY/配置单位 / main_continuous | 相对 0.50%，涨幅 0.15pct | `single_source` |
| SMM/Mysteel/赣州小金属 | 每个机构、合同各自所有 | 其他机构仅并列 | explicit | 原始合同与单位 | 不跨合同合并 | `single_source` |
| 非 ST A 股宽度 | Sina + Eastmoney | TradingView China 仅沪深无日期补充 | explicit；TV=session_only | count | 样本差 0.5%，单项家数 `max(10, 0.3%)` | 冲突不选边 |

Cboe 只能增加 SPX 的来源证据，不能拥有 DJI/IXIC。ECB、LME 官方页面和其他机构报价只有在日期、合同、单位完全一致时才可升级为数值复核源。

## 目标市场日

- 美股使用 `America/New_York` 和算法化 NYSE 全日休市日（元旦、MLK、总统日、耶稣受难日、阵亡将士纪念日、六月节、独立日、劳动节、感恩节、圣诞节）计算最近已完成交易日；16:15 ET 前不接受当天收盘。
- 国内期货和 A 股宽度使用已确认的上一 A 股交易日；夜盘自然日不得覆盖交易日字段。
- 官方日度外汇、LME 与专业报价采用两主源最新共同日期，同时要求不晚于采集时点且自然日年龄不超过 4 天；周末/假日允许共同日期回退。
- 两来源即使数值一致，只要共同日期早于其目标日或超过 max age，也必须是 `stale`。

## 日期与校验

1. 07:40 的美股、欧股和国际商品只取最近已经结束的交易日；不能因为北京时间已进入新一天就把尚未开盘的美国市场记为当日收盘。
2. 两个明确日期、同单位、同合约的独立来源在容差内才产生共识值。
3. 日期、单位或合约不同直接标记冲突；小金属不同机构口径并列展示。
4. TradingView 没有可靠市场日期时只能写入 supplemental evidence，不参与交易日证明。
5. 官方新闻可单源进入报告；媒体新闻至少两个独立发布域名。
6. 所有失败都记录来源 ID 和异常类型，不写秘密、不把空值变成 0。

## 项目数据流

### `daily_info`

```text
launchd 07:40 → A股交易日门 → 批量来源预取
→ Observation/VerificationResult → 非ST宽度与官方新闻
→ 确定性 Markdown/HTML/JSON → 原子发布
```

### `stock`

```text
原有 launchd/run_slot → trading_gate → preflight
→ fetch_astock 结构化 raw → news
→ source_provenance → market_fact_registry
→ 原有 signals/narrative/report/quality/publish
```

## 取数预算

- 通用连接超时 5 秒、单请求总超时 20 秒；仅传输失败可重试 1 次，重试计入预算。
- Tencent 全局批量 1 次、Sina 全局批量 1 次、Cboe 1 次、BoC 1 次、BoE 1 次、ECB 1 次。
- TradingView America、Global、China 各最多 1 次 POST；每次最多 6000 个 symbol，超过即拒绝而非静默拆批。
- 国内期货每个 provider 每个品种最多 2 次（含重试），单次运行每个 provider 最多 24 次。
- Sina/Eastmoney 宽度分页分别最多 70/60 次，100 条/页；必须满足终止页、三市场覆盖和最小 1000 条，否则整源失败。
- NBS 2、Fed 2、ECB 新闻 1 个 feed；每个响应最多 5 MiB、每源最多保留 10 条。
- BLS 每次最多 1 个批次、25 series；SEC 每次最多 5 个配置 CIK、每 CIK 1 次。
- 某来源失败必须及时返回外层触发备源，不能长时间阻塞。

## 非 ST 宽度定义

- 只接受来源市场筛选明确标为上交所、深交所、北交所的 A 股证券；排除 B 股、ETF、基金、债券、可转债和存托凭证。
- 名称先剥离 `XD/XR/DR` 前缀，再排除 `ST/*ST/S*ST`、名称含“退市”或以“退”结尾。
- `status != trading`、价格小于等于 0、昨收缺失/为 0、涨跌幅缺失的证券视为停牌或无效，不进入样本。
- `change_pct > 0/< 0/== 0` 分别为上涨、下跌、平盘；平盘不含停牌。
- 以 `venue:code` 去重；重复代码、未知 venue、分页不完整均使该来源冲突/失败。
- 必须满足 `上涨 + 下跌 + 平盘 == 统计样本`，并为三市场分别保留样本数。
- Sina 与 Eastmoney 代码集合或计数超容差时结果为 `conflict`，不选择某一方。TradingView China 没有明确日期，只保存沪深 supplemental 快照，不验证某个 `expected_date`。

## 输出要求

- 行情表同时显示现值、绝对变化、变化比例、数据日期、核验状态与来源。
- 国际金属覆盖铜、铝、锌、铅、镍、锡、钴。
- 小金属至少覆盖钨精矿、钼铁，并在可得时列出钴、铟、碳酸锂等已启用报价。
- 非 ST A 股宽度显示样本、上涨、下跌、平盘及比例。
- 重要新闻最多 20 条，按重要性和发布时间排序。

## 测试与交付

- 两个项目分别执行 TDD：先看到目标测试失败，再写最小实现。
- `daily_info` 完整门：`python3 -m unittest discover tests`。
- `stock` 完整门：`python3 -m unittest discover tests`，并验证 provenance/FACT registry。
- 最后执行受控现场请求，保存日期、样本量和来源状态，不输出秘密。
- 通过独立只读审查后，才把 `stock` 隔离 worktree 的已验证补丁同步回原工作树。
