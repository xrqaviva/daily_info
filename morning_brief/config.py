import json
from pathlib import Path


class ConfigError(ValueError):
    pass


SOURCE_FIELDS = {
    "status", "roles", "date_quality", "endpoint_type",
    "timeout_seconds", "max_requests", "url", "ownership", "limitations",
}
SOURCE_STATUSES = {"enabled", "supplemental", "on_demand", "disabled"}
DATE_QUALITIES = {
    "explicit", "derived_official_daily", "session_only", "not_applicable",
}
ENDPOINT_TYPES = {
    "https_get_json", "https_post_json", "https_get_csv", "https_get_text",
    "https_get_text_table", "rss_xml", "on_demand_json", "library_wrapper",
}


def load_source_catalog(path):
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError("cannot load source catalog: %s" % type(exc).__name__)
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "sources"}:
        raise ConfigError("source catalog root is invalid")
    if payload.get("schema_version") != 1 or not isinstance(payload.get("sources"), dict):
        raise ConfigError("source catalog schema is invalid")
    sources = payload["sources"]
    for source_id, row in sources.items():
        if not isinstance(source_id, str) or not source_id.strip():
            raise ConfigError("source id is invalid")
        if not isinstance(row, dict) or set(row) != SOURCE_FIELDS:
            raise ConfigError("source %s fields are invalid" % source_id)
        if row["status"] not in SOURCE_STATUSES:
            raise ConfigError("source %s status is invalid" % source_id)
        if row["date_quality"] not in DATE_QUALITIES:
            raise ConfigError("source %s date quality is invalid" % source_id)
        if row["endpoint_type"] not in ENDPOINT_TYPES:
            raise ConfigError("source %s endpoint type is invalid" % source_id)
        if not isinstance(row["roles"], list) or not row["roles"]:
            raise ConfigError("source %s roles are invalid" % source_id)
        if not isinstance(row["ownership"], list):
            raise ConfigError("source %s ownership is invalid" % source_id)
        if not isinstance(row["timeout_seconds"], int) or row["timeout_seconds"] <= 0:
            raise ConfigError("source %s timeout is invalid" % source_id)
        if not isinstance(row["max_requests"], int) or row["max_requests"] < 0:
            raise ConfigError("source %s request budget is invalid" % source_id)
        if not str(row["url"]).startswith("https://"):
            raise ConfigError("source %s URL is invalid" % source_id)
        if not isinstance(row["limitations"], str):
            raise ConfigError("source %s limitations are invalid" % source_id)
    return sources


def load_instruments(path):
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError("cannot load instrument config: %s" % type(exc).__name__)
    instruments = payload.get("instruments") if isinstance(payload, dict) else None
    if not isinstance(instruments, dict):
        raise ConfigError("instrument config must contain an instruments object")
    for key, item in instruments.items():
        if key in ("sectors", "supplemental"):
            if not isinstance(item, list):
                raise ConfigError("%s must be a list" % key)
            continue
        if key == "us_stock_groups":
            if not isinstance(item, dict):
                raise ConfigError("us_stock_groups must be an object")
            for group_key, group in item.items():
                if not isinstance(group, dict) or not isinstance(group.get("stocks"), list):
                    raise ConfigError("us_stock_groups.%s must have a stocks list" % group_key)
                for stock in group["stocks"]:
                    if not isinstance(stock, dict) or not stock.get("symbol"):
                        raise ConfigError("us_stock_groups.%s stock needs a symbol" % group_key)
            continue
        if not isinstance(item, dict) or not isinstance(item.get("sources"), list):
            raise ConfigError("instrument %s has no sources" % key)
    return instruments
