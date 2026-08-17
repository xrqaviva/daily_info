import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from .breadth_collect import BreadthCollector
from .calendar import TradingCalendar
from .config import load_instruments
from .http import CurlClient
from .market import MarketCollector
from .news_collect import CodexNewsProvider, NewsCollector, YingmiClient
from .sources.official_feeds import OfficialFeedProvider
from .pipeline import MorningBriefPipeline
from .report import ReportWriter
from .state import StateStore


def _load_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError("cannot load config: %s" % type(exc).__name__)
    if not isinstance(value, dict):
        raise ValueError("config root must be an object")
    return value


class RunLock:
    def __init__(self, path, *, stale_seconds=7200):
        self.path = Path(path)
        self.stale_seconds = int(stale_seconds)
        self.acquired = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                str(self.path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
        except FileExistsError:
            try:
                stale = time.time() - self.path.stat().st_mtime > self.stale_seconds
            except OSError:
                stale = False
            if not stale:
                raise RuntimeError("morning brief is already running")
            try:
                self.path.unlink()
            except OSError:
                raise RuntimeError("stale run lock cannot be replaced")
            descriptor = os.open(
                str(self.path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write("%s\n" % os.getpid())
        self.acquired = True
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.acquired = False


def build_pipeline(root):
    root = Path(root).resolve()
    runtime = _load_json(root / "config" / "runtime.json")
    calendar_config = _load_json(root / "config" / "calendar.json")
    client = CurlClient(timeout=25)
    instruments = load_instruments(root / "config" / "instruments.json")
    key_file = os.environ.get("YINGMI_KEY_FILE") or runtime.get("yingmi_key_file")
    providers = [YingmiClient(key_file=key_file)] if key_file else []
    fallback_config = runtime.get("codex_news_fallback") or {}
    fallback_providers = []
    if fallback_config.get("enabled"):
        fallback_providers.append(CodexNewsProvider(
            root,
            timeout=int(fallback_config.get("timeout_seconds") or 300),
            executable=(
                runtime.get("codex_executable")
                or fallback_config.get("executable")
                or "codex"
            ),
        ))
    news = NewsCollector(
        providers,
        client,
        tools=runtime.get("news_tools"),
        fallback_providers=fallback_providers,
        fallback_threshold=int(
            fallback_config.get("minimum_publishable_items")
            or fallback_config.get("minimum_url_candidates")
            or 4
        ),
        official_providers=[OfficialFeedProvider(client)],
    )
    return MorningBriefPipeline(
        calendar=TradingCalendar(client, calendar_config.get("years") or {}),
        market=MarketCollector(client),
        breadth=BreadthCollector(client),
        news=news,
        writer=ReportWriter(root / str(runtime.get("output_dir") or "reports")),
        state=StateStore(
            root / str(runtime.get("state_file") or "reports/index/state.json")
        ),
        instruments=instruments,
    )


def _as_of(value):
    if value:
        moment = datetime.datetime.fromisoformat(str(value))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        return moment.astimezone(ZoneInfo("Asia/Shanghai")).isoformat()
    return datetime.datetime.now(ZoneInfo("Asia/Shanghai")).replace(
        microsecond=0
    ).isoformat()


def _lock_path(root):
    try:
        runtime = _load_json(Path(root) / "config" / "runtime.json")
        relative = runtime.get("lock_file") or "state/run.lock"
    except ValueError:
        relative = "state/run.lock"
    return Path(root) / str(relative)


def _parser():
    parser = argparse.ArgumentParser(description="A股盘前双源晨报")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="采集并生成当日晨报")
    run.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    run.add_argument("--as-of", help="测试/重跑用 ISO 8601 截止时间")
    run.add_argument("--force", action="store_true", help="非交易日也生成（重跑周末/假日版）")
    return parser


def main(argv=None, *, pipeline_factory=build_pipeline):
    args = _parser().parse_args(argv)
    root = Path(args.root).resolve()
    try:
        with RunLock(_lock_path(root)):
            result = pipeline_factory(root).run(
                as_of=_as_of(args.as_of), force=bool(args.force)
            )
    except Exception as exc:
        result = {"status": "error", "error": type(exc).__name__}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 2 if result.get("status") == "blocked" else 0


if __name__ == "__main__":
    sys.exit(main())
