"""Exercise the native persistence shell against local Git repositories only."""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import unittest


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/a1-external-research-exact8-through-a3-v1.yml"
)
STATE = "backend/research/prep/a1_external_research_exact8_forward_state_v1.json"


def native_persist_script():
    text = WORKFLOW.read_text()
    block = text.split("      - name: Persist append-only forward source state\n", 1)[1]
    block = block.split("      - uses: actions/upload-artifact@v4\n", 1)[0]
    return textwrap.dedent(block.split("        run: |\n", 1)[1])


class Exact8StoragePersistenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.writer = self.root / "writer"
        self.other = self.root / "other"
        self.real_git = shutil.which("git")
        self.assertIsNotNone(self.real_git)
        self.git(
            self.root, "init", "--bare", "--initial-branch=master", str(self.remote)
        )
        self.git(self.root, "clone", str(self.remote), str(self.writer))
        self.configure(self.writer)
        self.initial = b'{"fixture_state": "original"}\n'
        self.generated = b'{"fixture_state": "generated", "formal_credit": 0}\n'
        state = self.writer / STATE
        state.parent.mkdir(parents=True)
        state.write_bytes(self.initial)
        self.git(self.writer, "add", STATE)
        self.git(self.writer, "commit", "-m", "initial fixture")
        self.git(self.writer, "push", "origin", "HEAD:master")
        self.git(self.root, "clone", str(self.remote), str(self.other))
        self.configure(self.other)

    def git(self, directory, *args):
        result = subprocess.run(
            [self.real_git, "-C", str(directory), *args],
            capture_output=True,
            text=True,
            check=False,
            env={
                **os.environ,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
            },
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip()

    def configure(self, directory):
        self.git(directory, "config", "user.name", "offline fixture")
        self.git(directory, "config", "user.email", "fixture@invalid")

    def remote_bytes(self, path=STATE):
        return subprocess.check_output(
            [self.real_git, "--git-dir", str(self.remote), "show", f"master:{path}"]
        )

    def other_commit(self, path, contents):
        target = self.other / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
        self.git(self.other, "add", path)
        self.git(self.other, "commit", "-m", "other writer fixture")
        self.git(self.other, "push", "origin", "HEAD:master")

    def run_native(self, race_count=0):
        env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        if race_count:
            shim = self.root / "shim"
            shim.mkdir()
            wrapper = shim / "git"
            wrapper.write_text(
                "#!/bin/bash\nset -euo pipefail\n"
                'if [ "${1:-}" = push ] && [ "${2:-}" = origin ]; then\n'
                '  count=0; if [ -f "$EXACT8_FIXTURE_COUNTER" ]; then read -r count < "$EXACT8_FIXTURE_COUNTER"; fi\n'
                '  count=$((count + 1)); printf \'%s\\n\' "$count" > "$EXACT8_FIXTURE_COUNTER"\n'
                '  if [ "$count" -le "$EXACT8_FIXTURE_RACES" ]; then\n'
                f'    {shlex.quote(self.real_git)} -C "$EXACT8_FIXTURE_OTHER" pull --ff-only origin master\n'
                '    printf \'%s\\n\' "$count" > "$EXACT8_FIXTURE_OTHER/race.txt"\n'
                f'    {shlex.quote(self.real_git)} -C "$EXACT8_FIXTURE_OTHER" add race.txt\n'
                f'    {shlex.quote(self.real_git)} -C "$EXACT8_FIXTURE_OTHER" commit -m "race $count"\n'
                f'    {shlex.quote(self.real_git)} -C "$EXACT8_FIXTURE_OTHER" push origin HEAD:master\n'
                "  fi\nfi\n"
                f'exec {shlex.quote(self.real_git)} "$@"\n'
            )
            wrapper.chmod(0o755)
            env.update(
                PATH=str(shim) + os.pathsep + env.get("PATH", ""),
                EXACT8_FIXTURE_COUNTER=str(self.root / "push-count"),
                EXACT8_FIXTURE_RACES=str(race_count),
                EXACT8_FIXTURE_OTHER=str(self.other),
            )
        return subprocess.run(
            ["bash", "-c", native_persist_script()],
            cwd=self.writer,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_unrelated_remote_commit_preserves_generated_state_and_other_writer(self):
        (self.writer / STATE).write_bytes(self.generated)
        self.other_commit("unrelated.txt", b"preserved\n")
        result = self.run_native()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.remote_bytes(), self.generated)
        self.assertEqual(self.remote_bytes("unrelated.txt"), b"preserved\n")
        self.assertEqual(
            self.git(
                self.writer, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
            ),
            STATE,
        )

    def test_same_state_remote_change_is_not_merged_or_overwritten(self):
        (self.writer / STATE).write_bytes(self.generated)
        foreign = b'{"fixture_state": "another owner"}\n'
        self.other_commit(STATE, foreign)
        remote_head = self.git(self.other, "rev-parse", "HEAD")
        result = self.run_native()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HOLD_EXACT8_REMOTE_STATE_CHANGED", result.stdout)
        self.assertEqual(self.remote_bytes(), foreign)
        self.assertEqual(self.git(self.remote, "rev-parse", "master"), remote_head)
        self.assertEqual((self.writer / STATE).read_bytes(), self.generated)

    def test_push_time_race_retries_same_generated_bytes_without_recomputing(self):
        (self.writer / STATE).write_bytes(self.generated)
        result = self.run_native(race_count=1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.root / "push-count").read_text().strip(), "2")
        self.assertEqual(self.remote_bytes(), self.generated)
        self.assertEqual(self.remote_bytes("race.txt"), b"1\n")

    def test_repeated_push_races_stop_after_three_attempts_and_retain_bytes(self):
        (self.writer / STATE).write_bytes(self.generated)
        result = self.run_native(race_count=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HOLD_EXACT8_PERSIST_RETRY_EXHAUSTED", result.stdout)
        self.assertEqual((self.root / "push-count").read_text().strip(), "3")
        self.assertEqual(self.remote_bytes(), self.initial)
        self.assertEqual((self.writer / STATE).read_bytes(), self.generated)

    def test_no_state_delta_creates_no_commit_or_push(self):
        original = self.git(self.writer, "rev-parse", "HEAD")
        result = self.run_native()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("NO_STATE_DELTA", result.stdout)
        self.assertEqual(self.git(self.writer, "rev-parse", "HEAD"), original)
        self.assertEqual(self.git(self.remote, "rev-parse", "master"), original)

    def test_final_receipt_upload_runs_even_after_persist_failure(self):
        workflow = WORKFLOW.read_text()
        block = workflow.split(
            "      - name: Persist append-only forward source state\n", 1
        )[1]
        upload = block.split("      - uses: actions/upload-artifact@v4\n", 1)[1]
        upload = upload.split("      - name: Upsert compact status on issue 566\n", 1)[
            0
        ]
        self.assertIn("        if: always()\n", upload)
        self.assertIn("out/a1_external_research_exact8_through_a3_v1.json", upload)
        self.assertIn(STATE, upload)
        self.assertNotIn("--force", native_persist_script())


if __name__ == "__main__":
    unittest.main()
