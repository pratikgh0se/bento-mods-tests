"""Risky sessions (4.1.4 per-session subagent stats) and rules R10/R11 (4.2): AC 52-55."""
import json
import os
import re
import unittest

from tbharness import *  # noqa
from test_spend import SpendBase, T, OLD
from test_analyze import AnalyzeBase, sb, set_spend_breakdown

MARKER = "ZQX-UNIQUE-MARKER-7731"
SID = "aaaaaaaa-0000-0000-0000-000000000001"


def sid_for(i, prefix="ab"):
    return "%s%06d-0000-0000-0000-000000000000" % (prefix, i)


def steps(n, model="claude-sonnet-5-5", inp=10, prefix="u", out=0):
    """n unique deduped assistant steps"""
    return [asst_line(T, model, inp, out, 0, 0, mid="%s%d" % (prefix, k), rid="r%s%d" % (prefix, k))
            for k in range(n)]


def agent_call(tool_id, mid, rid="rq", prompt="do it"):
    return {"type": "assistant", "timestamp": T,
            "message": {"id": mid, "role": "assistant", "model": "claude-sonnet-5-5",
                        "content": [{"type": "tool_use", "id": tool_id, "name": "Agent",
                                     "input": {"prompt": prompt, "description": "d"}}],
                        "usage": {"input_tokens": 1, "output_tokens": 1,
                                  "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}},
            "requestId": rid}


class RiskyBase(SpendBase):
    def risky(self):
        line, bd = self.probe_bd()
        self.assertIn("risky_sessions", bd)
        return bd["risky_sessions"], bd

    def session_stats(self, bd, short="aaaaaaaa"):
        for t in bd["top_sessions"]:
            if t["session"] == short:
                return t
        self.fail("session %s not in top_sessions" % short)


class TestNested(RiskyBase):
    def test_ac52_agent_in_subagent_file_counts(self):
        """AC52: distinct Agent tool_use ids in subagent files increment nested_spawns"""
        write_jsonl(self.main(), steps(1, prefix="m"))
        write_jsonl(self.sub(name="s1"), [agent_call("toolu_1", "a1", "q1"), agent_call("toolu_2", "a2", "q2")])
        write_jsonl(self.sub(name="s2"), [agent_call("toolu_3", "a3", "q3")])
        rs, bd = self.risky()
        self.assertEqual(len(rs), 1)
        r = rs[0]
        self.assertEqual(r["nested_spawns"], 3)
        self.assertEqual(r["subagent_count"], 2)
        self.assertEqual(r["reasons"], ["nested"])
        self.assertEqual(r["session"], "aaaaaaaa")
        self.assertEqual(r["project"], "-proj-a")

    def test_ac52_duplicate_message_counts_once(self):
        """AC52: same message duplicated across lines counts once (distinct tool_use ids)"""
        write_jsonl(self.sub(), [agent_call("toolu_1", "a1", "q1"), agent_call("toolu_1", "a1", "q1"),
                                 agent_call("toolu_1", "a1", "q1")])
        rs, _ = self.risky()
        self.assertEqual(rs[0]["nested_spawns"], 1)

    def test_ac52_agent_in_main_file_not_nested(self):
        """AC52: an Agent tool_use in the main file is not nested; session not risky"""
        write_jsonl(self.main(), [agent_call("toolu_1", "a1", "q1"), agent_call("toolu_2", "a2", "q2")])
        write_jsonl(self.sub(), steps(3))
        rs, bd = self.risky()
        self.assertEqual(rs, [])
        st = self.session_stats(bd)
        self.assertEqual(st["nested_spawns"], 0)

    def test_ac52_non_agent_tool_use_in_subagent_not_counted(self):
        """AC52: only name == Agent counts"""
        ln = agent_call("toolu_1", "a1", "q1")
        ln["message"]["content"][0]["name"] = "Bash"
        write_jsonl(self.sub(), [ln])
        rs, _ = self.risky()
        self.assertEqual(rs, [])

    def test_ac52_no_nested_gives_no_r10(self):
        """AC52: a session with 0 nested spawns gives no R10"""
        sc = Scenario(self.env)
        sc.build()
        set_spend_breakdown(self.env, dict(sb(), risky_sessions=[]))
        p = self.env.analyze()
        self.assertExit(p, 0)
        ids = proposal_ids(json.loads(p.stdout))
        self.assertEqual([i for i in ids if i.startswith("session-")], [])


class TestBoundaries(RiskyBase):
    def test_ac53_100_steps_300000_context_not_risky(self):
        """AC53: 100 steps and max context exactly 300000 -> no R11 / not risky"""
        lines = steps(99, prefix="a")
        lines.append(asst_line(T, "claude-sonnet-5-5", 100000, 0, 150000, 50000, mid="big", rid="rbig"))
        write_jsonl(self.sub(), lines)
        rs, bd = self.risky()
        self.assertEqual(rs, [])
        st = self.session_stats(bd)
        self.assertEqual(st["max_subagent_steps"], 100)
        self.assertEqual(st["max_subagent_context"], 300000)

    def test_ac53_101_steps_is_risky_steps(self):
        """AC53: 101 steps -> reasons has steps (not context)"""
        write_jsonl(self.sub(), steps(101))
        rs, _ = self.risky()
        self.assertEqual(len(rs), 1)
        self.assertEqual(rs[0]["reasons"], ["steps"])
        self.assertEqual(rs[0]["max_subagent_steps"], 101)
        self.assertEqual(rs[0]["worst_agent"]["steps"], 101)

    def test_ac53_context_300001_is_risky_context(self):
        """AC53: context 300001 -> reasons has context"""
        write_jsonl(self.sub(), [asst_line(T, "claude-sonnet-5-5", 100000, 0, 150000, 50001, mid="big", rid="r")])
        rs, _ = self.risky()
        self.assertEqual(len(rs), 1)
        self.assertEqual(rs[0]["reasons"], ["context"])
        self.assertEqual(rs[0]["max_subagent_context"], 300001)
        self.assertEqual(rs[0]["worst_agent"]["max_context"], 300001)

    def test_ac53_context_is_input_plus_cache_read_plus_cache_creation(self):
        """AC53: output tokens do not count; each of the three inputs counts"""
        write_jsonl(self.sub(name="a"), [asst_line(T, "claude-sonnet-5-5", 1, 900000, 0, 0, mid="o", rid="r")])
        write_jsonl(self.sub(name="b"), [asst_line(T, "claude-sonnet-5-5", 0, 0, 300001, 0, mid="cr", rid="r")])
        rs, _ = self.risky()
        self.assertEqual(rs[0]["max_subagent_context"], 300001)
        write_jsonl(self.sub(sid="bbbbbbbb-0000-0000-0000-000000000002", name="c"),
                    [asst_line(T, "claude-sonnet-5-5", 0, 0, 0, 300001, mid="cc", rid="r")])
        rs, _ = self.risky()
        self.assertEqual(sorted(r["session"] for r in rs), ["aaaaaaaa", "bbbbbbbb"])

    def test_ac53_101_lines_100_unique_messages_not_risky(self):
        """AC53: steps are computed on deduped messages"""
        lines = steps(100)
        lines.append(dict(lines[0]))
        self.assertEqual(len(lines), 101)
        write_jsonl(self.sub(), lines)
        rs, bd = self.risky()
        self.assertEqual(rs, [])
        self.assertEqual(self.session_stats(bd)["max_subagent_steps"], 100)

    def test_ac53_steps_are_per_file_not_summed(self):
        """4.1.4: max_subagent_steps is the max of any one subagent file"""
        write_jsonl(self.sub(name="a"), steps(60, prefix="a"))
        write_jsonl(self.sub(name="b"), steps(60, prefix="b"))
        rs, bd = self.risky()
        self.assertEqual(rs, [])
        st = self.session_stats(bd)
        self.assertEqual(st["max_subagent_steps"], 60)
        self.assertEqual(st["subagent_count"], 2)

    def test_ac53_old_steps_outside_window_not_counted(self):
        """4.1.4: same window as spend (7 days)"""
        write_jsonl(self.sub(), [asst_line(OLD, "claude-sonnet-5-5", 1, 0, 0, 0, mid="o%d" % k, rid="r")
                                 for k in range(150)])
        rs, bd = self.risky()
        self.assertEqual(rs, [])

    def test_subagent_count_only_files_with_counted_steps(self):
        """4.1.4: subagent_count = files with >= 1 counted step"""
        write_jsonl(self.sub(name="a"), steps(2, prefix="a"))
        write_jsonl(self.sub(name="empty"), [{"type": "user", "timestamp": T,
                                              "message": {"role": "user", "content": "hi"}}])
        write_jsonl(self.sub(name="old"), [asst_line(OLD, "claude-sonnet-5-5", 1, 0, 0, 0, mid="x", rid="r")])
        _, bd = self.risky()
        self.assertEqual(self.session_stats(bd)["subagent_count"], 1)

    def test_worst_agent_most_steps_with_tiebreaks(self):
        """4.1.4: worst_agent = most steps; ties: greater max context, then file name"""
        write_jsonl(self.sub(name="a"), steps(101, inp=10, prefix="a"))
        write_jsonl(self.sub(name="b"), steps(101, inp=10, prefix="b") +
                    [])
        # b gets a bigger single step via a replacement fixture: same count, larger context
        write_jsonl(self.sub(name="c"), steps(100, inp=10, prefix="c") +
                    [asst_line(T, "claude-sonnet-5-5", 500000, 0, 0, 0, mid="cbig", rid="rc")])
        rs, _ = self.risky()
        w = rs[0]["worst_agent"]
        self.assertEqual(w["steps"], 101)
        self.assertEqual(w["max_context"], 500000, "tie on steps broken by greater max context")
        self.assertEqual(sorted(w.keys()), ["est_usd", "max_context", "steps"])
        # c: 100*10 + 500000 input tokens at sonnet 2/Mtok
        self.assertAlmostEqual(w["est_usd"], (1000 + 500000) * 2 / 1e6, places=4)

    def test_worst_agent_name_tiebreak(self):
        """4.1.4: still tied -> file name (ascending: 'a' beats 'b')"""
        write_jsonl(self.sub(name="b"), steps(101, inp=10, prefix="b", out=1000))
        write_jsonl(self.sub(name="a"), steps(101, inp=10, prefix="a", out=0))
        rs, _ = self.risky()
        w = rs[0]["worst_agent"]
        self.assertEqual(w["steps"], 101)
        # file a: cost from input only (10*101 tokens); file b also has output tokens -> higher cost
        self.assertAlmostEqual(w["est_usd"], 1010 * 2 / 1e6, places=4)


class TestRiskyList(RiskyBase):
    def test_entry_shape_reasons_sorted_and_order(self):
        """4.1.4: entry fields, reasons sorted subset, est_usd desc then project then session"""
        # session A: all three reasons, expensive
        write_jsonl(self.main(sid_for(1)), steps(1, prefix="m1"))
        write_jsonl(self.sub(sid_for(1), name="x"), steps(101, prefix="s1") + [agent_call("t1", "n1", "q")] +
                    [asst_line(T, "claude-sonnet-5-5", 400000, 0, 0, 0, mid="big", rid="r")])
        # session B: nested only, cheap
        write_jsonl(self.sub(sid_for(2), name="x"), [agent_call("t2", "n2", "q")])
        # session C: calm
        write_jsonl(self.main(sid_for(3)), steps(5, prefix="m3"))
        write_jsonl(self.sub(sid_for(3), name="x"), steps(5, prefix="s3"))
        rs, bd = self.risky()
        self.assertEqual([r["session"] for r in rs], ["ab000001", "ab000002"])
        a = rs[0]
        self.assertEqual(sorted(a.keys()), sorted([
            "project", "session", "est_usd", "subagent_count", "nested_spawns", "max_subagent_steps",
            "max_subagent_context", "worst_agent", "reasons"]))
        self.assertEqual(a["reasons"], ["context", "nested", "steps"])
        self.assertEqual(rs[1]["reasons"], ["nested"])
        self.assertGreater(a["est_usd"], rs[1]["est_usd"])
        self.assertEqual(len(a["session"]), 8)

    def test_equal_cost_ties_by_project_then_session(self):
        """4.1.4: ties on est_usd -> project, then session"""
        for proj, sid in (("-proj-b", sid_for(1)), ("-proj-a", sid_for(9)), ("-proj-a", sid_for(5))):
            write_jsonl(self.sub(sid, proj, "x"), [agent_call("t" + sid[:8], "n" + sid[:8], "q")])
        rs, _ = self.risky()
        self.assertEqual([(r["project"], r["session"]) for r in rs],
                         [("-proj-a", "ab000005"), ("-proj-a", "ab000009"), ("-proj-b", "ab000001")])

    def test_capped_at_20(self):
        """4.1.4: risky_sessions capped at 20, keeping the highest est_usd"""
        for i in range(1, 22):
            write_jsonl(self.sub(sid_for(i), name="x"),
                        [asst_line(T, "claude-sonnet-5-5", 1000 * i, 0, 0, 0, mid="m%d" % i, rid="r"),
                         agent_call("t%d" % i, "n%d" % i, "q")])
        rs, _ = self.risky()
        self.assertEqual(len(rs), 20)
        got = [r["session"] for r in rs]
        self.assertEqual(got[0], "ab000021")
        self.assertNotIn("ab000001", got)

    def test_top_sessions_gain_four_fields(self):
        """4.1.4: top_sessions entries carry the 4 subagent stats (and only those added)"""
        write_jsonl(self.main(), steps(1, prefix="m"))
        write_jsonl(self.sub(name="a"), steps(12, prefix="a") + [agent_call("t1", "n1", "q")])
        write_jsonl(self.sub(name="b"), steps(3, prefix="b"))
        _, bd = self.risky()
        t = bd["top_sessions"][0]
        self.assertEqual(sorted(t.keys()), sorted([
            "project", "session", "est_usd", "dominant_model", "subagent_count", "nested_spawns",
            "max_subagent_steps", "max_subagent_context"]))
        self.assertEqual(t["subagent_count"], 2)
        self.assertEqual(t["nested_spawns"], 1)
        self.assertEqual(t["max_subagent_steps"], 13)
        self.assertEqual(t["max_subagent_context"], 10)

    def test_top_sessions_zero_stats_without_subagents(self):
        """4.1.4: session with no subagent files -> zeros"""
        write_jsonl(self.main(), steps(2, prefix="m"))
        rs, bd = self.risky()
        self.assertEqual(rs, [])
        t = bd["top_sessions"][0]
        for k in ("subagent_count", "nested_spawns", "max_subagent_steps", "max_subagent_context"):
            self.assertEqual(t[k], 0, k)

    def test_risky_sessions_empty_list_when_no_transcripts(self):
        """4.1.4: key present and empty"""
        rs, _ = self.risky()
        self.assertEqual(rs, [])


def risky_entry(sid8="e74b1935", nested=0, steps_=10, ctx=1000, est=12.5, count=4):
    reasons = []
    if ctx > 300000:
        reasons.append("context")
    if nested > 0:
        reasons.append("nested")
    if steps_ > 100:
        reasons.append("steps")
    return {"project": "-proj-a", "session": sid8, "est_usd": est, "subagent_count": count,
            "nested_spawns": nested, "max_subagent_steps": steps_, "max_subagent_context": ctx,
            "worst_agent": {"steps": steps_, "max_context": ctx, "est_usd": 3.25}, "reasons": reasons}


class TestRules(AnalyzeBase):
    def run_rs(self, entries):
        sc = self.scenario()
        sc.build()
        set_spend_breakdown(self.env, dict(sb(), risky_sessions=entries))
        p = self.env.analyze()
        self.assertExit(p, 0)
        return json.loads(p.stdout)

    def test_ac54_r10_nested_flag(self):
        """AC54: R10 flag, id session-nested-<8>, saving 0, evidence counts and cost"""
        d = self.run_rs([risky_entry(nested=331, count=430, est=1289.0)])
        pr = by_id(d, "session-nested-e74b1935")
        self.assertIsNotNone(pr)
        self.assertEqual(pr["rule"], "R10")
        self.assertEqual(pr["action"]["type"], "flag")
        self.assertEqual(pr["est_saving_tokens"], 0)
        self.assertRegex(pr["evidence"], r"331")
        self.assertRegex(pr["evidence"], r"430")
        self.assertRegex(pr["evidence"], r"1289")
        self.assertNotIn("session-runaway-e74b1935", proposal_ids(d))

    def test_ac54_r11_runaway_by_steps(self):
        """AC54: R11 on steps > 100"""
        d = self.run_rs([risky_entry(steps_=101, ctx=5000, est=7.5)])
        pr = by_id(d, "session-runaway-e74b1935")
        self.assertIsNotNone(pr)
        self.assertEqual(pr["rule"], "R11")
        self.assertEqual(pr["action"]["type"], "flag")
        self.assertEqual(pr["est_saving_tokens"], 0)
        self.assertRegex(pr["evidence"], r"101")
        self.assertRegex(pr["evidence"], r"3\.25")
        self.assertNotIn("session-nested-e74b1935", proposal_ids(d))

    def test_ac54_r11_runaway_by_context(self):
        """AC54: R11 on context > 300000"""
        d = self.run_rs([risky_entry(ctx=300001)])
        pr = by_id(d, "session-runaway-e74b1935")
        self.assertIsNotNone(pr)
        self.assertRegex(pr["evidence"], r"300001|300,001")

    def test_ac54_r11_boundary_not_fired(self):
        """AC54/AC53: 100 steps and 300000 context -> no R11"""
        d = self.run_rs([risky_entry(steps_=100, ctx=300000, nested=0)])
        self.assertEqual([i for i in proposal_ids(d) if i.startswith("session-")], [])

    def test_ac54_both_rules_for_one_session(self):
        """AC54: nested + runaway -> both proposals"""
        d = self.run_rs([risky_entry(nested=2, steps_=280, ctx=960000)])
        ids = proposal_ids(d)
        self.assertIn("session-nested-e74b1935", ids)
        self.assertIn("session-runaway-e74b1935", ids)

    def test_ac54_apply_exits_6(self):
        """AC54: apply.sh exits 6 for both"""
        self.run_rs([risky_entry(nested=2, steps_=280, ctx=960000)])
        self.assertExit(self.env.apply("session-nested-e74b1935"), 6)
        self.assertExit(self.env.apply("session-runaway-e74b1935"), 6)

    def test_ac54_ids_stable_across_runs(self):
        """4.2: id derived only from rule + subject"""
        d1 = self.run_rs([risky_entry(nested=2, est=5.0)])
        p = self.env.analyze(now="2026-10-19T09:30:00Z")
        d2 = json.loads(p.stdout)
        self.assertEqual(proposal_ids(d1), proposal_ids(d2))

    def test_no_risky_key_in_ledger_no_session_proposals(self):
        """4.2: ledger spend_breakdown without risky_sessions -> nothing evaluated"""
        sc = self.scenario()
        sc.build()
        set_spend_breakdown(self.env, sb())
        p = self.env.analyze()
        self.assertExit(p, 0)
        self.assertEqual([i for i in proposal_ids(json.loads(p.stdout)) if i.startswith("session-")], [])


class TestReportAndNoText(RiskyBase):
    def report(self):
        return read(os.path.join(self.env.vault, "Reports", "Token Budget 2026-W43.md")).decode()

    def risky_section(self):
        t = self.report()
        self.assertIn("### Risky sessions", t)
        a = t.index("### Risky sessions")
        b = t.index("\n## ", a)
        sec = t[a:b]
        return sec, t

    def test_ac54_report_risky_sessions_max5_sorted(self):
        """AC54: report lists at most 5 risky sessions, est. USD desc; only H3 and inside Spend breakdown"""
        for i in range(1, 8):
            write_jsonl(self.sub(sid_for(i), name="x"),
                        [asst_line(T, "claude-sonnet-5-5", 100000 * i, 0, 0, 0, mid="m%d" % i, rid="r"),
                         agent_call("t%d" % i, "n%d" % i, "q")])
        p = self.env.run_sh()
        self.assertExit(p, 0)
        sec, full = self.risky_section()
        found = re.findall(r"ab00000\d", sec)
        self.assertEqual(found, ["ab000007", "ab000006", "ab000005", "ab000004", "ab000003"])
        # F36 AC61: the allowed H3s are exactly Risky sessions and (inside Regressions) Handoff health
        self.assertEqual(re.findall(r"^### (.+?)\s*$", full, flags=re.M), ["Risky sessions", "Handoff health"])
        self.assertLess(full.index("## Spend breakdown"), full.index("### Risky sessions"))
        self.assertLess(full.index("### Risky sessions"), full.index("## Regressions"))
        self.assertIn("-proj-a", sec)
        self.assertRegex(sec, r"nested")

    def test_ac54_report_none_when_no_risky(self):
        """AC54: 'None' when no risky sessions"""
        write_jsonl(self.main(), steps(2, prefix="m"))
        self.assertExit(self.env.run_sh(), 0)
        sec, _ = self.risky_section()
        self.assertIn("None", sec)

    def test_ac54_end_to_end_proposals_via_run(self):
        """AC54: run.sh -> proposals R10/R11 with 8-char ids, apply exits 6"""
        write_jsonl(self.sub(), steps(101, prefix="s") + [agent_call("t1", "n1", "q")])
        self.assertExit(self.env.run_sh(), 0)
        d = json.loads(read(self.env.p("proposals", "%s.json" % WEEK)))
        ids = proposal_ids(d)
        self.assertIn("session-nested-aaaaaaaa", ids)
        self.assertIn("session-runaway-aaaaaaaa", ids)
        self.assertEqual(by_id(d, "session-nested-aaaaaaaa")["est_saving_tokens"], 0)
        self.assertExit(self.env.apply("session-runaway-aaaaaaaa"), 6)

    def test_ac55_marker_nowhere(self):
        """AC55: unique marker in message text, prompts, tool inputs never reaches any output"""
        lines = [asst_line(T, "claude-sonnet-5-5", 10, 1, 0, 0, mid="a%d" % k, rid="r", text=MARKER)
                 for k in range(101)]
        lines.append(agent_call("t1", "n1", "q", prompt=MARKER))
        bash = agent_call("t2", "n2", "q2", prompt=MARKER)
        bash["message"]["content"][0].update({"name": "Bash", "input": {"command": "echo " + MARKER}})
        lines.append(bash)
        lines.append({"type": "user", "timestamp": T,
                      "message": {"role": "user", "content": MARKER + " prompt"}})
        write_jsonl(self.sub(name="agent-" + MARKER[:6]), lines)
        write_jsonl(self.main(), [
            asst_line(T, "claude-opus-5-5", 10, 1, 0, 0, mid="mm", rid="r", text=MARKER),
            {"type": "user", "timestamp": T, "message": {"role": "user", "content": MARKER}}])
        p = self.env.run_sh()
        self.assertExit(p, 0)
        blob = p.stdout + p.stderr
        for root in (self.env.state, self.env.vault):
            for rel in file_tree(root):
                blob += read(os.path.join(root, rel)).decode(errors="replace")
        self.assertNotIn(MARKER, blob)
        self.assertIn("aaaaaaaa", self.report(), "sessions identified by 8-char id")
        d = json.loads(read(self.env.p("proposals", "%s.json" % WEEK)))
        self.assertIn("session-nested-aaaaaaaa", proposal_ids(d))

    def test_ac55_ledger_risky_entries_have_only_id_fields(self):
        """AC55: entries identified by project dir name + 8-char id; no path/name fields"""
        write_jsonl(self.sub(name="agent-secret-name"), [agent_call("t1", "n1", "q")])
        line, bd = self.probe_bd()
        r = bd["risky_sessions"][0]
        blob = json.dumps(bd)
        self.assertNotIn("agent-secret-name", blob)
        self.assertNotIn(self.env.claude_home, blob)
        self.assertNotIn(SID, blob)
        self.assertEqual(r["session"], SID[:8])


if __name__ == "__main__":
    unittest.main()
