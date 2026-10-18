"""Spend breakdown (4.1.4) and plugin surfaces (4.1.2): AC 45 (manifest side), 46-49, 51."""
import json
import os
import re
import unittest

from tbharness import *  # noqa

FAMILIES = ("fable", "opus", "sonnet", "haiku", "other")
T = ago(1, NOW)           # one day before probe time, inside the 7-day window
OLD = ago(8, NOW)         # outside the window


class SpendBase(Base):
    def proj(self, name="-proj-a"):
        return os.path.join(self.env.claude_home, "projects", name)

    def main(self, sid="aaaaaaaa-0000-0000-0000-000000000001", proj="-proj-a"):
        return os.path.join(self.proj(proj), sid + ".jsonl")

    def sub(self, sid="aaaaaaaa-0000-0000-0000-000000000001", proj="-proj-a", name="x"):
        return os.path.join(self.proj(proj), sid, "subagents", name + ".jsonl")

    def probe_bd(self, extra=None):
        p = self.env.probe(extra=extra)
        self.assertExit(p, 0, "probe")
        line = self.env.ledger()[-1]
        self.assertIn("spend_breakdown", line)
        return line, line["spend_breakdown"]


class TestSpendMath(SpendBase):
    def opus_fixture(self):
        write_jsonl(self.main(), [asst_line(T, "claude-opus-5-5", 1000000, 100000, 2000000, 200000,
                                            mid="m1", rid="r1")])

    def test_ac47_opus_exact_74_usd(self):
        """AC47: 1,000,000 in / 100,000 out / 2,000,000 cache_read / 200,000 cache_creation -> 7.4"""
        self.opus_fixture()
        _, bd = self.probe_bd()
        o = bd["by_family"]["opus"]
        self.assertEqual((o["input"], o["output"], o["cache_read"], o["cache_creation"]),
                         (1000000, 100000, 2000000, 200000))
        self.assertAlmostEqual(o["est_usd"], 7.4, places=4)
        self.assertAlmostEqual(bd["total_est_usd"], 7.4, places=4)
        self.assertEqual(bd["window_days"], 7)
        self.assertEqual(bd["prices_as_of"], "2026-10-11")
        self.assertEqual(sorted(bd["by_family"].keys()), sorted(FAMILIES))
        self.assertAlmostEqual(bd["frontier_share"], 1.0, places=4)

    def test_ac47_all_five_families_present_even_when_empty(self):
        """AC47 / 4.1.4: all five families always present"""
        self.opus_fixture()
        _, bd = self.probe_bd()
        for f in FAMILIES:
            for k in ("input", "output", "cache_read", "cache_creation", "est_usd"):
                self.assertIn(k, bd["by_family"][f])
        self.assertEqual(bd["by_family"]["sonnet"]["est_usd"], 0)

    def test_ac47_per_family_sums_and_other_bucket(self):
        """AC47: fable/opus/sonnet/haiku/other each priced from the seed table; claude-foo-1 -> other; case-insensitive"""
        write_jsonl(self.main(), [
            asst_line(T, "claude-fable-5-1", 100000, 10000, 200000, 20000, mid="f1", rid="r"),     # 1+0.5+0.05+0.25 = 1.8
            asst_line(T, "claude-opus-5-5", 1000000, 100000, 2000000, 200000, mid="o1", rid="r"),  # 7.4
            asst_line(T, "claude-sonnet-5-5", 1000000, 0, 0, 0, mid="s1", rid="r"),                # 2.0
            asst_line(T, "CLAUDE-HAIKU-5-5", 0, 2000000, 0, 0, mid="h1", rid="r"),                 # 1.0
            asst_line(T, "claude-foo-1", 0, 0, 0, 1000000, mid="x1", rid="r"),                      # 5.0 (opus row)
        ])
        _, bd = self.probe_bd()
        f = bd["by_family"]
        self.assertAlmostEqual(f["fable"]["est_usd"], 1.8, places=4)
        self.assertAlmostEqual(f["opus"]["est_usd"], 7.4, places=4)
        self.assertAlmostEqual(f["sonnet"]["est_usd"], 2.0, places=4)
        self.assertAlmostEqual(f["haiku"]["est_usd"], 1.0, places=4)
        self.assertAlmostEqual(f["other"]["est_usd"], 5.0, places=4)
        self.assertEqual(f["other"]["cache_creation"], 1000000)
        self.assertEqual(f["haiku"]["output"], 2000000)
        self.assertAlmostEqual(bd["total_est_usd"], 17.2, places=4)
        self.assertAlmostEqual(bd["frontier_share"], (1.8 + 7.4) / 17.2, places=3)

    def test_ac47_synthetic_and_old_lines_excluded(self):
        """AC47: <synthetic> model and lines older than 7 days are excluded"""
        write_jsonl(self.main(), [
            asst_line(T, "claude-opus-5-5", 1000000, 100000, 2000000, 200000, mid="m1", rid="r1"),
            asst_line(T, "<synthetic>", 9000000, 9000000, 9000000, 9000000, mid="syn", rid="r"),
            asst_line(OLD, "claude-opus-5-5", 9000000, 9000000, 9000000, 9000000, mid="old", rid="r"),
            {"type": "user", "timestamp": T, "message": {"role": "user", "content": "hi",
                                                          "usage": {"input_tokens": 9000000}}},
        ])
        _, bd = self.probe_bd()
        self.assertAlmostEqual(bd["total_est_usd"], 7.4, places=4)
        self.assertEqual(bd["messages_counted"], 1)

    def test_ac47_malformed_lines_skipped(self):
        """4.1.4: malformed lines skipped"""
        write_jsonl(self.main(), ["{not json", asst_line(T, "claude-opus-5-5", 1000000, 100000, 2000000, 200000,
                                                          mid="m1", rid="r1")])
        _, bd = self.probe_bd()
        self.assertAlmostEqual(bd["total_est_usd"], 7.4, places=4)

    def test_ac47_prices_override_changes_result(self):
        """AC47: TOKEN_BUDGET_PRICES override (file path; see SPEC-GAPS)"""
        self.opus_fixture()
        prices = os.path.join(self.env.root, "prices.json")
        write(prices, json.dumps({"asOf": "2026-01-01", "source": "test", "families": {
            "fable": {"input": 10, "output": 50, "cache_read": 0.25, "cache_write5m": 12.5},
            "opus": {"input": 8, "output": 20, "cache_read": 0.2, "cache_write5m": 5},
            "sonnet": {"input": 2, "output": 10, "cache_read": 0.1, "cache_write5m": 2.5},
            "haiku": {"input": 0.1, "output": 0.5, "cache_read": 0.01, "cache_write5m": 0.125},
            "other": {"input": 4, "output": 20, "cache_read": 0.2, "cache_write5m": 5}}}))
        line, bd = self.probe_bd(extra={"TOKEN_BUDGET_PRICES": prices})
        self.assertAlmostEqual(bd["by_family"]["opus"]["est_usd"], 11.4, places=4)   # 8+2+0.4+1.0
        self.assertNotIn("prices_override_invalid", line["warnings"])

    def test_ac47_invalid_prices_override_warns_and_falls_back(self):
        """AC47"""
        self.opus_fixture()
        bad = os.path.join(self.env.root, "bad-prices.json")
        write(bad, "{ not json")
        line, bd = self.probe_bd(extra={"TOKEN_BUDGET_PRICES": bad})
        self.assertIn("prices_override_invalid", line["warnings"])
        self.assertAlmostEqual(bd["by_family"]["opus"]["est_usd"], 7.4, places=4)

    def test_ac48_cache_hit_ratio_0625(self):
        """AC48: 2,000,000 / (1,000,000 + 2,000,000 + 200,000)"""
        self.opus_fixture()
        _, bd = self.probe_bd()
        self.assertAlmostEqual(bd["cache_hit_ratio"], 0.625, places=4)

    def test_ac48_cache_hit_ratio_spans_all_families(self):
        """AC48: all families"""
        write_jsonl(self.main(), [
            asst_line(T, "claude-opus-5-5", 100, 0, 100, 0, mid="a", rid="r"),
            asst_line(T, "claude-sonnet-5-5", 100, 0, 300, 0, mid="b", rid="r")])
        _, bd = self.probe_bd()
        self.assertAlmostEqual(bd["cache_hit_ratio"], 400 / 600, places=3)

    def test_ac48_null_with_no_data_and_no_transcripts_warning(self):
        """AC48 + 4.1.4: no transcripts in window -> zeros, ratio null, warning no_transcripts"""
        line, bd = self.probe_bd()
        self.assertIsNone(bd["cache_hit_ratio"])
        self.assertEqual(bd["total_est_usd"], 0)
        self.assertIn("no_transcripts", line["warnings"])
        self.assertEqual(sorted(bd["by_family"].keys()), sorted(FAMILIES))
        self.assertEqual(bd["cost_share"]["main"], 0)
        self.assertEqual(bd["cost_share"]["subagent"], 0)
        self.assertEqual(bd["frontier_share"], 0)
        self.assertEqual(bd["top_sessions"], [])

    def test_ccusage_weekly_copied(self):
        """4.1.4: ccusage_weekly_usd copies spend.weekly_usd (null when unavailable)"""
        line, bd = self.probe_bd(extra={"TOKEN_BUDGET_CCUSAGE_BIN": "/nonexistent/ccusage"})
        self.assertIsNone(bd["ccusage_weekly_usd"])
        self.assertIsNone(line["spend"]["weekly_usd"])


class TestDedupe(SpendBase):
    def test_ac46_triple_duplicate_across_main_and_subagent_counts_once(self):
        """AC46: same (message.id, requestId) on 3 lines, split across main and subagent files"""
        write_jsonl(self.main(), [
            asst_line(T, "claude-opus-5-5", 100, 10, 0, 0, mid="dup", rid="rq"),
            asst_line(T, "claude-opus-5-5", 100, 50, 0, 0, mid="dup", rid="rq")])
        write_jsonl(self.sub(), [asst_line(T, "claude-opus-5-5", 100, 30, 0, 0, mid="dup", rid="rq")])
        _, bd = self.probe_bd()
        o = bd["by_family"]["opus"]
        self.assertEqual(o["output"], 50, "keep the line with the greatest output_tokens")
        self.assertEqual(o["input"], 100, "counted once")
        self.assertEqual(bd["duplicates_dropped"], 2)
        self.assertEqual(bd["messages_counted"], 1)

    def test_ac46_lines_without_any_id_never_deduped(self):
        """AC46"""
        write_jsonl(self.main(), [
            asst_line(T, "claude-sonnet-5-5", 0, 7, 0, 0),
            asst_line(T, "claude-sonnet-5-5", 0, 7, 0, 0)])
        _, bd = self.probe_bd()
        self.assertEqual(bd["by_family"]["sonnet"]["output"], 14)
        self.assertEqual(bd["duplicates_dropped"], 0)
        self.assertEqual(bd["messages_counted"], 2)

    def test_ac46_line_with_only_one_id_uses_the_one_it_has(self):
        """4.1.4: a line missing either id uses the one it has"""
        write_jsonl(self.main(), [
            asst_line(T, "claude-haiku-5-5", 0, 3, 0, 0, mid="only-msg"),
            asst_line(T, "claude-haiku-5-5", 0, 9, 0, 0, mid="only-msg")])
        _, bd = self.probe_bd()
        self.assertEqual(bd["by_family"]["haiku"]["output"], 9)
        self.assertEqual(bd["duplicates_dropped"], 1)

    def test_ac46_combined_counts(self):
        """AC46: dropped = 2 (triple) ; messages_counted after dedupe"""
        write_jsonl(self.main(), [
            asst_line(T, "claude-opus-5-5", 1, 10, 0, 0, mid="d", rid="q"),
            asst_line(T, "claude-opus-5-5", 1, 50, 0, 0, mid="d", rid="q"),
            asst_line(T, "claude-sonnet-5-5", 0, 7, 0, 0)])
        write_jsonl(self.sub(), [asst_line(T, "claude-opus-5-5", 1, 30, 0, 0, mid="d", rid="q"),
                                 asst_line(T, "claude-sonnet-5-5", 0, 7, 0, 0)])
        _, bd = self.probe_bd()
        self.assertEqual(bd["duplicates_dropped"], 2)
        self.assertEqual(bd["messages_counted"], 3)

    def test_ac46_same_ids_different_ids_not_merged(self):
        """AC46 inverse: same message.id with different requestId is a different key"""
        write_jsonl(self.main(), [
            asst_line(T, "claude-opus-5-5", 0, 10, 0, 0, mid="m", rid="r1"),
            asst_line(T, "claude-opus-5-5", 0, 10, 0, 0, mid="m", rid="r2")])
        _, bd = self.probe_bd()
        self.assertEqual(bd["by_family"]["opus"]["output"], 20)
        self.assertEqual(bd["duplicates_dropped"], 0)


class TestShares(SpendBase):
    CANARY = "CANARY-PROMPT-TEXT-9f3a"

    def fixture(self):
        def sid(c):
            return "%s%s%s%s%s%s%s%s-0000-0000-0000-000000000000" % ((c,) * 8)
        self.sids = {c: sid(c) for c in "abcdef"}
        n = [0]

        def msg(model, inp):
            n[0] += 1
            return asst_line(T, model, inp, 0, 0, 0, mid="m%d" % n[0], rid="r%d" % n[0], text=self.CANARY)
        # costs: sonnet input 2/Mtok -> 500000 tok = 1.0 USD ; opus 4/Mtok
        write_jsonl(self.main(self.sids["a"], "-proj-a"), [msg("claude-sonnet-5-5", 500000),
                    {"type": "user", "timestamp": T, "message": {"role": "user", "content": self.CANARY}}])
        write_jsonl(self.sub(self.sids["a"], "-proj-a"), [msg("claude-opus-5-5", 1250000)])         # 5.0
        write_jsonl(self.main(self.sids["b"], "-proj-b"), [msg("claude-sonnet-5-5", 2000000)])     # 4.0
        write_jsonl(self.main(self.sids["c"], "-proj-c"), [msg("claude-sonnet-5-5", 1500000)])     # 3.0
        write_jsonl(self.main(self.sids["d"], "-proj-e"), [msg("claude-sonnet-5-5", 1000000)])     # 2.0
        write_jsonl(self.main(self.sids["e"], "-proj-d"), [msg("claude-sonnet-5-5", 1000000)])     # 2.0 tie
        write_jsonl(self.main(self.sids["f"], "-proj-f"), [msg("claude-sonnet-5-5", 500000)])      # 1.0 (6th)
        # main total = 1+4+3+2+2+1 = 13 ; subagent = 5 ; total 18

    def test_ac49_cost_share(self):
        """AC49"""
        self.fixture()
        _, bd = self.probe_bd()
        self.assertAlmostEqual(bd["total_est_usd"], 18.0, places=3)
        self.assertAlmostEqual(bd["cost_share"]["main"], 13 / 18, places=3)
        self.assertAlmostEqual(bd["cost_share"]["subagent"], 5 / 18, places=3)

    def test_ac49_top_sessions_order_size_and_parent_includes_subagent(self):
        """AC49"""
        self.fixture()
        _, bd = self.probe_bd()
        ts = bd["top_sessions"]
        self.assertEqual(len(ts), 5)
        for t in ts:
            self.assertEqual(sorted(t.keys()), sorted([
                "dominant_model", "est_usd", "project", "session", "subagent_count", "nested_spawns",
                "max_subagent_steps", "max_subagent_context"]))
            self.assertEqual(len(t["session"]), 8)
        self.assertEqual(ts[0]["project"], "-proj-a")
        self.assertEqual(ts[0]["session"], "aaaaaaaa")
        self.assertAlmostEqual(ts[0]["est_usd"], 6.0, places=3)      # 1.0 main + 5.0 subagent
        self.assertEqual(ts[0]["dominant_model"], "opus")
        self.assertEqual([t["project"] for t in ts], ["-proj-a", "-proj-b", "-proj-c", "-proj-d", "-proj-e"])
        costs = [t["est_usd"] for t in ts]
        self.assertEqual(costs, sorted(costs, reverse=True))
        self.assertEqual(ts[1]["dominant_model"], "sonnet")
        self.assertNotIn("-proj-f", [t["project"] for t in ts])

    def test_ac49_no_message_text_anywhere_in_state_or_report(self):
        """AC49 + 8: fixture message text never reaches ledger, manifest, proposals, logs or report"""
        self.fixture()
        p = self.env.run_sh()
        self.assertExit(p, 0)
        blob = p.stdout + p.stderr
        for root in (self.env.state, self.env.vault):
            for rel in file_tree(root):
                blob += read(os.path.join(root, rel)).decode(errors="replace")
        self.assertNotIn(self.CANARY, blob)
        self.assertNotIn("assistant words", blob)


class TestSpendReport(SpendBase):
    def section(self):
        t = read(os.path.join(self.env.vault, "Reports", "Token Budget 2026-W43.md")).decode()
        a = t.index("## Spend breakdown")
        b = t.index("## Regressions")
        return t[a:b], t

    def test_ac51_spend_breakdown_section_content(self):
        """AC51"""
        write_jsonl(self.main(), [asst_line(T, "claude-opus-5-5", 1000000, 100000, 2000000, 200000,
                                            mid="m1", rid="r1")])
        write_jsonl(self.sub(), [asst_line(T, "claude-sonnet-5-5", 0, 500000, 0, 0, mid="m2", rid="r2")])
        p = self.env.run_sh(extra={"TOKEN_BUDGET_CCUSAGE_BIN": "/nonexistent/ccusage"})
        self.assertExit(p, 0)
        sec, full = self.section()
        low = sec.lower()
        for f in FAMILIES:
            self.assertIn(f, low)
        self.assertRegex(sec, r"estimate \(prices as of 2026-10-11\)")
        self.assertRegex(sec, r"0\.625|62\.5")
        self.assertIn("main", low)
        self.assertIn("subagent", low)
        self.assertIn("aaaaaaaa", sec)
        self.assertIn("-proj-a", sec)
        self.assertIn("ccusage n/a", sec)
        self.assertRegex(sec, r"7\.4")
        self.assertRegex(sec, r"7[ -]day|7d|last 7|7 days", "window 7 days should be stated")
        fm, _ = split_fm(full)
        self.assertIn("spend_est_usd_7d", fm)
        self.assertAlmostEqual(float(fm["spend_est_usd_7d"]), 12.4, places=2)

    def test_ac51_section_between_breakdown_and_regressions(self):
        """AC26/AC51: heading order"""
        self.assertExit(self.env.run_sh(), 0)
        _, full = self.section()
        h2 = re.findall(r"^## (.+?)\s*$", full, flags=re.M)
        self.assertEqual(h2.index("Spend breakdown"), h2.index("Breakdown") + 1)
        self.assertEqual(h2.index("Regressions"), h2.index("Spend breakdown") + 1)

    def test_ac51_empty_window_still_renders_section(self):
        """AC51: no transcripts -> zeros; section present, still labelled as estimate"""
        self.assertExit(self.env.run_sh(), 0)
        sec, _ = self.section()
        self.assertRegex(sec, r"estimate \(prices as of 2026-10-11\)|n/a")


def split_fm(text):
    end = text.index("\n---\n", 4)
    fm = {}
    for line in text[4:end].splitlines():
        m = re.match(r"^([A-Za-z_0-9]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2)
    return fm, text[end + 5:]


class TestSurfaces(Base):
    """AC45 (manifest side): surfaces detection for each marker, from fixture plugin dirs."""

    def mkplugin(self, name, files=(), dirs=(), plugin_json=None):
        root = os.path.join(self.env.root, "plugins-src", name)
        os.makedirs(root, exist_ok=True)
        for d in dirs:
            os.makedirs(os.path.join(root, d), exist_ok=True)
        for f, content in files:
            write(os.path.join(root, f), content)
        if plugin_json is not None:
            write(os.path.join(root, "plugin.json"), json.dumps(plugin_json))
            write(os.path.join(root, ".claude-plugin", "plugin.json"), json.dumps(plugin_json))
        return root

    def register(self, plugins):
        """plugins: {name: install dir}"""
        inst = {"version": 2, "plugins": {}}
        enabled = {}
        for name, path in plugins.items():
            key = "%s@testmkt" % name
            inst["plugins"][key] = [{"scope": "user", "installPath": path, "version": "1.0.0",
                                     "installedAt": "2026-10-01T00:00:00Z"}]
            enabled[key] = True
        write(os.path.join(self.env.claude_home, "plugins", "installed_plugins.json"), json.dumps(inst))
        self.env.set_settings({"env": {"K": "1"}, "enabledPlugins": enabled})

    def surfaces(self):
        p = self.env.probe()
        self.assertExit(p, 0)
        m = self.env.manifest_of(self.env.ledger()[0])
        return {pl["name"]: pl.get("surfaces") for pl in m["plugins"]}

    def test_ac45_each_marker(self):
        """AC45 / 4.1.2: every documented marker"""
        hook_cfg = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": []}]}}
        d = {
            "p-skills": self.mkplugin("p-skills", dirs=["skills/a"]),
            "p-agents": self.mkplugin("p-agents", dirs=["agents"]),
            "p-hooksjson": self.mkplugin("p-hooksjson", files=[("hooks/hooks.json", "{}")]),
            "p-hookskey": self.mkplugin("p-hookskey", plugin_json=hook_cfg),
            "p-mods": self.mkplugin("p-mods", files=[("hooks/register.ts", "export {}")]),
            "p-mcpjson": self.mkplugin("p-mcpjson", files=[(".mcp.json", "{}")]),
            "p-mcpkey": self.mkplugin("p-mcpkey", plugin_json={"mcpServers": {"s": {"command": "x"}}}),
            "p-cmddir": self.mkplugin("p-cmddir", dirs=["commands"]),
            "p-cmdkey": self.mkplugin("p-cmdkey", plugin_json={"commands": ["./c.md"]}),
            "p-status": self.mkplugin("p-status", plugin_json={"statusLine": {"type": "command", "command": "x"}}),
            "p-empty": self.mkplugin("p-empty"),
            "p-emptyhooks": self.mkplugin("p-emptyhooks", plugin_json={"hooks": {}}),
            "p-multi": self.mkplugin("p-multi", dirs=["skills/a", "agents"], files=[("hooks/hooks.json", "{}")]),
        }
        self.register(d)
        s = self.surfaces()
        self.assertEqual(s["p-skills"], ["skills"])
        self.assertEqual(s["p-agents"], ["agents"])
        self.assertEqual(s["p-hooksjson"], ["hooks"])
        self.assertEqual(s["p-hookskey"], ["hooks"])
        self.assertEqual(s["p-mods"], ["hooks"])
        self.assertEqual(s["p-mcpjson"], ["mcp"])
        self.assertEqual(s["p-mcpkey"], ["mcp"])
        self.assertEqual(s["p-cmddir"], ["commands"])
        self.assertEqual(s["p-cmdkey"], ["commands"])
        self.assertEqual(s["p-status"], ["statusline"])
        self.assertEqual(s["p-empty"], [])
        self.assertEqual(s["p-emptyhooks"], [], "an empty `hooks` key is not a hooks surface")
        self.assertEqual(s["p-multi"], ["agents", "hooks", "skills"], "sorted")

    def test_ac45_unreadable_dir_gives_empty_surfaces(self):
        """AC45 / 4.1.2: unreadable dir -> []"""
        self.register({"p-gone": os.path.join(self.env.root, "does-not-exist")})
        self.assertEqual(self.surfaces()["p-gone"], [])


if __name__ == "__main__":
    unittest.main()
