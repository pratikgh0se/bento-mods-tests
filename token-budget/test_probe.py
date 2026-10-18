"""Probe contract tests: AC 1-11 and AC 44."""
import json
import os
import re
import unittest

from tbharness import *  # noqa


def sum_check(cats):
    skip = ("system_tools_deferred", "mcp_tools_deferred", "free_space", "autocompact_buffer")
    return sum(v for k, v in cats.items() if k not in skip and isinstance(v, int))


class ProbeBase(Base):
    def run_probe(self, *args, **kw):
        return self.env.probe(*args, **kw)

    def ok_probe(self, *args, **kw):
        p = self.run_probe(*args, **kw)
        self.assertExit(p, 0, "probe")
        lines = self.env.ledger()
        self.assertEqual(len(lines), 1)
        return lines[0]


class TestProbeInvocation(ProbeBase):
    def test_ac01_exactly_two_haiku_invocations(self):
        """AC1"""
        self.ok_probe()
        calls = self.env.fake_calls("claude")
        self.assertEqual(len(calls), 2, calls)
        for c in calls:
            a = c["argv"]
            self.assertIn("-p", a)
            self.assertIn("--model", a)
            self.assertEqual(a[a.index("--model") + 1], "haiku")
        first, second = calls
        self.assertIn("/context", first["argv"])
        self.assertNotIn("--output-format", first["argv"])
        a = second["argv"]
        self.assertIn("--output-format", a)
        self.assertEqual(a[a.index("--output-format") + 1], "json")
        self.assertIn("reply with the single word ok", a)

    def test_ac02_cwd_is_empty_scratch_dir_deleted_afterwards(self):
        """AC2"""
        # decoy: the directory the probe is started from has CLAUDE.md, .claude, .git
        write(os.path.join(self.env.work, "CLAUDE.md"), "decoy")
        os.makedirs(os.path.join(self.env.work, ".claude"))
        os.makedirs(os.path.join(self.env.work, ".git"))
        self.ok_probe(cwd=self.env.work)
        calls = self.env.fake_calls("claude")
        self.assertEqual(len(calls), 2)
        for c in calls:
            self.assertEqual(c["listing"], [], "scratch dir must be empty at call time")
            self.assertNotEqual(c["cwd"], os.path.realpath(self.env.work))
            self.assertFalse(os.path.exists(c["cwd"]), "scratch dir must be deleted afterwards")

    def test_ac11_dry_run_writes_nothing_and_prints_ledger_line(self):
        """AC11"""
        os.makedirs(self.env.state)
        p = self.run_probe("--dry-run")
        self.assertExit(p, 0)
        self.assertEqual(file_tree(self.env.state), {})
        found = None
        for line in p.stdout.splitlines():
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if isinstance(o, dict) and "total_always_loaded" in o:
                found = o
        self.assertIsNotNone(found, "dry-run must print the ledger line to stdout")
        self.assertEqual(found["total_always_loaded"], 28700)
        self.assertEqual(len(self.env.fake_calls("claude")), 2)


class TestLedgerLine(ProbeBase):
    def test_ac03_schema_and_append_only(self):
        """AC3"""
        old = [json.dumps(ledger_line("2026-W41", "2026-10-05T09:00:03Z", 31000)),
               json.dumps(ledger_line("2026-W42", "2026-10-12T09:00:03Z", 30300))]
        os.makedirs(self.env.state)
        before = ("\n".join(old) + "\n").encode()
        write(self.env.ledger_path, before)
        # prior ledger lines reference manifests; give them to be safe
        p = self.run_probe()
        self.assertExit(p, 0)
        after = read(self.env.ledger_path)
        self.assertTrue(after.startswith(before), "prior lines must be unchanged")
        rest = after[len(before):].decode()
        self.assertTrue(rest.endswith("\n"))
        self.assertEqual(rest.count("\n"), 1, "exactly one new line")
        line = json.loads(rest)
        self.assertEqual(
            sorted(line.keys()),
            sorted(["schema", "ts", "week", "cli_version", "model", "total_always_loaded",
                    "category_sum_check", "categories", "context_window", "trivial_turn",
                    "spend", "spend_breakdown", "handoff_health", "manifest", "denied_mcp_notices", "warnings"]))
        self.assertEqual(line["schema"], 1)
        self.assertEqual(line["ts"], NOW)
        self.assertEqual(line["week"], "2026-W43")
        self.assertEqual(line["model"], "haiku")
        self.assertEqual(sorted(line["categories"].keys()), sorted(CATEGORY_KEYS + ["other"]))
        self.assertIsInstance(line["categories"]["other"], dict)
        self.assertEqual(
            line["trivial_turn"],
            {"input_tokens": 9, "output_tokens": 5, "cache_creation_input_tokens": 28600,
             "cache_read_input_tokens": 0, "total_cost_usd": 0.0123})
        self.assertEqual(sorted(line["spend"].keys()), ["daily_usd", "weekly_usd"])
        self.assertEqual(line["manifest"], "manifests/2026-10-19T09-00-03Z.json")
        self.assertTrue(os.path.isfile(self.env.p(line["manifest"])))
        self.assertIsInstance(line["warnings"], list)
        self.assertIsInstance(line["denied_mcp_notices"], int)

    def test_ac03_ledger_created_when_absent_with_one_line(self):
        """AC3"""
        line = self.ok_probe()
        self.assertEqual(line["total_always_loaded"], 28700)

    def test_ac06_ccusage_missing(self):
        """AC6"""
        p = self.run_probe(extra={"TOKEN_BUDGET_CCUSAGE_BIN": "/nonexistent/ccusage"})
        self.assertExit(p, 0)
        line = self.env.ledger()[0]
        self.assertIsNone(line["spend"]["daily_usd"])
        self.assertIsNone(line["spend"]["weekly_usd"])
        self.assertIn("ccusage", line["warnings"])

    def test_ac06_ccusage_nonzero_exit(self):
        """AC6"""
        p = self.run_probe(extra={"FAKE_CCUSAGE_MODE": "fail"})
        self.assertExit(p, 0)
        line = self.env.ledger()[0]
        self.assertIsNone(line["spend"]["daily_usd"])
        self.assertIsNone(line["spend"]["weekly_usd"])
        self.assertIn("ccusage", line["warnings"])

    def test_ac06_ccusage_ok_values_are_null_or_numbers(self):
        """AC6 (minimal: ccusage output format is not defined by the spec, see SPEC-GAPS)"""
        line = self.ok_probe()
        for k in ("daily_usd", "weekly_usd"):
            self.assertIn(k, line["spend"])
            v = line["spend"][k]
            self.assertTrue(v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)))


class TestContextParsing(ProbeBase):
    def test_ac04_header_total_window_and_sum_check(self):
        """AC4"""
        self.env.set_context(make_context(BASIC_ROWS, total="16.2k", window="200k"))
        line = self.ok_probe()
        self.assertEqual(line["total_always_loaded"], 16200)
        self.assertEqual(line["context_window"], 200000)
        cats = line["categories"]
        self.assertEqual(line["category_sum_check"], 16185)
        self.assertEqual(line["category_sum_check"], sum_check(cats))
        self.assertNotIn("category_sum_mismatch", line["warnings"])

    def test_ac04_mismatch_over_2_percent_warns_but_succeeds(self):
        """AC4"""
        self.env.set_context(make_context(BASIC_ROWS, total="20.0k", window="200k"))
        line = self.ok_probe()
        self.assertEqual(line["total_always_loaded"], 20000)
        self.assertIn("category_sum_mismatch", line["warnings"])

    def test_ac04_deferred_detail_table_does_not_affect_mcp_tools(self):
        """AC4 (pitfall 1): synthetic ctx lists deferred tools in the detail table; no 'MCP tools' row"""
        self.env.set_context(make_context(BASIC_ROWS))
        line = self.ok_probe()
        self.assertEqual(line["categories"]["mcp_tools"], 0)
        self.assertEqual(line["categories"]["mcp_tools_deferred"], 67000)

    def test_ac05_number_formats(self):
        """AC5: 1.2k / 627 / 12,345"""
        self.env.set_context(make_context(BASIC_ROWS))
        c = self.ok_probe()["categories"]
        self.assertEqual(c["system_prompt"], 1200)
        self.assertEqual(c["system_tools"], 627)
        self.assertEqual(c["memory_files"], 12345)

    def test_ac05_row_name_mapping(self):
        """AC5: 'MCP server instructions' and 'System tools (deferred)'"""
        self.env.set_context(make_context(BASIC_ROWS))
        c = self.ok_probe()["categories"]
        self.assertEqual(c["mcp_server_instructions"], 513)
        self.assertEqual(c["system_tools_deferred"], 22500)
        self.assertEqual(c["mcp_tools_deferred"], 67000)
        self.assertEqual(c["free_space"], 100000)
        self.assertEqual(c["autocompact_buffer"], 33000)
        self.assertEqual(c["messages"], 1500)

    def test_ac05_missing_categories_are_zero_not_absent(self):
        """AC5/4.1.3: missing categories parse as 0"""
        rows = [("System prompt", "3.3k"), ("System tools", "11.2k"), ("Messages", "1.5k")]
        self.env.set_context(make_context(rows, total="16k"))
        c = self.ok_probe()["categories"]
        for k in CATEGORY_KEYS:
            self.assertIn(k, c)
        self.assertEqual(c["skills"], 0)
        self.assertEqual(c["mcp_tools"], 0)

    def test_ac05_skill_token_cells_in_manifest(self):
        """AC5: per-skill '< 20' -> 10, '~110' -> 110, plain numbers as-is"""
        skills = [("alpha-skill", "User", "< 20"), ("beta-skill", "User", "~110"),
                  ("gamma-skill", "User", "1.2k"), ("delta-skill", "Project", "85")]
        self.env.set_context(make_context(BASIC_ROWS, skills=skills))
        line = self.ok_probe()
        m = {s["name"]: s for s in self.env.manifest_of(line)["skills"]}
        self.assertEqual(m["alpha-skill"]["tokens"], 10)
        self.assertEqual(m["beta-skill"]["tokens"], 110)
        self.assertEqual(m["gamma-skill"]["tokens"], 1200)
        self.assertEqual(m["delta-skill"]["tokens"], 85)
        self.assertEqual(m["alpha-skill"]["source"], "user")
        self.assertEqual(m["delta-skill"]["source"], "project")

    def test_unknown_rows_go_to_other_not_dropped(self):
        """4.1.1 (no AC number): unknown rows land in `other`"""
        rows = BASIC_ROWS + [("Mystery thing", "1.1k")]
        self.env.set_context(make_context(rows))
        line = self.ok_probe()
        other = line["categories"]["other"]
        self.assertIn(1100, list(other.values()))
        self.assertTrue(any("mystery" in k.lower() for k in other))

    def test_ac07_enterprise_policy_notices_counted_not_errors(self):
        """AC7"""
        warn = ["Warning: claude.ai MCP servers blocked by enterprise policy: claude.ai Drive",
                "Warning: claude.ai MCP servers blocked by enterprise policy: claude.ai Slack"]
        self.env.set_context(make_context(BASIC_ROWS, warning_lines=warn))
        line = self.ok_probe()
        self.assertEqual(line["denied_mcp_notices"], 2)
        self.assertEqual(line["total_always_loaded"], 16200)
        for w in line["warnings"]:
            self.assertNotIn("enterprise", w.lower())
            self.assertNotIn("blocked", w.lower())

    def test_ac07_no_notices_means_zero(self):
        """AC7"""
        self.env.set_context(make_context(BASIC_ROWS))   # synthetic: no warning line
        self.assertEqual(self.ok_probe()["denied_mcp_notices"], 0)

    def test_ac08_unparseable_context_exit_3_ledger_unchanged(self):
        """AC8"""
        os.makedirs(self.env.state)
        seed = (json.dumps(ledger_line("2026-W42", "2026-10-12T09:00:03Z", 30300)) + "\n").encode()
        write(self.env.ledger_path, seed)
        self.env.set_context("I am sorry, I cannot do that.\nNo tables here.\n")
        p = self.run_probe()
        self.assertExit(p, 3)
        self.assertEqual(read(self.env.ledger_path), seed)
        self.assertEqual([f for f in file_tree(self.env.state) if f.startswith("manifests")], [])

    def test_ac08_unparseable_context_without_prior_ledger(self):
        """AC8"""
        self.env.set_context("garbage\n")
        p = self.run_probe()
        self.assertExit(p, 3)
        self.assertEqual(self.env.ledger(), [])
        self.assertEqual([f for f in file_tree(self.env.state) if f.startswith("manifests")], [])

    def test_ac08_missing_tokens_header_exit_3(self):
        """4.1.1: header missing -> exit 3"""
        self.env.set_context(make_context(BASIC_ROWS, header=False))
        p = self.run_probe()
        self.assertExit(p, 3)
        self.assertEqual(self.env.ledger(), [])


class TestProbeExitCodes(ProbeBase):
    def test_exit_2_claude_missing_nothing_written(self):
        """4.1.3 exit 2 / section 6"""
        p = self.run_probe(extra={"TOKEN_BUDGET_CLAUDE_BIN": "/nonexistent/claude",
                                  "PATH": "/usr/bin:/bin"})
        self.assertExit(p, 2)
        self.assertEqual(self.env.ledger(), [])
        self.assertEqual([f for f in file_tree(self.env.state) if f.startswith("manifests")], [])

    def test_exit_4_trivial_turn_json_unparseable(self):
        """4.1.3 exit 4: no partial ledger line"""
        p = self.run_probe(extra={"FAKE_JSON_MODE": "garbage"})
        self.assertExit(p, 4)
        self.assertEqual(self.env.ledger(), [])

    def test_exit_4_trivial_turn_network_failure(self):
        """section 6: API failure on trivial turn -> exit 4"""
        p = self.run_probe(extra={"FAKE_JSON_MODE": "fail"})
        self.assertExit(p, 4)
        self.assertEqual(self.env.ledger(), [])

    def test_exit_5_state_dir_unwritable(self):
        """4.1.3 exit 5"""
        blocker = os.path.join(self.env.root, "blocker")
        write(blocker, "i am a file")
        p = self.run_probe(extra={"TOKEN_BUDGET_STATE_DIR": os.path.join(blocker, "state")})
        self.assertExit(p, 5)


class TestManifest(ProbeBase):
    def settings(self, **kw):
        s = {"env": {"HARMLESS": "1"}}
        s.update(kw)
        self.env.set_settings(s)

    def manifest(self):
        return self.env.manifest_of(self.ok_probe())

    def test_ac09_top_level_shape_and_sorting(self):
        """AC9"""
        skills = [("zeta", "User", "~50"), ("alpha", "User", "~60"), ("alpha", "Project", "~70"),
                  ("mid", "User", "< 20")]
        self.env.set_context(make_context(BASIC_ROWS, skills=skills))
        m = self.manifest()
        self.assertEqual(m["schema"], 1)
        self.assertEqual(m["ts"], NOW)
        for k in ("skills", "mcp_servers", "denied_mcp_servers", "plugins", "claude_md",
                  "hooks", "skill_overrides", "env"):
            self.assertIn(k, m)
        keys = [(s["name"], s["source"]) for s in m["skills"]]
        self.assertEqual(keys, sorted(keys))
        names = [s["name"] for s in m["mcp_servers"]]
        self.assertEqual(names, sorted(names))
        self.assertEqual(m["denied_mcp_servers"], sorted(m["denied_mcp_servers"]))

    def test_ac09_object_keys_sorted_everywhere(self):
        """AC9: 'Object keys sorted' (checked on the raw file)"""
        self.env.set_context(make_context(BASIC_ROWS, skills=[("a", "User", "~50")]))
        self.settings(skillOverrides={"zz": "off", "aa": "off"})
        line = self.ok_probe()
        bad = []

        def hook(pairs):
            ks = [k for k, _ in pairs]
            if ks != sorted(ks):
                bad.append(ks)
            return dict(pairs)
        json.loads(read(self.env.p(line["manifest"])).decode(), object_pairs_hook=hook)
        self.assertEqual(bad, [])

    def test_ac09_compact_window_null_when_unset(self):
        """AC9"""
        self.settings()
        m = self.manifest()
        self.assertIn("CLAUDE_CODE_AUTO_COMPACT_WINDOW", m["env"])
        self.assertIsNone(m["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"])

    def test_ac09_compact_window_from_settings_env(self):
        """AC9"""
        self.settings(env={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "400000"})
        m = self.manifest()
        self.assertEqual(m["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "400000")

    def test_ac09_compact_window_from_process_env(self):
        """AC9 / 4.1.2: null only if unset in BOTH process env and settings"""
        self.settings()
        p = self.run_probe(extra={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "400000"})
        self.assertExit(p, 0)
        m = self.env.manifest_of(self.env.ledger()[0])
        self.assertEqual(m["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "400000")

    def test_ac09_denied_mcp_servers_from_settings(self):
        """AC9"""
        self.settings(deniedMcpServers=[{"serverName": "claude.ai Slack"}, {"serverName": "Alpha"}])
        m = self.manifest()
        self.assertEqual(m["denied_mcp_servers"], ["Alpha", "claude.ai Slack"])

    def test_ac09_skill_overrides_from_settings(self):
        """AC9 / 4.1.2 example"""
        self.settings(skillOverrides={"some-skill": "off"})
        m = self.manifest()
        self.assertEqual(m["skill_overrides"], {"some-skill": "off"})

    def test_ac09_claude_md_bytes_and_est_tokens(self):
        """AC9 / 4.1.2: est_tokens = ceil(bytes/4)"""
        write(os.path.join(self.env.claude_home, "CLAUDE.md"), "x" * 4210)
        write(os.path.join(self.env.vault, "_CLAUDE.md"), "y" * 9120)
        self.settings()
        m = self.manifest()
        self.assertEqual(m["claude_md"]["user"]["bytes"], 4210)
        self.assertEqual(m["claude_md"]["user"]["est_tokens"], 1053)
        self.assertEqual(m["claude_md"]["vault"]["bytes"], 9120)
        self.assertEqual(m["claude_md"]["vault"]["est_tokens"], 2280)

    def test_ac09_hooks_truncated_to_120_chars(self):
        """AC9 / 4.1.2"""
        cmd = "echo " + "a" * 300
        self.settings(hooks={"SessionStart": [{"matcher": "", "hooks": [
            {"type": "command", "command": cmd}]}]})
        m = self.manifest()
        hooks = [h for h in m["hooks"] if h["event"] == "SessionStart"]
        self.assertEqual(len(hooks), 1)
        self.assertEqual(hooks[0]["matcher"], "")
        self.assertLessEqual(len(hooks[0]["command"]), 120)
        self.assertTrue(hooks[0]["command"].startswith("echo aaaa"))

    def test_ac09_settings_invalid_json_records_warning(self):
        """section 6: invalid settings -> `settings_error` warning, empty hooks/overrides, probe continues"""
        write(self.env.settings, "{ this is not json")
        line = self.ok_probe()
        self.assertIn("settings_error", line["warnings"])
        m = self.env.manifest_of(line)
        self.assertEqual(m["hooks"], [])
        self.assertEqual(m["skill_overrides"], {})

    def test_ac09_plugin_skill_source_from_context(self):
        """AC9 / 4.1.2: skills[].source for plugin skills is plugin:<name>"""
        skills = [("superpowers:brainstorming", "Plugin (superpowers)", "~80")]
        self.env.set_context(make_context(BASIC_ROWS, skills=skills))
        m = self.manifest()
        match = [s for s in m["skills"] if s["name"].endswith("brainstorming")]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["source"], "plugin:superpowers")
        self.assertEqual(match[0]["tokens"], 80)


class TestRedactionNames(ProbeBase):
    def test_skill_names_containing_secretish_words_not_redacted_in_manifest(self):
        """8 redaction: sk- pattern must not fire inside planning-and-task-breakdown; names never redacted"""
        skills = [("planning-and-task-breakdown", "User", "~80"), ("design-tokens", "User", "~60")]
        self.env.set_context(make_context(BASIC_ROWS, skills=skills))
        line = self.ok_probe()
        raw = read(self.env.p(line["manifest"])).decode()
        names = [x["name"] for x in json.loads(raw)["skills"]]
        self.assertIn("planning-and-task-breakdown", names)
        self.assertIn("design-tokens", names)
        self.assertNotIn("[REDACTED]", "".join(names))

    def test_real_looking_sk_key_in_hook_still_redacted(self):
        """8 redaction"""
        self.env.set_settings({"hooks": {"SessionStart": [{"matcher": "", "hooks": [
            {"type": "command", "command": "run --with sk-abc12345678 now"}]}]}})
        skills = [("planning-and-task-breakdown", "User", "~80")]
        self.env.set_context(make_context(BASIC_ROWS, skills=skills))
        line = self.ok_probe()
        raw = read(self.env.p(line["manifest"])).decode()
        self.assertNotIn("sk-abc12345678", raw)
        self.assertIn("[REDACTED]", raw)
        self.assertIn("planning-and-task-breakdown", raw)


class TestSecrets(ProbeBase):
    SECRETS = ["sk-abc12345678", "ghp_abcdefgh12345678", "sk-live1234567890abcd",
               "SUPERSECRETHEADERVALUE", "QUERYSECRET", "CREDFILESECRET", "xoxb-1234567890-abcdef"]

    def test_ac10_no_secret_anywhere_in_state_output(self):
        """AC10"""
        self.env.set_settings({
            "env": {"X_API_KEY": "sk-abc12345678", "OTHER": "fine"},
            "mcpServers": {"leaky": {
                "type": "http", "url": "https://x.example/mcp?key=QUERYSECRET",
                "headers": {"Authorization": "Bearer ghp_abcdefgh12345678",
                            "X-Thing": "SUPERSECRETHEADERVALUE"},
                "env": {"SLACK_TOKEN": "xoxb-1234567890-abcdef"}}},
            "hooks": {"SessionStart": [{"matcher": "", "hooks": [{
                "type": "command",
                "command": 'curl -H "Authorization: Bearer sk-live1234567890abcd" https://h.example/x'}]}]},
        })
        write(os.path.join(self.env.claude_home, ".credentials.json"),
              json.dumps({"token": "CREDFILESECRET"}))
        write(os.path.join(self.env.claude_home, ".mcp.json"),
              json.dumps({"mcpServers": {"leaky2": {"headers": {"Authorization": "SUPERSECRETHEADERVALUE"}}}}))
        p = self.run_probe()
        self.assertExit(p, 0)
        blob = (p.stdout + p.stderr)
        for path, _h in file_tree(self.env.state).items():
            blob += read(os.path.join(self.env.state, path)).decode(errors="replace")
        for s in self.SECRETS:
            self.assertNotIn(s, blob, "secret leaked: %s" % s)

    def test_ac10_secret_in_context_raw_log_is_redacted(self):
        """section 6/8: raw /context saved on parse failure must be redacted"""
        self.env.set_context("garbage with sk-abc12345678 and api_key=ghp_abcdefgh12345678\n")
        p = self.run_probe()
        self.assertExit(p, 3)
        blob = p.stdout + p.stderr
        for path in file_tree(self.env.state):
            blob += read(os.path.join(self.env.state, path)).decode(errors="replace")
        self.assertNotIn("sk-abc12345678", blob)
        self.assertNotIn("ghp_abcdefgh12345678", blob)


class TestRealCaptures(ProbeBase):
    """AC44: the real 2026-10-15 captures parse and satisfy AC4."""

    EXPECT = {
        "before": dict(total=30300, window=1000000, sum=30248, cats={
            "system_prompt": 3300, "system_tools": 11200, "mcp_tools": 627,
            "mcp_server_instructions": 1200, "mcp_tools_deferred": 102100,
            "system_tools_deferred": 22500, "custom_agents": 521, "memory_files": 2000,
            "skills": 9900, "messages": 1500, "free_space": 936700, "autocompact_buffer": 33000}, notices=0),
        "after": dict(total=28700, window=200000, sum=28734, cats={
            "system_prompt": 3300, "system_tools": 11200, "mcp_tools": 0,
            "mcp_server_instructions": 513, "mcp_tools_deferred": 67000,
            "system_tools_deferred": 22500, "custom_agents": 521, "memory_files": 1800,
            "skills": 9900, "messages": 1500, "free_space": 138300, "autocompact_buffer": 33000}, notices=0),
        "after2": dict(total=28700, window=200000, sum=28734, cats={
            "system_prompt": 3300, "system_tools": 11200, "mcp_tools": 0,
            "mcp_server_instructions": 513, "mcp_tools_deferred": 67000,
            "system_tools_deferred": 22500, "custom_agents": 521, "memory_files": 1800,
            "skills": 9900, "messages": 1500, "free_space": 138300, "autocompact_buffer": 33000}, notices=1),
    }
    FILES = {"before": CTX_BEFORE, "after": CTX_AFTER, "after2": CTX_AFTER2}

    def check(self, name):
        exp = self.EXPECT[name]
        self.env.set_context(self.FILES[name])
        line = self.ok_probe()
        self.assertEqual(line["total_always_loaded"], exp["total"])
        self.assertEqual(line["context_window"], exp["window"])
        for k, v in exp["cats"].items():
            self.assertEqual(line["categories"][k], v, k)
        self.assertEqual(line["category_sum_check"], exp["sum"])
        self.assertEqual(line["category_sum_check"], sum_check(line["categories"]))
        self.assertNotIn("category_sum_mismatch", line["warnings"])
        self.assertEqual(line["denied_mcp_notices"], exp["notices"])
        return line

    def test_ac44_before(self):
        """AC44"""
        self.check("before")

    def test_ac44_after(self):
        """AC44"""
        self.check("after")

    def test_ac44_after2_with_enterprise_policy_warning(self):
        """AC44 + AC7: after2 begins with a 'blocked by enterprise policy' warning line"""
        self.check("after2")

    def test_ac44_real_skill_cells_in_manifest(self):
        """AC44 + AC5: real skills table: '~340' -> 340; '< 20' -> 10"""
        self.env.set_context(CTX_AFTER2)
        m = self.env.manifest_of(self.ok_probe())
        by = {}
        for s in m["skills"]:
            by.setdefault(s["name"], []).append(s)
        self.assertEqual(by["academy-guide"][0]["tokens"], 340)
        self.assertEqual(by["academy-guide"][0]["source"], "user")
        self.assertEqual(by["caveman"][0]["tokens"], 140)
        wrap = [s for s in m["skills"] if s["name"].endswith("verification-before-completion")]
        self.assertTrue(wrap)
        self.assertEqual(wrap[0]["tokens"], 10)
        self.assertEqual(wrap[0]["source"], "plugin:superpowers")


if __name__ == "__main__":
    unittest.main()
