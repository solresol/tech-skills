"""Exercise cron notification routing without contacting APIs or the database."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "hourlycron.sh"
SUCCESS = "Hourly batch check fetched completed batches successfully"


class HourlyCronTests(unittest.TestCase):
    def run_cron(self, batchcheck_status=0, batchfetch_status=0):
        with tempfile.TemporaryDirectory(prefix="tech-skills-hourlycron-") as directory:
            root = Path(directory)
            script = root / "hourlycron.sh"
            shutil.copy2(SCRIPT, script)
            home = root / "home"
            bin_dir = home / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            calls = root / "uv-calls.txt"
            uv = bin_dir / "uv"
            uv.write_text(
                "#!/bin/bash\n"
                'printf "%s\\n" "$*" >> "$MOCK_UV_CALLS"\n'
                'echo "mock uv stdout: $*"\n'
                'echo "mock uv stderr: $*" >&2\n'
                'case "$*" in\n'
                '  "run batchcheck.py") exit "$MOCK_BATCHCHECK_STATUS" ;;\n'
                '  "run batchfetch.py --show-costs") exit "$MOCK_BATCHFETCH_STATUS" ;;\n'
                '  *) exit 99 ;;\n'
                "esac\n"
            )
            uv.chmod(0o755)
            git = bin_dir / "git"
            git.write_text(
                "#!/bin/bash\n"
                '[ "$*" = "rev-parse HEAD" ] || exit 99\n'
                "echo mock-head\n"
            )
            git.chmod(0o755)
            env = dict(
                os.environ,
                HOME=str(home),
                PATH="/usr/bin:/bin",
                MOCK_UV_CALLS=str(calls),
                MOCK_BATCHCHECK_STATUS=str(batchcheck_status),
                MOCK_BATCHFETCH_STATUS=str(batchfetch_status),
            )
            result = subprocess.run(
                ["bash", str(script)],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            log = (root / "logs" / "hourlycron_latest.log").read_text()
            return result, calls.read_text().splitlines(), log

    def assert_alert(self, result, log, message):
        self.assertEqual(result.stderr, "")
        self.assertRegex(
            result.stdout,
            r"^\[[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\] "
            + message
            + r"\n$",
        )
        self.assertIn(message, log)

    def test_completed_batches_are_logged_without_email_output(self):
        result, calls, log = self.run_cron()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assertEqual(calls, ["run batchcheck.py", "run batchfetch.py --show-costs"])
        self.assertIn(SUCCESS, log)
        self.assertIn("mock uv stdout: run batchcheck.py", log)
        self.assertIn("mock uv stderr: run batchfetch.py --show-costs", log)

    def test_pending_batches_exit_quietly_without_fetching(self):
        result, calls, log = self.run_cron(batchcheck_status=3)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assertEqual(calls, ["run batchcheck.py"])
        self.assertIn("Hourly batch check found no completed batches; exiting quietly", log)
        self.assertNotIn(SUCCESS, log)

    def test_batchcheck_failure_preserves_exit_status_and_alert(self):
        result, calls, log = self.run_cron(batchcheck_status=7)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(calls, ["run batchcheck.py"])
        self.assert_alert(result, log, "Hourly batch check encountered an error")
        self.assertIn("FAILURE uv run batchcheck.py (exit 7,", log)
        self.assertNotIn(SUCCESS, log)

    def test_batchfetch_failure_preserves_exit_status_and_alert(self):
        result, calls, log = self.run_cron(batchfetch_status=11)
        self.assertEqual(result.returncode, 11)
        self.assertEqual(calls, ["run batchcheck.py", "run batchfetch.py --show-costs"])
        self.assert_alert(result, log, "Hourly batch check failed during batchfetch step")
        self.assertIn("FAILURE uv run batchfetch.py --show-costs (exit 11,", log)
        self.assertNotIn(SUCCESS, log)


if __name__ == "__main__":
    unittest.main()
