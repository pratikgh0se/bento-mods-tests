"""Handoff health (docs/token-budget-spec.md "Handoff health (2026-10-16)"): H.1 input/ledger, H.2 report subsection,
H.3 rule R12, ACs 57-68. Fixtures are health.jsonl files (hook spec F36.B shape) placed in the temp root and passed via
HANDOFF_HEALTH_FILE. NOW = 2026-10-19T09:00:03Z (probe/run), ANALYZE_NOW = 2026-10-19T09:00:10Z (analyze), TZ=UTC."""
import datetime as dt
import json
import os
import re
import unittest

from tbharness import *  # noqa
from test_analyze import AnalyzeBase

MARK = "ZQX-HH-MARKER-9917"
IP, NS = "In progress", "Exact next step"


def hts(days=0.0, secs=0, base=NOW):
    t = iso(base) - dt.timedelta(days=days, seconds=secs)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def cl(ts, agent_file="fresh", fallback="skipped", trigger="auto", errors=(), stale=(), status="ok",
       truncated=False, **extra):
    d = {"ts": ts, "sid": "abcd1234", "trigger": trigger, "agent_file": agent_file, "stale_sections": list(stale),
         "fallback": fallback, "duration_ms": 120, "output_chars": 5000, "truncated": truncated,
         "errors": list(errors), "status": status, "hook_version": "1.1.0", "canary_child": False}
    d.update(extra)
    return d


def can(ts, result="pass", reason=None, **extra):
    d = {"ts": ts, "sid": "abcd1234", "trigger": "canary", "result": result, "reason": reason,
         "variants": {"A": result, "B": result}, "duration_ms": 90000, "est_cost_usd": 0.07,
         "hook_version": "1.1.0", "canary_child": False}
    d.update(extra)
    return d


def write_health(path, lines):
    write(path, "".join((l if isinstance(l, str) else json.dumps(l)) + "\n" for l in lines))


def twelve():
    """12 in-window compaction lines with a hand-computed table (see test_ac57)."""
    t = lambda i: hts(0.5 + i * 0.4)
    return [
        cl(t(1)), cl(t(2)), cl(t(3), trigger="manual"), cl(t(4), truncated=True),                      # ok x4
        cl(t(5), errors=["git"], status="ok"),                                                          # degraded: section_error:git
        cl(t(6), "absent", "ok", status="degraded"),                                                    # reduced (own status lies)
        cl(t(7), "absent", "failed", status="ok"),                                                      # degraded
        cl(t(8), "absent", "timeout", trigger="manual"),                                                # degraded
        cl(t(9), "absent", "disabled"),                                                                 # degraded
        cl(t(10), "stale", "ok", stale=[]),                                                             # reduced
        cl(t(11), "stale", "ok", stale=[IP, NS]),                                                       # degraded (agent_stale)
        cl(t(12), "stale", "disabled", trigger="manual", stale=[]),                                     # degraded (agent_stale)
    ]


def seven_canary():
    return [can("2026-10-18T03:41:02Z"),
            can("2026-10-17T01:00:00Z", "fail", "c5"), can("2026-10-17T03:41:02Z"),
            can("2026-10-16T03:41:02Z"),
            can("2026-10-15T03:41:02Z", "fail", "no_compaction"),
            can("2026-10-14T03:41:02Z", "skip", "claude_missing"),
            can("2026-10-13T03:41:02Z")]


class HHBase(Base):
    def setUp(self):
        super().setUp()
        self.hf = os.path.join(self.env.root, "hh", "health.jsonl")

    def extra(self):
        return {"HANDOFF_HEALTH_FILE": self.hf}

    def put(self, lines):
        write_health(self.hf, lines)

    def probe_hh(self):
        p = self.env.probe(extra=self.extra())
        self.assertExit(p, 0, "probe")
        line = self.env.ledger()[-1]
        self.assertIn("handoff_health", line, "ledger line must carry handoff_health")
        return line, line["handoff_health"]

    def report(self):
        return read(os.path.join(self.env.vault, "Reports", "Token Budget 2026-W43.md")).decode()

    def run_report(self, *args, **kw):
        extra = self.extra()
        extra.update(kw.pop("extra", {}))
        p = self.env.run_sh(*args, extra=extra, **kw)
        self.assertExit(p, 0, "run.sh")
        return self.report()

    def section(self, text=None):
        t = text if text is not None else self.report()
        self.assertIn("### Handoff health", t)
        a = t.index("### Handoff health")
        m = re.search(r"\n(## |### |<!-- token-budget:end)", t[a + 5:])
        b = a + 5 + m.start() if m else len(t)
        return t[a:b]


# ---------------------------------------------------------------- AC 57-59 parsing
class TestParsing(HHBase):
    def fixture57(self):
        lines = twelve()
        lines += [cl(hts(8), "absent", "failed"), cl(hts(20))]              # older than 7 days: not counted
        lines += ["{ this is not json", json.dumps({"agent_file": "fresh", "fallback": "skipped"})]   # malformed, no ts
        lines += [cl(hts(1), canary_child=True)]                           # ignored
        lines += seven_canary()
        self.put(lines)

    def test_ac57_counts_match_hand_table(self):
        self.fixture57()
        _, h = self.probe_hh()
        self.assertEqual(h["window_days"], 7)
        self.assertEqual(h["compactions"], 12)
        self.assertEqual((h["auto"], h["manual"]), (9, 3))
        self.assertEqual((h["ok"], h["reduced"], h["degraded"]), (4, 2, 6))
        self.assertEqual(h["ok"] + h["reduced"] + h["degraded"], h["compactions"])
        self.assertEqual(h["agent_file"], {"fresh": 5, "stale": 3, "absent": 4})
        self.assertEqual(h["fallback"], {"skipped": 5, "ok": 3, "failed": 1, "timeout": 1, "disabled": 2})
        self.assertEqual(h["errors_total"], 1)
        self.assertEqual(h["truncated"], 1)
        self.assertEqual(h["ignored"], 3)  # malformed + no-ts + canary_child (lines older than 7 days are not "ignored")

    def test_ac57_status_key_is_never_trusted(self):
        self.put([cl(hts(1), "absent", "ok", status="degraded"), cl(hts(1.1), "absent", "failed", status="ok"),
                  cl(hts(1.2), "fresh", "skipped", status="degraded")])
        _, h = self.probe_hh()
        self.assertEqual((h["ok"], h["reduced"], h["degraded"]), (1, 1, 1))

    def test_ac57_single_line_classes(self):
        cases = [
            (dict(errors=["git"]), "degraded"),
            (dict(agent_file="absent", fallback="ok"), "reduced"),
            (dict(agent_file="absent", fallback="failed"), "degraded"),
            (dict(agent_file="absent", fallback="timeout"), "degraded"),
            (dict(agent_file="absent", fallback="disabled"), "degraded"),
            (dict(agent_file="stale", fallback="ok", stale=[IP]), "degraded"),
            (dict(agent_file="stale", fallback="ok", stale=[]), "reduced"),
            (dict(), "ok"),
        ]
        for kw, want in cases:
            with self.subTest(kw=kw):
                self.put([cl(hts(1), **kw)])
                _, h = self.probe_hh()
                self.assertEqual(h[want], 1, (kw, h))
                self.assertEqual(h["compactions"], 1)

    def test_ac57_old_lines_without_status_key_work(self):
        d = cl(hts(1), "absent", "ok")
        del d["status"]
        del d["canary_child"]
        self.put([d])
        _, h = self.probe_hh()
        self.assertEqual(h["reduced"], 1)

    def test_ac58_rate_rounding_and_null(self):
        self.put([cl(hts(1)), cl(hts(1.1), "absent", "failed"), cl(hts(1.2), "absent", "ok")])
        _, h = self.probe_hh()
        self.assertEqual(h["degraded_rate"], 0.3333)  # reduced not in the numerator
        self.put([cl(hts(1)), cl(hts(1.1), "absent", "failed"), cl(hts(1.2), "absent", "failed"), cl(hts(1.3))])
        self.assertEqual(self.probe_hh()[1]["degraded_rate"], 0.5)
        self.put([can(hts(1)), cl(hts(30))])
        _, h = self.probe_hh()
        self.assertEqual(h["compactions"], 0)
        self.assertIsNone(h["degraded_rate"])

    def test_ac58_top_reasons(self):
        self.put([
            cl(hts(1), errors=["bash", "git"]),
            cl(hts(1.1), errors=["git"]),
            cl(hts(1.2), "absent", "failed"),
            cl(hts(1.3), "absent", "failed"),
            cl(hts(1.4), "absent", "timeout"),
            cl(hts(1.5), "absent", "ok"),                    # reduced: contributes nothing
            cl(hts(1.6), "stale", "ok", stale=[]),           # reduced: nothing
        ])
        _, h = self.probe_hh()
        self.assertEqual(h["top_reasons"], [{"reason": "agent_absent", "count": 3},
                                            {"reason": "fallback_failed", "count": 2},
                                            {"reason": "section_error:git", "count": 2}])
        self.assertLessEqual(len(h["top_reasons"]), 3)

    def test_ac58_top_reasons_stale_and_section_names(self):
        self.put([cl(hts(1), "stale", "ok", stale=[IP, NS]), cl(hts(1.1), "stale", "disabled", stale=[]),
                  cl(hts(1.2), errors=["bash"])])
        _, h = self.probe_hh()
        self.assertEqual(h["top_reasons"][0], {"reason": "agent_stale", "count": 2})
        self.assertEqual(h["top_reasons"][1:], [{"reason": "section_error:bash", "count": 1}])

    def test_ac58_no_reasons_when_no_degraded(self):
        self.put([cl(hts(1)), cl(hts(1.1), "absent", "ok")])
        _, h = self.probe_hh()
        self.assertEqual(h["top_reasons"], [])

    def test_ac59_canary_strip(self):
        self.put(seven_canary() + [can("2026-10-01T03:41:02Z", "fail", "c1")])  # one outside the window
        _, h = self.probe_hh()
        c = h["canary"]
        self.assertEqual((c["pass"], c["fail"], c["skip"]), (4, 2, 1))
        self.assertEqual(c["nights"], [{"date": "2026-10-13", "result": "pass"}, {"date": "2026-10-14", "result": "skip"},
                                       {"date": "2026-10-15", "result": "fail"}, {"date": "2026-10-16", "result": "pass"},
                                       {"date": "2026-10-17", "result": "pass"},  # later line of the date wins
                                       {"date": "2026-10-18", "result": "pass"}])
        self.assertEqual(c["last_ts"], "2026-10-18T03:41:02Z")
        self.assertLessEqual(len(c["nights"]), 7)

    def test_ac59_last_ts_is_newest_overall_even_outside_window(self):
        self.put([can("2026-10-05T03:41:02Z", "fail", "c2"), can("2026-10-02T03:41:02Z")])
        _, h = self.probe_hh()
        c = h["canary"]
        self.assertEqual((c["pass"], c["fail"], c["skip"]), (0, 0, 0))
        self.assertEqual(c["nights"], [])
        self.assertEqual(c["last_ts"], "2026-10-05T03:41:02Z")

    def test_ac59_no_canary_last_ts_null(self):
        self.put([cl(hts(1))])
        _, h = self.probe_hh()
        self.assertIsNone(h["canary"]["last_ts"])
        self.assertEqual((h["canary"]["pass"], h["canary"]["fail"], h["canary"]["skip"]), (0, 0, 0))

    def test_ac59_canary_child_canary_line_ignored(self):
        self.put([can("2026-10-18T03:41:02Z", canary_child=True)])
        _, h = self.probe_hh()
        self.assertIsNone(h["canary"]["last_ts"])
        self.assertEqual(h["ignored"], 1)

    def test_window_edge_is_inclusive_at_7_days(self):
        self.put([cl(hts(7)), cl(hts(7, 1))])
        _, h = self.probe_hh()
        self.assertEqual(h["compactions"], 1)

    def test_ledger_has_only_documented_keys(self):
        self.fixture57 = TestParsing.fixture57.__get__(self)
        self.fixture57()
        _, h = self.probe_hh()
        self.assertEqual(sorted(h.keys()), sorted(["window_days", "compactions", "auto", "manual", "ok", "reduced", "degraded",
                                                   "degraded_rate", "agent_file", "fallback", "errors_total", "truncated",
                                                   "top_reasons", "canary", "ignored"]))


# ---------------------------------------------------------------- AC 60
class TestMissing(HHBase):
    def test_ac60_missing_file(self):
        p = self.env.probe(extra=self.extra())
        self.assertExit(p, 0)
        line = self.env.ledger()[-1]
        self.assertIn("handoff_health", line)
        self.assertIsNone(line["handoff_health"])
        self.assertIn("handoff-health", line["warnings"])
        t = self.run_report("--force")
        sec = self.section(t)
        self.assertEqual([l for l in sec.strip().split("\n") if l.strip()], ["### Handoff health", "n/a"])
        self.assertNotIn("FLAG handoff-degraded", t)

    def test_ac60_directory_in_place_of_file(self):
        os.makedirs(self.hf)
        p = self.env.probe(extra=self.extra())
        self.assertExit(p, 0)
        line = self.env.ledger()[-1]
        self.assertIsNone(line["handoff_health"])
        self.assertIn("handoff-health", line["warnings"])

    def test_ac60_no_r12_when_null(self):
        self.run_report()
        p = self.env.analyze(extra=self.extra())
        self.assertExit(p, 0)
        self.assertNotIn("handoff-degraded", [x["id"] for x in json.loads(p.stdout)["proposals"]])

    def test_ac60_old_ledger_without_key(self):
        sc = Scenario(self.env)
        sc.build()
        self.assertNotIn("handoff_health", self.env.ledger()[-1])
        p = self.env.analyze(extra={"HANDOFF_HEALTH_FILE": os.path.join(self.env.root, "nope")})
        self.assertExit(p, 0)
        self.assertNotIn("handoff-degraded", [x["id"] for x in json.loads(p.stdout)["proposals"]])

    def test_ac60_empty_file_is_data_not_missing(self):
        write(self.hf, "")
        line, h = self.probe_hh()
        self.assertEqual(h["compactions"], 0)
        self.assertNotIn("handoff-health", line["warnings"])
        sec = self.section(self.run_report("--force"))
        self.assertIn("no data in window", sec)


# ---------------------------------------------------------------- AC 61 report
SUMMARY_RE = r"^compactions \d+ \(auto \d+, manual \d+\), ok \d+, reduced \d+, degraded \d+ \(\d+(\.\d)?%\), window 7 days \(as of \d{4}-\d\d-\d\d\)$"


class TestReport(HHBase):
    def setUp(self):
        super().setUp()
        lines = twelve() + seven_canary()
        self.put(lines)

    def test_ac61_structure_and_h3s(self):
        t = self.run_report()
        h2 = re.findall(r"^## (.+?)\s*$", t, flags=re.M)
        for a, b in zip(["Headline", "Breakdown", "Spend breakdown", "Regressions", "Proposals",
                         "Applied since last report", "Measurement notes"],
                        [x for x in h2 if x != "For future agent"]):
            self.assertEqual(a, b)
        self.assertEqual(re.findall(r"^### (.+?)\s*$", t, flags=re.M), ["Risky sessions", "Handoff health"])
        reg = t.index("## Regressions")
        hh = t.index("### Handoff health")
        self.assertGreater(hh, reg)
        self.assertLess(hh, t.index("## Proposals"))
        if "### Risky sessions" in t:
            self.assertLess(t.index("### Risky sessions"), reg)
        self.assertEqual(t.count("### Handoff health"), 1)

    def test_ac61_lines_in_order(self):
        sec = self.section(self.run_report())
        lines = [l for l in sec.split("\n")[1:] if l.strip()]
        self.assertRegex(lines[0], SUMMARY_RE)
        self.assertEqual(lines[0], "compactions 12 (auto 9, manual 3), ok 4, reduced 2, degraded 6 (50.0%), window 7 days (as of 2026-10-19)")
        self.assertEqual(lines[1], "fallback: ok 3, failed 1, timeout 1, skipped 5, disabled 2")
        self.assertEqual(lines[2], "agent file: fresh 5, stale 3, absent 4")
        strip = " · ".join(["2026-10-13 pass", "2026-10-14 skip", "2026-10-15 fail", "2026-10-16 pass",
                            "2026-10-17 pass", "2026-10-18 pass"])
        head = "canary: 4 pass / 2 fail / 1 skip in the last 7 nights"
        # spec H.2.3: the canary line "followed by a one-line strip": accept the strip on the same line or on the next one
        if lines[3] == head:
            self.assertEqual(lines[4], strip)
            rest = lines[5:]
        else:
            self.assertIn(lines[3], (head + " " + strip, head + " · " + strip, head + "\n" + strip))
            rest = lines[4:]
        self.assertEqual(rest[0], "top reasons: agent_absent x3, agent_stale x2, fallback_failed x1")
        self.assertTrue(rest[1].startswith("FLAG handoff-degraded: "), lines)
        self.assertEqual(sec.count("(as of "), 1)

    def test_ac61_regressions_list_comes_first(self):
        t = self.run_report()
        a = t.index("## Regressions")
        b = t.index("### Handoff health")
        before = t[a + len("## Regressions"):b].strip()
        self.assertTrue(before != "", "overhead list or 'None' must precede the subsection")

    def test_ac61_summary_when_zero_compactions(self):
        self.put([can("2026-10-18T03:41:02Z")])
        sec = self.section(self.run_report("--force"))
        lines = [l for l in sec.split("\n")[1:] if l.strip()]
        self.assertRegex(lines[0], r"^compactions 0 \(auto 0, manual 0\), ok 0, reduced 0, degraded n/a, window 7 days \(as of 2026-10-19\)$")

    def test_ac61_canary_no_runs(self):
        self.put([cl(hts(1))])
        sec = self.section(self.run_report("--force"))
        self.assertIn("canary: no runs recorded", sec)

    def test_ac61_canary_stale_suffix(self):
        self.put([cl(hts(1)), can("2026-10-14T03:41:02Z")])
        sec = self.section(self.run_report("--force"))
        self.assertRegex(sec, r"canary: .*\(last run 2026-10-14, stale\)")

    def test_ac61_canary_fresh_has_no_stale_suffix(self):
        self.put([cl(hts(1)), can("2026-10-18T03:41:02Z")])
        sec = self.section(self.run_report("--force"))
        self.assertNotIn("(last run", sec)

    def test_ac61_top_reasons_none(self):
        self.put([cl(hts(1)), can("2026-10-18T03:41:02Z")])
        sec = self.section(self.run_report("--force"))
        self.assertIn("top reasons: none", sec)
        self.assertNotIn("FLAG handoff-degraded", sec)

    def test_ac61_headline_and_notification_unchanged_shape(self):
        t = self.run_report()
        self.assertRegex(t, r"(?m)^overhead \S+ \([^)]*\), spend .*, \d+ proposals?")


# ---------------------------------------------------------------- AC 62 no-text
class TestNoText(HHBase):
    def test_ac62_marker_appears_nowhere(self):
        lines = twelve() + seven_canary()
        for l in lines:
            for k in list(l.keys()):
                if isinstance(l[k], str) and k != "ts":
                    l[k] = l[k] + MARK
            l["extra_text_" + MARK] = "message text " + MARK
            l["sid"] = "sid" + MARK
        lines[0]["reason"] = MARK
        lines[0]["errors"] = [MARK]
        lines[1]["stale_sections"] = [MARK]
        lines[-1]["reason"] = MARK
        self.put(lines)
        p = self.env.run_sh(extra=self.extra())
        self.assertExit(p, 0)
        self.assertNotIn(MARK, p.stdout + p.stderr)
        for root in (self.env.state, self.env.vault, self.env.home):
            for d, _dirs, files in os.walk(root):
                for f in files:
                    self.assertNotIn(MARK.encode(), read(os.path.join(d, f)), os.path.join(d, f))

    def test_ac62_subsection_has_only_fixed_words_digits_dates_codes(self):
        self.put(twelve() + seven_canary())
        sec = self.section(self.run_report())
        for l in [x for x in sec.split("\n")[1:] if x.strip()]:
            words = ["pass", "fail", "skip", "ok", "failed", "timeout", "skipped", "disabled", "fresh", "stale", "absent",
                     "reduced", "degraded", "compactions", "auto", "manual", "window", "days", "as", "of", "fallback", "agent",
                     "file", "canary", "in", "the", "last", "nights", "top", "reasons", "none", "FLAG", "handoff-degraded",
                     "rate", "canary_fail", "canary_stale", "agent_absent", "agent_stale", "fallback_failed",
                     "fallback_timeout", "section_error:\\w+"]
            words.sort(key=len, reverse=True)
            pat = r"\d{4}-\d\d-\d\d|\d+(\.\d)?%?|" + "|".join(words) + r"|[x:,/·()_]|\s"
            stripped = re.sub(pat, "", l)
            self.assertEqual(stripped, "", l)


# ---------------------------------------------------------------- AC 63-66 R12
def full_hh(compactions=10, degraded=0, reduced=0, canary_fail=0, last_ts=None, top=()):
    return {"window_days": 7, "compactions": compactions, "auto": compactions, "manual": 0,
            "ok": compactions - degraded - reduced, "reduced": reduced, "degraded": degraded,
            "degraded_rate": round(degraded / compactions, 4) if compactions else None,
            "agent_file": {"fresh": 0, "stale": 0, "absent": 0},
            "fallback": {"skipped": 0, "ok": 0, "failed": 0, "timeout": 0, "disabled": 0},
            "errors_total": 0, "truncated": 0, "top_reasons": list(top),
            "canary": {"pass": 0, "fail": canary_fail, "skip": 0, "nights": [], "last_ts": last_ts}, "ignored": 0}


class TestR12(AnalyzeBase):
    def run_hh(self, hh):
        sc = self.scenario()
        sc.build()
        lines = jsonl(self.env.ledger_path)
        lines[-1]["handoff_health"] = hh
        write(self.env.ledger_path, "".join(json.dumps(l) + "\n" for l in lines))
        p = self.env.analyze()
        self.assertExit(p, 0)
        return json.loads(p.stdout)

    def r12(self, hh):
        return by_id(self.run_hh(hh), "handoff-degraded")

    def test_ac63_rate_boundary(self):
        self.assertIsNone(self.r12(full_hh(10, 1)))
        pr = self.r12(full_hh(10, 2))
        self.assertIsNotNone(pr)
        self.assertEqual(pr["evidence"]["triggers"], ["rate"])
        self.assertIsNotNone(self.r12(full_hh(1, 1)))
        self.assertIsNone(self.r12(full_hh(0, 0)))

    def test_ac63_integer_arithmetic(self):
        self.assertIsNone(self.r12(full_hh(20, 2)))
        self.assertIsNotNone(self.r12(full_hh(21, 3)))

    def test_ac63_reduced_never_counts(self):
        self.assertIsNone(self.r12(full_hh(10, 0, reduced=10)))
        self.assertIsNotNone(self.r12(full_hh(10, 2, reduced=8)))

    def test_ac64_canary_fail(self):
        pr = self.r12(full_hh(0, 0, canary_fail=1, last_ts="2026-10-18T03:41:02Z"))
        self.assertIsNotNone(pr)
        self.assertEqual(pr["evidence"]["triggers"], ["canary_fail"])

    def test_ac64_skip_only_never_fires(self):
        hh = full_hh(5, 0, last_ts="2026-10-18T03:41:02Z")
        hh["canary"]["skip"] = 7
        self.assertIsNone(self.r12(hh))

    def test_ac65_stale_boundary(self):
        self.assertIsNone(self.r12(full_hh(5, 0, last_ts="2026-10-16T09:00:10Z")))   # exactly 3 days before ANALYZE_NOW
        pr = self.r12(full_hh(5, 0, last_ts="2026-10-16T09:00:09Z"))                 # 3 days + 1 s
        self.assertIsNotNone(pr)
        self.assertEqual(pr["evidence"]["triggers"], ["canary_stale"])

    def test_ac65_no_canary_ever_none(self):
        self.assertIsNone(self.r12(full_hh(5, 0, last_ts=None)))

    def test_ac65_trigger_order(self):
        pr = self.r12(full_hh(10, 5, canary_fail=2, last_ts="2026-10-10T03:41:02Z"))
        self.assertEqual(pr["evidence"]["triggers"], ["rate", "canary_fail", "canary_stale"])

    def test_ac66_proposal_shape(self):
        top = [{"reason": "agent_absent", "count": 3}]
        pr = self.r12(full_hh(10, 5, canary_fail=2, last_ts="2026-10-10T03:41:02Z", top=top))
        self.assertEqual(pr["id"], "handoff-degraded")
        self.assertEqual(pr["rule"], "R12")
        self.assertEqual(pr["action"]["type"], "flag")
        self.assertEqual(pr["est_saving_tokens"], 0)
        ev = pr["evidence"]
        self.assertIsInstance(ev, dict)
        for k in ("compactions", "degraded", "degraded_rate", "canary_fail", "canary_last_ts", "top_reasons", "triggers"):
            self.assertIn(k, ev)
        self.assertEqual((ev["compactions"], ev["degraded"], ev["degraded_rate"], ev["canary_fail"]), (10, 5, 0.5, 2))
        self.assertEqual(ev["canary_last_ts"], "2026-10-10T03:41:02Z")
        self.assertEqual(ev["top_reasons"], top)
        d = self.run_hh(full_hh(10, 5, canary_fail=2, last_ts="2026-10-10T03:41:02Z"))
        self.assertEqual(proposal_ids(d).count("handoff-degraded"), 1)

    def test_ac66_apply_exits_6_without_change(self):
        self.run_hh(full_hh(10, 5))
        before = file_tree(self.env.claude_home)
        self.assertExit(self.env.apply("handoff-degraded"), 6)
        self.assertEqual(file_tree(self.env.claude_home), before)

    def test_ac66_not_suppressed_by_insufficient_history(self):
        sc = self.scenario(history=False)
        sc.build()
        lines = jsonl(self.env.ledger_path)
        lines[-1]["handoff_health"] = full_hh(10, 5)
        write(self.env.ledger_path, "".join(json.dumps(l) + "\n" for l in lines))
        p = self.env.analyze()
        self.assertExit(p, 0)
        self.assertIn("handoff-degraded", proposal_ids(json.loads(p.stdout)))

    def test_ac66_stable_id_and_deterministic(self):
        d1 = self.run_hh(full_hh(10, 5))
        p1 = self.env.analyze()
        p2 = self.env.analyze()
        self.assertEqual(p1.stdout, p2.stdout)
        self.assertEqual(proposal_ids(d1), proposal_ids(json.loads(p2.stdout)))


class TestR12Report(HHBase):
    def test_ac66_report_flag_line_and_proposal(self):
        self.put(twelve() + seven_canary())
        t = self.run_report()
        sec = self.section(t)
        flag = [l for l in sec.split("\n") if l.startswith("FLAG handoff-degraded:")]
        self.assertEqual(len(flag), 1)
        self.assertIn("rate", flag[0])
        self.assertIn("canary_fail", flag[0])
        props = t[t.index("## Proposals"):t.index("## Applied since last report")]
        self.assertIn("handoff-degraded", props)
        self.assertGreaterEqual(props.count("handoff-degraded"), 1)
        m = re.search(r"(\d+) proposals?", t[:t.index("## Breakdown")])
        self.assertIsNotNone(m)

    def test_ac66_no_flag_when_healthy(self):
        self.put([cl(hts(1 + i / 10)) for i in range(10)] + [can("2026-10-18T03:41:02Z")])
        t = self.run_report()
        self.assertNotIn("FLAG handoff-degraded", t)
        self.assertNotIn("handoff-degraded", t[t.index("## Proposals"):t.index("## Applied since last report")])

    def test_ac64_old_canary_fail_does_not_fire_fail_trigger(self):
        self.put([can(hts(8), "fail", "c3")])
        p = self.env.run_sh(extra=self.extra())
        self.assertExit(p, 0)
        d = json.loads(read(self.env.p("proposals", "2026-W43.json")))
        pr = by_id(d, "handoff-degraded")
        self.assertIsNotNone(pr)  # newest canary is 8 days old: stale
        self.assertEqual(pr["evidence"]["triggers"], ["canary_stale"])


# ---------------------------------------------------------------- AC 67-68
class TestDeterminism(HHBase):
    def test_ac67_byte_identical_and_idempotent(self):
        self.put(twelve() + seven_canary())
        self.assertExit(self.env.run_sh(extra=self.extra()), 0)
        p1 = self.env.analyze(extra=self.extra())
        self.assertExit(p1, 0)
        r1 = self.report()
        l1 = self.env.ledger()
        self.assertExit(self.env.run_sh("--force", extra=self.extra()), 0)
        r2 = self.report()
        self.assertEqual(r2.count("### Handoff health"), 1)
        self.assertEqual(self.section(r1), self.section(r2))
        self.assertEqual(len(self.env.ledger()), len(l1) + 1)  # --force appends (AC 41); same-week re-run without it keeps one
        q1 = self.env.analyze(extra=self.extra())
        q2 = self.env.analyze(extra=self.extra())
        self.assertEqual(q1.stdout, q2.stdout)

    def test_ac67_same_week_rerun_keeps_one_ledger_line(self):
        self.put(twelve())
        self.assertExit(self.env.run_sh(extra=self.extra()), 0)
        self.assertExit(self.env.run_sh(extra=self.extra(), now="2026-10-21T10:00:00Z"), 0)
        self.assertEqual(len(self.env.ledger()), 1)

    def test_ac67_vault_unset_exit_0_no_report(self):
        self.put(twelve())
        p = self.env.run_sh(extra=self.extra(), vault=False)
        self.assertExit(p, 0)
        for d, _dirs, files in os.walk(self.env.root):
            for f in files:
                self.assertFalse(f.startswith("Token Budget") and f.endswith(".md"), f)

    def test_ac68_health_reader_is_read_only_and_calls_nothing(self):
        self.put(twelve() + seven_canary())
        self.probe_hh()  # ledger line first (analyze needs one)
        before = file_tree(os.path.dirname(self.hf))
        st = os.stat(self.hf)
        self.env.fake_calls  # (probe itself may call the fake claude; only analyze is checked below)
        open(self.env.log, "w").close()
        if os.path.exists(self.env.shim_log):
            open(self.env.shim_log, "w").close()
        p = self.env.analyze(extra=self.extra())
        self.assertExit(p, 0)
        self.assertEqual(file_tree(os.path.dirname(self.hf)), before)
        self.assertEqual(os.stat(self.hf).st_mtime, st.st_mtime)
        self.assertEqual(self.env.fake_calls("claude"), [])
        self.assertEqual(self.env.fake_calls("ccusage"), [])
        self.assertEqual(self.env.shim_calls(), [])

    def test_ac68_read_only_health_dir_still_works(self):
        self.put(twelve())
        os.chmod(self.hf, 0o444)
        os.chmod(os.path.dirname(self.hf), 0o555)
        self.addCleanup(os.chmod, os.path.dirname(self.hf), 0o755)
        line, h = self.probe_hh()
        self.assertEqual(h["compactions"], 12)

    def test_ac57_health_path_flag_overrides(self):
        self.put(twelve())
        other = os.path.join(self.env.root, "other.jsonl")
        write_health(other, [cl(hts(1))])
        p = self.env.probe(extra={"HANDOFF_HEALTH_FILE": other})
        self.assertExit(p, 0)
        self.assertEqual(self.env.ledger()[-1]["handoff_health"]["compactions"], 1)


if __name__ == "__main__":
    unittest.main()
