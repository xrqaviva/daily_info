"""固定 HTML 模板与 Markdown→HTML 转换器。

md 是每日生成的内容（render_markdown 的输出）；HTML 由 md 经本模块的固定
模板自动转换得到，样式集中在 REPORT_CSS（共享文件 reports/report.css）。
模板或样式变更后运行 scripts/rerender_html.py，即可让所有历史页面同步，
避免“新的页面换了样式、老页面没换”。
"""

import html
import re


REPORT_CSS = """:root{--bg:#eef1f5;--card:#ffffff;--card-2:#f4f7fa;--border:#e2e8ef;--text:#1c2733;--muted:#65707c;--accent:#1769aa;--up:#d9384a;--down:#0c8f5e;--flat:#87929e;--warn:#b45309}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;margin:0;background:var(--bg);color:var(--text);-webkit-font-smoothing:antialiased;line-height:1.6}
main{width:100%;margin:0;padding:28px 20px 56px}
h1{font-size:24px;margin:4px 0 6px;letter-spacing:.5px}
h2{font-size:17px;margin:0 0 14px;padding:8px 12px;border-left:3px solid var(--accent);background:rgba(23,105,170,.06);border-radius:0 6px 6px 0}
.meta{color:var(--muted);font-size:13.5px}
section{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px 18px 14px;margin:16px 0;box-shadow:0 2px 10px rgba(25,50,90,.05)}
details.alert{margin:16px 0;border:1px solid rgba(180,83,9,.35);background:#fffaf0;border-radius:10px;padding:0 14px}
details.alert summary{cursor:pointer;padding:10px 0;font-weight:600;color:#8a5a12;list-style:none}
details.alert summary::-webkit-details-marker{display:none}
details.alert summary::before{content:"▸  ";color:#b45309}
details.alert[open] summary::before{content:"▾  "}
details.alert ul{margin:0 0 10px;padding-left:20px}
details.alert li{margin:3px 0;color:#7a5a1e}
details.status{margin:16px 0;border:1px solid var(--border);background:var(--card);border-radius:10px;padding:0 14px}
details.status summary{cursor:pointer;padding:10px 0;font-weight:600;color:var(--muted);list-style:none}
details.status summary::-webkit-details-marker{display:none}
details.status summary::before{content:"▸  ";color:var(--accent)}
details.status[open] summary::before{content:"▾  "}
details.status ul{margin:0 0 10px;padding-left:20px}
details.status li{margin:3px 0;color:var(--muted)}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
.table-wrap{width:100%;overflow-x:auto}
.trend td{vertical-align:middle}
td.trend{min-width:96px;padding:2px 6px!important}
.sparkline{display:block}
.sparkline polyline{fill:none;stroke-width:1.4;vector-effect:non-scaling-stroke}
.spark-up polyline{stroke:var(--up,#d9384a)}
.spark-down polyline{stroke:var(--down,#0c8f5e)}
th{position:sticky;top:0;background:var(--card-2);color:var(--muted);font-size:12.5px;font-weight:600;letter-spacing:.3px;z-index:1}
th,td{padding:9px 12px;border-bottom:1px solid var(--border);text-align:left;white-space:nowrap}
tbody tr:hover td{background:rgba(23,105,170,.05)}
.num{text-align:right}
.src{font-size:11.5px;color:var(--muted);white-space:normal;line-height:1.5;max-width:220px}
.src a{color:var(--muted);text-decoration:none}
.src a:hover{color:var(--accent);text-decoration:underline}
.up{color:var(--up)}
.down{color:var(--down)}
.flat{color:var(--flat)}
.status-verified{color:#0c8f5e}
.status-single{color:var(--warn)}
.status-conflict{color:#c2410c}
.status-unavailable{color:var(--muted)}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
article{border-top:1px solid var(--border);padding:12px 0}
article h3{margin:0 0 6px;font-size:15px;line-height:1.5}
article p{margin:4px 0;color:var(--muted);font-size:13.5px}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;border:1px solid var(--border);color:var(--muted);background:var(--card-2);vertical-align:1px}
.tag.official{color:#0c8f5e;border-color:rgba(12,143,94,.4);background:rgba(12,143,94,.08)}
footer{color:var(--muted);margin-top:24px;font-size:13px}
.legend{color:var(--muted);font-size:12.5px;margin-top:8px}
.legend .up{color:var(--up)}
.legend .down{color:var(--down)}
@media (max-width:720px){h1{font-size:20px}main{padding:18px 12px 40px}}
"""

CSS_VERSION = "5"


HTML_SHELL = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>A股盘前双源晨报｜{date}</title><link rel="stylesheet" href="../../report.css?v={css_version}"></head><body><main>{body}<p class="legend"><span class="up">涨 ▲</span> / <span class="down">跌 ▼</span>（红涨绿跌）—— 颜色仅辅助展示，核验状态以表格为准。</p><footer>本报告仅作信息整理，不构成投资建议。</footer></main></body></html>"""


_STATUS_CLASS = {
    "已双源核验": "status-verified",
    "待核验（仅单源）": "status-single",
    "待核验（双源冲突）": "status-conflict",
    "不可用": "status-unavailable",
    "单源参考": "status-single",
}


def _inline(text):
    text = html.escape(str(text), quote=True)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda match: '<a href="%s">%s</a>' % (match.group(2), match.group(1)),
        text,
    )
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\\([\\`*_{}\[\]<>#|])", r"\1", text)
    return text


def _sign_class(text):
    text = str(text or "").strip()
    if text == "—":
        return "num flat"
    if " / " in text or ("+" in text and "-" in text):
        return "num"
    match = re.search(r"[+-]\s*[\d,]+(?:\.\d+)?", text)
    if not match:
        return "num"
    try:
        value = float(match.group(0).replace(",", "").replace(" ", ""))
    except ValueError:
        return "num"
    if value > 0:
        return "num up"
    if value < 0:
        return "num down"
    return "num flat"


def _column_kind(header):
    text = str(header or "").strip()
    if text == "核验状态":
        return "status"
    if text in ("上涨", "上涨率"):
        return "up"
    if text in ("下跌", "下跌率"):
        return "down"
    if text == "平盘":
        return "flat"
    if text in ("绝对变化", "变化比例"):
        return "sign"
    if text in ("最新值", "有效样本"):
        return "num"
    if text == "来源":
        return "src"
    return "plain"


def _split_row(line):
    return [cell.strip() for cell in str(line).strip().strip("|").split("|")]


def _cell(header, cell_text):
    kind = _column_kind(header)
    if kind == "status":
        css = _STATUS_CLASS.get(cell_text, "")
    elif kind == "up":
        css = "num up" if cell_text != "—" else "num flat"
    elif kind == "down":
        css = "num down" if cell_text != "—" else "num flat"
    elif kind == "flat":
        css = "num flat"
    elif kind == "sign":
        css = _sign_class(cell_text)
    elif kind == "num":
        css = "num flat" if cell_text == "—" else "num"
    elif kind == "src":
        css = "src"
    else:
        css = ""
    if cell_text and str(cell_text).startswith("SPARK:"):
        # 月趋势迷你折线图：SPARK|date,close;date,close 数据 -> SVG
        raw = str(cell_text)[6:].strip()
        points = []
        for pair in raw.split(";"):
            if not pair:
                continue
            date, _, close = pair.partition(",")
            points.append((date, close))
        svg = sparkline_svg(points)
        if svg:
            return '<td class="trend">%s</td>' % svg
        return '<td class="trend">—</td>'
    content = _inline(cell_text)
    return '<td class="%s">%s</td>' % (css, content) if css else "<td>%s</td>" % content


def _render_table(rows):
    header = _split_row(rows[0])
    head = "".join("<th>%s</th>" % _inline(item) for item in header)
    body = "".join(
        "<tr>%s</tr>" % "".join(
            _cell(header[index], cell)
            for index, cell in enumerate(_split_row(row))
        )
        for row in rows[2:]
    )
    return '<div class="table-wrap"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (head, body)


def _details_list(css_class, title, items):
    return '<details class="%s"><summary>%s（%d 条，点击展开）</summary><ul>%s</ul></details>' % (
        css_class, title, len(items),
        "".join("<li>%s</li>" % _inline(item) for item in items),
    )


def _status_item_html(item):
    if "：" in item:
        label, status = item.split("：", 1)
        css = _STATUS_CLASS.get(status)
        if css:
            return '<li>%s：<span class="%s">%s</span></li>' % (
                _inline(label), css, _inline(status),
            )
    return "<li>%s</li>" % _inline(item)



def sparkline_svg(points, width=92, height=28):
    """近 30 点收盘序列 -> 内联 SVG 迷你折线（月趋势列，HTML 用）。"""
    values = [float(value) for _date, value in points if value is not None]
    if len(values) < 2:
        return ""
    low, high = min(values), max(values)
    span = high - low
    if span <= 0:
        span = max(abs(high) * 1e-6, 1e-9)
    step_x = width / (len(values) - 1)
    coords = []
    for index, value in enumerate(values):
        x = round(index * step_x, 2)
        y = round(height - 2 - (value - low) / span * (height - 4), 2)
        coords.append("%s,%s" % (x, y))
    direction = "up" if values[-1] >= values[0] else "down"
    return (
        '<svg class="sparkline spark-%s" viewBox="0 0 %d %d" width="%d" height="%d" '
        'preserveAspectRatio="none" aria-label="月趋势迷你图">'
        '<polyline points="%s" fill="none" vector-effect="non-scaling-stroke"/></svg>'
        % (direction, width, height, width, height, " ".join(coords))
    )


def sparkline_ascii(points, width=14):
    """近 30 点收盘序列 -> ASCII 迷你柱（月趋势列，Markdown/终端用）。"""
    values = [float(value) for _date, value in points if value is not None]
    if len(values) < 2:
        return ""
    low, high = min(values), max(values)
    span = high - low
    if span <= 0:
        span = max(abs(high) * 1e-6, 1e-9)
    levels = "▁▂▃▄▅▆▇█"
    sampled = values[::max(1, len(values) // width)][:width]
    return "".join(levels[min(7, int((value - low) / span * 8))] for value in sampled)


def md_to_html(markdown):
    lines = str(markdown or "").splitlines()
    out = []
    index = 0
    total = len(lines)

    while index < total:
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if stripped.startswith("# "):
            out.append("<h1>%s</h1>" % _inline(stripped[2:].strip()))
            index += 1
            continue
        if stripped.startswith("### "):
            out.append("<h3>%s</h3>" % _inline(stripped[4:].strip()))
            index += 1
            continue
        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            if heading == "数据告警":
                items = []
                cursor = index + 1
                while cursor < total and not lines[cursor].strip():
                    cursor += 1
                while cursor < total and lines[cursor].strip().startswith("- "):
                    items.append(lines[cursor].strip()[2:].strip())
                    cursor += 1
                out.append(_details_list("alert", "数据告警", items))
                index = cursor
                continue
            if heading == "核验状态":
                items = []
                cursor = index + 1
                while cursor < total and not lines[cursor].strip():
                    cursor += 1
                while cursor < total and lines[cursor].strip().startswith("- "):
                    items.append(lines[cursor].strip()[2:].strip())
                    cursor += 1
                out.append(
                    '<details class="status"><summary>核验状态（%d 条，点击展开）</summary>'
                    "<ul>%s</ul></details>" % (
                        len(items),
                        "".join(_status_item_html(item) for item in items),
                    )
                )
                index = cursor
                continue
            out.append("<h2>%s</h2>" % _inline(heading))
            index += 1
            continue
        if stripped.startswith("> "):
            out.append('<p class="rule">%s</p>' % _inline(stripped[2:].strip()))
            index += 1
            continue
        if stripped.startswith("|"):
            rows = []
            while index < total and lines[index].strip().startswith("|"):
                rows.append(lines[index])
                index += 1
            out.append(_render_table(rows))
            continue
        if stripped == "---":
            cursor = index + 1
            while cursor < total and not lines[cursor].strip():
                cursor += 1
            if cursor < total and lines[cursor].strip().startswith("本报告仅作信息整理"):
                index = cursor + 1
                continue
            out.append("<hr>")
            index += 1
            continue
        if re.match(r"^\d+\.\s", stripped):
            out.append("<article><h3>%s</h3>" % _inline(stripped))
            index += 1
            metas = []
            while index < total:
                line = lines[index]
                text = line.strip()
                if text.startswith("- ") and line.startswith("   "):
                    metas.append(text[2:].strip())
                    index += 1
                elif not text:
                    index += 1
                else:
                    break
            for meta in metas:
                rendered = _inline(meta)
                if "核验：官方一手单源" in rendered:
                    rendered = rendered.replace(
                        "核验：官方一手单源",
                        '核验：<span class="tag official">官方一手单源</span>',
                    )
                elif "核验：媒体双源" in rendered:
                    rendered = rendered.replace(
                        "核验：媒体双源",
                        '核验：<span class="tag">媒体双源</span>',
                    )
                out.append('<p class="meta">%s</p>' % rendered)
            out.append("</article>")
            continue
        if stripped.startswith("- "):
            items = []
            while index < total and lines[index].strip().startswith("- "):
                items.append(lines[index].strip()[2:].strip())
                index += 1
            out.append("<ul>%s</ul>" % "".join(
                "<li>%s</li>" % _inline(item) for item in items
            ))
            continue
        if stripped.startswith("采集截止：") or stripped.startswith("上一A股交易日："):
            out.append('<p class="meta">%s</p>' % _inline(stripped))
            index += 1
            continue
        if stripped.startswith("本报告仅作信息整理"):
            index += 1
            continue
        out.append("<p>%s</p>" % _inline(stripped))
        index += 1
        continue
    return "\n".join(out)
