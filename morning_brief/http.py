import json
import subprocess
from urllib.parse import urlsplit


class SourceError(RuntimeError):
    pass


class CurlClient:
    _TRANSIENT_RETURN_CODES = {5, 6, 7, 18, 28, 35, 52, 56, 92}

    def __init__(self, *, runner=subprocess.run, timeout=20):
        self.runner = runner
        self.timeout = int(timeout)

    def _run(self, command, *, input_bytes=None):
        last_exception = None
        for attempt in range(2):
            try:
                kwargs = {
                    "capture_output": True,
                    "timeout": self.timeout + 5,
                }
                if input_bytes is not None:
                    kwargs["input"] = input_bytes
                result = self.runner(command, **kwargs)
            except (OSError, subprocess.SubprocessError) as exc:
                last_exception = exc
                if attempt == 0:
                    continue
                raise SourceError("curl failed: %s" % type(exc).__name__)
            if result.returncode == 0:
                return result
            if (
                attempt == 0
                and result.returncode in self._TRANSIENT_RETURN_CODES
            ):
                continue
            raise SourceError("curl rc=%s" % result.returncode)
        raise SourceError(
            "curl failed: %s" % type(last_exception).__name__
            if last_exception is not None else "curl failed"
        )

    def get_text(self, url, *, headers=None):
        parsed = urlsplit(str(url))
        if parsed.scheme != "https" or not parsed.hostname:
            raise SourceError("only HTTPS source URLs are allowed")
        command = [
            "curl", "--silent", "--show-error", "--location",
            "--fail", "--compressed",
            "--user-agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "--proto", "=https", "--tlsv1.2",
            "--connect-timeout", "5", "--max-time", str(self.timeout),
            "--max-filesize", "5242880",
        ]
        for name, value in (headers or {}).items():
            command.extend(["-H", "%s: %s" % (name, value)])
        command.append(url)
        result = self._run(command)
        raw = result.stdout
        if isinstance(raw, bytes):
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    text = raw.decode("gb18030", "strict")
                except UnicodeDecodeError:
                    raise SourceError("source response encoding is unsupported")
        else:
            text = str(raw)
        if not text.strip():
            raise SourceError("empty source response")
        return text

    def get_json(self, url, *, headers=None):
        text = self.get_text(url, headers=headers)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise SourceError("source response is not JSON")

    def post_json(self, url, payload, *, headers=None):
        parsed = urlsplit(str(url))
        if parsed.scheme != "https" or not parsed.hostname:
            raise SourceError("only HTTPS source URLs are allowed")

        def escaped(value):
            text = str(value)
            if any(ord(character) < 32 or ord(character) == 127 for character in text):
                raise SourceError("curl config value contains control characters")
            return text.replace("\\", "\\\\").replace('"', '\\"')

        config = [
            'url = "%s"' % escaped(url),
            'request = "POST"',
            'header = "Content-Type: application/json"',
            'data = "%s"' % escaped(json.dumps(payload, ensure_ascii=False)),
        ]
        for name, value in (headers or {}).items():
            config.append('header = "%s: %s"' % (escaped(name), escaped(value)))
        command = [
            "curl", "--silent", "--show-error", "--location", "--fail",
            "--compressed",
            "--user-agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "--proto", "=https", "--tlsv1.2", "--connect-timeout", "5",
            "--max-time", str(self.timeout), "--max-filesize", "5242880",
            "--config", "-",
        ]
        result = self._run(
            command,
            input_bytes=("\n".join(config) + "\n").encode("utf-8"),
        )
        raw = result.stdout.decode("utf-8", "strict") if isinstance(result.stdout, bytes) else str(result.stdout)
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SourceError("source response is not JSON")
