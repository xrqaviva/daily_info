import datetime
import json
from pathlib import Path

from .report import _write_atomic


class StateStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def news_since(self, as_of, *, initial_hours=336):
        end = datetime.datetime.fromisoformat(str(as_of))
        saved = self.load().get("last_successful_as_of")
        try:
            start = datetime.datetime.fromisoformat(str(saved))
        except (TypeError, ValueError):
            start = end - datetime.timedelta(hours=int(initial_hours))
        if start >= end:
            start = end - datetime.timedelta(hours=int(initial_hours))
        return start.isoformat()

    def mark_success(self, as_of, report_date):
        payload = {
            "last_successful_as_of": str(as_of),
            "last_report_date": str(report_date),
        }
        _write_atomic(
            self.path,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
