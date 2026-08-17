## 目标
把 HTML 生成架构改为「md 为每天生成的内容，HTML 由 md 经固定模板自动转换生成」；样式抽成共享 CSS 文件。模板/CSS 变更时，**所有页面（含历史报告）一起变化**，不再"新的换了、老的没换"。

## 设计
1. **新增 `morning_brief/templates.py`**：
   - `REPORT_CSS`：固定样式表（白底清爽、`details.alert` 折叠、涨绿跌红、核验四色、表头吸顶、新闻标签、响应式）。
   - `HTML_SHELL`：固定 HTML 骨架，`<link rel="stylesheet" href="../../report.css">`（从 `.runs/<run>/` 解析到 `reports/report.css`）+ `<main>` 占位 + 图例。
   - `md_to_html(md)`：自定义 Markdown 子集转换器（兼容现有全部 md 格式）：
     - `#/##/###` 标题、`>` 规则引用、`- ` 列表、`N. ` 新闻条目（文章卡片）、`---`、段落、行内 `**粗体**`/`[文](链接)`/`\`code\``；
     - 管道表格 → `<table>`：表头/正文；单元格加类——核验状态列按文本映射四色；数值列按 `+/-` 号着色、`—` 置灰；A 股宽度列（上涨/上涨率→绿、下跌/下跌率→红、平盘→灰）；
     - `## 数据告警` 标题后列表 → 包进 `<details class="alert"><summary>数据告警（N 条，点击展开）</summary>`（折叠机制在模板，位置由 md 决定）；
     - 末尾免责声明行 → `<footer>`。
2. **`morning_brief/report.py`**：
   - `render_html(model)` 改为：`HTML_SHELL` + `md_to_html(render_markdown(model))`（`<title>` 取 model 的 report_date；正文完全来自 md），删除内嵌 CSS。
   - `ReportWriter.write` 额外原子写入共享样式 `reports/report.css`（幂等）。
3. **新增 `scripts/rerender_html.py`**：遍历 `reports/.runs/*/`，用各自 md + 当前模板重渲染 HTML（**只改 html，不动 md/evidence/state**）；模板结构变更后用它批量同步所有页面。

## 测试（RED → GREEN）
- 新增 `tests/test_templates.py`：md_to_html 的标题/表格类名/链接/告警折叠与计数/新闻卡片/footer/引用块。
- `tests/test_report.py`：render_html 内容断言应保持通过（验证转换器保真：`6,300.00`、`+100.00`、`已双源核验`、`https://stooq.com/spx`、`央行发布政策`、`新闻核验缺口` 等）；新增断言 html 含 `report.css` 链接、writer 写出 `report.css`。
- 全量 164 项 + 新增全部通过；py_compile / bash -n 门禁。

## 文档
- `docs/日常报告交接.md`：补充「HTML 由 md 转换生成、样式共享 `reports/report.css`、模板变更后运行 `scripts/rerender_html.py` 让所有页面同步；md 是每日生成内容」。

## 落地（实施后执行）
1. 写入 `reports/report.css`；
2. 用当前模板从今天的 md 重渲染 `reports/index` 的 HTML；
3. **批量重渲染全部 19 份历史 run 的 HTML**（md/evidence/state 一律不动）→ 所有页面同模板；
4. 浏览器抽查今天与一份老报告，确认样式一致、告警折叠、涨跌配色正常；
5. 不改 launchd、不动 stock、不初始化 Git；`reports/index` 与日期归档结构保持现状。