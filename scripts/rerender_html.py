#!/usr/bin/env python3
"""用当前 HTML 模板把所有历史 run 的 HTML 从各自 Markdown 重渲染。

模板或样式（morning_brief/templates.py）变更后运行本脚本，让所有页面
同步到同一模板。只改写 A股盘前晨报.html，不动 md/evidence/state。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from morning_brief.report import _write_atomic  # noqa: E402
from morning_brief.templates import CSS_VERSION, HTML_SHELL, REPORT_CSS, md_to_html  # noqa: E402


def render_html_from_md(md_text, report_date):
    body = md_to_html(md_text)
    return HTML_SHELL.replace(
        "{date}", report_date
    ).replace("{css_version}", CSS_VERSION).replace("{body}", body)


def main():
    runs_root = ROOT / "reports" / ".runs"
    css_path = ROOT / "reports" / "report.css"
    _write_atomic(css_path, REPORT_CSS)
    updated = 0
    for run_dir in sorted(runs_root.iterdir()):
        md_path = run_dir / "A股盘前晨报.md"
        html_path = run_dir / "A股盘前晨报.html"
        if not md_path.is_file():
            continue
        report_date = run_dir.name[:10]
        _write_atomic(html_path, render_html_from_md(
            md_path.read_text(encoding="utf-8"), report_date
        ))
        updated += 1
    print("re-rendered %d html files; shared css -> %s" % (updated, css_path))


if __name__ == "__main__":
    main()
