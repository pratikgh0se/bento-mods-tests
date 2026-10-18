"""autosync.sh contract tests (ACs 29-34 per repo, 66-69; two repos: public + overlay)."""
import os, re, unittest
from msharness import Base

TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3"
SUBJ = re.compile(r"^autosync: \d{4}-\d{2}-\d{2} \((\d+) files\)$")


class AutoBase(Base):
    OVERLAY_GIT = True

    def setUp(self):
        super().setUp()
        s = self.s
        s.basic_home()
        s.use_overlay()
        s.rw("claude/hooks/x.sh", "old\n")
        s.hw(".claude/hooks/x.sh", "old\n")                  # machine == public: export leaves it alone
        self.origin_pub = os.path.join(s.sb, "origin-pub.git")
        self.origin_ov = os.path.join(s.sb, "origin-ov.git")
        for o in (self.origin_pub, self.origin_ov):
            s.sh("git", "init", "-q", "--bare", o, cwd=s.sb)
        r = s.run("export.sh")
        assert r.returncode == 0, r.stdout + r.stderr
        s.git_init(s.repo)
        s.sh("git", "remote", "add", "origin", self.origin_pub, cwd=s.repo)
        s.sh("git", "push", "-q", "-u", "origin", "main", cwd=s.repo)
        if self.OVERLAY_GIT:
            s.git_init(s.ov)
            s.sh("git", "remote", "add", "origin", self.origin_ov, cwd=s.ov)
            s.sh("git", "push", "-q", "-u", "origin", "main", cwd=s.ov)
        open(s.log, "w").close()

    # ---- helpers
    def d(self, which):
        return self.s.repo if which == "pub" else self.s.ov

    def count(self, which="pub"):
        return int(self.s.sh("git", "rev-list", "--count", "HEAD", cwd=self.d(which)).stdout)

    def origin_head(self, which="pub"):
        o = self.origin_pub if which == "pub" else self.origin_ov
        return self.s.sh("git", "--git-dir", o, "rev-parse", "main").stdout.strip()

    def head(self, which="pub"):
        return self.s.sh("git", "rev-parse", "HEAD", cwd=self.d(which)).stdout.strip()

    def subject(self, which="pub"):
        return self.s.sh("git", "log", "-1", "--format=%s", cwd=self.d(which)).stdout.strip()

    def nfiles(self, which="pub"):
        out = self.s.sh("git", "show", "--name-only", "--format=", "HEAD", cwd=self.d(which)).stdout
        return len([l for l in out.splitlines() if l])

    def logtxt(self):
        p = os.path.join(self.s.home, ".local/state/machine-setup/autosync.log")
        if not os.path.exists(p):
            return ""
        with open(p) as f:
            return f.read()

    def osa(self):
        return [c for c in self.s.shim_calls() if c.startswith("osascript")]

    def auto(self, **kw):
        return self.s.run("autosync.sh", **kw)

    def change_overlay(self):
        self.s.hw(".claude/CLAUDE.md", "# changed\n")
        self.s.hw(".claude/hooks/b.sh", "echo b\n")

    def change_public(self):
        self.s.hw(".claude/hooks/x.sh", "new\n")


class TestAutosync(AutoBase):
    def test_ac29_no_changes(self):  # AC 29
        n, m = self.count(), self.count("ov")
        r = self.auto()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertEqual((self.count(), self.count("ov")), (n, m))
        self.assertEqual(self.osa(), [])
        log = self.logtxt()
        self.assertIn("no changes (public)", log)
        self.assertIn("no changes (overlay)", log)
        self.assertRegex(log.splitlines()[0], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d .*start")
        self.assertRegex(log, r"(?m)^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d overlay: %s$" % re.escape(self.s.ov))

    def test_ac30_ac67_changes_in_both(self):  # AC 30, 67
        n, m = self.count(), self.count("ov")
        self.change_overlay()
        self.change_public()
        r = self.auto()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.count(), self.count("ov")), (n + 1, m + 1))
        for w in ("pub", "ov"):
            mm = SUBJ.match(self.subject(w))
            self.assertTrue(mm, self.subject(w))
            self.assertEqual(int(mm.group(1)), self.nfiles(w))
        self.assertEqual(self.origin_head("ov"), self.head("ov"))
        self.assertNotEqual(self.origin_head(), self.head())     # amended by AC 87: public held
        log = self.logtxt()
        for pat in (r"committed \d+ files \(public\)", r"committed \d+ files \(overlay\)",
                    r"pushed \(overlay\)"):
            self.assertRegex(log, pat)
        self.assertNotIn("pushed (public)", log)
        self.assertEqual(len(self.osa()), 1)                     # only the AC 87 review notification
        self.assertEqual(r.stdout, "")

    def test_ac67_only_overlay_changes(self):  # AC 67
        n, m = self.count(), self.count("ov")
        self.change_overlay()
        r = self.auto()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.count(), n)
        self.assertEqual(self.count("ov"), m + 1)
        log = self.logtxt()
        self.assertIn("no changes (public)", log)
        self.assertRegex(log, r"committed \d+ files \(overlay\)")
        self.assertRegex(log, r"pushed \(overlay\)")
        self.assertNotIn("pushed (public)", log)

    def test_ac31_ac68_secret_failure_blocks_both(self):  # AC 31, 68
        n, m, oh, ooh = self.count(), self.count("ov"), self.origin_head(), self.origin_head("ov")
        self.change_overlay()
        self.change_public()
        self.s.hw(".claude/hooks/t.py", "key = %s\n" % TOKEN)
        r = self.auto()
        self.assertEqual(r.returncode, 1)
        self.assertEqual((self.count(), self.count("ov")), (n, m))
        self.assertEqual((self.origin_head(), self.origin_head("ov")), (oh, ooh))
        osa = self.osa()
        self.assertEqual(len(osa), 1, osa)
        self.assertIn("machine-setup: autosync failed (export)", osa[0])
        self.assertIn("FAILED (export)", self.logtxt())

    def test_ac68_leak_failure_blocks_both(self):  # AC 68
        n, m, oh, ooh = self.count(), self.count("ov"), self.origin_head(), self.origin_head("ov")
        self.change_overlay()                                      # overlay would commit
        self.s.hw(".claude/hooks/x.sh", "cd /Users/someone/x\n")   # public generic file gets a leak
        r = self.auto()
        self.assertEqual(r.returncode, 1)
        self.assertEqual((self.count(), self.count("ov")), (n, m))
        self.assertEqual((self.origin_head(), self.origin_head("ov")), (oh, ooh))
        osa = self.osa()
        self.assertEqual(len(osa), 1)
        self.assertIn("autosync failed (export)", osa[0])
        self.assertIn("FAILED (export)", self.logtxt())

    def test_ac32_pull_failure_no_upstream(self):  # AC 32 (public)
        self.s.sh("git", "branch", "--unset-upstream", cwd=self.s.repo)
        n = self.count()
        r = self.auto()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.count(), n)
        self.assertIn("FAILED (pull)", self.logtxt())
        osa = self.osa()
        self.assertEqual(len(osa), 1)
        self.assertIn("(pull)", osa[0])

    def test_ac32_pull_failure_overlay_non_ff(self):  # AC 32 per repo (overlay)
        s = self.s
        other = os.path.join(s.sb, "other")
        s.sh("git", "clone", "-q", self.origin_ov, other, cwd=s.sb)
        s.w(other, "remote.txt", "r\n")
        s.sh("git", "add", "-A", cwd=other)
        s.sh("git", "commit", "-q", "-m", "remote", cwd=other)
        s.sh("git", "push", "-q", "origin", "main", cwd=other)
        s.w(s.ov, "local.txt", "l\n")
        s.sh("git", "add", "-A", cwd=s.ov)
        s.sh("git", "commit", "-q", "-m", "local", cwd=s.ov)
        r = self.auto()
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILED (pull)", self.logtxt())
        self.assertIn("(pull)", self.osa()[0])

    def test_ac33_push_failure_overlay(self):  # AC 33 (overlay only; public is never pushed, AC 87)
        m, ooh = self.count("ov"), self.origin_head("ov")
        self.s.sh("git", "remote", "set-url", "--push", "origin",
                  os.path.join(self.s.sb, "gone.git"), cwd=self.s.ov)
        self.change_overlay()
        r = self.auto()
        self.assertEqual(r.returncode, 1)
        osa = self.osa()
        self.assertEqual(len(osa), 1)
        self.assertIn("(push)", osa[0])
        self.assertIn("FAILED (push)", self.logtxt())
        self.assertEqual(self.count("ov"), m + 1)
        self.assertTrue(self.subject("ov").startswith("autosync:"))
        self.assertEqual(self.origin_head("ov"), ooh)

    def test_ac33_public_broken_push_url_is_irrelevant(self):  # amended: public never pushed
        n, oh = self.count(), self.origin_head()
        self.s.sh("git", "remote", "set-url", "--push", "origin",
                  os.path.join(self.s.sb, "gone.git"), cwd=self.s.repo)
        self.change_public()
        r = self.auto()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("FAILED (push)", self.logtxt())
        self.assertEqual(self.count(), n + 1)
        self.assertEqual(self.origin_head(), oh)

    def test_ac33_push_failure_overlay_with_public_held(self):  # 11.7 one push fails
        m, ooh = self.count("ov"), self.origin_head("ov")
        self.s.sh("git", "remote", "set-url", "--push", "origin",
                  os.path.join(self.s.sb, "gone.git"), cwd=self.s.ov)
        self.change_overlay()
        self.change_public()
        r = self.auto()
        self.assertEqual(r.returncode, 1)
        self.assertTrue(any("(push)" in c for c in self.osa()), self.osa())
        self.assertEqual(self.count("ov"), m + 1)               # local commit stays
        self.assertEqual(self.origin_head("ov"), ooh)
        self.assertNotEqual(self.origin_head(), self.head())    # public held for review (AC 87), not pushed

    def test_ac34_osascript_failure_does_not_change_exit(self):  # AC 34
        s = self.s
        s.set_state("osascript_fail", "1")
        s.hw(".claude/hooks/t.py", "key = %s\n" % TOKEN)
        r = self.auto()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(len(self.osa()), 1)
        os.remove(s.home + "/.claude/hooks/t.py")
        self.change_overlay()
        r = self.auto()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.osa()), 1)                    # no new notification


class TestAuthorGuard(AutoBase):
    def test_ac69_non_noreply_blocks_public_commit(self):  # AC 69
        s = self.s
        s.sh("git", "config", "user.email", "a@corp.org", cwd=s.repo)
        n = self.count()
        self.change_public()
        self.change_overlay()
        r = self.auto()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.count(), n)
        log = self.logtxt()
        self.assertIn("public repo author email is not a noreply address", log)
        self.assertIn("FAILED (commit)", log)
        osa = self.osa()
        self.assertEqual(len(osa), 1)
        self.assertIn("(commit)", osa[0])

    def test_ac69_noreply_commits(self):  # AC 69
        s = self.s
        s.sh("git", "config", "user.email", "1+x@users.noreply.github.com", cwd=s.repo)
        n = self.count()
        self.change_public()
        r = self.auto()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.count(), n + 1)

    def test_ac69_noreply_check_is_suffix_based(self):  # 11.7 "must end in"
        s = self.s
        s.sh("git", "config", "user.email", "x@users.noreply.github.com.evil.org", cwd=s.repo)
        n = self.count()
        self.change_public()
        r = self.auto()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.count(), n)


class TestOverlayNotGit(AutoBase):
    OVERLAY_GIT = False

    def test_overlay_not_a_git_repo(self):  # 11.7
        n = self.count()
        self.change_public()
        self.change_overlay()
        r = self.auto()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("overlay is not a git repo; skipping its git steps", self.logtxt())
        self.assertEqual(self.count(), n + 1)
        self.assertNotEqual(self.origin_head(), self.head())     # public never pushed (AC 87)


class TestNoOverlay(Base):
    def test_ac66_no_overlay_noop(self):  # AC 66
        s = self.s
        s.basic_home()
        s.git_init(s.repo)
        origin = os.path.join(s.sb, "o.git")
        s.sh("git", "init", "-q", "--bare", origin, cwd=s.sb)
        s.sh("git", "remote", "add", "origin", origin, cwd=s.repo)
        s.sh("git", "push", "-q", "-u", "origin", "main", cwd=s.repo)
        n = int(s.sh("git", "rev-list", "--count", "HEAD", cwd=s.repo).stdout)
        before_pub = s.snapshot(s.repo)
        for priv in ("none", None):
            open(s.log, "w").close()
            r = s.run("autosync.sh", priv=priv)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(r.stdout, "")
            with open(os.path.join(s.home, ".local/state/machine-setup/autosync.log")) as f:
                self.assertIn("no overlay configured; nothing to sync", f.read())
            self.assertEqual(int(s.sh("git", "rev-list", "--count", "HEAD", cwd=s.repo).stdout), n)
            self.assertEqual([c for c in s.shim_calls() if c.startswith("osascript")], [])
        self.assertEqual(before_pub, s.snapshot(s.repo))


if __name__ == "__main__":
    unittest.main()
