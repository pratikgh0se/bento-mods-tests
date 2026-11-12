"""AC 159 (F42.4 amendment 2026-11-09): `--ledger-maintain <path>` input checks run first.
Black-box: nonexistent path / regular file -> stderr `ledger-maintain: no such directory: <path>`, exit 2, nothing created;
existing dir without a ledger -> stdout `no ledger for <dir>`, exit 0, nothing created; existing ledger still works."""
import os, re, subprocess, sys
import test_f42_lossless_rules as _f42
from helpers import PRE


class MaintainBadDir(_f42.F42):
    def snapshot(self):
        """(dirs, {file: bytes}) of the handoffs dir tree; empty when it does not exist."""
        dirs, files = [], {}
        for root, ds, fs in os.walk(self.hd):
            dirs.append(os.path.relpath(root, self.hd))
            for f in fs:
                p = os.path.join(root, f)
                files[os.path.relpath(p, self.hd)] = open(p, "rb").read()
        return sorted(dirs), files

    def run_maintain(self, arg):
        return subprocess.run([sys.executable, PRE, "--ledger-maintain", arg], input="", capture_output=True,
                              text=True, env=self.env(None), timeout=60, cwd=self.tmp)

    def assert_untouched_and_uncalled(self, before):
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.shim_invoked())
        self.assertEqual(self.merge_calls(), 0)
        self.assertEqual(self.projects(), [])

    def test_ac159_nonexistent_path(self):
        path = os.path.join(self.rt, "no", "such", "dir")
        before = self.snapshot()
        r = self.run_maintain(path)
        self.assertEqual(r.stderr, "ledger-maintain: no such directory: %s\n" % path)
        self.assertEqual(r.stdout, "")
        self.assertEqual(r.returncode, 2)
        self.assert_untouched_and_uncalled(before)
        self.assertFalse(os.path.exists(path))

    def test_ac159_nonexistent_path_as_given_relative(self):
        before = self.snapshot()
        r = self.run_maintain("mistyped-portfolio")
        self.assertEqual(r.stderr, "ledger-maintain: no such directory: mistyped-portfolio\n")
        self.assertEqual((r.stdout, r.returncode), ("", 2))
        self.assert_untouched_and_uncalled(before)

    def test_ac159_nonexistent_path_with_seeded_ledger_elsewhere(self):
        self.seed(["- D1 [2026-10-20] Never ship on Friday | why: rule"])
        path = os.path.join(self.rt, "typo")
        before = self.snapshot()
        r = self.run_maintain(path)
        self.assertEqual(r.stderr, "ledger-maintain: no such directory: %s\n" % path)
        self.assertEqual((r.stdout, r.returncode), ("", 2))
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.shim_invoked())

    def test_ac159_regular_file(self):
        path = os.path.join(self.rt, "afile.txt")
        with open(path, "w") as f:
            f.write("x")
        before = self.snapshot()
        r = self.run_maintain(path)
        self.assertEqual(r.stderr, "ledger-maintain: no such directory: %s\n" % path)
        self.assertEqual(r.stdout, "")
        self.assertEqual(r.returncode, 2)
        self.assert_untouched_and_uncalled(before)
        self.assertEqual(open(path).read(), "x")

    def test_ac159_existing_dir_without_ledger(self):
        d = os.path.join(self.rt, "fresh")
        os.makedirs(d)
        subprocess.run(["git", "init", "-q", d], check=True, capture_output=True)
        before = self.snapshot()
        r = self.run_maintain(d)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(r.stdout.rstrip("\n"), "no ledger for %s" % d)
        self.assert_untouched_and_uncalled(before)

    def test_ac159_existing_dir_without_ledger_subdir_of_repo(self):
        # the repo of F39.setUp has no ledger seeded; key resolves to the repo root
        before = self.snapshot()
        r = self.run_maintain(self.cwd)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(r.stdout.rstrip("\n"), "no ledger for %s" % self.cwd)
        self.assert_untouched_and_uncalled(before)
        self.assertFalse(os.path.exists(os.path.join(self.pdir(), "decisions.lock")))

    def test_ac159_no_ledger_folder_present_but_no_decisions_md(self):
        # a project folder without decisions.md counts as no ledger and is left as found (no lock created)
        os.makedirs(self.pdir())
        before = self.snapshot()
        r = self.run_maintain(self.repo_root)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(r.stdout.rstrip("\n"), "no ledger for %s" % self.repo_root)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.shim_invoked())

    def test_ac159_existing_ledger_still_works(self):
        self.seed(["- D1 [2026-10-20] Never ship on Friday | why: rule", "- D2 [2026-10-21] Approve release 1.2 | why: ok"])
        self.set_shim("merge", out="RESOLVE D2: done\n")
        self.set_shim("summary", out="RESOLVE D2: done\n")
        r = self.run_maintain(self.cwd)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertRegex(r.stdout.strip(), r"^kind=0 resolved=1 superseded=0 active_before=2 active_after=1$")
        self.assertTrue(self.shim_invoked() or self.merge_calls() > 0)
