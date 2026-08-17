# 2026-07-29 晨报正确性修复实施计划

## 发现与基线

- 仓库根：`/Users/aviva/Projects/daily_info`；无 `AGENTS.md`；当前目录不是 Git 仓库。
- 既有正式输出和 `reports/latest` 属于外部状态，本轮只生成 `reports/previews/...` 隔离产物。
- 修改前全量基线（2026-07-29）：`python3 -m unittest discover -s tests -v`，147 passed，0 failed/error/skipped。
- A股银河 AD API 凭据在当前环境不可用；沿用既有公开新浪/东方财富结构化源，不伪造 AD 快照。

## 实施顺序

1. 写连续合约、异常 OHLC、宽度日期隐藏、新闻补源门槛和查询覆盖的失败测试。
2. 运行聚焦测试，确认每个失败都对应目标缺陷。
3. 修改解析、验证、渲染、查询和配置；运行聚焦测试直至通过。
4. 运行集成/全量测试、Python/JSON/shell/plist 语法检查和隔离真实报告。
5. 检查隔离产物无错误日期家数、无报告日盘中收盘、新闻补源证据完整、合约标签明确。
6. 进行独立只读金融正确性审查；阻断项按 RED→GREEN 修复并重跑全部门禁。

## 测试矩阵

| 门禁 | 行为 | 命令/证据 | RED | GREEN |
|---|---|---|---|---|
| Unit | 东方财富采用供应商日涨跌反推前值 | `tests.test_free_market_sources` | 旧实现返回相邻连续收盘 | 结算涨跌额/比例一致 |
| Unit | 新浪不可能 OHLC 行被拒绝 | `tests.test_free_market_sources` | 旧实现仍接纳 | 抛出 `SourceError` |
| Unit | 日期错误优先于重复代码 | `tests.test_breadth*` | 旧实现返回 duplicate | 返回 unexpected date |
| UI/static | Markdown/HTML 隐藏错误日期家数 | `tests.test_report` + 静态 HTML 断言 | 旧实现泄漏家数 | 只显示日期/来源/原因 |
| Unit/integration | 新闻按可发布条数补源 | `tests.test_news_collect` | 旧实现不补源 | 补源后二域事件发布 |
| Unit | 默认查询覆盖收盘、财报、国内期货 | `tests.test_news_collect` | 缺少类别 | 类别/关键词存在 |
| Config | LME供应商合约标签不冒充官方收盘 | `tests.test_config` | 旧标签含糊 | 明确 provider 3M continuous |
| Security/privacy | 无新密钥、URL仍为HTTPS、异常不泄漏正文 | 测试与人工范围检查 | N/A（无秘密写入） | 保持既有安全边界 |
| Artifact | 真实隔离晨报 | `python3 -m morning_brief.cli ...` 指向 preview | N/A | 日期/值/标签/证据完整且 latest 未变 |
| Build | Python/JSON/shell/plist | 既有仓库命令 | N/A | 全部 exit 0 |
| Full | 全套回归 | `python3 -m unittest discover -s tests -v` | N/A | 0 failure/error |

## UI与发布说明

- 用户可见变化是静态 Markdown/HTML；没有可点击的应用交互控件，真实点击测试 N/A。执行渲染测试、HTML 静态结构检查和隔离预览。
- 当前非 Git 仓库，staged patch、branch/upstream、commit/push/PR/merge 均 N/A；用文件清单和内容检查代替 diff 门禁。
- 未经额外授权不覆盖正式 `latest`，不更改 launchd，不部署或发送报告。
