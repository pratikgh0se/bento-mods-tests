"""run.sh orchestration, report + notification: AC 26-31, 38, 40, 41."""
import json
import os
import re
import subprocess
import unittest

from tbharness import *  # noqa

W42_NOW = "2026-10-12T09:00:03Z"
REPORT_REL = os.path.join("Reports", "Token Budget 2026-W43.md")
H2_ORDER = ["For future agent", "Headline", "Breakdown", "Spend breakdown", "Regressions",
            "Proposals", "Applied since last report", "Measurement notes"]


def split_frontmatter(text):
    assert text.startswith("---\n"), "report must start with frontmatter"
    end = text.index("\n---\n", 4)
    fm = {}
    for line in text[4:end].splitlines():
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2)
    return fm, text[end + 5:]


class RunBase(Base):
    def report_path(self):
        return os.path.join(self.env.vault, REPORT_REL)

    def report(self):
        return read(self.report_path()).decode()

    def full_run(self, *args, **kw):
        return self.env.run_sh(*args, **kw)

    def two_runs(self, first_ctx, second_ctx, notify="0"):
        """W42 run then W43 run, each with its own /context capture."""
        self.env.set_context(first_ctx)
        p = self.env.run_sh(now=W42_NOW)
        self.assertExit(p, 0, "first run")
        self.env.set_context(second_ctx)
        return self.env.run_sh(now=NOW, notify=notify)

    def notify_lines(self, p):
        return [l for l in p.stdout.splitlines() if l.startswith("NOTIFY: ")]


class TestReport(RunBase):
    def test_ac26_report_structure(self):
        """AC26"""
        p = self.full_run()
        self.assertExit(p, 0)
        self.assertTrue(os.path.isfile(self.report_path()), os.listdir(self.env.vault))
        text = self.report()
        fm, body = split_frontmatter(text)
        for k in ("type", "date", "week", "tags"):
            self.assertIn(k, fm)
        self.assertEqual(fm["type"], "report")
        self.assertEqual(fm["week"], "2026-W43")
        self.assertEqual(fm["date"], "2026-10-19")
        self.assertEqual(fm["overhead_tokens"], "28700")
        h2 = re.findall(r"^## (.+?)\s*$", body, flags=re.M)
        self.assertEqual(h2[0], "For future agent")
        self.assertEqual(h2, H2_ORDER)
        self.assertIn("[[Bento]]", body)
        self.assertRegex(body, r"\(as of \d{4}-\d{2}-\d{2}\)")
        self.assertIn("<!-- token-budget:begin -->", text)
        self.assertIn("<!-- token-budget:end -->", text)
        self.assertLess(text.index("<!-- token-budget:begin -->"), text.index("## Headline"))
        self.assertLess(text.index("## Measurement notes"), text.index("<!-- token-budget:end -->"))
        self.assertGreater(text.index("<!-- token-budget:begin -->"), text.index("## For future agent"))

    def test_ac26_reports_dir_created_when_absent(self):
        """4.3: Create Reports/ if absent"""
        self.assertFalse(os.path.exists(os.path.join(self.env.vault, "Reports")))
        self.assertExit(self.full_run(), 0)
        self.assertTrue(os.path.isdir(os.path.join(self.env.vault, "Reports")))

    def test_ac27_baseline_headline(self):
        """AC27: first run shows (baseline) in place of the delta"""
        p = self.full_run(extra={"CLAUDE_SETTINGS_FILE": self.env.settings,
                                 "TOKEN_BUDGET_CCUSAGE_BIN": "/nonexistent/ccusage"})
        self.assertExit(p, 0)
        text = self.report()
        m = re.search(r"^overhead 28\.7k \(baseline\), spend n/a, (\d+) proposals?", text, flags=re.M)
        self.assertIsNotNone(m, text)
        fm, _ = split_frontmatter(text)
        self.assertEqual(int(fm["proposals"]), int(m.group(1)))

    def test_ac27_headline_delta_down(self):
        """AC27: 'overhead 28.7k (-1.6k), spend ..., N proposals' for fixture values"""
        self.env.set_context(CTX_BEFORE)
        extra = {"TOKEN_BUDGET_CCUSAGE_BIN": "/nonexistent/ccusage"}
        self.assertExit(self.env.run_sh(now=W42_NOW, extra=extra), 0)
        self.env.set_context(CTX_AFTER2)
        p = self.env.run_sh(now=NOW, extra=extra)
        self.assertExit(p, 0)
        text = self.report()
        m = re.search(r"^overhead 28\.7k \(-1\.6k\), spend n/a, (\d+) proposals?", text, flags=re.M)
        self.assertIsNotNone(m, text)
        fm, _ = split_frontmatter(text)
        self.assertEqual(fm["delta_tokens"], "-1600")
        self.assertEqual(int(fm["proposals"]), int(m.group(1)))

    def test_ac27_headline_delta_up_uses_ascii_plus(self):
        """AC27: sign is ASCII +/-"""
        p = self.two_runs(CTX_AFTER2, CTX_BEFORE)
        self.assertExit(p, 0)
        text = self.report()
        self.assertRegex(text, r"(?m)^overhead 30\.3k \(\+1\.6k\), spend ")

    def test_ac28_rerun_preserves_outside_and_replaces_inside(self):
        """AC28"""
        os.makedirs(os.path.dirname(self.report_path()))
        write(self.report_path(),
              "---\ntype: report\n---\n# My own title\n\nHAND-WRITTEN-ABOVE\n\n"
              "<!-- token-budget:begin -->\nSTALE-INSIDE-CONTENT\n<!-- token-budget:end -->\n\n"
              "HAND-WRITTEN-BELOW\n")
        self.assertExit(self.full_run(), 0)
        t = self.report()
        self.assertIn("HAND-WRITTEN-ABOVE", t)
        self.assertIn("HAND-WRITTEN-BELOW", t)
        self.assertIn("# My own title", t)
        self.assertNotIn("STALE-INSIDE-CONTENT", t)
        self.assertEqual(t.count("<!-- token-budget:begin -->"), 1)
        self.assertEqual(t.count("<!-- token-budget:end -->"), 1)
        self.assertEqual(t.count("## Headline"), 1)
        self.assertLess(t.index("HAND-WRITTEN-ABOVE"), t.index("<!-- token-budget:begin -->"))
        self.assertGreater(t.index("HAND-WRITTEN-BELOW"), t.index("<!-- token-budget:end -->"))

    def test_ac28_second_generation_does_not_duplicate_sections(self):
        """AC28: run twice (second forced) -> still one of each section; outside edits survive"""
        self.assertExit(self.full_run(), 0)
        t = self.report()
        t = t.replace("<!-- token-budget:end -->", "<!-- token-budget:end -->\n\nMY-NOTES-AFTER\n")
        write(self.report_path(), t)
        self.assertExit(self.full_run("--force"), 0)
        t2 = self.report()
        self.assertIn("MY-NOTES-AFTER", t2)
        for h in H2_ORDER:
            self.assertEqual(len(re.findall(r"^## %s\s*$" % re.escape(h), t2, flags=re.M)), 1, h)
        self.assertEqual(t2.count("<!-- token-budget:begin -->"), 1)

    def test_ac29_vault_unset_exit_0_no_file_anywhere(self):
        """AC29"""
        p = self.full_run(vault=False)
        self.assertExit(p, 0)
        self.assertEqual(self.find_reports(), [])
        self.assertEqual(len(self.env.ledger()), 1, "measurement itself still happens")

    def test_ac29_vault_missing_dir_exit_0_no_file_anywhere(self):
        """AC29"""
        missing = os.path.join(self.env.root, "no-such-vault")
        p = self.full_run(extra={"OBSIDIAN_VAULT_PATH": missing})
        self.assertExit(p, 0)
        self.assertFalse(os.path.exists(missing))
        self.assertEqual(self.find_reports(), [])

    def find_reports(self):
        hits = []
        for d, dirs, files in os.walk(self.env.root):
            for f in files:
                if f.startswith("Token Budget") and f.endswith(".md"):
                    hits.append(os.path.join(d, f))
            if "Reports" in dirs:
                hits.append(os.path.join(d, "Reports"))
        return hits

    def test_ac30_notify_zero_prints_one_line_and_never_calls_osascript(self):
        """AC30"""
        p = self.full_run(notify="0")
        self.assertExit(p, 0)
        lines = self.notify_lines(p)
        self.assertEqual(len(lines), 1, p.stdout)
        self.assertRegex(lines[0], r"^NOTIFY: (REGRESSION: )?overhead 28\.7k \(baseline\), spend n/a|"
                                   r"^NOTIFY: (REGRESSION: )?overhead 28\.7k \(baseline\), spend \$")
        self.assertEqual([c for c in self.env.shim_calls() if c.startswith("osascript")], [])

    def test_ac30_notify_line_carries_report_headline(self):
        """AC30: the NOTIFY text is the headline"""
        p = self.full_run(extra={"TOKEN_BUDGET_CCUSAGE_BIN": "/nonexistent/ccusage"})
        self.assertExit(p, 0)
        line = self.notify_lines(p)[0]
        m = re.search(r"overhead 28\.7k \(baseline\), spend n/a, \d+ proposals?", line)
        self.assertIsNotNone(m, line)
        self.assertIn(m.group(0), self.report())

    def test_ac30_regression_prefix_in_notification(self):
        """4.3: if regressions exist, prefix the headline with 'REGRESSION: '"""
        p = self.two_runs(CTX_AFTER2, CTX_BEFORE)   # +1600 > 1000
        self.assertExit(p, 0)
        lines = self.notify_lines(p)
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r"^NOTIFY: REGRESSION: overhead 30\.3k \(\+1\.6k\)")

    def test_notify_one_calls_osascript_display_notification(self):
        """4.3: osascript -e 'display notification ... with title \"Token Budget <week>\"'"""
        p = self.full_run(notify="1")
        self.assertExit(p, 0)
        self.assertEqual(self.notify_lines(p), [])
        calls = [c for c in self.env.shim_calls() if c.startswith("osascript")]
        self.assertEqual(len(calls), 1, calls)
        self.assertIn("display notification", calls[0])
        self.assertIn('with title "Token Budget 2026-W43"', calls[0])
        self.assertIn("overhead 28.7k", calls[0])

    def test_ac31_vault_git_state_untouched(self):
        """AC31 (see SPEC-GAPS: untracked new report would change `git status`; we compare .git and log)"""
        def git(*a):
            return subprocess.run(["git", "-C", self.env.vault] + list(a), capture_output=True,
                                  text=True, env={"PATH": os.environ["PATH"], "HOME": self.env.home,
                                                  "GIT_CONFIG_NOSYSTEM": "1"})
        self.assertEqual(git("init", "-q").returncode, 0)
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "t")
        write(os.path.join(self.env.vault, "note.md"), "hello")
        git("add", "note.md")
        self.assertEqual(git("commit", "-q", "-m", "init").returncode, 0)
        log_before = git("log", "--all", "--format=%H %s").stdout
        gitdir = os.path.join(self.env.vault, ".git")
        tree_before = file_tree(gitdir)
        self.assertExit(self.full_run(), 0)
        self.assertTrue(os.path.isfile(self.report_path()))
        self.assertEqual(git("log", "--all", "--format=%H %s").stdout, log_before)
        self.assertEqual(file_tree(gitdir), tree_before)
        self.assertEqual(git("status", "--porcelain").stdout.strip(), "?? Reports/")


class TestReportCapAndNames(RunBase):
    def setup_skills(self, n, names=None):
        names = names or ["capskill-%02d" % i for i in range(n)]
        skills = [(nm, "User", "~%d" % (200 + i)) for i, nm in enumerate(names)]
        self.env.set_context(make_context(BASIC_ROWS, skills=skills))
        self.env.set_settings({"env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "400000"}})
        write(os.path.join(self.env.claude_home, "projects", "-p", "old.jsonl"),
              json.dumps({"type": "user", "timestamp": ago(60),
                          "message": {"role": "user", "content": "hi"}}) + "\n")
        return names

    def proposals_section(self):
        t = read(os.path.join(self.env.vault, REPORT_REL)).decode()
        a = t.index("## Proposals")
        b = t.index("## Applied since last report")
        return t[a:b]

    def table_rows(self, sec):
        rows = [l for l in sec.splitlines() if l.startswith("|")]
        return rows[2:]       # drop header + separator

    def test_cap_25_proposals_gives_20_rows_and_more_line(self):
        """4.3: at most top 20 rows, then `+N more in proposals/<week>.json`"""
        self.setup_skills(25)
        self.assertExit(self.env.run_sh(), 0)
        sec = self.proposals_section()
        self.assertEqual(len(self.table_rows(sec)), 20, sec)
        self.assertRegex(sec, r"(?m)^\+5 more in proposals/2026-W43\.json\s*$")
        self.assertIn("skill-desc-long-capskill-24", sec)
        self.assertNotIn("skill-desc-long-capskill-00", sec)

    def test_cap_exactly_20_proposals_has_no_more_line(self):
        """4.3"""
        self.setup_skills(20)
        self.assertExit(self.env.run_sh(), 0)
        sec = self.proposals_section()
        self.assertEqual(len(self.table_rows(sec)), 20, sec)
        self.assertNotRegex(sec, r"(?m)^\+\d+ more")

    def test_skill_names_unredacted_in_report_and_manifest(self):
        """8 redaction: names like planning-and-task-breakdown / design-tokens survive in manifest, proposals, report"""
        self.setup_skills(2, ["planning-and-task-breakdown", "design-tokens"])
        self.assertExit(self.env.run_sh(), 0)
        rep = read(os.path.join(self.env.vault, REPORT_REL)).decode()
        prop = read(self.env.p("proposals", "2026-W43.json")).decode()
        man = read(self.env.p(self.env.ledger()[0]["manifest"])).decode()
        for n in ("planning-and-task-breakdown", "design-tokens"):
            self.assertIn("skill-desc-long-" + n, rep)
            self.assertIn(n, prop)
            self.assertIn(n, man)
        self.assertNotIn("skill-desc-long-[REDACTED]", rep + prop)


class TestRunOrchestration(RunBase):
    def test_last_run_marker_and_log(self):
        """4.5"""
        p = self.full_run()
        self.assertExit(p, 0)
        lr = json.loads(read(self.env.p("last-run.json")))
        self.assertEqual(lr["status"], "ok")
        self.assertEqual(lr["exit"], 0)
        self.assertEqual(lr["week"], "2026-W43")
        self.assertEqual(lr["ts"][:10], "2026-10-19")
        self.assertTrue(os.path.isdir(self.env.p("logs")))

    def test_probe_failure_exit_10_and_notification(self):
        """4.5 exit 10 + section 6: 'Token Budget failed: probe'"""
        p = self.full_run(extra={"TOKEN_BUDGET_CLAUDE_BIN": "/nonexistent/claude", "PATH": "/usr/bin:/bin"})
        self.assertExit(p, 10)
        self.assertIn("NOTIFY: Token Budget failed: probe", p.stdout)
        lr = json.loads(read(self.env.p("last-run.json")))
        self.assertEqual((lr["status"], lr["exit"]), ("failed", 10))
        self.assertEqual(self.env.ledger(), [])
        self.assertFalse(os.path.exists(os.path.join(self.env.vault, "Reports")))

    def test_analyze_failure_exit_11_stops_later_stages(self):
        """4.5 exit 11: corrupt ledger line -> analyze exit 3 -> run.sh exit 11; never repaired"""
        os.makedirs(self.env.state)
        write(self.env.ledger_path, "this line is corrupt\n")
        p = self.full_run()
        self.assertExit(p, 11)
        self.assertIn("NOTIFY: Token Budget failed: analyze", p.stdout)
        self.assertTrue(read(self.env.ledger_path).startswith(b"this line is corrupt\n"))
        self.assertFalse(os.path.exists(self.report_path()))

    # ---- AC38
    def test_ac38_run_never_modifies_settings(self):
        """AC38: end-to-end run against fixtures; settings sha256 unchanged; no auto-apply by env"""
        self.env.set_settings({"env": {"KEEP": "1"}, "hooks": {}, "model": "opus"})
        before = sha256(self.env.settings)
        extra = {"TOKEN_BUDGET_AUTO_APPLY": "1", "AUTO_APPLY": "1", "TOKEN_BUDGET_APPLY": "1",
                 "TOKEN_BUDGET_YES": "1", "TOKEN_BUDGET_FORCE": "1"}
        for now in (W42_NOW, NOW):
            p = self.env.run_sh(now=now, extra=extra, unset=())
            self.assertExit(p, 0)
            self.assertEqual(sha256(self.env.settings), before)
        self.assertEqual(self.env.applied(), [])
        self.assertEqual(self.env.backups(), [])
        self.assertFalse(os.path.exists(self.env.p("applied.jsonl")))
        # a proposal *was* produced but only advisory
        prop = json.loads(read(self.env.p("proposals", "2026-W43.json")))
        self.assertIsInstance(prop["proposals"], list)

    # ---- AC40
    def seed_last_run(self, ts, status="ok", week="2026-W43"):
        os.makedirs(self.env.state, exist_ok=True)
        write(self.env.p("last-run.json"),
              json.dumps({"ts": ts, "week": week, "status": status, "exit": 0 if status == "ok" else 10}))

    def log_text(self, p):
        out = p.stdout + p.stderr
        lp = self.env.p("logs", "run.log")
        if os.path.exists(lp):
            out += read(lp).decode(errors="replace")
        return out

    def test_ac40_catch_up_runs_when_last_run_absent(self):
        """AC40"""
        p = self.env.run_sh("--catch-up", now="2026-10-21T12:00:00Z")
        self.assertExit(p, 0)
        self.assertEqual(len(self.env.ledger()), 1)
        self.assertEqual(len(self.env.fake_calls("claude")), 2)

    def test_ac40_catch_up_noop_when_ok_in_current_week(self):
        """AC40"""
        self.seed_last_run("2026-10-19T09:00:05Z")
        p = self.env.run_sh("--catch-up", now="2026-10-21T12:00:00Z")
        self.assertExit(p, 0)
        self.assertEqual(self.env.ledger(), [])
        self.assertEqual(self.env.fake_calls("claude"), [])
        self.assertIn("catch-up: not needed", self.log_text(p))

    def test_ac40_catch_up_runs_when_last_run_is_previous_week(self):
        """AC40"""
        self.seed_last_run("2026-10-12T09:00:05Z", week="2026-W42")
        p = self.env.run_sh("--catch-up", now="2026-10-21T12:00:00Z")
        self.assertExit(p, 0)
        self.assertEqual(len(self.env.ledger()), 1)

    def test_ac40_catch_up_runs_when_last_run_failed(self):
        """4.5: no-op only if status ok"""
        self.seed_last_run("2026-10-19T09:00:05Z", status="failed")
        p = self.env.run_sh("--catch-up", now="2026-10-21T12:00:00Z")
        self.assertExit(p, 0)
        self.assertEqual(len(self.env.ledger()), 1)

    def test_ac40_monday_0859_last_run_after_previous_monday_0900_is_noop(self):
        """AC40: most recent Monday 09:00 at Mon 08:59 is the previous Monday"""
        self.seed_last_run("2026-10-20T10:00:00Z", week="2026-W43")
        p = self.env.run_sh("--catch-up", now="2026-10-26T08:59:00Z")
        self.assertExit(p, 0)
        self.assertEqual(self.env.ledger(), [])
        self.assertIn("catch-up: not needed", self.log_text(p))

    def test_ac40_monday_0901_same_last_run_runs(self):
        """AC40: at Mon 09:01 the most recent Monday 09:00 is today; last-run is older"""
        self.seed_last_run("2026-10-20T10:00:00Z", week="2026-W43")
        p = self.env.run_sh("--catch-up", now="2026-10-26T09:01:00Z")
        self.assertExit(p, 0)
        self.assertEqual(len(self.env.ledger()), 1)

    # ---- AC41
    def test_ac41_two_runs_same_week_one_ledger_line(self):
        """AC41"""
        self.assertExit(self.env.run_sh(now="2026-10-19T09:00:03Z"), 0)
        self.assertExit(self.env.run_sh(now="2026-10-21T10:00:00Z"), 0)
        self.assertEqual(len(self.env.ledger()), 1)

    def test_ac41_force_appends_second_line(self):
        """AC41"""
        self.assertExit(self.env.run_sh(now="2026-10-19T09:00:03Z"), 0)
        self.assertExit(self.env.run_sh("--force", now="2026-10-21T10:00:00Z"), 0)
        lines = self.env.ledger()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["week"], lines[1]["week"])

    def test_ac41_new_week_appends_new_line(self):
        """AC41 inverse"""
        self.assertExit(self.env.run_sh(now="2026-10-12T09:00:03Z"), 0)
        self.assertExit(self.env.run_sh(now="2026-10-19T09:00:03Z"), 0)
        self.assertEqual([l["week"] for l in self.env.ledger()], ["2026-W42", "2026-W43"])


if __name__ == "__main__":
    unittest.main()
