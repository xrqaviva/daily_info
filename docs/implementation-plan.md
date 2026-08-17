# A 股双源晨报实施计划

## Discovery 与基线

- 项目根目录：`/Users/aviva/Projects/daily_info`；非 Git 仓库，无 AGENTS.md、代码、测试或历史。
- 私有路径：只读 stock 密钥文件；不得进入报告、日志、夹具或配置内容。
- 基线：2026-07-18 运行 `python3 -m unittest discover -s tests -v`，因 `tests` 不存在返回 ImportError。无可比较的绿基线。
- UI：生成静态 HTML，无交互控件；需要渲染/文本一致性检查，点击交互 N/A。

## 有序任务

1. 先测试并实现标准记录、双源数值核验、板块排序和 A 股宽度过滤。
2. 先测试并实现来源适配器的纯解析函数、HTTP/curl 客户端与配置加载。
3. 先测试并实现新闻官方域名规则、媒体双源合并、时间窗口、去重和 20 条上限。
4. 先测试并实现交易日历双源门禁、休市跳过和跨休市新闻状态。
5. 先测试并实现统一报告模型、Markdown/HTML/evidence 原子输出和 latest 文件。
6. 先测试并实现 CLI、07:40 shell 包装、LaunchAgent 候选、锁和日志脱敏。
7. 运行真实在线冒烟、生成样例、静态 HTML QA、秘密扫描、完整测试与独立只读审查。

真实在线冒烟与双源现场一致性验收已由用户明确暂缓，等待另一对话中的新增来源完成；其余离线验证和独立审查继续执行，不把暂缓项标记为通过。

## 测试矩阵

- Unit：解析器、日期/单位对齐、容差边界、单源/冲突/不可用、ST/停牌/退市过滤、板块排序、新闻来源独立性。
- Integration：固定夹具通过完整 pipeline 生成三种一致输出；休市不输出；失败产生降级报告。
- Live contract：每一类实际来源至少探测一次，记录 HTTP/解析/数据日期；失败不得算通过。
- Security/privacy：密钥只由环境或指定文件读取；报告、日志、源码、测试夹具秘密扫描为零命中。
- Artifact：Markdown、HTML 与 evidence 的值、日期、状态和 URL 一致；latest 不得指向旧运行。
- Build/syntax：`python3 -m py_compile`、`bash -n`、`plutil -lint`。
- Full suite：最后一次变更后运行 `python3 -m unittest discover -s tests -v` 并报告精确计数。

## 验收停点

- 若真实接口无法为某类提供两个同口径来源，实现仍可交付但该类必须保持 `single_source/unavailable`，不得宣称已验证。
- 系统级唤醒与 LaunchAgent 安装不在自动执行范围；项目验证后请求授权。
