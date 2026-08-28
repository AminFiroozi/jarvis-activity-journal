import subprocess
import tempfile
import unittest
from pathlib import Path

from src.project_evidence import collect_project_event


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True)


class CollectProjectEventTests(unittest.TestCase):
    def test_returns_none_without_git_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(collect_project_event(Path(directory)))

    def test_reads_branch_and_latest_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _run("init", "-q", cwd=root)
            _run("config", "user.email", "a@b.c", cwd=root)
            _run("config", "user.name", "Test", cwd=root)
            (root / "file.txt").write_text("hello", encoding="utf-8")
            _run("add", ".", cwd=root)
            _run("commit", "-q", "-m", "initial commit", cwd=root)

            event = collect_project_event(root)

            self.assertIsNotNone(event)
            self.assertEqual(event["source"], "git-project")
            self.assertEqual(event["latestCommitMessage"], "initial commit")
            self.assertEqual(event["changedFileCount"], 0)


if __name__ == "__main__":
    unittest.main()
