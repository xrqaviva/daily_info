import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from morning_brief.cli import RunLock, main


class FakePipeline:
    def __init__(self, result):
        self.result = result
        self.as_of = None

    def run(self, *, as_of, force=False):
        self.as_of = as_of
        self.force = force
        return self.result


class CliTests(unittest.TestCase):
    def test_generated_and_skipped_are_success_but_blocked_is_error(self):
        with tempfile.TemporaryDirectory() as directory:
            for status, expected in (("generated", 0), ("skipped", 0), ("blocked", 2)):
                pipeline = FakePipeline({"status": status})
                output = io.StringIO()
                with redirect_stdout(output):
                    code = main(
                        ["run", "--root", directory, "--as-of", "2026-07-20T07:40:00+08:00"],
                        pipeline_factory=lambda root: pipeline,
                    )
                self.assertEqual(code, expected)
                self.assertIn('"status": "%s"' % status, output.getvalue())

    def test_run_lock_prevents_overlap_and_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.lock"
            with RunLock(path):
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    with RunLock(path):
                        pass
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
