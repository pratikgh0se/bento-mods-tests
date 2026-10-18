"""Overlay discovery (ACs 36-40), repos/dirs/manual-steps (49-50), launchd + placeholders (51-55)."""
import json, os, plistlib, re, unittest
from msharness import Base, PLIST, DEFAULT_PREFIX
from test_bootstrap import render

TMPL_PLIST = PLIST.replace("__X__", "")


class OvBase(Base):
    def boot(self, *a, **kw):
        return self.s.run("bootstrap.sh", *a, **kw)

    def calls(self, pat):
        import re as _re
        return [c for c in self.s.shim_calls() if _re.match(pat, c)]


class TestDiscovery(OvBase):
    def setUp(self):
        super().setUp()
        self.s.pub_reset()

    def test_ac36_env_wins_over_sibling(self):  # AC 36
        s = self.s
        sib = s.sibling()
        s.w(sib, "claude/CLAUDE.md", "SIBLING\n")
        s.ow("claude/CLAUDE.md", "FROM-A\n")
        r = self.boot("--dry-run")
        self.assertEqual(r.stdout.splitlines()[1], "  overlay: " + s.ov)
        r = self.boot("--no-repos", "--no-plugins")
        self.assertEqual(open(s.home + "/.claude/CLAUDE.md").read(), "FROM-A\n")

    def test_ac36_symlinked_env_dir_is_resolved(self):  # 11.2 "symlink allowed, resolved"
        s = self.s
        s.ow("claude/CLAUDE.md", "A\n")
        link = os.path.join(s.sb, "ovlink")
        os.symlink(s.ov, link)
        r = self.boot("--dry-run", priv=link)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines()[1], "  overlay: " + s.ov)

    def test_ac37_unset_or_empty_uses_sibling(self):  # AC 37
        s = self.s
        sib = s.sibling()
        s.w(sib, "claude/CLAUDE.md", "SIB\n")
        for priv in (None, ""):
            with self.subTest(priv=priv):
                r = self.boot("--dry-run", priv=priv)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout.splitlines()[1], "  overlay: " + sib)
                self.assertIn("install    .claude/CLAUDE.md", r.stdout)

    def test_ac38_none_ignores_sibling(self):  # AC 38
        s = self.s
        sib = s.sibling()
        s.w(sib, "claude/CLAUDE.md", "SIB\n")
        s.w(sib, "repos.tsv", "__HOME__/CodeBase/x\trepo\t/nonexistent/x.git\tmain\t\n")
        r = self.boot("--dry-run", priv="none")
        self.assertEqual(r.stdout.splitlines()[1], "  overlay: none (generic install)")
        self.assertNotIn("CLAUDE.md", r.stdout)
        self.assertNotIn("git clone", r.stdout)

    def test_ac39_non_directory_value_all_scripts(self):  # AC 39
        s = self.s
        bad_missing = os.path.join(s.sb, "does-not-exist")
        bad_file = s.w(s.sb, "afile", "x")
        for val in (bad_missing, bad_file):
            for script, args in (("bootstrap.sh", ["--dry-run"]), ("bootstrap.sh", ["--no-repos", "--no-plugins"]),
                                 ("export.sh", []), ("autosync.sh", [])):
                with self.subTest(val=val, script=script, args=args):
                    before = s.snapshot(s.home)
                    pub_before = s.snapshot(s.repo)
                    r = s.run(script, *args, priv=val)
                    self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                    self.assertIn("overlay: MACHINE_SETUP_PRIVATE=%s is not a directory" % val, r.stderr)
                    self.assertEqual(before, s.snapshot(s.home))
                    self.assertEqual(pub_before, s.snapshot(s.repo))

    def test_ac39_no_fallback_to_sibling(self):  # 11.2 "no fallback"
        s = self.s
        s.sibling()
        r = self.boot("--dry-run", priv=os.path.join(s.sb, "nope"))
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("overlay: " + s.sibling(), r.stdout)

    def test_ac40_no_overlay_dry_run(self):  # AC 40
        r = self.boot("--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[1], "  overlay: none (generic install)")
        self.assertIn("  skipped (no overlay repos.tsv)", lines)
        heads = [l for l in lines if re.match(r"== [1-7]\. |== summary", l)]
        self.assertEqual(len(heads), 8)
        self.assertEqual(lines[-1], "  DRY RUN complete: nothing was changed.")

    def test_ac40_no_overlay_real_run_installs_public_templates(self):  # AC 40
        s = self.s
        s.rw("claude/CLAUDE.md.template", "generic\n")
        s.rw("claude/settings.template.json", '{"a": 1}\n')
        # a denylist living in an overlay dir that is NOT selected must not matter / leak
        deny = s.w(s.sb, "elsewhere/leak-denylist.txt", "zebrapersonal\n")
        r = self.boot("--no-repos", "--no-plugins")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(open(s.home + "/.claude/CLAUDE.md").read(), "generic\n")
        self.assertEqual(json.loads(open(s.home + "/.claude/settings.json").read()), {"a": 1})
        self.assertIsNone(s.tree_has_text(s.home, "zebrapersonal"))

    def test_ac40_real_public_templates_install(self):  # AC 40 with the shipped templates
        self.s.cleanup(); Base.setUp(self)     # fresh, un-reset public copy
        s = self.s
        r = self.boot("--no-repos", "--no-plugins")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.isfile(s.home + "/.claude/CLAUDE.md"))
        self.assertTrue(os.path.isfile(s.home + "/.claude/settings.json"))
        json.loads(open(s.home + "/.claude/settings.json").read())
        self.assertFalse(os.path.exists(s.home + "/.claude/settings.template.md"))
        self.assertIsNone(s.tree_has_text(s.home, "__HOME__"))


class TestRepoDirsManual(OvBase):
    def setUp(self):
        super().setUp()
        self.s.pub_reset()

    def test_ac49_public_repos_tsv_ignored(self):  # AC 49
        s = self.s
        row = "__HOME__/CodeBase/foo\trepo\t/nonexistent/foo.git\tmain\t\n"
        s.rw("repos.tsv", row)
        s.rw("repos.tsv.example", row)
        os.makedirs(s.home + "/CodeBase/foo/.git")
        for ov in (False, True):
            if ov:
                s.use_overlay()
            r = self.boot("--dry-run")
            self.assertIn("  skipped (no overlay repos.tsv)", r.stdout)
            self.assertNotIn("git clone", r.stdout)
            self.assertNotIn("present  foo", r.stdout)

    def test_ac49_overlay_repos_used(self):  # AC 49
        s = self.s
        s.rw("repos.tsv", "__HOME__/CodeBase/pubrow\trepo\t/nonexistent/p.git\tmain\t\n")
        s.ow("repos.tsv", "__HOME__/CodeBase/ovrow\trepo\t/nonexistent/o.git\tmain\t\n")
        r = self.boot("--dry-run")
        self.assertRegex(r.stdout, r"git clone /nonexistent/o\.git CodeBase/ovrow")
        self.assertNotIn("pubrow", r.stdout)

    def test_ac50_dirs_txt(self):  # AC 50
        s = self.s
        s.ow("dirs.txt", "CodeBase\n__HOME__/.local/share/extra/logs\n.cache/mine\n")
        r = self.boot("--dry-run")
        lines = [l.strip() for l in r.stdout.splitlines()]
        for d in (["CodeBase", ".local/share/extra/logs", ".cache/mine"]):
            self.assertIn("[dry-run] mkdir -p " + d, lines)
        self.assertIn("[dry-run] mkdir -p .local/state/claude-handoffs", lines)

    def test_ac50_public_defaults_exact(self):  # AC 50 (no overlay)
        r = self.boot("--dry-run")
        mk = sorted(re.findall(r"mkdir -p (\S+)", r.stdout))
        self.assertEqual(mk, sorted([".local/state/claude-handoffs", ".claude/hooks", ".claude/skills", ".claude/commands",
                                     ".local/state/token-budget", ".local/state/machine-setup",
                                     "Library/LaunchAgents", ".agents/skills"]))

    def test_ac50_manual_steps(self):  # AC 50
        s = self.s
        r = self.boot("--dry-run")
        self.assertIn("  Manual steps still needed:", r.stdout)
        self.assertIn("    - claude login (credentials are never stored in this repo)", r.stdout)
        self.assertNotIn("ollama", r.stdout)
        self.assertNotIn(".env", r.stdout)
        s.ow("manual-steps.txt", "    - do the thing\n- another thing\n")
        r = self.boot("--dry-run")
        self.assertIn("    - claude login (credentials are never stored in this repo)", r.stdout)
        self.assertIn("do the thing", r.stdout)
        self.assertIn("another thing", r.stdout)
        a = r.stdout.index("Manual steps still needed")
        self.assertGreater(r.stdout.index("do the thing"), a)

    def test_sec11_4_no_ollama_special_case(self):  # 11.4 ollama-serve special case removed
        s = self.s
        s.ow("launchd/ollama-serve.plist", PLIST % ("__LABEL_PREFIX__.ollama-serve", "__HOME__", "o"))
        s.ow("launchd/deps.tsv", "%s.ollama-serve\t__HOME__/x\tr\tstuff\n" % DEFAULT_PREFIX)
        os.makedirs(s.home + "/x")
        r = self.boot("--dry-run", "--launchd")
        self.assertNotIn("OLLAMA_MODELS", r.stdout)


class TestLaunchdTemplates(OvBase):
    AUTOSYNC = DEFAULT_PREFIX + ".machine-setup-autosync"

    def test_ac51_without_launchd_flag_nothing_happens(self):  # AC 51
        s = self.s
        s.use_overlay()
        for flag in ("--dry-run", None):
            args = ["--dry-run"] if flag else ["--no-repos", "--no-plugins"]
            r = self.boot(*args)
            self.assertIn("  skipped (pass --launchd to install launchd jobs)", r.stdout)
            self.assertNotIn(self.AUTOSYNC, r.stdout)
        self.assertEqual(self.calls(r"launchctl"), [])
        la = os.path.join(s.home, "Library/LaunchAgents")
        self.assertEqual(os.listdir(la) if os.path.isdir(la) else [], [])

    def test_ac51_template_skipped_without_overlay(self):  # AC 51
        r = self.boot("--dry-run", "--launchd")
        self.assertIn("SKIP     %s  (needs a private overlay; none configured)" % self.AUTOSYNC, r.stdout)
        self.assertIn("launchd skipped: " + self.AUTOSYNC, r.stdout)

    def test_ac51_template_with_empty_overlay(self):  # AC 51
        s = self.s
        s.use_overlay()
        r = self.boot("--dry-run", "--launchd")
        self.assertIn("%s: not loaded, not installed -> install, bootstrap" % self.AUTOSYNC, r.stdout)
        r = self.boot("--no-repos", "--no-plugins", "--launchd")
        p = os.path.join(s.home, "Library/LaunchAgents", self.AUTOSYNC + ".plist")
        self.assertTrue(os.path.isfile(p), r.stdout + r.stderr)
        raw = open(p, "rb").read()
        self.assertNotIn(b"__", raw)
        d = plistlib.loads(raw)
        self.assertEqual(d["Label"], self.AUTOSYNC)
        blob = json.dumps(d)
        self.assertIn(s.ov, blob)                                   # MACHINE_SETUP_PRIVATE=<overlay>
        self.assertIn(os.path.join(s.repo, "setup", "autosync.sh"), blob)
        self.assertIn("MACHINE_SETUP_PRIVATE", blob)    # env var or inline assignment, either form
        self.assertTrue([c for c in self.calls(r"launchctl bootstrap") if self.AUTOSYNC in c])

    def test_ac52_label_prefix_from_config(self):  # AC 52
        s = self.s
        s.ow("config.env", "# comment\n\nLABEL_PREFIX=com.example.me\nUNKNOWN=1\n")
        r = self.boot("--no-repos", "--no-plugins", "--launchd")
        p = os.path.join(s.home, "Library/LaunchAgents", "com.example.me.machine-setup-autosync.plist")
        self.assertTrue(os.path.isfile(p), r.stdout + r.stderr)
        self.assertEqual(plistlib.loads(open(p, "rb").read())["Label"], "com.example.me.machine-setup-autosync")
        self.assertFalse(os.path.exists(os.path.join(
            s.home, "Library/LaunchAgents", DEFAULT_PREFIX + ".machine-setup-autosync.plist")))

    def test_ac52_label_prefix_quotes_stripped(self):  # 11.5
        s = self.s
        s.ow("config.env", 'LABEL_PREFIX="com.quoted"\n')
        r = self.boot("--dry-run", "--launchd")
        self.assertIn("com.quoted.machine-setup-autosync", r.stdout)
        self.assertNotIn('"', "".join(l for l in r.stdout.splitlines() if "machine-setup-autosync" in l))

    def test_ac52_invalid_label_prefix(self):  # AC 52
        s = self.s
        for bad in ("com bad", "$(touch X)", "a/b", "-lead", ""):
            with self.subTest(bad=bad):
                s.cleanup(); self.setUp()
                s = self.s
                s.ow("config.env", "LABEL_PREFIX=%s\n" % bad)
                before = s.snapshot(s.home)
                r = self.boot("--no-repos", "--no-plugins", "--launchd")
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("config: invalid LABEL_PREFIX", r.stderr)
                self.assertEqual(before, s.snapshot(s.home))

    def test_ac52_config_env_not_evaluated(self):  # AC 52
        s = self.s
        wd = os.path.join(s.sb, "cwd")
        os.makedirs(wd)
        s.ow("config.env", "LABEL_PREFIX=com.ok\nX=$(touch SENTINEL)\nY=`touch SENTINEL2`\n")
        r = self.boot("--dry-run", cwd=wd)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for d in (wd, s.ov, s.repo, s.home, s.sb):
            self.assertFalse(os.path.exists(os.path.join(d, "SENTINEL")), d)
            self.assertFalse(os.path.exists(os.path.join(d, "SENTINEL2")), d)

    def test_ac53_overlay_plists_and_deps(self):  # AC 53
        s = self.s
        s.pub_reset()
        label = DEFAULT_PREFIX + ".mine"
        s.ow("launchd/mine.plist", PLIST % ("__LABEL_PREFIX__.mine", "__HOME__", "m"))
        s.ow("launchd/deps.tsv", "# label\trequired_path\trepo\tneeds\n%s\t__HOME__/req\tr\tstuff\n" % label)
        os.makedirs(s.home + "/req")
        r = self.boot("--no-repos", "--no-plugins", "--launchd")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        got = open(os.path.join(s.home, "Library/LaunchAgents", label + ".plist")).read()
        self.assertEqual(got, render(PLIST % ("__LABEL_PREFIX__.mine", "__HOME__", "m"), s.home))

    def test_ac53_same_label_overlay_wins(self):  # AC 53
        s = self.s
        s.pub_reset()
        label = DEFAULT_PREFIX + ".dup"
        s.rw("launchd/dup.plist.tmpl", PLIST % ("__LABEL_PREFIX__.dup", "__HOME__", "from-public"))
        s.rw("launchd/deps.tsv", "%s\t__HOME__/req\tr\tstuff\n" % label)
        s.ow("launchd/dup.plist", PLIST % ("__LABEL_PREFIX__.dup", "__HOME__", "from-overlay"))
        s.ow("launchd/deps.tsv", "%s\t__HOME__/req\tr\tstuff\n" % label)
        os.makedirs(s.home + "/req")
        r = self.boot("--no-repos", "--no-plugins", "--launchd")
        got = open(os.path.join(s.home, "Library/LaunchAgents", label + ".plist")).read()
        self.assertIn("from-overlay", got)
        self.assertNotIn("from-public", got)

    def test_ac53_plist_without_placeholders_byte_identical(self):  # AC 53, 11.5 idempotent renderer
        s = self.s
        s.pub_reset()
        body = PLIST % ("com.example.static", "/opt", "x")
        s.ow("launchd/static.plist", body)
        s.ow("launchd/deps.tsv", "com.example.static\t__HOME__/req\tr\tstuff\n")
        os.makedirs(s.home + "/req")
        self.boot("--no-repos", "--no-plugins", "--launchd")
        self.assertEqual(open(os.path.join(s.home, "Library/LaunchAgents/com.example.static.plist")).read(), body)

    def test_ac53_public_deps_and_overlay_deps_both_processed(self):  # 11.4
        s = self.s
        s.pub_reset()
        s.rw("launchd/pub.plist.tmpl", PLIST % ("__LABEL_PREFIX__.pub", "__HOME__", "p"))
        s.rw("launchd/deps.tsv", "%s.pub\t__HOME__/req\tr\tstuff\n" % DEFAULT_PREFIX)
        s.ow("launchd/own.plist", PLIST % ("__LABEL_PREFIX__.own", "__HOME__", "o"))
        s.ow("launchd/deps.tsv", "%s.own\t__HOME__/req\tr\tstuff\n" % DEFAULT_PREFIX)
        os.makedirs(s.home + "/req")
        r = self.boot("--dry-run", "--launchd")
        self.assertIn("%s.pub: not loaded, not installed" % DEFAULT_PREFIX, r.stdout)
        self.assertIn("%s.own: not loaded, not installed" % DEFAULT_PREFIX, r.stdout)

    def test_ac54_unresolved_placeholder_file(self):  # AC 54
        s = self.s
        s.pub_reset()
        s.ow("claude/hooks/bad.sh", "echo __FOO__\n")
        s.ow("claude/hooks/good.sh", "echo ok\n")
        r = self.boot("--no-repos", "--no-plugins")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"  WARN: unresolved placeholder __FOO__ in \S*bad\.sh")
        self.assertFalse(os.path.exists(s.home + "/.claude/hooks/bad.sh"))
        self.assertTrue(os.path.exists(s.home + "/.claude/hooks/good.sh"))

    def test_ac54_unresolved_placeholder_plist(self):  # AC 54
        s = self.s
        s.pub_reset()
        label = DEFAULT_PREFIX + ".bad"
        s.ow("launchd/bad.plist", PLIST % ("__LABEL_PREFIX__.bad", "__HOME__/__FOO__", "b"))
        s.ow("launchd/deps.tsv", "%s\t__HOME__/req\tr\tstuff\n" % label)
        os.makedirs(s.home + "/req")
        r = self.boot("--no-repos", "--no-plugins", "--launchd")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("WARN: unresolved placeholder __FOO__", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(s.home, "Library/LaunchAgents", label + ".plist")))
        self.assertEqual([c for c in self.calls(r"launchctl bootstrap") if label in c], [])

    def test_ac54_secret_placeholder_not_flagged(self):  # AC 54
        s = self.s
        s.pub_reset()
        s.ow("claude/settings.json", json.dumps({"env": {"MY_TOKEN": "__SECRET:ENV_MY_TOKEN__"}}))
        r = self.boot("--no-repos", "--no-plugins")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("unresolved placeholder", r.stdout)
        self.assertIn("__SECRET:ENV_MY_TOKEN__", open(s.home + "/.claude/settings.json").read())

    def test_sec11_5_repo_and_overlay_placeholders(self):  # 11.5
        s = self.s
        s.pub_reset()
        s.rw("claude/hooks/p.sh", "R=__REPO__ O=__OVERLAY__ P=__LABEL_PREFIX__ H=__HOME__\n")
        s.use_overlay()
        self.assertEqual(self.boot("--no-repos", "--no-plugins").returncode, 0)
        self.assertEqual(open(s.home + "/.claude/hooks/p.sh").read(),
                         "R=%s O=%s P=com.machine-setup H=%s\n" % (s.repo, s.ov, s.home))

    def test_sec11_5_overlay_placeholder_without_overlay_is_skipped(self):  # 11.5
        s = self.s
        s.pub_reset()
        s.rw("claude/hooks/needs-ov.sh", "O=__OVERLAY__\n")
        r = self.boot("--no-repos", "--no-plugins")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("unresolved placeholder", r.stdout)
        self.assertFalse(os.path.exists(s.home + "/.claude/hooks/needs-ov.sh"))

    def test_ac55_rerun_idempotent_with_overlay(self):  # AC 55
        s = self.s
        s.pub_reset()
        label = DEFAULT_PREFIX + ".t1"
        s.ow("claude/CLAUDE.md", "hi __HOME__\n")
        s.rw("claude/settings.template.json", '{"a": 1}\n')
        s.ow("claude/hooks/h.sh", "echo __HOME__\n")
        s.ow("launchd/t1.plist", PLIST % ("__LABEL_PREFIX__.t1", "__HOME__", "x"))
        s.ow("launchd/deps.tsv", "%s\t__HOME__/req\tr\tstuff\n" % label)
        os.makedirs(s.home + "/req")
        r1 = self.boot("--no-repos", "--no-plugins", "--launchd")
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        s.set_state("loaded.txt", label + "\n")
        open(s.log, "w").close()
        bk = s.home + "/.machine-setup-backup"
        had = sorted(os.listdir(bk)) if os.path.isdir(bk) else []
        r2 = self.boot("--no-repos", "--no-plugins", "--launchd")
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        for f in ("CLAUDE.md", "settings.json", "hooks/h.sh"):
            self.assertIn("unchanged  .claude/" + f, r2.stdout)
        self.assertIn(label + ": loaded, unchanged", r2.stdout)
        self.assertEqual(sorted(os.listdir(bk)) if os.path.isdir(bk) else [], had)
        self.assertEqual(self.calls(r"launchctl (bootstrap|bootout)"), [])


if __name__ == "__main__":
    unittest.main()
