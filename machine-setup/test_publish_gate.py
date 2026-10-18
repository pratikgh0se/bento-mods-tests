"""Public push gate contract tests (ACs 87-90): autosync never pushes the public repo;
setup/publish.sh publishes after review."""
import os, unittest
from test_autosync import AutoBase, SUBJ
from msharness import MS_REPO

LEAK = "cd /Users/someone/x\n"


class GateBase(AutoBase):
    def upstream_count(self):
        return int(self.s.sh("git", "rev-list", "--count", "@{u}..HEAD", cwd=self.s.repo).stdout)

    def local_commit(self, content="local edit\n", name="claude/hooks/x.sh", msg="manual: edit"):
        s = self.s
        s.rw(name, content)
        s.sh("git", "add", "-A", cwd=s.repo)
        s.sh("git", "commit", "-q", "-m", msg, cwd=s.repo)

    def pub(self, *args, **kw):
        return self.s.run("publish.sh", *args, **kw)

    def review_notes(self):
        return [c for c in self.osa() if "awaiting review" in c]


class TestAc87(GateBase):
    def test_ac87_public_change_commits_locally_not_pushed(self):  # AC 87
        n, oh = self.count(), self.origin_head()
        m = self.count("ov")
        self.change_public()
        self.change_overlay()
        r = self.auto()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.count(), n + 1)
        mm = SUBJ.match(self.subject())
        self.assertTrue(mm, self.subject())
        self.assertEqual(int(mm.group(1)), self.nfiles())
        self.assertEqual(self.origin_head(), oh)
        k = self.upstream_count()
        self.assertEqual(k, 1)
        log = self.logtxt()
        self.assertIn("committed %d files (public)" % self.nfiles(), log)
        self.assertIn("public push held for review (%d unpushed)" % k, log)
        self.assertNotIn("pushed (public)", log)
        self.assertEqual(self.count("ov"), m + 1)
        self.assertEqual(self.origin_head("ov"), self.head("ov"))
        self.assertIn("pushed (overlay)", log)

    def test_ac87_one_notification_with_text_and_title(self):  # AC 87
        self.change_public()
        self.change_overlay()
        r = self.auto()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        osa = self.osa()
        self.assertEqual(len(osa), 1, osa)
        k = self.upstream_count()
        self.assertIn("machine-setup: %d public commit(s) awaiting review" % k, osa[0])
        self.assertIn("machine-setup", osa[0])

    def test_ac87_public_only_change(self):  # AC 87
        oh = self.origin_head()
        self.change_public()
        r = self.auto()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.origin_head(), oh)
        self.assertEqual(len(self.review_notes()), 1)


class TestAc88(GateBase):
    def test_ac88_earlier_unpushed_commits_held_and_notified(self):  # AC 88
        self.local_commit("a\n", name="NOTES-a.txt")
        self.local_commit("b\n", name="NOTES-b.txt", msg="manual: second")
        n, oh = self.count(), self.origin_head()
        k = self.upstream_count()
        self.assertEqual(k, 2)
        self.change_overlay()
        r = self.auto()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.count(), n)
        self.assertEqual(self.origin_head(), oh)
        self.assertIn("public push held for review (%d unpushed)" % k, self.logtxt())
        notes = self.osa()
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("machine-setup: %d public commit(s) awaiting review" % k, notes[0])

    def test_ac88_no_changes_with_unpushed_still_notifies(self):  # AC 88
        self.local_commit("a\n", name="NOTES-a.txt")
        r = self.auto()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("public push held for review (1 unpushed)", self.logtxt())
        self.assertEqual(len(self.review_notes()), 1)

    def test_ac88_zero_unpushed_no_line_no_notification(self):  # AC 88
        self.change_overlay()
        r = self.auto()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("held for review", self.logtxt())
        self.assertEqual(self.osa(), [])
        self.auto()
        self.assertNotIn("held for review", self.logtxt())
        self.assertEqual(self.osa(), [])


class TestAc89(GateBase):
    def test_nothing_to_publish(self):  # AC 89
        oh = self.origin_head()
        r = self.pub()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("nothing to publish", r.stdout)
        self.assertEqual(self.origin_head(), oh)

    def test_nothing_to_publish_with_push_flag(self):  # AC 89 (literal: K = 0)
        oh = self.origin_head()
        r = self.pub("--push")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("nothing to publish", r.stdout)
        self.assertEqual(self.origin_head(), oh)

    def test_no_args_shows_review_and_pushes_nothing(self):  # AC 89
        self.local_commit(msg="manual: reviewable-subject")
        oh = self.origin_head()
        r = self.pub()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("reviewable-subject", r.stdout)
        self.assertRegex(r.stdout, r"claude/hooks/x\.sh\s*\|")
        self.assertRegex(r.stdout, r"1 file changed")
        self.assertIn("run setup/publish.sh --push to publish", r.stdout)
        self.assertEqual(self.origin_head(), oh)
        self.assertEqual(self.upstream_count(), 1)

    def test_push_publishes(self):  # AC 89
        self.local_commit()
        self.local_commit("two\n", msg="manual: two")
        r = self.pub("--push")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("published 2 commit(s)", r.stdout)
        self.assertEqual(self.origin_head(), self.head())
        self.assertEqual(self.upstream_count(), 0)

    def test_push_after_autosync_flow(self):  # AC 87 + 89 end to end
        self.change_public()
        self.assertEqual(self.auto().returncode, 0)
        self.assertNotEqual(self.origin_head(), self.head())
        r = self.pub("--push")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.origin_head(), self.head())

    def test_push_blocked_by_leak_scan(self):  # AC 89
        self.local_commit(LEAK, msg="manual: leaky")
        oh = self.origin_head()
        r = self.pub("--push")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.origin_head(), oh)
        self.assertNotIn("published", r.stdout)
        self.assertIn("claude/hooks/x.sh", r.stdout + r.stderr)

    def test_clean_commit_passes_scan(self):  # AC 89
        self.local_commit("clean change\n", msg="manual: clean")
        r = self.pub("--push")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_push_failure_exits_1(self):  # AC 89
        self.local_commit()
        self.s.sh("git", "remote", "set-url", "--push", "origin",
                  os.path.join(self.s.sb, "gone.git"), cwd=self.s.repo)
        r = self.pub("--push")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("published", r.stdout)
        self.assertTrue(r.stderr.strip() or "gone.git" in r.stdout)

    def test_never_touches_overlay(self):  # AC 89
        self.local_commit()
        ov_head, ov_origin = self.head("ov"), self.origin_head("ov")
        snap = self.s.snapshot(self.s.ov)
        for args in ((), ("--push",)):
            self.pub(*args)
        self.assertEqual(self.head("ov"), ov_head)
        self.assertEqual(self.origin_head("ov"), ov_origin)
        self.assertEqual(snap, self.s.snapshot(self.s.ov))

    def test_unknown_argument_usage_exit_2(self):  # AC 89
        self.local_commit()
        oh = self.origin_head()
        r = self.pub("--bogus")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertTrue(r.stderr.strip())
        self.assertEqual(self.origin_head(), oh)


class TestAc90(unittest.TestCase):
    def test_readmes_mention_publish_push(self):  # AC 90
        for rel in ("README.md", "setup/README.md"):
            with open(os.path.join(MS_REPO, rel)) as f:
                self.assertIn("setup/publish.sh --push", f.read(), rel)


if __name__ == "__main__":
    unittest.main()
