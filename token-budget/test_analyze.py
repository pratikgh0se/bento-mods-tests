"""analyze.py contract tests: AC 12-25 and AC 43."""
import ast
import copy
import json
import os
import unittest

from tbharness import *  # noqa


class AnalyzeBase(Base):
    def scenario(self, **kw):
        return Scenario(self.env, **kw)

    def go(self, sc, **kw):
        p, data = sc.run(**kw)
        self.assertExit(p, 0, "analyze")
        return data


class TestDeterminismAndShape(AnalyzeBase):
    def test_ac12_byte_identical_and_canonical_format(self):
        """AC12"""
        sc = self.scenario()
        sc.cur["skills"] = [skill("a"), skill("b", "project")]
        sc.prev["skills"] = [skill("a")]
        sc.delta = 1500
        sc.build()
        p1 = self.env.analyze()
        f1 = read(self.env.p("proposals", "%s.json" % WEEK))
        p2 = self.env.analyze()
        f2 = read(self.env.p("proposals", "%s.json" % WEEK))
        self.assertExit(p1, 0)
        self.assertExit(p2, 0)
        self.assertEqual(p1.stdout, p2.stdout)
        self.assertEqual(f1, f2)
        self.assertEqual(p1.stdout, json.dumps(json.loads(p1.stdout), sort_keys=True, indent=2) + "\n")

    def test_ac12_proposals_file_has_same_content_as_stdout(self):
        """AC12 / 4.2: 'writes proposals/<week>.json and prints the analysis JSON (same content)'"""
        sc = self.scenario()
        p, data = sc.run()
        self.assertExit(p, 0)
        self.assertEqual(json.loads(read(self.env.p("proposals", "%s.json" % WEEK))), data)

    def test_analysis_top_level_schema(self):
        """4.2 analysis output schema (no AC number)"""
        sc = self.scenario()
        sc.delta = 200
        data = self.go(sc)
        for k in ("schema", "week", "generated_at", "baseline", "current", "previous",
                  "delta_tokens", "category_deltas", "spend", "regressions", "proposals", "stats"):
            self.assertIn(k, data)
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["week"], WEEK)
        self.assertEqual(data["generated_at"], ANALYZE_NOW)
        self.assertIs(data["baseline"], False)
        self.assertEqual(data["current"]["total_always_loaded"], 30200)
        self.assertEqual(data["previous"]["total_always_loaded"], 30000)
        self.assertEqual(data["delta_tokens"], 200)
        self.assertEqual(data["category_deltas"]["skills"], 200)
        self.assertEqual(data["spend"], {"daily_usd": 14.2, "weekly_usd": 61.8})
        self.assertEqual(data["stats"]["window_days"], 30)

    def test_stats_transcripts_scanned_and_malformed_lines(self):
        """section 6 / 4.2 notes (no AC number)"""
        sc = self.scenario()
        sc.transcript(["{this is not json", json.dumps(
            sc.tool_use("Bash", {}, ago(2, ANALYZE_NOW)))])
        sc.transcript([sc.tool_use("Bash", {}, ago(3, ANALYZE_NOW))])
        data = self.go(sc)
        self.assertEqual(data["stats"]["transcripts_scanned"], 3)  # history + 2
        self.assertEqual(data["stats"]["malformed_lines"], 1)

    def test_exit_2_ledger_missing(self):
        """4.2 exit 2"""
        os.makedirs(self.env.state)
        self.assertExit(self.env.analyze(), 2)

    def test_exit_2_ledger_empty(self):
        """4.2 exit 2"""
        os.makedirs(self.env.state)
        write(self.env.ledger_path, "")
        self.assertExit(self.env.analyze(), 2)

    def test_exit_3_corrupt_ledger_line_reports_line_number_never_repairs(self):
        """4.2 exit 3 + section 6"""
        sc = self.scenario().build()
        good = read(self.env.ledger_path)
        bad = good + b"{{{ corrupt\n"
        write(self.env.ledger_path, bad)
        p = self.env.analyze()
        self.assertExit(p, 3)
        self.assertIn("3", p.stderr)
        self.assertEqual(read(self.env.ledger_path), bad)

    def test_exit_4_manifest_missing(self):
        """4.2 exit 4"""
        sc = self.scenario().build()
        os.remove(self.env.p("manifests", Scenario.CUR_TS.replace(":", "-") + ".json"))
        self.assertExit(self.env.analyze(), 4)

    def test_ac25_static_no_network_llm_subprocess_random(self):
        """AC25 (static import check of analyze.py)"""
        path = os.path.join(TOOLS, "analyze.py")
        tree = ast.parse(read(path).decode())
        banned = {"socket", "ssl", "urllib", "http", "requests", "httpx", "subprocess",
                  "anthropic", "openai", "ftplib", "smtplib", "telnetlib", "random",
                  "asyncio", "aiohttp", "multiprocessing", "pty"}
        found = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                found.update(a.name.split(".")[0] for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module:
                found.add(n.module.split(".")[0])
        self.assertEqual(found & banned, set(), "banned imports in analyze.py")
        calls = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "os" \
                    and n.attr in ("system", "popen", "spawnl", "spawnv", "execv", "execl", "fork"):
                calls.add(n.attr)
        self.assertEqual(calls, set())


class TestRegressions(AnalyzeBase):
    def test_ac13_plus_1000_is_not_overhead_up(self):
        """AC13"""
        sc = self.scenario()
        sc.delta = 1000
        data = self.go(sc)
        self.assertEqual(data["delta_tokens"], 1000)
        self.assertNotIn("overhead_up", reg_kinds(data))

    def test_ac13_plus_1001_is_overhead_up_naming_largest_category(self):
        """AC13"""
        sc = self.scenario()
        sc.delta = 1001
        data = self.go(sc)
        ups = [r for r in data["regressions"] if r["kind"] == "overhead_up"]
        self.assertEqual(len(ups), 1)
        self.assertEqual(ups[0]["delta_tokens"], 1001)
        self.assertIn("skills +1001", ups[0]["cause"])
        self.assertEqual(ups[0]["id"], "reg-overhead-up")
        self.assertIn("skills", ups[0]["evidence"])

    def test_ac13_cause_joins_positive_categories_sorted_desc_then_name(self):
        """4.2 regression rules: '<category> +<n>' joined by '; ', n desc then name"""
        sc = self.scenario()
        sc.cur_cats["system_prompt"] += 300
        sc.cur_cats["messages"] += 300
        sc.cur_cats["skills"] += 600
        sc.prev_total = 30000
        sc.delta = 0
        sc.build()
        # patch total so delta = 1200 (skills +600 via categories, others 300+300)
        lines = jsonl(self.env.ledger_path)
        lines[-1]["total_always_loaded"] = 31200
        write(self.env.ledger_path, "".join(json.dumps(l) + "\n" for l in lines))
        p = self.env.analyze()
        self.assertExit(p, 0)
        data = json.loads(p.stdout)
        up = [r for r in data["regressions"] if r["kind"] == "overhead_up"][0]
        self.assertIn("skills +600; messages +300; system_prompt +300", up["cause"])

    def test_ac13_decrease_is_not_a_regression(self):
        """AC13 inverse"""
        sc = self.scenario()
        sc.delta = -5000
        data = self.go(sc)
        self.assertNotIn("overhead_up", reg_kinds(data))
        self.assertEqual(data["delta_tokens"], -5000)

    def test_ac14_new_skill_with_flat_overhead(self):
        """AC14"""
        sc = self.scenario()
        sc.cur["skills"] = [skill("fresh", "user")]
        data = self.go(sc)
        self.assertEqual(data["delta_tokens"], 0)
        r = [r for r in data["regressions"] if r["kind"] == "new_skill"]
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["cause"], "new skill: fresh from user")
        self.assertNotIn("overhead_up", reg_kinds(data))

    def test_ac14_same_skill_name_new_source_is_new_skill(self):
        """4.2: skill (name, source) absent previously"""
        sc = self.scenario()
        sc.prev["skills"] = [skill("dup", "user")]
        sc.cur["skills"] = [skill("dup", "user"), skill("dup", "project")]
        data = self.go(sc)
        causes = [r["cause"] for r in data["regressions"] if r["kind"] == "new_skill"]
        self.assertEqual(causes, ["new skill: dup from project"])

    def test_ac14_new_mcp_with_flat_overhead(self):
        """AC14"""
        sc = self.scenario()
        sc.cur["mcp_servers"] = [local_mcp("shiny-server")]
        data = self.go(sc)
        r = [r for r in data["regressions"] if r["kind"] == "new_mcp"]
        self.assertEqual([x["cause"] for x in r], ["new MCP: shiny-server"])
        self.assertNotIn("overhead_up", reg_kinds(data))

    def test_ac14_new_plugin_with_flat_overhead(self):
        """AC14"""
        sc = self.scenario()
        sc.cur["plugins"] = [{"name": "newplug", "version": "1.2.3", "source": "mkt"}]
        data = self.go(sc)
        r = [r for r in data["regressions"] if r["kind"] == "new_plugin"]
        self.assertEqual([x["cause"] for x in r], ["new plugin: newplug 1.2.3"])
        self.assertNotIn("overhead_up", reg_kinds(data))

    def test_plugin_version_change_informational(self):
        """4.2 plugin_version"""
        sc = self.scenario()
        sc.prev["plugins"] = [{"name": "pl", "version": "1.0.0", "source": "m"}]
        sc.cur["plugins"] = [{"name": "pl", "version": "1.1.0", "source": "m"}]
        data = self.go(sc)
        r = [r for r in data["regressions"] if r["kind"] == "plugin_version"]
        self.assertEqual([x["cause"] for x in r], ["plugin pl 1.0.0 -> 1.1.0"])
        self.assertNotIn("new_plugin", reg_kinds(data))

    def test_cli_version_change_informational(self):
        """4.2 cli_version"""
        sc = self.scenario()
        sc.prev_cli = "2.1.88"
        sc.cur_cli = "2.1.90"
        data = self.go(sc)
        r = [r for r in data["regressions"] if r["kind"] == "cli_version"]
        self.assertEqual([x["cause"] for x in r], ["CLI 2.1.88 -> 2.1.90"])

    def test_regressions_sorted_by_kind_order_then_cause(self):
        """4.2: kind order overhead_up,new_skill,new_mcp,new_plugin,plugin_version,cli_version"""
        sc = self.scenario()
        sc.delta = 2000
        sc.prev["plugins"] = [{"name": "pl", "version": "1.0.0", "source": "m"}]
        sc.cur["plugins"] = [{"name": "pl", "version": "1.1.0", "source": "m"},
                             {"name": "np", "version": "0.1", "source": "m"}]
        sc.cur["skills"] = [skill("zz"), skill("aa")]
        sc.cur["mcp_servers"] = [local_mcp("srv")]
        sc.cur_cli = "2.1.90"
        data = self.go(sc)
        order = ["overhead_up", "new_skill", "new_mcp", "new_plugin", "plugin_version", "cli_version"]
        kinds = reg_kinds(data)
        self.assertEqual(kinds, sorted(kinds, key=order.index))
        self.assertEqual(set(kinds), set(order))
        skills_causes = [r["cause"] for r in data["regressions"] if r["kind"] == "new_skill"]
        self.assertEqual(skills_causes, sorted(skills_causes))

    def test_ac15_single_ledger_line_is_baseline(self):
        """AC15"""
        sc = self.scenario()
        sc.single = True
        sc.cur["skills"] = [skill("fresh")]
        sc.delta = 5000
        data = self.go(sc)
        self.assertIs(data["baseline"], True)
        self.assertEqual(data["regressions"], [])
        self.assertIsInstance(data["proposals"], list)

    def test_baseline_still_produces_proposals(self):
        """4.2: baseline -> 'proposals still produced'"""
        sc = self.scenario()
        sc.single = True
        sc.cur["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = None
        data = self.go(sc)
        self.assertIn("compact-window", proposal_ids(data))

    def test_previous_week_is_latest_earlier_week_not_week_minus_one(self):
        """4.2: previous = latest ledger line whose week is earlier than the newest line's week"""
        sc = self.scenario()
        sc.extra_lines = [("2026-W38", "2026-09-21T09:00:03Z", 20000)]
        sc.prev_total = 26000
        sc.build()
        lines = jsonl(self.env.ledger_path)
        for l in lines:           # the 'prev' line is relabelled W40: a gap of 3 weeks
            if l["ts"] == Scenario.PREV_TS:
                l["week"] = "2026-W40"
        write(self.env.ledger_path, "".join(json.dumps(l) + "\n" for l in lines))
        p = self.env.analyze()
        self.assertExit(p, 0)
        data = json.loads(p.stdout)
        self.assertEqual(data["previous"]["total_always_loaded"], 26000)
        self.assertEqual(data["delta_tokens"], 0)

    def test_previous_skips_same_week_reruns(self):
        """4.2: two lines in the newest week -> previous is from an earlier week"""
        sc = self.scenario()
        sc.build()
        lines = jsonl(self.env.ledger_path)
        rerun = copy.deepcopy(lines[-1])
        rerun["ts"] = "2026-10-19T09:30:03Z"
        rerun["total_always_loaded"] = 31500
        rerun["manifest"] = lines[-1]["manifest"]
        lines.append(rerun)
        write(self.env.ledger_path, "".join(json.dumps(l) + "\n" for l in lines))
        p = self.env.analyze()
        self.assertExit(p, 0)
        data = json.loads(p.stdout)
        self.assertEqual(data["current"]["total_always_loaded"], 31500)
        self.assertEqual(data["previous"]["total_always_loaded"], 30000)
        self.assertEqual(data["delta_tokens"], 1500)


class TestRulesR1(AnalyzeBase):
    """AC16 (amended): R1 = long-description flag; AC17: R1/R8/R9 unaffected by the history guard."""

    def flagged(self, tokens, source="user", name="longdesc", history=True, used=False):
        sc = self.scenario(history=history)
        sc.cur["skills"] = [skill(name, source, tokens)]
        sc.prev["skills"] = list(sc.cur["skills"])
        if used:
            sc.skill_use(name, 2)
        return self.go(sc)

    def test_ac16_151_tokens_gives_flag_saving_91(self):
        """AC16"""
        data = self.flagged(151)
        pr = by_id(data, "skill-desc-long-longdesc")
        self.assertIsNotNone(pr, proposal_ids(data))
        self.assertEqual(pr["rule"], "R1")
        self.assertEqual(pr["action"]["type"], "flag")
        self.assertEqual(pr["est_saving_tokens"], 91)
        self.assertIn("title", pr)
        self.assertIn("evidence", pr)
        self.assertIn("command", pr)

    def test_ac16_exactly_150_and_below_gives_none(self):
        """AC16"""
        for t in (150, 149, 40):
            with self.subTest(tokens=t):
                env = Env(self)
                sc = Scenario(env)
                sc.cur["skills"] = [skill("longdesc", "user", t)]
                sc.prev["skills"] = list(sc.cur["skills"])
                p, data = sc.run()
                self.assertExit(p, 0)
                self.assertNotIn("skill-desc-long-longdesc", proposal_ids(data))

    def test_ac16_project_skill_saving_is_tokens_minus_60(self):
        """AC16"""
        data = self.flagged(400, source="project", name="projbig")
        pr = by_id(data, "skill-desc-long-projbig")
        self.assertIsNotNone(pr)
        self.assertEqual(pr["est_saving_tokens"], 340)

    def test_ac16_plugin_and_builtin_skills_never_flagged(self):
        """AC16"""
        sc = self.scenario()
        sc.cur["skills"] = [skill("plugbig", "plugin:foo", 500), skill("bibig", "builtin", 500)]
        sc.prev["skills"] = list(sc.cur["skills"])
        data = self.go(sc)
        self.assertEqual([i for i in proposal_ids(data) if i.startswith("skill-desc-long-")], [])

    def test_ac16_usage_data_is_irrelevant(self):
        """AC16: R1 uses no usage data (a heavily used long skill is still flagged)"""
        data = self.flagged(200, used=True)
        self.assertIn("skill-desc-long-longdesc", proposal_ids(data))

    def test_ac16_never_any_skilloverrides_patch_or_off_even_without_transcripts(self):
        """AC16: no proposal contains a skillOverrides patch or 'off', regardless of usage (no transcripts at all)"""
        sc = self.scenario(history=False)
        sc.cur["skills"] = [skill("idle1", "user", 40), skill("idle2", "project", 300),
                            skill("pl", "plugin:x", 30)]
        sc.prev["skills"] = list(sc.cur["skills"])
        data = self.go(sc)
        blob = json.dumps(data["proposals"])
        self.assertNotIn("skillOverrides", blob)
        self.assertNotIn('"off"', blob)
        self.assertEqual([i for i in proposal_ids(data) if i.startswith("skill-off-")], [])

    def test_ac16_with_old_transcripts_unused_skill_never_turned_off(self):
        """AC16: also with sufficient history and an unused skill"""
        sc = self.scenario()
        sc.cur["skills"] = [skill("idle1", "user", 40)]
        sc.prev["skills"] = list(sc.cur["skills"])
        data = self.go(sc)
        self.assertEqual([i for i in proposal_ids(data) if i.startswith("skill-off-")], [])
        self.assertNotIn("skillOverrides", json.dumps(data["proposals"]))

    def test_ac16_flag_apply_exits_6(self):
        """AC16 + 4.4: advisory"""
        self.flagged(200)
        self.assertExit(self.env.apply("skill-desc-long-longdesc"), 6)

    def test_ac16_existing_override_does_not_matter_for_listing_cost_flag(self):
        """AC16: skills with an existing 'off' override are not listed, but R1 is purely manifest-token based;
        (see SPEC-GAPS: override interplay unspecified) -> only asserted: no crash"""
        sc = self.scenario()
        sc.cur["skills"] = [skill("already", "user", 200, override="off")]
        sc.cur["skill_overrides"] = {"already": "off"}
        sc.prev["skills"] = list(sc.cur["skills"])
        sc.prev["skill_overrides"] = {"already": "off"}
        p, data = sc.run()
        self.assertExit(p, 0)

    def test_ac17_short_history_suppresses_r6_r7_but_not_r1(self):
        """AC17"""
        sc = self.scenario(history=False)
        sc.transcript([{"type": "user", "timestamp": ago(10, ANALYZE_NOW),
                        "message": {"role": "user", "content": "hello"}}])
        sc.cur["skills"] = [skill("longone", "user", 300), skill("pskill", "plugin:idleplug", 55)]
        sc.cur["mcp_servers"] = [connector("claude.ai Idle")]
        sc.cur["plugins"] = [{"name": "idleplug", "version": "1", "source": "m", "surfaces": ["skills"]}]
        sc.prev = copy.deepcopy(sc.cur)
        data = self.go(sc)
        ids = proposal_ids(data)
        self.assertEqual([i for i in ids if i.startswith(("mcp-deny-", "plugin-unused-"))], [])
        self.assertIn("skill-desc-long-longone", ids)
        self.assertIs(data["stats"]["insufficient_history"], True)

    def test_ac17_no_transcripts_at_all_is_insufficient(self):
        """AC17 (no transcripts exist -> fewer than 14 days)"""
        sc = self.scenario(history=False)
        sc.cur["mcp_servers"] = [connector("claude.ai Idle")]
        sc.prev["mcp_servers"] = list(sc.cur["mcp_servers"])
        data = self.go(sc)
        self.assertNotIn("mcp-deny-claude-ai-idle", proposal_ids(data))
        self.assertIs(data["stats"]["insufficient_history"], True)

    def test_ac17_sufficient_history_is_not_flagged(self):
        """AC17 inverse"""
        sc = self.scenario()
        data = self.go(sc)
        self.assertFalse(data["stats"].get("insufficient_history", False))

    def test_ac17_other_rules_unaffected_by_short_history(self):
        """AC17: R3 still fires"""
        sc = self.scenario(history=False)
        sc.cur["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = None
        sc.prev["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = None
        data = self.go(sc)
        self.assertIn("compact-window", proposal_ids(data))

    def test_ac17_r8_r9_unaffected_by_short_history(self):
        """AC17: R8/R9 evaluate even with insufficient history"""
        sc = self.scenario(history=False)
        sc.build()
        set_spend_breakdown(self.env, sb(total=10.0, frontier=0.9, sub=0.05, ratio=0.5))
        p = self.env.analyze()
        self.assertExit(p, 0)
        data = json.loads(p.stdout)
        self.assertIn("spend-frontier-main", proposal_ids(data))
        self.assertIn("spend-cache-low", proposal_ids(data))
        self.assertIs(data["stats"]["insufficient_history"], True)


def sb(total=10.0, frontier=0.5, sub=0.5, ratio=0.9):
    return {"window_days": 7, "prices_as_of": "2026-10-11", "messages_counted": 10,
            "duplicates_dropped": 0, "by_family": spend_blank_families(),
            "total_est_usd": total, "cache_hit_ratio": ratio,
            "cost_share": {"main": round(1 - sub, 4), "subagent": sub},
            "frontier_share": frontier, "top_sessions": [], "ccusage_weekly_usd": 61.8}


def set_spend_breakdown(env, bd):
    lines = jsonl(env.ledger_path)
    lines[-1]["spend_breakdown"] = bd
    write(env.ledger_path, "".join(json.dumps(l) + "\n" for l in lines))


class TestSpendRules(AnalyzeBase):
    def run_sb(self, **kw):
        sc = self.scenario()
        sc.build()
        set_spend_breakdown(self.env, sb(**kw))
        p = self.env.analyze()
        self.assertExit(p, 0)
        return json.loads(p.stdout)

    def test_ac50_r8_frontier_exactly_070_none(self):
        """AC50"""
        d = self.run_sb(frontier=0.70, sub=0.10)
        self.assertNotIn("spend-frontier-main", proposal_ids(d))

    def test_ac50_r8_frontier_071_sub_029_fires(self):
        """AC50"""
        d = self.run_sb(frontier=0.71, sub=0.29)
        pr = by_id(d, "spend-frontier-main")
        self.assertIsNotNone(pr)
        self.assertEqual(pr["rule"], "R8")
        self.assertEqual(pr["action"]["type"], "flag")
        self.assertEqual(pr["est_saving_tokens"], 0)
        self.assertRegex(pr["evidence"], r"0?\.71|71")
        self.assertRegex(pr["evidence"], r"0?\.29|29")

    def test_ac50_r8_sub_share_030_none(self):
        """AC50"""
        d = self.run_sb(frontier=0.71, sub=0.30)
        self.assertNotIn("spend-frontier-main", proposal_ids(d))

    def test_ac50_r9_ratio_080_none(self):
        """AC50"""
        d = self.run_sb(ratio=0.80)
        self.assertNotIn("spend-cache-low", proposal_ids(d))

    def test_ac50_r9_ratio_079_fires(self):
        """AC50"""
        d = self.run_sb(ratio=0.79)
        pr = by_id(d, "spend-cache-low")
        self.assertIsNotNone(pr)
        self.assertEqual(pr["rule"], "R9")
        self.assertEqual(pr["action"]["type"], "flag")
        self.assertEqual(pr["est_saving_tokens"], 0)
        self.assertRegex(pr["evidence"], r"0?\.79|79")

    def test_ac50_r9_null_ratio_none(self):
        """AC50"""
        d = self.run_sb(ratio=None)
        self.assertNotIn("spend-cache-low", proposal_ids(d))

    def test_ac50_both_skipped_when_total_zero(self):
        """AC50"""
        d = self.run_sb(total=0, frontier=1.0, sub=0.0, ratio=0.1)
        ids = proposal_ids(d)
        self.assertNotIn("spend-frontier-main", ids)
        self.assertNotIn("spend-cache-low", ids)

    def test_ac50_flag_apply_exits_6(self):
        """AC50 + 4.4"""
        self.run_sb(frontier=0.9, sub=0.0)
        self.assertExit(self.env.apply("spend-frontier-main"), 6)

    def test_ac50_no_spend_breakdown_in_ledger_no_spend_proposals(self):
        """4.2 R8/R9: ledger without spend_breakdown -> nothing evaluated"""
        sc = self.scenario()
        data = self.go(sc)
        ids = proposal_ids(data)
        self.assertNotIn("spend-frontier-main", ids)
        self.assertNotIn("spend-cache-low", ids)


class TestNamesAndSubagents(AnalyzeBase):
    def test_skill_names_not_redacted_in_proposals(self):
        """8 redaction: skill names never redacted (planning-and-task-breakdown, design-tokens)"""
        sc = self.scenario()
        sc.cur["skills"] = [skill("planning-and-task-breakdown", "user", 200),
                            skill("design-tokens", "user", 180)]
        sc.prev["skills"] = list(sc.cur["skills"])
        p, data = sc.run()
        self.assertExit(p, 0)
        for n in ("planning-and-task-breakdown", "design-tokens"):
            pr = by_id(data, "skill-desc-long-" + n)
            self.assertIsNotNone(pr, proposal_ids(data))
            self.assertIn(n, read(self.env.p("proposals", "%s.json" % WEEK)).decode())
        self.assertNotIn("[REDACTED]", p.stdout)

    def sub_transcript(self, sc, name, days):
        d = os.path.join(sc.proj, "sid-1", "subagents")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "x.jsonl"), "a") as f:
            f.write(json.dumps(sc.tool_use("Skill", {"skill": name}, ago(days, ANALYZE_NOW))) + "\n")

    def plug_scenario(self):
        sc = self.scenario()
        sc.cur["plugins"] = [{"name": "subplug", "version": "1", "source": "m", "surfaces": ["skills"]}]
        sc.cur["skills"] = [skill("subskill", "plugin:subplug", 30)]
        sc.prev = copy.deepcopy(sc.cur)
        return sc

    def test_subagent_transcript_skill_use_counts(self):
        """Skill-usage note: projects/<p>/<sid>/subagents/*.jsonl within 30 days counts (R7 usage)"""
        sc = self.plug_scenario()
        self.sub_transcript(sc, "subplug:subskill", 5)
        p, data = sc.run()
        self.assertExit(p, 0)
        self.assertNotIn("plugin-unused-subplug", proposal_ids(data))

    def test_subagent_transcript_older_than_30_days_does_not_count(self):
        """Skill-usage note: window still applies to subagent transcripts"""
        sc = self.plug_scenario()
        self.sub_transcript(sc, "subplug:subskill", 31)
        p, data = sc.run()
        self.assertExit(p, 0)
        self.assertIn("plugin-unused-subplug", proposal_ids(data))


class TestRulesR2(AnalyzeBase):
    def test_ac18_project_beats_user_removes_user_copy_via_shell(self):
        """AC18"""
        sc = self.scenario()
        sc.cur["skills"] = [skill("twin", "user", 50, "~/.claude/skills/twin"),
                            skill("twin", "project", 60, "/proj/.claude/skills/twin")]
        sc.prev["skills"] = list(sc.cur["skills"])
        sc.skill_use("twin", 2)
        data = self.go(sc)
        dups = [i for i in proposal_ids(data) if i.startswith("skill-dup-twin-")]
        self.assertEqual(dups, ["skill-dup-twin-user"])
        pr = by_id(data, "skill-dup-twin-user")
        self.assertEqual(pr["rule"], "R2")
        self.assertEqual(pr["action"]["type"], "shell")
        argv = pr["action"]["argv"]
        self.assertIsInstance(argv, list)
        self.assertEqual(argv[0], "rm")
        self.assertTrue(argv[-1].endswith(".claude/skills/twin"), argv)
        self.assertEqual(pr["est_saving_tokens"], 50)

    def test_ac18_user_copy_duplicated_by_plugin_copy_is_removed(self):
        """AC18 / 4.2 R2"""
        sc = self.scenario()
        sc.cur["skills"] = [skill("shared", "user", 70, "~/.claude/skills/shared"),
                            skill("shared", "plugin:pl", 20)]
        sc.prev["skills"] = list(sc.cur["skills"])
        sc.skill_use("shared", 2)
        data = self.go(sc)
        dups = [i for i in proposal_ids(data) if i.startswith("skill-dup-shared-")]
        self.assertEqual(dups, ["skill-dup-shared-user"])
        self.assertEqual(by_id(data, "skill-dup-shared-user")["action"]["type"], "shell")

    def test_ac18_plugin_copy_never_removed_by_shell(self):
        """AC18"""
        sc = self.scenario()
        sc.cur["skills"] = [skill("shared2", "user", 70), skill("shared2", "plugin:pl", 20)]
        sc.prev["skills"] = list(sc.cur["skills"])
        sc.skill_use("shared2", 2)
        data = self.go(sc)
        self.assertNotIn("skill-dup-shared2-plugin-pl", proposal_ids(data))
        for p in data["proposals"]:
            if p["action"]["type"] == "shell":
                self.assertNotIn("plugin", " ".join(p["action"]["argv"]))

    def test_ac18_all_plugin_duplicates_give_flag_only(self):
        """AC18"""
        sc = self.scenario()
        sc.cur["skills"] = [skill("pp", "plugin:one", 20), skill("pp", "plugin:two", 30)]
        sc.prev["skills"] = list(sc.cur["skills"])
        sc.skill_use("one:pp", 2)
        data = self.go(sc)
        dups = [p for p in data["proposals"] if p["id"].startswith("skill-dup-pp-")]
        self.assertTrue(dups)
        for p in dups:
            self.assertEqual(p["action"]["type"], "flag")
            self.assertEqual(p["est_saving_tokens"], 0)
            self.assertEqual(p["rule"], "R2")

    def test_ac18_no_duplicates_no_r2(self):
        """AC18 inverse"""
        sc = self.scenario()
        sc.cur["skills"] = [skill("u1", "user"), skill("u2", "project")]
        sc.prev["skills"] = list(sc.cur["skills"])
        sc.skill_use("u1", 2)
        sc.skill_use("u2", 2)
        data = self.go(sc)
        self.assertEqual([i for i in proposal_ids(data) if i.startswith("skill-dup-")], [])


class TestRulesR3toR7(AnalyzeBase):
    def test_ac19_unset_window_proposes_compact_window(self):
        """AC19"""
        sc = self.scenario()
        sc.cur["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = None
        sc.prev["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = None
        data = self.go(sc)
        pr = by_id(data, "compact-window")
        self.assertIsNotNone(pr)
        self.assertEqual(pr["rule"], "R3")
        self.assertEqual(pr["est_saving_tokens"], 0)
        self.assertEqual(pr["action"]["type"], "json_patch")
        self.assertEqual(pr["action"]["ops"], [
            {"op": "add", "path": "/env/CLAUDE_CODE_AUTO_COMPACT_WINDOW", "value": "400000"}])

    def test_ac19_any_set_value_means_no_proposal(self):
        """AC19"""
        for val in ("400000", "200000", "123"):
            with self.subTest(val=val):
                env = Env(self)
                sc = Scenario(env)
                sc.cur["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = val
                sc.prev["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = val
                p, data = sc.run()
                self.assertExit(p, 0)
                self.assertNotIn("compact-window", proposal_ids(data))

    def r4(self, prev_tools, cur_tools, mcp_prev, mcp_cur, with_tools=True):
        sc = self.scenario()
        sp = local_mcp("srv", 100, tools=len(prev_tools), deferred=False)
        scur = local_mcp("srv", 140, tools=len(cur_tools), deferred=False)
        if with_tools:
            sp["tools"] = [{"name": n, "tokens": 20} for n in prev_tools]
            scur["tools"] = [{"name": n, "tokens": 20} for n in cur_tools]
        sc.prev["mcp_servers"] = [sp]
        sc.cur["mcp_servers"] = [scur]
        sc.prev_cats["mcp_tools"] = mcp_prev
        sc.cur_cats["mcp_tools"] = mcp_cur
        return self.go(sc)

    def test_ac20_new_tool_name_with_mcp_tools_grown_gives_flag(self):
        """AC20"""
        data = self.r4(["a", "b"], ["a", "b", "c"], 100, 140)
        hits = [p for p in data["proposals"] if p["id"].startswith("mcp-new-srv-")]
        self.assertEqual(len(hits), 1, proposal_ids(data))
        self.assertTrue(hits[0]["id"].endswith("-c"))
        self.assertEqual(hits[0]["action"]["type"], "flag")
        self.assertEqual(hits[0]["rule"], "R4")
        self.assertEqual(hits[0]["est_saving_tokens"], 20)  # R4: tool tokens if known

    def test_ac20_new_tool_name_with_mcp_tools_unchanged_gives_none(self):
        """AC20"""
        data = self.r4(["a", "b"], ["a", "b", "c"], 100, 100)
        self.assertEqual([i for i in proposal_ids(data) if i.startswith("mcp-new-")], [])

    def test_ac20_tool_count_growth_without_tools_gives_none(self):
        """AC20"""
        data = self.r4(["a", "b"], ["a", "b", "c"], 100, 140, with_tools=False)
        self.assertEqual([i for i in proposal_ids(data) if i.startswith("mcp-new-")], [])

    def test_ac20_mcp_tools_grown_but_no_new_tool_name_gives_none(self):
        """AC20 / R4: requires a new name"""
        data = self.r4(["a", "b"], ["a", "b"], 100, 140)
        self.assertEqual([i for i in proposal_ids(data) if i.startswith("mcp-new-")], [])

    def test_ac21_claudemd_exactly_20_percent_no_proposal(self):
        """AC21"""
        sc = self.scenario()
        sc.prev["claude_md"]["user"] = {"path": "p", "bytes": 1000, "est_tokens": 250}
        sc.cur["claude_md"]["user"] = {"path": "p", "bytes": 1200, "est_tokens": 300}
        data = self.go(sc)
        self.assertEqual([i for i in proposal_ids(data) if i.startswith("claudemd-grew-")], [])

    def test_ac21_claudemd_21_percent_proposes_flag(self):
        """AC21"""
        sc = self.scenario()
        sc.prev["claude_md"]["user"] = {"path": "p", "bytes": 1000, "est_tokens": 250}
        sc.cur["claude_md"]["user"] = {"path": "p", "bytes": 1210, "est_tokens": 303}
        data = self.go(sc)
        pr = by_id(data, "claudemd-grew-user")
        self.assertIsNotNone(pr)
        self.assertEqual(pr["rule"], "R5")
        self.assertEqual(pr["action"]["type"], "flag")
        self.assertEqual(pr["est_saving_tokens"], 53)
        self.assertIsNone(by_id(data, "claudemd-grew-vault"))

    def test_ac21_vault_claudemd_growth(self):
        """AC21"""
        sc = self.scenario()
        sc.prev["claude_md"]["vault"] = {"path": "v", "bytes": 4000, "est_tokens": 1000}
        sc.cur["claude_md"]["vault"] = {"path": "v", "bytes": 5000, "est_tokens": 1250}
        data = self.go(sc)
        pr = by_id(data, "claudemd-grew-vault")
        self.assertIsNotNone(pr)
        self.assertEqual(pr["est_saving_tokens"], 250)

    def test_ac22_unused_connector_gets_deny_proposal(self):
        """AC22"""
        sc = self.scenario()
        sc.cur["mcp_servers"] = [connector("claude.ai Context7", 600)]
        sc.prev["mcp_servers"] = list(sc.cur["mcp_servers"])
        data = self.go(sc)
        pr = by_id(data, "mcp-deny-claude-ai-context7")
        self.assertIsNotNone(pr)
        self.assertEqual(pr["rule"], "R6")
        self.assertEqual(pr["est_saving_tokens"], 600)
        self.assertEqual(pr["action"]["type"], "json_patch")
        self.assertEqual(pr["action"]["ops"], [
            {"op": "add", "path": "/deniedMcpServers/-",
             "value": {"serverName": "claude.ai Context7"}}])

    def test_ac22_already_denied_connector_gets_none(self):
        """AC22"""
        sc = self.scenario()
        sc.cur["mcp_servers"] = [connector("claude.ai Context7", 600)]
        sc.cur["denied_mcp_servers"] = ["claude.ai Context7"]
        sc.prev["mcp_servers"] = list(sc.cur["mcp_servers"])
        sc.prev["denied_mcp_servers"] = ["claude.ai Context7"]
        data = self.go(sc)
        self.assertEqual([i for i in proposal_ids(data) if i.startswith("mcp-deny-")], [])

    def test_ac22_connector_with_tool_calls_gets_none(self):
        """AC22: MCP usage = tool_use names starting mcp__<server-normalised>__"""
        sc = self.scenario()
        sc.cur["mcp_servers"] = [connector("claude.ai Context7", 600)]
        sc.prev["mcp_servers"] = list(sc.cur["mcp_servers"])
        sc.tool("mcp__claude_ai_Context7__query-docs", 5)
        data = self.go(sc)
        self.assertEqual([i for i in proposal_ids(data) if i.startswith("mcp-deny-")], [])

    def test_ac22_connector_call_31_days_ago_is_unused(self):
        """AC22: 30-day window"""
        sc = self.scenario()
        sc.cur["mcp_servers"] = [connector("claude.ai Context7", 600)]
        sc.prev["mcp_servers"] = list(sc.cur["mcp_servers"])
        sc.tool("mcp__claude_ai_Context7__query-docs", 31)
        data = self.go(sc)
        self.assertIn("mcp-deny-claude-ai-context7", proposal_ids(data))

    def test_ac22_local_servers_never_get_r6(self):
        """4.2 R6: only kind connector"""
        sc = self.scenario()
        sc.cur["mcp_servers"] = [local_mcp("my-local", 500)]
        sc.prev["mcp_servers"] = list(sc.cur["mcp_servers"])
        data = self.go(sc)
        self.assertEqual([i for i in proposal_ids(data) if i.startswith("mcp-deny-")], [])

    # ---- R7 / AC43
    def r7_scenario(self):
        sc = self.scenario()
        sc.cur["plugins"] = [
            {"name": "idleplug", "version": "1.0", "source": "m", "surfaces": ["skills"]},
            {"name": "skillplug", "version": "1.0", "source": "m", "surfaces": ["skills"]},
            {"name": "skillplug2", "version": "1.0", "source": "m", "surfaces": ["skills"]},
            {"name": "agentplug", "version": "1.0", "source": "m", "surfaces": ["agents", "skills"]},
        ]
        sc.cur["skills"] = [
            skill("a", "plugin:idleplug", 25), skill("b", "plugin:idleplug", 15),
            skill("usedskill", "plugin:skillplug", 30),
            skill("usedskill2", "plugin:skillplug2", 30),
            skill("x", "plugin:agentplug", 30)]
        sc.prev = copy.deepcopy(sc.cur)
        sc.skill_use("skillplug:usedskill", 29)
        sc.skill_use("usedskill2", 29)
        sc.tool("Task", 3, {"subagent_type": "agentplug:worker", "prompt": "x"})
        return sc

    def surf_scenario(self, surfaces):
        sc = self.scenario()
        sc.cur["plugins"] = [{"name": "surfplug", "version": "1", "source": "m", "surfaces": surfaces}]
        sc.cur["skills"] = [skill("sk", "plugin:surfplug", 33)]
        sc.prev = copy.deepcopy(sc.cur)
        return sc

    def test_ac45_plugins_with_hook_mcp_commands_statusline_never_unused(self):
        """AC45"""
        for surf in (["hooks", "skills"], ["mcp", "skills"], ["commands", "skills"],
                     ["skills", "statusline"], ["hooks"], ["agents", "hooks", "skills"]):
            with self.subTest(surfaces=surf):
                env = Env(self)
                sc = Scenario(env)
                sc.cur["plugins"] = [{"name": "surfplug", "version": "1", "source": "m", "surfaces": surf}]
                sc.cur["skills"] = [skill("sk", "plugin:surfplug", 33)]
                sc.prev = copy.deepcopy(sc.cur)
                p, data = sc.run()
                self.assertExit(p, 0)
                self.assertNotIn("plugin-unused-surfplug", proposal_ids(data))

    def test_ac45_skills_only_plugin_zero_invocations_proposed(self):
        """AC45"""
        data = self.go(self.surf_scenario(["skills"]))
        pr = by_id(data, "plugin-unused-surfplug")
        self.assertIsNotNone(pr)
        self.assertEqual(pr["est_saving_tokens"], 33)

    def test_ac45_agents_and_skills_plugin_proposed(self):
        """AC45: subset of {skills, agents}"""
        data = self.go(self.surf_scenario(["agents", "skills"]))
        self.assertIn("plugin-unused-surfplug", proposal_ids(data))

    def test_ac45_empty_surfaces_never_unused(self):
        """AC45"""
        data = self.go(self.surf_scenario([]))
        self.assertNotIn("plugin-unused-surfplug", proposal_ids(data))

    def test_ac43_unused_plugin_gets_flag_proposal(self):
        """AC43"""
        data = self.go(self.r7_scenario())
        pr = by_id(data, "plugin-unused-idleplug")
        self.assertIsNotNone(pr)
        self.assertEqual(pr["rule"], "R7")
        self.assertEqual(pr["action"]["type"], "flag")
        self.assertEqual(pr["est_saving_tokens"], 40)

    def test_ac43_used_plugins_get_none(self):
        """AC43: skill invoked 29 days ago, subagent used"""
        data = self.go(self.r7_scenario())
        ids = [i for i in proposal_ids(data) if i.startswith("plugin-unused-")]
        self.assertEqual(ids, ["plugin-unused-idleplug"])

    def test_plugin_skill_used_via_plugin_colon_name_counts_as_used(self):
        """4.2 notes: plugin skill 'foo' (plugin:bar) used as Skill input 'bar:foo' -> used (R7)"""
        sc = self.scenario()
        sc.cur["plugins"] = [{"name": "bar", "version": "1", "source": "m", "surfaces": ["skills"]}]
        sc.cur["skills"] = [skill("foo", "plugin:bar", 30)]
        sc.prev = copy.deepcopy(sc.cur)
        sc.skill_use("bar:foo", 5)
        data = self.go(sc)
        self.assertNotIn("plugin-unused-bar", proposal_ids(data))

    def test_plugin_skill_other_prefix_does_not_count(self):
        """4.2 notes: 'baz:foo' is neither 'foo' nor 'bar:foo' -> plugin bar unused"""
        sc = self.scenario()
        sc.cur["plugins"] = [{"name": "bar", "version": "1", "source": "m", "surfaces": ["skills"]}]
        sc.cur["skills"] = [skill("foo", "plugin:bar", 30)]
        sc.prev = copy.deepcopy(sc.cur)
        sc.skill_use("baz:foo", 5)
        data = self.go(sc)
        self.assertIn("plugin-unused-bar", proposal_ids(data))

    def test_ac43_apply_of_plugin_unused_exits_6(self):
        """AC43: apply exits 6 for the produced flag proposal"""
        data = self.go(self.r7_scenario())
        p = self.env.apply("plugin-unused-idleplug")
        self.assertExit(p, 6)


class TestProposalContract(AnalyzeBase):
    def mixed(self):
        sc = self.scenario()
        sc.cur["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = None
        sc.prev["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = None
        sc.cur["skills"] = [skill("big", "user", 400), skill("small", "user", 151),
                            skill("tie-b", "user", 260), skill("tie-a", "user", 260),
                            skill("dupx", "user", 60), skill("dupx", "project", 60)]
        sc.cur["mcp_servers"] = [connector("claude.ai Docs", 627)]
        sc.prev["skills"] = list(sc.cur["skills"])
        sc.prev["mcp_servers"] = list(sc.cur["mcp_servers"])
        sc.skill_use("dupx", 2)
        return sc

    def test_ac23_proposals_match_schema(self):
        """AC23"""
        data = self.go(self.mixed())
        self.assertTrue(data["proposals"])
        for p in data["proposals"]:
            for k in ("id", "rule", "title", "evidence", "est_saving_tokens", "risk",
                      "action", "command"):
                self.assertIn(k, p)
            self.assertRegex(p["rule"], r"^R[1-7]$")
            self.assertIsInstance(p["est_saving_tokens"], int)
            self.assertGreaterEqual(p["est_saving_tokens"], 0)
            self.assertRegex(p["id"], r"^[a-z0-9-]+$")
            self.assertIn(p["action"]["type"], ("json_patch", "shell", "flag"))
            self.assertIsInstance(p["command"], str)
            self.assertTrue(p["command"])
            if p["action"]["type"] in ("json_patch", "shell"):
                self.assertTrue(p["command"].endswith("apply.sh " + p["id"]))
            if p["action"]["type"] == "json_patch":
                self.assertEqual(p["action"]["file"], "settings")
                for op in p["action"]["ops"]:
                    self.assertIn(op["op"], ("add", "replace", "remove"))
                    self.assertTrue(op["path"].startswith("/"))
            if p["action"]["type"] == "shell":
                self.assertIsInstance(p["action"]["argv"], list)
                for a in p["action"]["argv"]:
                    self.assertIsInstance(a, str)

    def test_ac23_sorted_by_saving_desc_then_id(self):
        """AC23"""
        data = self.go(self.mixed())
        pairs = [(-p["est_saving_tokens"], p["id"]) for p in data["proposals"]]
        self.assertEqual(pairs, sorted(pairs))
        ids = proposal_ids(data)
        self.assertLess(ids.index("skill-desc-long-tie-a"), ids.index("skill-desc-long-tie-b"))
        self.assertLess(ids.index("skill-desc-long-big"), ids.index("skill-desc-long-small"))

    def test_ac23_ids_stable_across_different_now(self):
        """AC23: same subject, different --now -> same ids"""
        sc = self.mixed()
        sc.build()
        a = json.loads(self.env.analyze(now="2026-10-19T09:00:10Z").stdout)
        b = json.loads(self.env.analyze(now="2026-10-19T21:15:00Z").stdout)
        self.assertEqual(sorted(proposal_ids(a)), sorted(proposal_ids(b)))
        self.assertTrue(proposal_ids(a))

    def test_ac23_ids_unique_duplicates_collapsed(self):
        """AC23/4.2: duplicates by id collapsed"""
        sc = self.scenario()
        sc.cur["skills"] = [skill("twice", "user", 200), skill("twice", "user", 200)]
        sc.prev["skills"] = list(sc.cur["skills"])
        data = self.go(sc)
        ids = proposal_ids(data)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids.count("skill-desc-long-twice"), 1)

    def test_ac23_slugs_lowercase_nonalnum_to_dash(self):
        """4.2 id slugs"""
        sc = self.scenario()
        sc.cur["skills"] = [skill("My_Skill.v2", "user", 200)]
        sc.prev["skills"] = list(sc.cur["skills"])
        data = self.go(sc)
        self.assertIn("skill-desc-long-my-skill-v2", proposal_ids(data))

    def test_ac24_already_applied_proposal_omitted(self):
        """AC24"""
        sc = self.scenario()
        sc.cur["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = None
        sc.prev["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = None
        sc.build()
        write(self.env.p("applied.jsonl"), json.dumps({
            "schema": 1, "ts": "2026-10-15T09:30:00Z", "action": "apply", "id": "compact-window",
            "backup": "backups/settings.20261015T093000Z.json", "settings_file": self.env.settings,
            "sha256_before": "0", "sha256_after": "1", "est_saving_tokens": 0}) + "\n")
        p = self.env.analyze()
        self.assertExit(p, 0)
        self.assertNotIn("compact-window", proposal_ids(json.loads(p.stdout)))

    def test_ac24_reverted_proposal_comes_back(self):
        """AC24: 'already applied (and not reverted)'"""
        sc = self.scenario()
        sc.cur["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = None
        sc.prev["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = None
        sc.build()
        write(self.env.p("applied.jsonl"),
              json.dumps({"schema": 1, "ts": "2026-10-15T09:30:00Z", "action": "apply",
                          "id": "compact-window", "backup": "b", "settings_file": "s",
                          "sha256_before": "0", "sha256_after": "1", "est_saving_tokens": 0}) + "\n" +
              json.dumps({"schema": 1, "ts": "2026-10-16T09:30:00Z", "action": "revert",
                          "id": "compact-window", "restored_from": "b"}) + "\n")
        p = self.env.analyze()
        self.assertExit(p, 0)
        self.assertIn("compact-window", proposal_ids(json.loads(p.stdout)))

    def test_ac24_noop_against_current_settings_omitted(self):
        """AC24: settings already have the value"""
        sc = self.scenario()
        sc.cur["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = None
        sc.prev["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = None
        self.env.set_settings({"env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "400000"}})
        data = self.go(sc)
        self.assertNotIn("compact-window", proposal_ids(data))

    def test_ac24_noop_deny_already_in_settings_omitted(self):
        """AC24: deniedMcpServers entry already present"""
        sc = self.scenario()
        sc.cur["mcp_servers"] = [connector("claude.ai Docs", 627)]
        sc.prev["mcp_servers"] = list(sc.cur["mcp_servers"])
        self.env.set_settings({"deniedMcpServers": [{"serverName": "claude.ai Docs"}]})
        data = self.go(sc)
        self.assertNotIn("mcp-deny-claude-ai-docs", proposal_ids(data))

    def test_analyze_does_not_modify_settings_or_state_inputs(self):
        """section 2/8: analyze writes only proposals/<week>.json (no auto-apply)"""
        sc = self.mixed()
        sc.build()
        before_settings = sha256(self.env.settings)
        before_ledger = sha256(self.env.ledger_path)
        before = file_tree(self.env.state)
        p = self.env.analyze()
        self.assertExit(p, 0)
        self.assertEqual(sha256(self.env.settings), before_settings)
        self.assertEqual(sha256(self.env.ledger_path), before_ledger)
        after = file_tree(self.env.state)
        new = set(after) - set(before)
        self.assertEqual(new, {"proposals/%s.json" % WEEK})
        for k in before:
            self.assertEqual(before[k], after[k], k)


if __name__ == "__main__":
    unittest.main()
