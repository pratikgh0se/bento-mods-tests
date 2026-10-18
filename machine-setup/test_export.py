"""export.sh contract tests (ACs 12-15, 17, 17a, 56-65). Always runs WITH an overlay unless stated."""
import json, os, re, unittest
from msharness import Base, PLIST, DEFAULT_PREFIX

TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3"
GEN_DIRS = ("claude/hooks/", "claude/commands/", "claude/skills/", "claude/agents/", "claude/output-styles/")


def dump(o):
    return json.dumps(o, indent=2, ensure_ascii=False) + "\n"


class ExportBase(Base):
    def setUp(self):
        super().setUp()
        self.s.basic_home()
        self.s.use_overlay()

    def export(self, *a, **kw):
        return self.s.run("export.sh", *a, **kw)

    def ov(self, rel):
        return os.path.join(self.s.ov, rel)

    def rp(self, rel):
        return os.path.join(self.s.repo, rel)

    def ovr(self, rel):
        with open(self.ov(rel)) as f:
            return f.read()

    def pub_changed(self, before):
        after = self.s.snapshot(self.s.repo)
        return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))

    def commit_both(self):
        self.s.git_init(self.s.repo)
        self.s.git_init(self.s.ov)


class TestExport(ExportBase):
    def test_ac12_ac57_outputs_overlay_and_home_tokenised(self):  # AC 12, 57
        s = self.s
        before = s.snapshot(s.repo)
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for f in ("claude/settings.json", "claude/CLAUDE.md", "claude/placeholders.txt",
                  "claude/plugins.json", "repos.tsv"):
            self.assertTrue(os.path.exists(self.ov(f)), f)
        heads = re.findall(r"^== (.+)$", r.stdout, re.M)
        want = ["overlay", "claude", "agents (~/.agents)", "launchd", "repos", "secret scan", "leak scan"]
        self.assertEqual([h for h in heads if h in want], want, heads)
        self.assertIn("  overlay: " + s.ov, r.stdout)
        changed = self.pub_changed(before)
        self.assertEqual([c for c in changed if not c.startswith(GEN_DIRS)], [], changed)
        for base in (s.repo, s.ov):
            self.assertIsNone(s.tree_has_text(base, s.home))
        for f in ("claude/settings.json", "claude/CLAUDE.md", "claude/hooks/a.sh"):
            self.assertIn("__HOME__", self.ovr(f), f)

    def test_ac57_never_written_public_files_unchanged(self):  # AC 57
        s = self.s
        s.rw("repos.tsv.example", "x\n")
        s.rw("agents/skill-lock.json", "{}\n")
        s.rw("claude/plugins.json", '{"marketplaces": [], "plugins": []}\n')
        s.rw("claude/placeholders.txt", "")
        s.rw("claude/skills.links.tsv", "")
        s.rw("claude/hook-deps.tsv", "")
        s.rw("claude/settings.template.json", dump({"a": 1}))
        s.rw("claude/CLAUDE.md.template", "t\n")
        s.rw("launchd/deps.tsv", "# label\trequired_path\trepo\tneeds\n")
        s.rw("docs/note.md", "doc\n")
        before = s.snapshot(s.repo)
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([c for c in self.pub_changed(before) if not c.startswith(GEN_DIRS)], [])

    def test_ac14_removed_hook_and_no_pycache(self):  # AC 14
        s = self.s
        s.hw(".claude/hooks/b.sh", "echo b\n")
        s.hw(".claude/hooks/__pycache__/m.cpython-312.pyc", "x")
        s.hw(".claude/hooks/m.pyc", "x")
        s.hw(".claude/hooks/.DS_Store", "x")
        self.assertEqual(self.export().returncode, 0)
        self.assertTrue(os.path.exists(self.ov("claude/hooks/b.sh")))
        os.remove(s.home + "/.claude/hooks/b.sh")
        self.assertEqual(self.export().returncode, 0)
        self.assertFalse(os.path.exists(self.ov("claude/hooks/b.sh")))
        self.assertTrue(os.path.exists(self.ov("claude/hooks/a.sh")))
        for base in (s.ov, s.repo):
            for dp, dn, fn in os.walk(os.path.join(base, "claude")):
                self.assertNotIn("__pycache__", dn)
                for n in fn:
                    self.assertFalse(n.endswith(".pyc") or n == ".DS_Store", n)

    def test_sec4_absent_source_dir_removes_overlay_dir(self):  # section 4 / 11.6
        self.s.ow("claude/agents/stale.md", "x\n")
        self.s.ow("claude/output-styles/stale.md", "x\n")
        self.assertEqual(self.export().returncode, 0)
        self.assertFalse(os.path.exists(self.ov("claude/agents")))
        self.assertFalse(os.path.exists(self.ov("claude/output-styles")))

    def test_ac15_skill_symlinks(self):  # AC 15
        s = self.s
        s.hw(".claude/skills/real/SKILL.md", "# real\n")
        s.hw(".claude/skills/synced/x/SKILL.md", "# synced\n")
        os.makedirs(s.home + "/elsewhere/lnk")
        os.symlink(s.home + "/elsewhere/lnk", s.home + "/.claude/skills/lnk")
        s.hw(".claude/commands/c.md", "c\n")
        os.symlink(s.home + "/elsewhere/lnk", s.home + "/.claude/commands/clink")
        self.assertEqual(self.export().returncode, 0)
        self.assertIn("lnk\t__HOME__/elsewhere/lnk", self.ovr("claude/skills.links.tsv").splitlines())
        self.assertIn("clink\t__HOME__/elsewhere/lnk", self.ovr("claude/commands.links.tsv").splitlines())
        self.assertFalse(os.path.lexists(self.ov("claude/skills/lnk")))
        self.assertFalse(os.path.lexists(self.ov("claude/skills/synced")))
        self.assertTrue(os.path.isfile(self.ov("claude/skills/real/SKILL.md")))
        self.assertTrue(os.path.isfile(self.ov("claude/commands/c.md")))
        rows = self.ovr("claude/skills.links.tsv").splitlines()
        self.assertEqual(rows, sorted(rows))

    def test_sec4_repos_tsv_in_overlay(self):  # section 4 / 11.6 repos.tsv
        s = self.s
        base = s.home + "/CodeBase"
        for n in ("zeta", "alpha", "machine-setup", "machine-setup-private", "detached", "nolink"):
            d = os.path.join(base, n)
            os.makedirs(d)
            s.sh("git", "init", "-q", cwd=d)
            s.sh("git", "commit", "-q", "--allow-empty", "-m", "i", cwd=d)
            if n != "nolink":
                s.sh("git", "remote", "add", "origin", "git@example.invalid:me/%s.git" % n, cwd=d)
        sha = s.sh("git", "rev-parse", "HEAD", cwd=base + "/detached").stdout.strip()
        s.sh("git", "checkout", "-q", "--detach", sha, cwd=base + "/detached")
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.rp("repos.tsv")))
        rows = [l.split("\t") for l in self.ovr("repos.tsv").splitlines() if l and not l.startswith("#")]
        names = [x[0] for x in rows]
        self.assertEqual(names, sorted(names))
        by = {x[0].rsplit("/", 1)[1]: x for x in rows}
        self.assertEqual(set(by), {"alpha", "zeta", "detached", "nolink"})
        self.assertTrue(rows[0][0].startswith("__HOME__/CodeBase/"))
        self.assertEqual(by["alpha"][1:4], ["repo", "git@example.invalid:me/alpha.git", "main"])
        self.assertEqual(by["nolink"][1], "local-only")
        self.assertEqual(by["detached"][3], "(detached)")

    def test_ac17a_plugins_step_failure_is_fatal(self):  # AC 17a
        for label, content in (("missing", None), ("invalid", "{not json")):
            with self.subTest(label):
                p = self.s.home + "/.claude/plugins/installed_plugins.json"
                if content is None:
                    os.remove(p)
                else:
                    with open(p, "w") as f:
                        f.write(content)
                r = self.export()
                self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertNotRegex(r.stdout, r"(?m)^\s+plugins\.json\s*$")
                self.s.hw(".claude/plugins/installed_plugins.json", '{"version": 2, "plugins": {}}\n')


class TestNoOverlay(Base):
    def test_ac56_no_overlay_refuses(self):  # AC 56
        s = self.s
        s.basic_home()
        before_repo = s.snapshot(s.repo)
        before_home = s.snapshot(s.home)
        for priv in ("none", None):
            r = s.run("export.sh", priv=priv)
            self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
            self.assertEqual(r.stdout, "")
            self.assertIn("refusing to write personal files", r.stderr)
            self.assertEqual(before_repo, s.snapshot(s.repo))
            self.assertEqual(before_home, s.snapshot(s.home))
        self.assertFalse(os.path.exists(os.path.join(s.work, "machine-setup-private")))

    def test_ac56_dry_run_without_overlay_also_refuses(self):  # 11.6 "no mode"
        self.s.basic_home()
        r = self.s.run("export.sh", "--dry-run", priv="none")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(r.stdout, "")

    def test_ac56_no_public_only_flag(self):  # 11.6 "no --public-only"
        r = self.s.run("export.sh", "--public-only", priv="none")
        self.assertNotEqual(r.returncode, 0)


class TestSettingsDiff(ExportBase):
    TEMPLATE = {"a": 1, "b": {"c": 1, "d": 2}, "permissions": {"allow": ["A"], "deny": ["D"]},
                "gone": True, "hooks": {"Stop": [1]}, "other": [1]}

    def live(self, obj):
        self.s.hw(".claude/settings.json", json.dumps(obj))

    def test_ac58_round_trip_and_only_differing_leaves(self):  # AC 58
        s = self.s
        s.rw("claude/settings.template.json", dump(self.TEMPLATE))
        live = {"a": 2, "b": {"c": 1, "d": 2}, "extra": "x",
                "permissions": {"allow": ["A", "B"], "deny": ["D"]},
                "hooks": {"Stop": [1]}, "other": [1, 2]}
        self.live(live)
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        got = json.loads(self.ovr("claude/settings.json"))
        self.assertEqual(got, {"a": 2, "extra": "x", "permissions": {"allow": ["B"]},
                               "gone": None, "other": [1, 2]})
        out = os.path.join(s.sb, "rt.json")
        rr = s.lib("merge_settings.py", self.rp("claude/settings.template.json"),
                   self.ov("claude/settings.json"), out)
        self.assertEqual(rr.returncode, 0, rr.stderr)
        with open(out) as f:
            self.assertEqual(json.loads(f.read()), live)

    def test_ac58_live_equal_template_gives_empty_object(self):  # AC 58
        s = self.s
        s.rw("claude/settings.template.json", dump(self.TEMPLATE))
        self.live(self.TEMPLATE)
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(self.ovr("claude/settings.json")), {})

    def test_ac58_template_union_item_missing_warns(self):  # AC 58
        s = self.s
        s.rw("claude/settings.template.json", dump({"permissions": {"deny": ["D", "E"]}}))
        self.live({"permissions": {"deny": ["D"]}})
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("  warning: template permission entry not expressible in overlay", r.stdout)

    def test_ac59_secret_scrubbing(self):  # AC 59 (carries 18-21)
        s = self.s
        s.rw("claude/settings.template.json", dump({}))
        self.live({"env": {"MY_API_TOKEN": "abc123", "PLAIN": "v"}})
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = json.loads(self.ovr("claude/settings.json"))
        self.assertEqual(d["env"]["MY_API_TOKEN"], "__SECRET:ENV_MY_API_TOKEN__")
        self.assertEqual(d["env"]["PLAIN"], "v")
        self.assertIn("ENV_MY_API_TOKEN", self.ovr("claude/placeholders.txt").splitlines())
        self.assertIsNone(s.tree_has_text(s.ov, "abc123"))
        self.assertIsNone(s.tree_has_text(s.repo, "abc123"))


class TestGenericRefresh(ExportBase):
    def test_ac60_public_generic_refresh(self):  # AC 60
        s = self.s
        s.rw("claude/hooks/x.sh", "old\n")
        s.rw("claude/hooks/z.sh", "keep\n")
        s.ow("claude/hooks/o.sh", "was-on-machine\n")
        s.hw(".claude/hooks/x.sh", "new %s\n" % s.home)
        s.hw(".claude/hooks/y.sh", "brand new\n")
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(self.rp("claude/hooks/x.sh")) as f:
            self.assertEqual(f.read(), "new __HOME__\n")
        self.assertFalse(os.path.exists(self.ov("claude/hooks/x.sh")))
        self.assertFalse(os.path.exists(self.rp("claude/hooks/y.sh")))
        self.assertEqual(self.ovr("claude/hooks/y.sh"), "brand new\n")
        with open(self.rp("claude/hooks/z.sh")) as f:
            self.assertEqual(f.read(), "keep\n")
        self.assertIn("  public: claude/hooks/z.sh not on this machine, left unchanged", r.stdout)
        self.assertFalse(os.path.exists(self.ov("claude/hooks/o.sh")))
        self.assertTrue(os.path.exists(self.ov("claude/hooks/a.sh")))

    def test_ac60_export_never_creates_or_deletes_public_files(self):  # 11.6
        s = self.s
        s.rw("claude/hooks/z.sh", "keep\n")
        before = s.snapshot(s.repo)
        self.assertEqual(self.export().returncode, 0)
        self.assertEqual(set(before), set(s.snapshot(s.repo)))

    def test_ac61_launchd_capture_default_prefix(self):  # AC 61
        s = self.s
        auto = DEFAULT_PREFIX + ".machine-setup-autosync"
        s.hw("Library/LaunchAgents/com.machine-setup.foo.plist", PLIST % ("com.machine-setup.foo", s.home, "foo"))
        s.hw("Library/LaunchAgents/com.other.bar.plist", PLIST % ("com.other.bar", s.home, "bar"))
        s.hw("Library/LaunchAgents/%s.plist" % auto, PLIST % (auto, s.home, "auto"))
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        p = self.ov("launchd/com.machine-setup.foo.plist")
        self.assertTrue(os.path.isfile(p), r.stdout)
        with open(p) as f:
            txt = f.read()
        self.assertIn("__LABEL_PREFIX__.foo", txt)
        self.assertIn("__HOME__/bin/foo", txt)
        self.assertNotIn(s.home, txt)
        self.assertNotIn("<string>com.machine-setup.foo</string>", txt)
        self.assertFalse(os.path.exists(self.ov("launchd/com.other.bar.plist")))
        self.assertEqual([f for f in os.listdir(self.ov("launchd")) if "autosync" in f], [])
        self.assertFalse(os.path.exists(self.rp("launchd/%s.plist" % auto)))
        self.assertTrue(self.ovr("launchd/deps.tsv").startswith("# label\trequired_path\trepo\tneeds"))

    def test_ac61_launchd_capture_custom_prefix(self):  # AC 61
        s = self.s
        s.ow("config.env", "LABEL_PREFIX=com.other\n")
        s.hw("Library/LaunchAgents/com.machine-setup.foo.plist", PLIST % ("com.machine-setup.foo", s.home, "foo"))
        s.hw("Library/LaunchAgents/com.other.bar.plist", PLIST % ("com.other.bar", s.home, "bar"))
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        p = self.ov("launchd/com.other.bar.plist")
        self.assertTrue(os.path.isfile(p))
        self.assertIn("__LABEL_PREFIX__.bar", self.ovr("launchd/com.other.bar.plist"))
        self.assertFalse(os.path.exists(self.ov("launchd/com.machine-setup.foo.plist")))

    def test_ac61_old_overlay_plists_removed(self):  # section 4 "old plists removed first"
        s = self.s
        s.ow("launchd/com.machine-setup.old.plist", PLIST % ("__LABEL_PREFIX__.old", "__HOME__", "o"))
        s.hw("Library/LaunchAgents/com.machine-setup.foo.plist", PLIST % ("com.machine-setup.foo", s.home, "foo"))
        self.assertEqual(self.export().returncode, 0)
        self.assertFalse(os.path.exists(self.ov("launchd/com.machine-setup.old.plist")))
        os.remove(s.home + "/Library/LaunchAgents/com.machine-setup.foo.plist")
        self.assertEqual(self.export().returncode, 0)
        self.assertFalse(os.path.exists(self.ov("launchd/com.machine-setup.foo.plist")))

    def test_ac61_template_label_plist_not_exported(self):  # AC 61 (label of a public template)
        s = self.s
        s.pub_reset(claude=False)
        s.rw("launchd/mine.plist.tmpl", PLIST % ("__LABEL_PREFIX__.mine", "__HOME__", "m"))
        s.hw("Library/LaunchAgents/com.machine-setup.mine.plist", PLIST % ("com.machine-setup.mine", s.home, "m"))
        self.assertEqual(self.export().returncode, 0)
        self.assertFalse(os.path.exists(self.ov("launchd/com.machine-setup.mine.plist")))
        self.assertFalse(os.path.exists(self.rp("launchd/com.machine-setup.mine.plist")))


class TestIdempotentDryRun(ExportBase):
    def test_ac62_idempotent_both_repos(self):  # AC 13 / 62
        s = self.s
        s.hw(".claude/skills/real/SKILL.md", "# s\n")
        s.hw(".claude/commands/c.md", "cmd\n")
        os.makedirs(s.home + "/elsewhere")
        os.symlink(s.home + "/elsewhere", s.home + "/.claude/skills/lnk")
        s.hw("Library/LaunchAgents/com.machine-setup.a.plist", PLIST % ("com.machine-setup.a", s.home, "a"))
        s.hw(".claude/settings.json", json.dumps({"env": {"MY_API_TOKEN": "abc"}, "p": s.home}))
        self.assertEqual(self.export().returncode, 0)
        snap_pub, snap_ov = s.snapshot(s.repo), s.snapshot(s.ov)
        self.commit_both()
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(snap_pub, s.snapshot(s.repo))
        self.assertEqual(snap_ov, s.snapshot(s.ov))
        self.assertEqual(s.sh("git", "status", "--porcelain", cwd=s.repo).stdout, "")
        self.assertEqual(s.sh("git", "status", "--porcelain", cwd=s.ov).stdout, "")

    def test_ac63_dry_run(self):  # AC 63
        s = self.s
        s.rw("claude/hooks/x.sh", "old\n")
        s.hw(".claude/hooks/x.sh", "new\n")
        pub0, ov0 = s.snapshot(s.repo), s.snapshot(s.ov)
        r = self.export("--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("  would write [overlay] claude/CLAUDE.md", r.stdout)
        self.assertIn("  would write [overlay] claude/settings.json", r.stdout)
        self.assertIn("  would write [public] claude/hooks/x.sh", r.stdout)
        self.assertEqual(pub0, s.snapshot(s.repo))
        self.assertEqual(ov0, s.snapshot(s.ov))
        self.assertEqual(self.export("-n").returncode, 0)
        self.assertEqual(self.export().returncode, 0)
        r3 = self.export("--dry-run")
        self.assertEqual(r3.returncode, 0)
        self.assertNotIn("would write [overlay] claude/CLAUDE.md", r3.stdout)
        s.hw(".claude/CLAUDE.md", "changed\n")
        r4 = self.export("--dry-run")
        self.assertIn("would write [overlay] claude/CLAUDE.md", r4.stdout)
        self.assertNotIn("would write [overlay] claude/settings.json", r4.stdout)

    def test_ac63_dry_run_same_exit_code_as_real_on_failure(self):  # AC 63
        s = self.s
        s.hw(".claude/hooks/x.py", "key = %s\n" % TOKEN)
        pub0, ov0 = s.snapshot(s.repo), s.snapshot(s.ov)
        rd = self.export("--dry-run")
        self.assertNotEqual(rd.returncode, 0)
        self.assertEqual(pub0, s.snapshot(s.repo))
        self.assertEqual(ov0, s.snapshot(s.ov))
        self.assertEqual(rd.returncode, self.export().returncode)

    def test_ac63_unknown_flag(self):  # AC 63
        self.assertEqual(self.export("--bogus").returncode, 2)


class TestFailures(ExportBase):
    def test_ac64_secret_in_live_hook(self):  # AC 17 / 31 / 64
        self.s.hw(".claude/hooks/x.py", "key = %s\n" % TOKEN)
        r = self.export()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("secret-scan: FAIL", r.stdout)

    def test_ac64_secret_in_overlay_only_file(self):  # AC 64
        self.s.hw(".claude/CLAUDE.md", "my token = %s\n" % TOKEN)
        r = self.export()
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("secret-scan: FAIL", r.stdout)
        self.assertIn("CLAUDE.md", r.stdout)

    def test_ac64_invalid_plugins_json(self):  # AC 17a / 64
        with open(self.s.home + "/.claude/plugins/installed_plugins.json", "w") as f:
            f.write("{not json")
        self.assertNotEqual(self.export().returncode, 0)

    def test_ac65_home_path_leak_into_existing_public_hook(self):  # AC 65
        s = self.s
        s.rw("claude/hooks/x.sh", "old\n")
        s.hw(".claude/hooks/x.sh", "cd /Users/someone/x\n")
        s.hw(".claude/hooks/y.sh", "cd /Users/someone/x\n")      # same text, overlay-only: fine
        r = self.export()
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("leak-scan: FAIL", r.stdout)
        self.assertRegex(r.stdout, r"claude/hooks/x\.sh:\d+: \[home-path\]")
        self.assertNotRegex(r.stdout, r"y\.sh:\d+: \[home-path\]")
        self.assertNotIn("/Users/someone", r.stdout)

    def test_ac65_leak_text_only_in_overlay_passes(self):  # AC 65
        self.s.hw(".claude/hooks/y.sh", "cd /Users/someone/x\n")
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class TestOverlayOwned(ExportBase):
    def rf(self, path):
        with open(path) as f:
            return f.read()

    def test_ac84_overlay_owned_precedence(self):  # AC 84
        s = self.s
        s.rw("claude/hooks/h.sh", "public-version\n")
        s.ow("claude/hooks/h.sh", "overlay-version\n")
        s.hw(".claude/hooks/h.sh", "live-edit\n")
        s.git_init(s.repo)
        pub = s.snapshot(s.repo)
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.ovr("claude/hooks/h.sh"), "live-edit\n")
        self.assertEqual(self.rf(self.rp("claude/hooks/h.sh")), "public-version\n")
        self.assertEqual(s.sh("git", "status", "--porcelain", cwd=s.repo).stdout, "")
        self.assertEqual(pub, s.snapshot(s.repo))
        # bootstrap installs the overlay copy
        os.remove(s.home + "/.claude/hooks/h.sh")
        rb = s.run("bootstrap.sh", "--no-repos", "--no-plugins")
        self.assertEqual(rb.returncode, 0, rb.stdout + rb.stderr)
        self.assertEqual(self.rf(s.home + "/.claude/hooks/h.sh"), "live-edit\n")
        # removing the overlay copy -> public one is installed
        os.remove(self.ov("claude/hooks/h.sh"))
        rb = s.run("bootstrap.sh", "--no-repos", "--no-plugins")
        self.assertEqual(rb.returncode, 0, rb.stdout + rb.stderr)
        self.assertEqual(self.rf(s.home + "/.claude/hooks/h.sh"), "public-version\n")

    def test_ac84_dry_run_lists_only_overlay_write(self):  # 11.6 overlay-owned
        s = self.s
        s.rw("claude/hooks/h.sh", "public-version\n")
        s.ow("claude/hooks/h.sh", "overlay-version\n")
        s.hw(".claude/hooks/h.sh", "live-edit\n")
        r = self.export("--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("would write [overlay] claude/hooks/h.sh", r.stdout)
        self.assertNotIn("would write [public] claude/hooks/h.sh", r.stdout)


if __name__ == "__main__":
    unittest.main()
