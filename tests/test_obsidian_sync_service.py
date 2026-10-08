"""Exercise the actual service scripts without requiring /data or s6 on the host."""

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "docker/s6-rc.d/obsidian-sync"


class ObsidianSyncServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.log = self.directory / "calls.jsonl"
        self.ready = self.directory / "ready"
        self.env = os.environ.copy()
        self.env.pop("OBSIDIAN_VAULT_PATH", None)
        self.env.pop("XDG_CONFIG_HOME", None)
        self.env.update(
            PATH=f"{self.bin}:{os.environ['PATH']}",
            HOME="/data",
            TEST_LOG=str(self.log),
            TEST_READY=str(self.ready),
        )
        # Guard shared config directories: the service must not create or chmod
        # them. Stand-ins record accidental mutations without writing /data.
        self.command(
            "mkdir",
            """import json, os, sys
with open(os.environ['TEST_LOG'], 'a') as f:
    f.write(json.dumps({'mkdir': sys.argv[1:], 'umask': os.umask(0)}) + '\\n')
sys.exit(int(os.environ.get('TEST_MKDIR_EXIT', '0')))
""",
        )
        self.command(
            "chmod",
            """import json, os, sys
with open(os.environ['TEST_LOG'], 'a') as f:
    f.write(json.dumps({'chmod': sys.argv[1:]}) + '\\n')
""",
        )
        self.command(
            "chown",
            "raise SystemExit('Ownership repair must only run in the Docker fixture')\n",
        )
        self.command(
            "id",
            "import os; print(os.environ.get('TEST_UID', '0'))\n",
        )
        self.command(
            "s6-setuidgid",
            """import json, os, sys
with open(os.environ['TEST_LOG'], 'a') as f:
    f.write(json.dumps({'user': sys.argv[1]}) + '\\n')
os.execvp(sys.argv[2], sys.argv[2:])
""",
        )
        self.command(
            "sleep",
            """import json, os, sys
with open(os.environ['TEST_LOG'], 'a') as f:
    f.write(json.dumps({'sleep': sys.argv[1:]}) + '\\n')
""",
        )
        self.command(
            "ob",
            """import json, os, signal, sys
from pathlib import Path
with open(os.environ['TEST_LOG'], 'a') as f:
    f.write(json.dumps({'ob': sys.argv[1:], 'home': os.environ['HOME'],
                       'config': os.environ.get('XDG_CONFIG_HOME'), 'pid': os.getpid()}) + '\\n')
if sys.argv[1:] == ['sync-list-local']:
    sys.exit(0)
if os.environ.get('TEST_WAIT') == '1':
    def stop(signum, frame):
        print('fake ob received SIGTERM', flush=True)
        sys.exit(0)
    signal.signal(signal.SIGTERM, stop)
    Path(os.environ['TEST_READY']).touch()
    signal.pause()
sys.exit(int(os.environ.get('TEST_OB_EXIT', '0')))
""",
        )

    def command(self, name, body):
        path = self.bin / name
        python = shutil.which("python3")
        path.write_text(f"#!{python}\n{body}")
        path.chmod(0o755)

    def run_script(self, name="run", *args):
        return subprocess.run(
            ["sh", str(SERVICE / name), *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=5,
        )

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_disabled_service_stays_down_without_touching_storage(self):
        for value in (None, ""):
            with self.subTest(value=value):
                if value is not None:
                    self.env["OBSIDIAN_VAULT_PATH"] = value
                self.assertEqual(self.run_script().returncode, 0)
                self.assertEqual(self.run_script("finish", "0", "0").returncode, 125)
                self.assertEqual(self.calls(), [])

    def test_valid_path_preserves_arguments_and_uses_persistent_credentials(self):
        self.env["OBSIDIAN_VAULT_PATH"] = "/data/.hermes/workspace/My Vault"
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(calls[0], {"user": "hermes"})
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1]["ob"], ["sync-list-local"])
        self.assertEqual(calls[2]["ob"], [
            "sync", "--continuous", "--path", self.env["OBSIDIAN_VAULT_PATH"],
        ])
        self.assertEqual(calls[2]["home"], "/data")
        self.assertIsNone(calls[2]["config"])

    def test_explicit_home_and_xdg_config_home_are_preserved(self):
        self.env.update(
            OBSIDIAN_VAULT_PATH="/data/vault",
            HOME="/data/custom-home",
            XDG_CONFIG_HOME="/data/custom-config",
        )
        self.assertEqual(self.run_script().returncode, 0)
        calls = self.calls()
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[2]["home"], "/data/custom-home")
        self.assertEqual(calls[2]["config"], "/data/custom-config")

    def test_already_unprivileged_service_does_not_drop_again(self):
        self.env.update(OBSIDIAN_VAULT_PATH="/data/vault", TEST_UID="10000")
        self.assertEqual(self.run_script().returncode, 0)
        self.assertFalse(any("user" in call for call in self.calls()))
        self.assertTrue(any("ob" in call for call in self.calls()))

    def test_paths_outside_persistent_storage_are_rejected(self):
        for path in ("relative/vault", "/tmp/vault", "/database/vault", "/data", "/data/../tmp/vault"):
            with self.subTest(path=path):
                self.env["OBSIDIAN_VAULT_PATH"] = path
                result = self.run_script()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("[obsidian-sync]", result.stderr)
                self.assertEqual(self.calls(), [])

    def test_sync_exit_is_propagated_and_finish_allows_delayed_restart(self):
        # s6 executes finish after both clean exits and failures; its non-125
        # return permits restart. The host harness does not emulate s6 itself.
        self.env["OBSIDIAN_VAULT_PATH"] = "/data/vault"
        for status in (0, 1, 3):
            with self.subTest(status=status):
                self.env["TEST_OB_EXIT"] = str(status)
                self.assertEqual(self.run_script().returncode, status)
                result = self.run_script("finish", str(status), "0")
                self.assertEqual(result.returncode, 0)
                self.assertIn("retrying in 3 seconds", result.stderr)
                self.assertEqual(self.calls()[-1], {"sleep": ["3"]})

    def test_exec_chain_delivers_sigterm_directly_to_sync(self):
        import time

        self.env.update(OBSIDIAN_VAULT_PATH="/data/vault", TEST_WAIT="1")
        process = subprocess.Popen(
            ["sh", str(SERVICE / "run")], env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            deadline = time.monotonic() + 5
            while not self.ready.exists() and time.monotonic() < deadline:
                if process.poll() is not None:
                    self.fail(f"Service exited early: {process.communicate()}")
                time.sleep(0.01)
            self.assertTrue(self.ready.exists(), "Sync did not start")
            self.assertEqual(self.calls()[-1]["pid"], process.pid)
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertIn("fake ob received SIGTERM", stdout)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_service_is_registered_without_overwriting_upstream_services(self):
        self.assertEqual((SERVICE / "type").read_text().strip(), "longrun")
        self.assertTrue((SERVICE / "dependencies.d/base").is_file())
        self.assertTrue((SERVICE.parent / "user/contents.d/obsidian-sync").is_file())
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("COPY docker/s6-rc.d/ /etc/s6-overlay/s6-rc.d/", dockerfile)
        self.assertIn('CMD ["sleep", "infinity"]', dockerfile)
        self.assertNotIn("\nENTRYPOINT", dockerfile)
        self.assertFalse((SERVICE.parent / "dashboard").exists())
        self.assertFalse((SERVICE.parent / "main-hermes").exists())


@unittest.skipUnless(os.environ.get("OBSIDIAN_TEST_IMAGE"), "requires a built Docker image")
class ObsidianOwnershipIntegrationTests(unittest.TestCase):
    def test_root_created_state_is_reused_without_changing_modes_or_other_files(self):
        # The real CLI lists an existing vault after the service repairs its
        # root-owned private state. A tiny fake handles only continuous sync so
        # this test never connects to a remote vault or needs credentials.
        script = r'''
set -eu
mkdir -p /test-bin
cat > /test-bin/ob <<'SH'
#!/bin/sh
if [ "$1" = sync-list-local ]; then
    exec node /opt/aio-npm/node_modules/obsidian-headless/cli.js "$@"
fi
exit 0
SH
chmod 0755 /test-bin/ob
export PATH=/test-bin:/command:$PATH
export OBSIDIAN_VAULT_PATH='/data/work/My Vault'
python3 - <<'PY'
import json, os
from pathlib import Path
base = Path(os.environ.get('XDG_CONFIG_HOME') or (Path(os.environ['HOME']) / '.config'))
vault = base / 'obsidian-headless/sync/test-vault'
vault.mkdir(parents=True, mode=0o700)
for path in (base, base / 'obsidian-headless', vault.parent, vault):
    path.chmod(0o700)
config = vault / 'config.json'
config.write_text(json.dumps({'vaultPath': os.environ['OBSIDIAN_VAULT_PATH'], 'host': 'sync.example.test'}))
config.chmod(0o600)
other = base / 'other-app'
other.mkdir()
(other / 'state').write_text('untouched')
outside = Path('/data/untouched-state')
outside.write_text('untouched')
(vault / 'outside-link').symlink_to(outside)
notes = Path(os.environ['OBSIDIAN_VAULT_PATH'])
notes.mkdir(parents=True)
notes.parent.chmod(0o700)
notes.chmod(0o700)
(notes / 'existing.md').write_text('root-created note')
(notes / 'existing.md').chmod(0o600)
(notes / 'outside-link').symlink_to(outside)
lock = notes / '.obsidian/.sync.lock'
lock.mkdir(parents=True)
lock.chmod(0o700)
os.utime(lock, (1000000000, 1000000000))
PY
sh /etc/s6-overlay/s6-rc.d/obsidian-sync/run
python3 - <<'PY'
import json, os, pwd, subprocess
from pathlib import Path
base = Path(os.environ.get('XDG_CONFIG_HOME') or (Path(os.environ['HOME']) / '.config'))
vault = base / 'obsidian-headless/sync/test-vault'
uid = pwd.getpwnam('hermes').pw_uid
for path in (base, base / 'obsidian-headless', vault.parent, vault):
    assert path.stat().st_uid == uid, path
    assert path.stat().st_mode & 0o777 == 0o700, path
assert (vault / 'config.json').stat().st_uid == uid
assert (vault / 'config.json').stat().st_mode & 0o777 == 0o600
assert (base / 'other-app/state').stat().st_uid == 0
assert Path('/data/untouched-state').stat().st_uid == 0
assert (vault / 'outside-link').is_symlink()
notes = Path(os.environ['OBSIDIAN_VAULT_PATH'])
assert notes.parent.stat().st_uid == uid
assert notes.stat().st_uid == uid
assert notes.stat().st_mode & 0o777 == 0o700
assert (notes / 'existing.md').stat().st_uid == uid
assert (notes / 'existing.md').stat().st_mode & 0o777 == 0o600
lock = notes / '.obsidian/.sync.lock'
assert lock.stat().st_uid == uid
assert lock.stat().st_mtime == 1000000000
assert (notes / 'outside-link').is_symlink()
subprocess.check_call(['/command/s6-setuidgid', 'hermes', 'python3', '-c',
    'import os, sys; from pathlib import Path; p=Path(sys.argv[1]); '
    '(p / "existing.md").write_text("updated by hermes"); '
    'os.utime(p / ".obsidian/.sync.lock", None)', str(notes)])
result = subprocess.check_output(['/command/s6-setuidgid', 'hermes', 'node',
    '/opt/aio-npm/node_modules/obsidian-headless/cli.js', 'sync-list-local', '--json'], text=True)
assert json.loads(result)['vaults'][0]['path'] == os.environ['OBSIDIAN_VAULT_PATH']
PY
'''
        for config_home in (None, "/data/custom-config"):
            with self.subTest(config_home=config_home):
                args = ["docker", "run", "--rm", "--entrypoint", "sh"]
                if config_home:
                    args += ["-e", f"XDG_CONFIG_HOME={config_home}"]
                args += [os.environ["OBSIDIAN_TEST_IMAGE"], "-c", script]
                result = subprocess.run(args, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
