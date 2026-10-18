"""apply.sh contract tests: AC 32-37."""
import copy
import json
import os
import re
import stat
import unittest

from tbharness import *  # noqa

T1 = "2026-10-19T09:30:00Z"
T2 = "2026-10-19T10:30:00Z"


def with_target(settings):
    s = copy.deepcopy(settings)
    s.setdefault("env", {})["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "400000"
    return s


class ApplyBase(Base):
    def setUp(self):
        self.env = apply_setup(self)

    def settings_obj(self):
        return json.loads(read(self.env.settings))


class TestApplyBasics(ApplyBase):
    def test_ac32_apply_compact_window(self):
        """AC32"""
        orig = read(self.env.settings)
        orig_obj = json.loads(orig)
        p = self.env.apply("compact-window", now=T1)
        self.assertExit(p, 0)
        # exactly one new backup, named by UTC compact ts, content == original, mode preserved
        self.assertEqual(self.env.backups(), ["settings.20261019T093000Z.json"])
        bk = self.env.p("backups", "settings.20261019T093000Z.json")
        self.assertEqual(read(bk), orig)
        self.assertEqual(stat.S_IMODE(os.stat(bk).st_mode), 0o640)
        # only the targeted key changed
        new_obj = self.settings_obj()
        self.assertEqual(new_obj, with_target(orig_obj))
        # key order preserved, 2-space indent
        self.assertEqual(list(new_obj.keys()), list(orig_obj.keys()))
        self.assertEqual(list(new_obj["env"].keys()), ["FOO", "CLAUDE_CODE_AUTO_COMPACT_WINDOW"])
        text = read(self.env.settings).decode()
        self.assertEqual(text.rstrip("\n"), json.dumps(new_obj, indent=2))
        # exactly one applied.jsonl line
        lines = self.env.applied()
        self.assertEqual(len(lines), 1)
        ln = lines[0]
        self.assertEqual(ln["schema"], 1)
        self.assertEqual(ln["action"], "apply")
        self.assertEqual(ln["id"], "compact-window")
        self.assertEqual(ln["ts"], T1)
        self.assertEqual(ln["backup"], "backups/settings.20261019T093000Z.json")
        self.assertEqual(os.path.realpath(ln["settings_file"]), os.path.realpath(self.env.settings))
        self.assertEqual(ln["sha256_before"], sha256(bk))
        self.assertEqual(ln["sha256_after"], sha256(self.env.settings))
        self.assertEqual(ln["est_saving_tokens"], 0)

    def test_ac32_apply_only_writes_settings_backups_applied_log(self):
        """section 8: apply.sh writes only: the settings file, backups/, applied.jsonl"""
        before = file_tree(self.env.state)
        self.assertExit(self.env.apply("compact-window", now=T1), 0)
        after = file_tree(self.env.state)
        new = set(after) - set(before)
        self.assertEqual(new, {"applied.jsonl", "backups/settings.20261019T093000Z.json"})
        for k in before:
            self.assertEqual(before[k], after[k], k)

    def test_ac32_json_status_output(self):
        """4.4 --json (flag position is unspecified, see SPEC-GAPS; id first)"""
        p = self.env.apply("compact-window", "--json", now=T1)
        self.assertExit(p, 0)
        self.assertEqual(json.loads(p.stdout.strip().splitlines()[-1]),
                         {"status": "applied", "id": "compact-window"})

    def test_ac33_second_apply_is_idempotent(self):
        """AC33"""
        self.assertExit(self.env.apply("compact-window", now=T1), 0)
        s1 = read(self.env.settings)
        log1 = read(self.env.p("applied.jsonl"))
        b1 = self.env.backups()
        p = self.env.apply("compact-window", now=T2)
        self.assertExit(p, 0)
        self.assertIn("already applied", p.stdout.lower())
        self.assertEqual(read(self.env.settings), s1)
        self.assertEqual(read(self.env.p("applied.jsonl")), log1)
        self.assertEqual(self.env.backups(), b1)

    def test_ac33_second_apply_json_status(self):
        """4.4: status already_applied"""
        self.assertExit(self.env.apply("compact-window", now=T1), 0)
        p = self.env.apply("compact-window", "--json", now=T2)
        self.assertExit(p, 0)
        self.assertEqual(json.loads(p.stdout.strip().splitlines()[-1])["status"], "already_applied")

    def test_list_shows_proposal_ids(self):
        """4.4 --list"""
        p = self.env.apply("--list")
        self.assertExit(p, 0)
        self.assertIn("compact-window", p.stdout)
        self.assertEqual(self.env.backups(), [])

    def test_newest_proposals_file_by_filename_wins(self):
        """4.4: looked up in the newest proposals/*.json by filename sort"""
        old = copy.deepcopy(COMPACT_PROPOSAL)
        old["action"]["ops"][0]["value"] = "111"
        write_proposals(self.env, [old], week="2026-W42")
        p = self.env.apply("compact-window", now=T1)
        self.assertExit(p, 0)
        self.assertEqual(self.settings_obj()["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "400000")

    def test_id_only_in_older_proposals_file_is_not_found(self):
        """4.4: only the newest file is consulted"""
        other = copy.deepcopy(COMPACT_PROPOSAL)
        other["id"] = "skill-off-legacy"
        other["command"] = "apply.sh skill-off-legacy"
        write_proposals(self.env, [other], week="2026-W41")
        self.assertExit(self.env.apply("skill-off-legacy"), 3)


class TestPatchSemantics(ApplyBase):
    def put(self, proposal):
        write_proposals(self.env, [proposal])

    def prop(self, pid, ops, saving=0):
        return {"id": pid, "rule": "R1", "title": "t", "evidence": "e", "est_saving_tokens": saving,
                "risk": "medium", "command": "apply.sh " + pid,
                "action": {"type": "json_patch", "file": "settings", "ops": ops}}

    def test_add_skill_override_creates_object(self):
        """4.2 R1 patch applies: add /skillOverrides/<name> (parent exists in settings)"""
        s = self.settings_obj()
        s["skillOverrides"] = {"existing": "off"}
        self.env.set_settings(s)
        self.put(self.prop("skill-off-foo", [{"op": "add", "path": "/skillOverrides/foo", "value": "off"}], 41))
        self.assertExit(self.env.apply("skill-off-foo", now=T1), 0)
        self.assertEqual(self.settings_obj()["skillOverrides"], {"existing": "off", "foo": "off"})
        self.assertEqual(self.env.applied()[0]["est_saving_tokens"], 41)

    def test_add_array_dash_appends(self):
        """4.4: array '-' append"""
        s = self.settings_obj()
        s["deniedMcpServers"] = [{"serverName": "a"}]
        self.env.set_settings(s)
        self.put(self.prop("mcp-deny-b", [{"op": "add", "path": "/deniedMcpServers/-",
                                           "value": {"serverName": "b"}}]))
        self.assertExit(self.env.apply("mcp-deny-b", now=T1), 0)
        self.assertEqual(self.settings_obj()["deniedMcpServers"],
                         [{"serverName": "a"}, {"serverName": "b"}])

    def test_add_array_dash_skips_if_equal_element_exists(self):
        """4.4: array '-' append skips if an equal element exists (counts as already applied)"""
        s = self.settings_obj()
        s["deniedMcpServers"] = [{"serverName": "b"}]
        self.env.set_settings(s)
        before = read(self.env.settings)
        self.put(self.prop("mcp-deny-b", [{"op": "add", "path": "/deniedMcpServers/-",
                                           "value": {"serverName": "b"}}]))
        p = self.env.apply("mcp-deny-b", now=T1)
        self.assertExit(p, 0)
        self.assertEqual(read(self.env.settings), before)
        self.assertEqual(self.env.backups(), [])
        self.assertEqual(self.env.applied(), [])

    def test_add_same_value_is_noop_counts_as_already_applied(self):
        """4.4: add to an existing path with the same value = no-op"""
        s = self.settings_obj()
        s["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "400000"
        self.env.set_settings(s)
        before = read(self.env.settings)
        p = self.env.apply("compact-window", now=T1)
        self.assertExit(p, 0)
        self.assertEqual(read(self.env.settings), before)
        self.assertEqual(self.env.backups(), [])
        self.assertEqual(self.env.applied(), [])

    def test_replace_missing_path_exit_4_no_change(self):
        """4.4: replace on a missing path -> exit 4"""
        self.put(self.prop("repl", [{"op": "replace", "path": "/nope/missing", "value": "x"}]))
        before = read(self.env.settings)
        p = self.env.apply("repl", now=T1)
        self.assertExit(p, 4)
        self.assertEqual(read(self.env.settings), before)
        self.assertEqual(self.env.applied(), [])

    def test_replace_existing_path_and_remove(self):
        """4.2 RFC 6902 subset: replace, remove"""
        self.put(self.prop("multi", [{"op": "replace", "path": "/model", "value": "sonnet"},
                                     {"op": "remove", "path": "/zeta"}]))
        self.assertExit(self.env.apply("multi", now=T1), 0)
        s = self.settings_obj()
        self.assertEqual(s["model"], "sonnet")
        self.assertNotIn("zeta", s)
        self.assertEqual(s["permissions"], DEFAULT_SETTINGS["permissions"])
        self.assertEqual(list(s.keys()), ["model", "env", "permissions", "hooks"])

    def test_failed_multi_op_patch_applies_nothing(self):
        """4.4/section 6: patch cannot apply -> exit 4 and nothing written"""
        self.put(self.prop("half", [{"op": "replace", "path": "/model", "value": "sonnet"},
                                    {"op": "replace", "path": "/not/there", "value": 1}]))
        before = read(self.env.settings)
        self.assertExit(self.env.apply("half", now=T1), 4)
        self.assertEqual(read(self.env.settings), before)
        self.assertEqual(self.env.applied(), [])


class TestMissingParent(Base):
    def test_add_creates_missing_parent_objects(self):
        """4.4: `add` creates missing parent objects (absent env)"""
        env = self.env = apply_setup(self, settings={"model": "opus", "zeta": [1]})
        p = env.apply("compact-window", now=T1)
        self.assertExit(p, 0)
        s = json.loads(read(env.settings))
        self.assertEqual(s["env"], {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "400000"})
        self.assertEqual(s["model"], "opus")
        self.assertEqual(len(env.backups()), 1)
        self.assertEqual(len(env.applied()), 1)

    def test_add_skill_override_creates_missing_skilloverrides(self):
        """4.4: absent skillOverrides is created"""
        env = self.env = apply_setup(self, settings={"model": "opus"}, proposals=[{
            "id": "skill-off-foo", "rule": "R1", "title": "t", "evidence": "e",
            "est_saving_tokens": 41, "risk": "medium", "command": "apply.sh skill-off-foo",
            "action": {"type": "json_patch", "file": "settings", "ops": [
                {"op": "add", "path": "/skillOverrides/foo", "value": "off"}]}}])
        self.assertExit(env.apply("skill-off-foo", now=T1), 0)
        self.assertEqual(json.loads(read(env.settings))["skillOverrides"], {"foo": "off"})


class TestRevert(ApplyBase):
    def test_ac34_revert_restores_byte_identical(self):
        """AC34"""
        orig = read(self.env.settings)
        self.assertExit(self.env.apply("compact-window", now=T1), 0)
        self.assertNotEqual(read(self.env.settings), orig)
        p = self.env.apply("--revert", "compact-window", now=T2)
        self.assertExit(p, 0)
        self.assertEqual(read(self.env.settings), orig)
        lines = self.env.applied()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[1]["action"], "revert")
        self.assertEqual(lines[1]["id"], "compact-window")
        self.assertEqual(lines[1]["restored_from"], "backups/settings.20261019T093000Z.json")

    def test_ac34_second_revert_is_noop(self):
        """AC34"""
        self.assertExit(self.env.apply("compact-window", now=T1), 0)
        self.assertExit(self.env.apply("--revert", "compact-window", now=T2), 0)
        s1 = read(self.env.settings)
        log1 = read(self.env.p("applied.jsonl"))
        bk1 = self.env.backups()
        p = self.env.apply("--revert", "compact-window", now="2026-10-19T11:30:00Z")
        self.assertExit(p, 0)
        self.assertIn("not applied", p.stdout.lower())
        self.assertEqual(read(self.env.settings), s1)
        self.assertEqual(read(self.env.p("applied.jsonl")), log1)
        self.assertEqual(self.env.backups(), bk1)

    def test_ac34_revert_never_applied_is_noop(self):
        """4.4: not applied -> exit 0 'not applied', no write"""
        before = read(self.env.settings)
        p = self.env.apply("--revert", "compact-window", now=T1)
        self.assertExit(p, 0)
        self.assertIn("not applied", p.stdout.lower())
        self.assertEqual(read(self.env.settings), before)
        self.assertEqual(self.env.applied(), [])

    def test_ac34_revert_json_status(self):
        """4.4 --json statuses reverted / not_applied"""
        self.assertExit(self.env.apply("compact-window", now=T1), 0)
        p = self.env.apply("--revert", "compact-window", "--json", now=T2)
        self.assertExit(p, 0)
        self.assertEqual(json.loads(p.stdout.strip().splitlines()[-1]),
                         {"status": "reverted", "id": "compact-window"})
        p = self.env.apply("--revert", "compact-window", "--json", now="2026-10-19T11:30:00Z")
        self.assertEqual(json.loads(p.stdout.strip().splitlines()[-1])["status"], "not_applied")

    def test_apply_again_after_revert_works(self):
        """4.4: latest apply line with no later revert"""
        self.assertExit(self.env.apply("compact-window", now=T1), 0)
        self.assertExit(self.env.apply("--revert", "compact-window", now=T2), 0)
        p = self.env.apply("compact-window", now="2026-10-19T11:30:00Z")
        self.assertExit(p, 0)
        self.assertEqual(self.settings_obj()["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "400000")
        self.assertEqual(len(self.env.backups()), 2)
        self.assertEqual([l["action"] for l in self.env.applied()], ["apply", "revert", "apply"])

    def test_ac35_revert_after_hand_edit_refused_exit_5(self):
        """AC35"""
        self.assertExit(self.env.apply("compact-window", now=T1), 0)
        s = self.settings_obj()
        s["handEdited"] = True
        self.env.set_settings(s)
        edited = read(self.env.settings)
        log1 = read(self.env.p("applied.jsonl"))
        p = self.env.apply("--revert", "compact-window", now=T2)
        self.assertExit(p, 5)
        self.assertEqual(read(self.env.settings), edited)
        self.assertEqual(read(self.env.p("applied.jsonl")), log1)

    def test_ac35_force_restores_after_hand_edit(self):
        """AC35"""
        orig = read(self.env.settings)
        self.assertExit(self.env.apply("compact-window", now=T1), 0)
        s = self.settings_obj()
        s["handEdited"] = True
        self.env.set_settings(s)
        p = self.env.apply("--revert", "compact-window", "--force", now=T2)
        self.assertExit(p, 0)
        self.assertEqual(read(self.env.settings), orig)
        self.assertEqual(self.env.applied()[-1]["action"], "revert")

    def test_exit_5_backup_missing(self):
        """4.4 exit 5: 'backup missing'"""
        self.assertExit(self.env.apply("compact-window", now=T1), 0)
        for b in self.env.backups():
            os.remove(self.env.p("backups", b))
        after_apply = read(self.env.settings)
        p = self.env.apply("--revert", "compact-window", now=T2)
        self.assertExit(p, 5)
        self.assertEqual(read(self.env.settings), after_apply)


class TestExitCodes(ApplyBase):
    def test_ac36_unknown_id_exit_3(self):
        """AC36"""
        before = read(self.env.settings)
        self.assertExit(self.env.apply("no-such-proposal"), 3)
        self.assertEqual(read(self.env.settings), before)
        self.assertEqual(self.env.backups(), [])

    def test_ac36_no_proposals_dir_exit_3(self):
        """AC36: not found"""
        import shutil
        shutil.rmtree(self.env.p("proposals"))
        self.assertExit(self.env.apply("compact-window"), 3)

    def test_ac36_two_ids_exit_2(self):
        """AC36"""
        other = copy.deepcopy(COMPACT_PROPOSAL)
        other["id"] = "skill-off-x"
        write_proposals(self.env, [COMPACT_PROPOSAL, other])
        before = read(self.env.settings)
        self.assertExit(self.env.apply("compact-window", "skill-off-x"), 2)
        self.assertEqual(read(self.env.settings), before)
        self.assertEqual(self.env.backups(), [])

    def test_no_args_exit_2(self):
        """4.4 usage error"""
        self.assertExit(self.env.apply(), 2)

    def test_ac36_flag_proposal_exit_6(self):
        """AC36"""
        flag = {"id": "plugin-unused-foo", "rule": "R7", "title": "t", "evidence": "e",
                "est_saving_tokens": 0, "risk": "low", "command": "apply.sh plugin-unused-foo",
                "action": {"type": "flag", "note": "disable via /plugin"}}
        write_proposals(self.env, [flag])
        before = read(self.env.settings)
        p = self.env.apply("plugin-unused-foo")
        self.assertExit(p, 6)
        self.assertEqual(read(self.env.settings), before)
        self.assertEqual(self.env.backups(), [])
        self.assertEqual(self.env.applied(), [])

    def shell_proposal(self):
        victim = os.path.join(self.env.root, "victim-skill-dir")
        os.makedirs(victim)
        write(os.path.join(victim, "SKILL.md"), "x")
        prop = {"id": "skill-dup-foo-user", "rule": "R2", "title": "t", "evidence": "e",
                "est_saving_tokens": 50, "risk": "low", "command": "apply.sh skill-dup-foo-user",
                "action": {"type": "shell", "argv": ["rm", "-r", victim]}}
        write_proposals(self.env, [prop])
        return victim

    def test_ac36_shell_without_yes_exit_7_no_change(self):
        """AC36"""
        victim = self.shell_proposal()
        before = read(self.env.settings)
        p = self.env.apply("skill-dup-foo-user")
        self.assertExit(p, 7)
        self.assertTrue(os.path.isdir(victim))
        self.assertEqual(read(self.env.settings), before)
        self.assertEqual(self.env.backups(), [])
        self.assertEqual(self.env.applied(), [])
        self.assertIn(victim, p.stdout + p.stderr)  # prints the argv

    def test_ac36_shell_with_yes_runs_argv(self):
        """4.4: shell proposals require --yes"""
        victim = self.shell_proposal()
        p = self.env.apply("skill-dup-foo-user", "--yes")
        self.assertExit(p, 0)
        self.assertFalse(os.path.exists(victim))

    def test_ac36_invalid_settings_json_exit_8_no_change(self):
        """AC36"""
        write(self.env.settings, "{ not json at all")
        before = read(self.env.settings)
        p = self.env.apply("compact-window", now=T1)
        self.assertExit(p, 8)
        self.assertEqual(read(self.env.settings), before)
        self.assertEqual(self.env.backups(), [])
        self.assertEqual(self.env.applied(), [])

    def test_exit_8_settings_missing(self):
        """4.4 exit 8: settings file missing"""
        os.remove(self.env.settings)
        p = self.env.apply("compact-window", now=T1)
        self.assertExit(p, 8)
        self.assertFalse(os.path.exists(self.env.settings))
        self.assertEqual(self.env.applied(), [])

    @unittest.skipIf(os.geteuid() == 0, "root ignores directory permissions")
    def test_ac37_unwritable_backup_dir_leaves_settings_identical(self):
        """AC37"""
        bdir = self.env.p("backups")
        os.makedirs(bdir)
        os.chmod(bdir, 0o500)
        self.addCleanup(os.chmod, bdir, 0o700)
        before = read(self.env.settings)
        p = self.env.apply("compact-window", now=T1)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(read(self.env.settings), before)
        self.assertEqual(self.env.applied(), [])

    def test_ac37_backups_path_is_a_file(self):
        """AC37 (portable variant): backup cannot be created"""
        write(self.env.p("backups"), "i am a file, not a dir")
        before = read(self.env.settings)
        p = self.env.apply("compact-window", now=T1)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(read(self.env.settings), before)
        self.assertEqual(self.env.applied(), [])

    def test_failure_leaves_no_temp_files_next_to_settings(self):
        """4.4: temp + atomic mv; failed apply (exit 4) leaves the directory unchanged"""
        write_proposals(self.env, [{
            "id": "repl", "rule": "R1", "title": "t", "evidence": "e", "est_saving_tokens": 0,
            "risk": "low", "command": "apply.sh repl",
            "action": {"type": "json_patch", "file": "settings",
                       "ops": [{"op": "replace", "path": "/nope", "value": 1}]}}])
        before = sorted(os.listdir(os.path.dirname(self.env.settings)))
        self.assertExit(self.env.apply("repl", now=T1), 4)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.env.settings))), before)


if __name__ == "__main__":
    unittest.main()
