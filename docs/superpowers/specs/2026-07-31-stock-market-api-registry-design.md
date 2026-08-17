# Stock 通用股市接口配置设计

日期：2026-07-31

## 目标

在 `/Users/aviva/Projects/stock` 维护一份通用、机器可读的股市接口配置。以后任何任务需要市场、汇率、商品、A 股宽度、小金属、宏观公告或财报原文数据时，先读取该配置，再按任务需要选择和接入接口。

本次只维护接口知识，不把新接口接入现有报告流水线。

## 文件范围

只增加或修改三个文件：

1. 新增 `config/market_api_registry.json`：通用接口配置。
2. 新增 `tests/test_market_api_registry.py`：只验证配置能解析、字段完整、ID唯一、URL安全且不含秘密。
3. 修改 `AGENTS.md`：增加一句“涉及外部市场数据时先读取 `config/market_api_registry.json`”。

不修改 `fetch_astock.py`、任何抓取器、provenance、FACT registry、报告、提示词、调度或运行产物。

## 配置内容

`config/market_api_registry.json` 使用固定结构：

- `schema_version`：配置版本。
- `updated_at`：最近人工核验日期。
- `purpose`：配置用途。
- `defaults`：连接超时、总超时、重试和安全约束。
- `interfaces`：接口数组。

每个接口包含：

- `id`、`provider`、`name`。
- `status`：`active`、`verified_catalog_only` 或 `on_demand`。
- `categories`：可提供的数据类别。
- `method`、`url_template`、`response_format`、`encoding`。
- `auth`：仅记录 `none` 或环境变量/本地密钥名称，不保存秘密值。
- `required_headers`、`parameters`、`symbol_examples` 或 `request_body_template`。
- `date_semantics`、`contract`、`independence_group`。
- `rate_or_request_limit`、`limitations`、`verified_at`。
- `existing_consumers`：若 stock 已在使用，列出消费者文件；尚未接线则为空数组。

## 收录范围

只收录已经验证可访问或 stock 当前正在使用的接口：

- 腾讯批量行情、腾讯欧洲指数。
- 新浪美股/国际期货行情、国际历史日线。
- 东方财富全球历史日线。
- Cboe SPX 官方历史 CSV。
- TradingView America、Global、China Scanner 补充接口。
- 加拿大央行、英格兰银行、ECB 官方日度参考汇率。
- SAFE/PBOC 人民币汇率中间价。
- 新浪、东方财富 A 股全市场宽度。
- 新浪、东方财富国内期货日线。
- SMM 钨/钼、赣州钨协、Mysteel 钼铁。
- LME 官方价格口径页面。
- 国家统计局、美联储、ECB 官方订阅。
- BLS Public Data API、SEC EDGAR submissions。
- stock 已使用的盈米新闻接口，只记录密钥位置，不记录密钥。

收费、积分、要求新注册密钥、明确禁止自动抓取或现场不稳定的接口继续由现有 `config/source_catalog.json` 记录为 disabled，不复制进通用可用接口配置。

## 使用规则

- `active` 表示 stock 已有代码消费者；`verified_catalog_only` 表示接口已核验但尚未接线；`on_demand` 表示只在特定任务中调用。
- 配置只提供请求模板和口径，不代表接口值已经双源核验。
- `date_semantics` 和 `contract` 必须在使用前匹配；不同合同不能因为数值接近而合并。
- TradingView 无可靠市场日期，只能作为补充。
- SAFE人民币中间价与 BoC/BoE/ECB 日度参考汇率是不同合同。
- LME供应商连续合约与 LME 官方 Closing Price 是不同合同。
- 后续任务接入某接口时自行按该任务的设计、TDD、provenance 和事实规则实施；本配置不改变当前生产行为。

## 验证

- 先运行现有完整测试作为基线。
- RED：新增结构测试，在配置文件不存在时确认失败。
- GREEN：增加配置后结构测试通过。
- 运行 `python3 -m json.tool config/market_api_registry.json`。
- 运行 `python3 -m unittest tests.test_market_api_registry` 和完整 `python3 -m unittest discover tests`。
- 检查配置中不存在密钥值、本机私有路径、HTTP URL、重复 ID、未知状态或空类别。
- 这是非 UI、非运行时变更，UI和现场取数均为 N/A；原因是本次不调用接口、不改变报告输出。

## 工作树与权限

在隔离 worktree 完成后，将上述三个文件精确同步进 `/Users/aviva/Projects/stock`，避开其 `.planning` 和其他用户改动。用户已授权写入 stock 仓库，但未授权 commit、push、PR、merge、deploy 或清理现有文件。

## 自查结论

- 范围已从“生产接线”收缩为“单一通用配置目录”。
- 配置可被人和程序直接读取，不引入跨仓依赖。
- 没有新增运行时依赖、抓取代码、事实政策或调度变更。
- 没有占位符、未定字段或秘密存储需求。
