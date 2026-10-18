"""setup/lib/merge_settings.py contract tests (ACs 41-45) and merged-install behaviour (AC 46-48)."""
import json, os, unittest
from msharness import Base


def dump(o):
    return json.dumps(o, indent=2, ensure_ascii=False) + "\n"


class MergeBase(Base):
    def merge(self, t, o, tname="t.json", oname="o.json"):
        """t/o: python object or None (= file absent). Returns (CompletedProcess, out_text|None)."""
        s = self.s
        tp, op, out = (os.path.join(s.sb, n) for n in (tname, oname, "out.json"))
        for p, obj in ((tp, t), (op, o)):
            if os.path.exists(p):
                os.remove(p)
            if obj is not None:
                with open(p, "w") as f:
                    f.write(obj if isinstance(obj, str) else json.dumps(obj))
        if os.path.exists(out):
            os.remove(out)
        r = s.lib("merge_settings.py", tp, op, out)
        txt = open(out).read() if os.path.exists(out) else None
        return r, txt


class TestMergeLib(MergeBase):
    def test_ac41_deep_merge_and_key_order(self):  # AC 41
        r, txt = self.merge({"a": {"x": 1, "y": 2}, "b": 1}, {"a": {"y": 3, "z": 4}, "c": 5})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(txt, dump({"a": {"x": 1, "y": 3, "z": 4}, "b": 1, "c": 5}))
        self.assertEqual(list(json.loads(txt)), ["a", "b", "c"])
        self.assertEqual(list(json.loads(txt)["a"]), ["x", "y", "z"])

    def test_ac41_template_key_order_wins_over_overlay_order(self):  # AC 41
        r, txt = self.merge('{"b": 1, "a": 1}', '{"z": 1, "a": 2, "y": 1}')
        self.assertEqual(list(json.loads(txt)), ["b", "a", "z", "y"])

    def test_ac41_unicode_not_escaped(self):  # 11.4 output format
        r, txt = self.merge({"a": "café"}, {})
        self.assertIn("café", txt)
        self.assertTrue(txt.endswith("\n"))

    def test_ac42_union_arrays(self):  # AC 42
        for key in ("allow", "deny", "ask"):
            with self.subTest(key):
                r, txt = self.merge({"permissions": {key: ["A", "B"]}}, {"permissions": {key: ["B", "C"]}})
                self.assertEqual(json.loads(txt)["permissions"][key], ["A", "B", "C"])

    def test_ac42_template_deny_survives_overlay_without_deny(self):  # AC 42
        r, txt = self.merge({"permissions": {"deny": ["Bash(rm -rf /)"]}},
                            {"permissions": {"allow": ["Read"]}})
        d = json.loads(txt)["permissions"]
        self.assertEqual(d["deny"], ["Bash(rm -rf /)"])
        self.assertEqual(d["allow"], ["Read"])

    def test_ac42_union_dedupes_deep_equal_objects(self):  # 11.4
        r, txt = self.merge({"permissions": {"allow": [{"a": 1}, "X", "X"]}},
                            {"permissions": {"allow": [{"a": 1}, "Y", "Y"]}})
        self.assertEqual(json.loads(txt)["permissions"]["allow"], [{"a": 1}, "X", "Y"])

    def test_ac43_other_arrays_replaced(self):  # AC 43
        r, txt = self.merge({"hooks": {"Stop": [{"x": 1}]}, "permissions": {"additionalDirectories": ["/a", "/b"]}},
                            {"hooks": {"Stop": [{"y": 2}]}, "permissions": {"additionalDirectories": ["/c"]}})
        d = json.loads(txt)
        self.assertEqual(d["hooks"]["Stop"], [{"y": 2}])
        self.assertEqual(d["permissions"]["additionalDirectories"], ["/c"])

    def test_ac43_union_only_at_exact_permission_paths(self):  # 11.4 "exactly"
        r, txt = self.merge({"other": {"permissions": {"allow": ["A"]}}},
                            {"other": {"permissions": {"allow": ["B"]}}})
        self.assertEqual(json.loads(txt)["other"]["permissions"]["allow"], ["B"])

    def test_ac44_null_deletes_key(self):  # AC 44
        r, txt = self.merge({"a": 1, "b": {"c": 1, "d": 2}}, {"a": None, "b": {"c": None}})
        self.assertEqual(json.loads(txt), {"b": {"d": 2}})

    def test_ac44_type_mismatch_overlay_wins(self):  # AC 44
        r, txt = self.merge({"a": "str", "b": {"x": 1}}, {"a": {"k": 1}, "b": 7})
        self.assertEqual(json.loads(txt), {"a": {"k": 1}, "b": 7})

    def test_ac44_scalar_overlay_wins(self):  # 11.4
        r, txt = self.merge({"theme": "dark"}, {"theme": "light"})
        self.assertEqual(json.loads(txt), {"theme": "light"})

    def test_ac45_single_input(self):  # AC 45
        t = {"a": {"x": 1}, "b": [1]}
        r, txt = self.merge(t, None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(txt), t)
        r, txt = self.merge(None, t)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(txt), t)

    def test_ac45_deterministic_and_idempotent(self):  # AC 45
        t = {"permissions": {"allow": ["A"], "deny": ["D"]}, "hooks": {"Stop": [1]}, "a": {"x": 1}}
        o = {"permissions": {"allow": ["B"]}, "hooks": {"Stop": [2]}, "a": {"y": 2}, "n": None}
        r1, m1 = self.merge(t, o)
        r2, m2 = self.merge(t, o)
        self.assertEqual(m1, m2)
        r3, m3 = self.merge(json.loads(m1), o)
        self.assertEqual(m1, m3)


class TestMergeInstall(Base):
    """AC 46-48 through bootstrap."""
    def setUp(self):
        super().setUp()
        self.s.pub_reset()

    def boot(self, *a):
        return self.s.run("bootstrap.sh", *a)

    def test_ac46_installed_settings_equals_merge_rendered(self):  # AC 46
        s = self.s
        s.rw("claude/settings.template.json", dump({"cmd": "__HOME__/x", "permissions": {"deny": ["D"]}, "a": 1}))
        s.ow("claude/settings.json", dump({"permissions": {"allow": ["__HOME__/y"]}, "a": 2, "b": "__LABEL_PREFIX__"}))
        r = self.boot("--no-repos", "--no-plugins")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        expected = dump({"cmd": s.home + "/x", "permissions": {"deny": ["D"], "allow": [s.home + "/y"]},
                         "a": 2, "b": "com.machine-setup"})
        self.assertEqual(open(s.home + "/.claude/settings.json").read(), expected)
        r = self.boot("--dry-run", "--no-repos", "--no-plugins")
        self.assertIn("unchanged  .claude/settings.json", r.stdout)

    def test_ac46_dry_run_reports_against_merged(self):  # AC 46
        s = self.s
        s.rw("claude/settings.template.json", dump({"a": 1}))
        s.ow("claude/settings.json", dump({"b": 2}))
        r = self.boot("--dry-run")
        self.assertIn("install    .claude/settings.json", r.stdout)
        s.hw(".claude/settings.json", dump({"a": 1}))           # template only: differs from merged
        r = self.boot("--dry-run")
        self.assertIn("overwrite (backup) .claude/settings.json", r.stdout)
        s.hw(".claude/settings.json", dump({"a": 1, "b": 2}))
        r = self.boot("--dry-run")
        self.assertIn("unchanged  .claude/settings.json", r.stdout)

    def test_ac45_neither_input_no_settings_installed(self):  # AC 45
        r = self.boot("--no-repos", "--no-plugins")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.s.home + "/.claude/settings.json"))
        self.assertNotIn(".claude/settings.json", r.stdout)

    def test_ac47_claude_md_overlay_replaces_template(self):  # AC 47
        s = self.s
        s.rw("claude/CLAUDE.md.template", "TEMPLATE\n")
        s.ow("claude/CLAUDE.md", "OVERLAY __HOME__\n")
        self.assertEqual(self.boot("--no-repos", "--no-plugins").returncode, 0)
        self.assertEqual(open(s.home + "/.claude/CLAUDE.md").read(), "OVERLAY %s\n" % s.home)

    def test_ac47_claude_md_template_when_overlay_lacks(self):  # AC 47
        s = self.s
        s.rw("claude/CLAUDE.md.template", "TEMPLATE\n")
        s.use_overlay()
        self.assertEqual(self.boot("--no-repos", "--no-plugins").returncode, 0)
        self.assertEqual(open(s.home + "/.claude/CLAUDE.md").read(), "TEMPLATE\n")
        self.assertFalse(os.path.exists(s.home + "/.claude/CLAUDE.md.template"))

    def test_ac48_other_claude_files(self):  # AC 48
        s = self.s
        s.rw("claude/hooks/pub.sh", "pub\n")
        s.rw("claude/hooks/both.sh", "public-version\n")
        s.rw("claude/commands/c.md", "pubcmd\n")
        s.ow("claude/hooks/both.sh", "overlay-version\n")
        s.ow("claude/hooks/ov.sh", "ov\n")
        s.ow("claude/agents/a.md", "agent\n")
        s.ow("claude/output-styles/o.md", "style\n")
        s.rw("claude/settings.template.md", "doc only\n")
        self.assertEqual(self.boot("--no-repos", "--no-plugins").returncode, 0)
        c = s.home + "/.claude/"
        self.assertEqual(open(c + "hooks/pub.sh").read(), "pub\n")
        self.assertEqual(open(c + "hooks/both.sh").read(), "overlay-version\n")
        self.assertEqual(open(c + "hooks/ov.sh").read(), "ov\n")
        self.assertEqual(open(c + "agents/a.md").read(), "agent\n")
        self.assertEqual(open(c + "output-styles/o.md").read(), "style\n")
        self.assertEqual(open(c + "commands/c.md").read(), "pubcmd\n")
        self.assertFalse(os.path.exists(c + "settings.template.md"))

    def test_ac48_plugins_union(self):  # AC 48 / 11.4
        s = self.s
        def pj(mks, plugins):
            return json.dumps({"marketplaces": [{"name": n, "source": {"source": "github", "repo": r}, "add_arg": r}
                                                for n, r in mks],
                               "plugins": [{"id": i, "enabled": e, "installed": True, "version": "1"}
                                           for i, e in plugins]})
        s.rw("claude/plugins.json", pj([("mk1", "p/one")], [("a@mk1", True), ("b@mk1", True)]))
        s.ow("claude/plugins.json", pj([("mk2", "o/two")], [("b@mk1", False), ("c@mk2", True)]))
        r = self.boot("--dry-run")
        self.assertIn("claude plugin install a@mk1   (state: enabled)", r.stdout)
        self.assertIn("claude plugin install b@mk1   (state: disabled)", r.stdout)
        self.assertIn("claude plugin install c@mk2   (state: enabled)", r.stdout)
        self.assertIn("(mk1)", r.stdout)
        self.assertIn("(mk2)", r.stdout)

    def test_ac48_overlay_only_plugins_json(self):  # 11.4 both optional
        s = self.s
        s.ow("claude/plugins.json", json.dumps({"marketplaces": [],
             "plugins": [{"id": "z@mk", "enabled": True, "installed": True, "version": "1"}]}))
        r = self.boot("--dry-run")
        self.assertIn("claude plugin install z@mk", r.stdout)
        self.assertNotIn("skipped (no plugins.json)", r.stdout)

    def test_ac48_links_tsv_overlay_row_wins(self):  # 11.4
        s = self.s
        os.makedirs(s.home + "/t1"); os.makedirs(s.home + "/t2")
        s.rw("claude/skills.links.tsv", "lnk\t__HOME__/t1\nonly\t__HOME__/t1\n")
        s.ow("claude/skills.links.tsv", "lnk\t__HOME__/t2\n")
        self.assertEqual(self.boot("--no-repos", "--no-plugins").returncode, 0)
        self.assertEqual(os.readlink(s.home + "/.claude/skills/lnk"), s.home + "/t2")
        self.assertEqual(os.readlink(s.home + "/.claude/skills/only"), s.home + "/t1")


if __name__ == "__main__":
    unittest.main()
