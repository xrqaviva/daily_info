# Stock 新增市场接口增量同步设计（已废弃）

> 2026-07-31 用户复核后认为本设计过重。该方案不实施；由 `2026-07-31-stock-market-api-registry-design.md` 的轻量配置目录方案取代。

日期：2026-07-30  
设计批准：用户于 2026-07-30 批准“stock 独立适配器 + 正式接入 raw/provenance/FACT”方案，并要求合并进 `/Users/aviva/Projects/stock`、确保正式运行链可以使用。

## 目标与成功标准

把 `daily_info` 在 2026-07-23 首轮双仓同步后形成、且已经通过受控响应或报告核验的新市场接口能力增量接入 `stock`。`stock` 必须独立请求和解析来源，不在运行时导入 `daily_info`、读取其缓存或依赖其报告。

成功标准：

1. `stock` 能通过标准库纯函数和现有 curl 传输边界采集欧洲三大指数、现货金银、配置化核心美股和人民币中间价证据。
2. 海外行情只接受采集时已经完成的目标市场交易日；盘中值、未来值、错误日期和不可能 OHLC 行不能覆盖上一完整收盘。
3. 连续合约现值、前值、绝对变化和涨跌幅采用同一供应商同一合约口径；检测到换月或口径冲突时保留 conflict/missing，不用相邻连续收盘伪造环比。
4. 新数值进入 `fetch_astock.py → raw → source_provenance.py → market_fact_registry.py` 正式链，报告和叙事只能消费通过 FACT 约束的事实。
5. 每个事实保留来源、尝试来源、不可用来源、日期、前值日期、采集时点、单位、合约和 `_evidence`；缺失或冲突不静默选边。
6. 完整测试、Python 3.9 兼容编译、shell/JSON/差异检查和受控现场探测通过后，精确同步到 `/Users/aviva/Projects/stock` 主工作树；不覆盖其现有 `.planning` 或其他用户改动。

## 已存在能力与增量范围

2026-07-23 已同步并继续复用：腾讯/新浪美股和国际期货、Cboe SPX、BoC/BoE/ECB 官方日度参考汇率、TradingView 补充扫描、国内期货、非 ST A 股宽度、SMM/赣州钨协/Mysteel、NBS/Fed/ECB 官方订阅、BLS 和 SEC。上述来源不重复实现。

本次新增：

- 新浪国际历史日线解析和目标日精确选行。
- 东方财富全球历史日线解析和供应商结算变化校验。
- 腾讯欧洲指数明确时间戳快照解析。
- 英国、法国、德国及 LME 市场最近完整交易日算法。
- 欧洲三大指数：FTSE 100、CAC 40、DAX。
- 现货黄金 XAU、现货白银 XAG。
- 配置化核心美股批量行情。
- 国家外汇管理局/中国人民银行人民币汇率中间价历史表解析。
- 相关 source catalog、preflight、provenance、FACT ownership 和机械质量门。

## 明确不在范围内

- 不改变 `stock` 的 10:00/11:30/13:30/15:00 调度或 `daily_info` 的 07:40 调度。
- 不建立跨项目运行时依赖或共享缓存。
- 不接入收费、积分、必须注册新密钥、明确禁止自动化或现场不稳定的来源。
- 不把 AP 等媒体网页当市场行情接口；新闻仍走现有官方订阅和媒体核验链。
- 不把 LME 供应商三个月连续报价描述成 LME 官方 Closing Price。
- 不把人民币中间价与 BoC/BoE/ECB 的“官方日度参考汇率”合并成同一合同。
- 不自动修改报告文案、定时任务、私有持仓、知识图谱或交易策略。
- 不提交、推送、合并分支、部署或发布；这些 Git/外部动作需要单独明确授权。

## 方案与架构

采用增量扩展现有 `scripts/free_market_sources.py` 和 `scripts/global_market_sources.py`，而不是复制 `daily_info` 包或创建第三个共享包。

### 纯解析层

在 `scripts/free_market_sources.py` 增加：

- `parse_sina_global_history(...)`：解析明确日期的新浪国际日线，拒绝不可能 OHLC、目标日缺失和非有限数。
- `parse_eastmoney_global_history(...)`：解析东方财富全球日线，优先使用供应商同日绝对变化/比例证明连续合约结算变化，拒绝跨月相邻收盘重算。
- `parse_tencent_gz_quote(...)`：解析欧洲指数时间戳，并按市场时区转换为交易日。
- `latest_completed_international_session(...)`：按 `uk/euronext/xetra/lme` 日历选择采集时已经完成的最近会话。
- `parse_safe_central_parity(...)`：解析 SAFE 官方日期表，只接受 USD 对人民币中间价的两个完整相邻发布日，输出独立合同。

所有解析器保持无网络副作用、Python 3.9 标准库-only，并返回现有 observation/envelope 能消费的固定字段。

### 配置层

新增 `config/global_instruments.json`，集中定义：

- 欧洲指数代码、市场、单位、合同、来源和容差。
- 现货贵金属代码、单位、合同、来源和目标会话。
- 核心美股分类、名称、代码、上市市场、来源、顺序和容差。
- 人民币中间价来源 URL、单位和独立合同。

配置加载器拒绝未知字段、重复代码、未知分类、非 HTTPS URL、非正容差和未批准 provider，避免名单散落在抓取器、模板或测试中。

### 核心美股固定篮子

Mag 7：AAPL、MSFT、GOOGL、AMZN、NVDA、META、TSLA。  
存储三雄：MU、SKHY、SNDK。  
光通信核心：AVGO、MRVL、COHR、LITE、CIEN、CRDO、GLW、ANET。  
扩展关注：WDC、STX、FN、AAOI、AMD、INTC、SPCX。

SK 海力士采用 Nasdaq ADR `SKHY`，与美光和闪迪使用同一美股完整会话；不混入韩国主板 `000660`。配置允许未来在获得用户批准后增删股票，不从新闻自由文本自动创造代码。

美国股票使用腾讯批量明确时间戳报价与东方财富历史日线交叉核验。单源失败时仍保留该股票的 envelope 和错误证据，但不能标双源一致；固定篮子中的任何股票不能因缺值从 raw 结构中静默消失。

## Raw 路由与事实所有权

新增或扩展以下结构：

| Raw 路由 | 内容 | 事实主源 | 发布规则 |
|---|---|---|---|
| `raw.外围欧洲` | FTSE、CAC、DAX | tencent + eastmoney | 同目标日、同合同、同单位且容差内才形成双源一致 |
| `raw.现货贵金属` | XAU、XAG | sina_global_history；可用第二明确日期源后加入 | 单源保留 evidence，不冒充双源 |
| `raw.核心美股` | 固定篮子 | tencent + eastmoney | 同一 NYSE/Nasdaq 完整会话双源一致才可作为严格事实 |
| `raw.人民币中间价` | USD/CNY 中间价 | safe_pbc | 官方单源 evidence；agreement 为 unproven，不与参考汇率混合 |

`raw.官方外汇` 继续表示 BoC/BoE/ECB 的 USD→quote 日度参考汇率；`raw.人民币中间价` 是另一合同。叙事和报告不得把两者当成同一瞬时成交价或互相替代。

`source_provenance.py` 和 `market_fact_registry.py` 为每个新 root 增加 provider ownership、session/date contract、agreement contract 和字段绑定。`raw.现货贵金属` 与 `raw.人民币中间价` 在只有单源时进入可审计 raw/provenance，但不升级为要求双源的可发布 FACT。

## 编排与数据流

1. `fetch_astock.py` 从 `config/global_instruments.json` 载入一次配置。
2. `collect_global_market(...)` 复用现有腾讯/新浪批量请求，并增加有界历史请求；同一批股票不逐只重复请求腾讯。
3. 每个品种按配置计算目标完整交易日，解析来源观察并调用现有合并函数。
4. 返回结果写入 `外围欧洲/现货贵金属/核心美股/人民币中间价` raw 路由，同时记录结构化 `errors`。
5. preflight 检查配置、provider 状态和接口可达性，不输出响应正文或凭证。
6. provenance 验证来源、日期、合同和一致性；FACT registry 只登记满足对应合同的字段。
7. 下游 digest、narrative 和 report 继续只从 FACT 读取量化市场数据，不允许搜索补数字。

## 请求预算与失败处理

- 连接超时 5 秒、总超时 20 秒；仅传输失败重试 1 次。
- 腾讯核心股票与现有美股/国际商品合并为一个有界批量请求。
- 新浪历史接口按配置品种请求，每品种最多 1 次；东方财富历史接口每品种最多 1 次。
- SAFE 中间价每次运行最多 1 次。
- 响应大小沿用现有 curl/读取上限；HTML/JSON/JSONP 解析失败只记录 provider ID 和错误类型。
- 目标日不存在、日期超前、日期过旧、前值缺失、前值为零、非有限数、单位/合同不一致、变化无法复算或值超容差时，状态为 conflict/stale/missing/unknown_as_of，不使用默认零和新闻数字。
- 连续合约换月时采用供应商当日结算变化；若供应商变化字段自身不一致则拒绝该观察。
- 新接口失败不阻断 A 股主行情采集，但 strict report gate 必须能看到缺口和降级状态。

## 测试矩阵

### 单元测试

- 新浪历史日线：目标日精确选行、缺目标日、未来日、非有限数、不可能 OHLC、缩放单位。
- 东方财富历史日线：供应商结算变化、跨月相邻收盘、字段不一致、目标日缺失。
- 国际日历：周末、英国/欧洲/LME节假日、采集时点尚未收盘。
- 腾讯欧洲：北京时间刷新日与交易所当地日期不同。
- SAFE：正常两日、值与日期解析、错误行、缺前值、非正值、未来发布日。
- 配置：固定篮子完整顺序、代码唯一、来源有效、SKHY/SPCX、未知字段拒绝。
- 核心美股：双源一致、单源、冲突、错误日期、股票必显 envelope。

### 集成测试

- `collect_global_market` 批量请求预算，四个新 raw 根节点及错误降级。
- `fetch_astock.py` 写入新根节点，旧根节点和现有字段保持兼容。
- provenance 接受合法证据、拒绝越权 provider/错误日期/伪一致。
- FACT registry 只绑定满足所有权与 agreement 的新字段；单源人民币中间价和现货金银不会冒充严格双源 FACT。
- preflight/source catalog 能发现新 provider 与配置问题而不泄漏秘密。

### 其他门禁

- 变更前及变更后运行 `python3 -m unittest discover tests`，记录精确数量。
- 运行全部 Python 文件编译、JSON 解析、`bash -n scripts/run_slot.sh` 和差异空白检查。
- 用固定上海时间执行受控真实接口探测，验证日期、会话、数值、错误和请求预算；现场源不可用不能记为测试通过。
- UI 检查为 N/A：本次不改变 HTML/CSS 或用户交互；若实现过程中需要改报告页面，则恢复真实构建与 UI 交互门。
- 安全/隐私检查覆盖 URL、日志、响应正文、密钥文件、本机路径和临时产物。
- 金融数据高风险，完成后必须进行独立只读代码审查；阻断发现先写失败测试复现再修复。

## 工作树、同步与发布边界

`/Users/aviva/Projects/stock` 当前 `main` 领先 `origin/main` 196 个提交，并有用户的 `.planning` 状态。实施从当前 HEAD 创建 `/private/tmp` 隔离 worktree，只修改本设计列出的生产、测试、配置和交付文档。

验证通过后生成精确补丁并应用到主 stock 工作树；应用前后检查目标文件是否出现并发变化。`.planning`、私有密钥、缓存、日志、`analysis/` 运行产物和调度文件均排除。同步完成后在主 stock 工作树重新运行完整测试和适用门禁，证明主仓库实际可用。

本次授权包含向 `/Users/aviva/Projects/stock` 写入经验证的文件，但不包含 commit、push、PR、merge、deploy、publish、删除或清理现有改动。

## 方案比较

1. **采用：独立适配器并接正式 raw/FACT 链。** 符合两个项目独立运行约束，同时确保 stock 实际消费新接口。
2. **不采用：只复制解析函数。** 文件存在但正式管线不会使用，不能满足“确保可以用上”。
3. **不采用：建立跨仓共享包。** 会引入运行时耦合、发布顺序和缓存一致性问题，违背当前独立报告约定。

## 设计自查结论

- 范围聚焦于增量接口，没有重复实现 7月23日已同步来源。
- `SKHY`、`SPCX`、SAFE单源证据和四个 raw 路由均有明确口径。
- 单源 evidence 与严格 FACT 的边界明确，没有降低原有双源市场事实政策。
- 没有占位符、未定字段、跨仓运行依赖或未授权 Git/部署动作。
