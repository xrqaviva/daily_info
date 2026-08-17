import json
import plistlib
import unittest
from pathlib import Path


class OperationsTests(unittest.TestCase):
    def test_launchd_log_directories_exist_in_clean_checkout(self):
        payload = plistlib.loads(
            Path("launchd/com.aviva.daily-info.plist").read_bytes()
        )
        for key in ("StandardOutPath", "StandardErrorPath"):
            self.assertTrue(
                Path(payload[key]).parent.exists(),
                "%s parent must exist before launchd starts" % key,
            )

    def test_launchd_script_exports_node_directory_for_codex_launcher(self):
        runtime = json.loads(Path("config/runtime.json").read_text(encoding="utf-8"))
        codex = Path(runtime["codex_executable"])
        self.assertTrue(codex.is_absolute())
        self.assertTrue((codex.parent / "node").exists())
        script = Path("scripts/run_morning.sh").read_text(encoding="utf-8")
        self.assertIn(str(codex.parent), script)
        self.assertIn("export PATH=", script)


if __name__ == "__main__":
    unittest.main()
