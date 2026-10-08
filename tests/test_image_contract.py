from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ImageContractTests(unittest.TestCase):
    def test_railway_storage_paths_and_native_dashboard_are_preserved(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        for setting in (
            "HOME=/data",
            "HERMES_HOME=/data/.hermes",
            "HERMES_WRITE_SAFE_ROOT=/data",
            "HERMES_LAZY_INSTALL_TARGET=/data/.hermes/lazy-packages",
            "HERMES_SKIP_CONFIG_MIGRATION=1",
            "HERMES_DASHBOARD_PORT=8080",
            "PLAYWRIGHT_BROWSERS_PATH=/opt/hermes/.playwright",
        ):
            self.assertIn(setting, dockerfile)
        self.assertNotIn("\nENTRYPOINT", dockerfile)
        self.assertIn('CMD ["sleep", "infinity"]', dockerfile)
        railway = (ROOT / ".railway/railway.ts").read_text()
        self.assertIn('healthcheck: "/api/status"', railway)
        self.assertNotIn("start:", railway)
        npm = (ROOT / "aio-npm/package.json").read_text()
        self.assertIn("playwright", npm)
        self.assertIn("apt-get install -y --no-install-recommends file ffmpeg ripgrep", dockerfile)
        self.assertNotIn(" gh ", dockerfile)
        self.assertNotIn("xurl", dockerfile)

    def test_preflight_hook_runs_delivery_check_before_profile_migration(self):
        hook = (ROOT / "docker/011-aio-preflight").read_text()
        self.assertLess(hook.index("check_pending_deliveries.py"), hook.index("migrate_hermes_configs.py"))
        self.assertIn("s6-setuidgid hermes python /app/migrate_hermes_configs.py", hook)
        self.assertIn('if [ "$check_rc" -eq 2 ]; then', hook)
        self.assertIn('elif [ "$check_rc" -ne 0 ]; then', hook)

    def test_only_readme_credits_original_project(self):
        original = "praveen-ks-2001/hermes-agent-template"
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
                continue
            try:
                content = path.read_text()
            except (UnicodeError, OSError):
                continue
            if original in content:
                hits.append(path.relative_to(ROOT).as_posix())
        self.assertEqual([path for path in hits if path != "tests/test_image_contract.py"], ["README.md"])
        readme = (ROOT / "README.md").read_text()
        self.assertEqual(readme.count("https://github.com/praveen-ks-2001/hermes-agent-template"), 1)

    def test_removed_wrapper_runtime_is_not_copied_or_referenced(self):
        for path in ("server.py", "start.sh", "templates"):
            self.assertFalse((ROOT / path).exists())
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertNotIn("server.py", dockerfile)
        self.assertNotIn("start.sh", dockerfile)


if __name__ == "__main__":
    unittest.main()
