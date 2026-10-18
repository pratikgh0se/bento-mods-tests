"""bootstrap.sh contract tests (ACs 1-11, as amended by section 11). Each test cites its AC number."""
import json, os, re, stat, unittest
from msharness import Base, PLIST, DEFAULT_PREFIX

HEADING_PREFIXES = ["== 1. prerequisites", "== 2. runtime directories", "== 3. repositories",
                    "== 4. ~/.claude files", "== 5. ~/.agents skills", "== 6. Claude plugins",
                    "== 7. launchd jobs", "== summary"]
DEFAULT_DIRS = [".local/state/claude-handoffs", ".claude/hooks", ".claude/skills", ".claude/commands",
                ".local/state/token-budget", ".local/state/machine-setup",
                "Library/LaunchAgents", ".agents/skills"]
LABEL = DEFAULT_PREFIX + ".t1"
LABEL_TOKEN = "__LABEL_PREFIX__.t1"


def plugins_json(plugins=(), mks=()):
    return json.dumps({"marketplaces": [{"name": m, "source": {"source": "github", "repo": "a/b"},
                                         "add_arg": "a/b"} for m in mks],
                       "plugins": [{"id": i, "enabled": e, "installed": True, "version": "1"}
                                   for i, e in plugins]}, indent=2) + "\n"


def render(text, home, prefix=DEFAULT_PREFIX):
    return text.replace("__HOME__", home).replace("__LABEL_PREFIX__", prefix)


class BootBase(Base):
    """Public copy emptied of claude/ and launchd/ so the test controls all content."""
    def setUp(self):
        super().setUp()
        self.s.pub_reset()

    def boot(self, *args, **kw):
        return self.s.run("bootstrap.sh", *args, **kw)

    def job(self, loaded, installed, label=LABEL, req_exists=True, repo="req-repo", name="t1"):
        """Personal overlay job. installed: None | 'same' | 'diff'."""
        s = self.s
        body = PLIST % (label.replace(DEFAULT_PREFIX, "__LABEL_PREFIX__"), "__HOME__", "x")
        s.ow("launchd/%s.plist" % name, body)
        req = os.path.join(s.home, "CodeBase", "req")
        if req_exists:
            os.makedirs(req, exist_ok=True)
        s.ow("launchd/deps.tsv", "# label\trequired_path\trepo\tneeds\n%s\t__HOME__/CodeBase/req\t%s\tstuff\n"
             % (label, repo))
        if installed:
            b = render(body, s.home) if installed == "same" \
                else render(PLIST % (label.replace(DEFAULT_PREFIX, "__LABEL_PREFIX__"), "__HOME__", "y"), s.home)
            s.hw("Library/LaunchAgents/%s.plist" % label, b)
        s.set_state("loaded.txt", label + "\n" if loaded else "")


class TestDryRun(BootBase):
    def test_ac1_dry_run_output_shape(self):  # AC 1
        self.s.use_overlay()
        r = self.boot("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertTrue(lines[0].startswith("machine-setup bootstrap  HOME=" + self.s.home), lines[0])
        self.assertIn("(DRY RUN)", lines[0])
        self.assertEqual(lines[1], "  overlay: " + self.s.ov)
        pos = []
        for h in HEADING_PREFIXES:
            idx = [i for i, l in enumerate(lines) if l.startswith(h)]
            self.assertEqual(len(idx), 1, h)
            pos.append(idx[0])
        self.assertEqual(pos, sorted(pos))
        self.assertEqual(lines[-1], "  DRY RUN complete: nothing was changed.")

    def test_ac2_dry_run_changes_nothing(self):  # AC 2
        s = self.s
        s.rw("claude/settings.template.json", '{"a": 1}\n')
        s.ow("claude/settings.json", '{"b": 2}\n')
        s.hw(".claude/settings.json", '{"a": 0}\n')
        s.ow("claude/plugins.json", plugins_json([("foo@mk", True)], ["mk"]))
        s.ow("repos.tsv", "__HOME__/CodeBase/foo\trepo\t/nonexistent/foo.git\tmain\t\n")
        self.job(loaded=False, installed=None)
        before = s.snapshot(s.home)
        r = self.boot("--dry-run", "--launchd")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(before, s.snapshot(s.home))
        self.assertFalse(os.path.exists(os.path.join(s.home, ".machine-setup-backup")))
        bad = [c for c in s.shim_calls()
               if re.match(r"launchctl (bootstrap|bootout)", c)
               or re.match(r"claude plugin (install|marketplace add)", c)
               or re.match(r"git clone", c) or c.startswith("npx")]
        self.assertEqual(bad, [])

    def test_ac3_file_decisions(self):  # AC 3
        s = self.s
        s.ow("claude/CLAUDE.md", "root __HOME__/x\n")
        s.hw(".claude/CLAUDE.md", "root %s/x\n" % s.home)
        s.rw("claude/settings.template.json", '{"a": 1}\n')
        s.hw(".claude/settings.json", '{"a": 2}\n')
        s.ow("claude/keybindings.json", "{}\n")
        r = self.boot("--dry-run")
        self.assertIn("unchanged  .claude/CLAUDE.md", r.stdout)
        self.assertIn("overwrite (backup) .claude/settings.json", r.stdout)
        self.assertIn("install    .claude/keybindings.json", r.stdout)
        for ex in ("placeholders.txt", "plugins.json", "hook-deps.tsv", "settings.template.md"):
            self.assertNotIn(".claude/" + ex, r.stdout)

    def test_ac3_template_claude_md_without_overlay(self):  # AC 3 (template fallback)
        s = self.s
        s.rw("claude/CLAUDE.md.template", "tmpl __HOME__\n")
        s.hw(".claude/CLAUDE.md", "tmpl %s\n" % s.home)
        r = self.boot("--dry-run")
        self.assertIn("unchanged  .claude/CLAUDE.md", r.stdout)
        self.assertNotIn("CLAUDE.md.template", r.stdout)

    def test_ac4_dirs(self):  # AC 4 / AC 50 list
        s = self.s
        os.makedirs(os.path.join(s.home, ".local/state/claude-handoffs"))
        r = self.boot("--dry-run")
        lines = [l.strip() for l in r.stdout.splitlines()]
        for d in DEFAULT_DIRS:
            has = any(l.endswith("mkdir -p " + d) for l in lines)
            self.assertEqual(has, d != ".local/state/claude-handoffs", d)

    def test_ac5_launchd_decisions(self):  # AC 5
        cases = [(True, "same", LABEL + ": loaded, unchanged"),
                 (True, "diff", "loaded, plist differs"),
                 (False, None, "not loaded, not installed"),
                 (False, "same", "not loaded, plist installed"),
                 (False, "diff", "not loaded, plist differs")]
        for loaded, inst, expect in cases:
            with self.subTest(loaded=loaded, inst=inst):
                self.s.cleanup(); self.setUp()
                self.job(loaded, inst)
                r = self.boot("--dry-run", "--launchd")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn(expect, r.stdout)
                if inst == "same" and loaded:
                    self.assertEqual(sum(LABEL in l for l in r.stdout.splitlines()), 1)

    def test_ac5_launchd_skipped_without_flag(self):  # AC 5 / 51
        self.job(False, None)
        r = self.boot("--dry-run")
        self.assertIn("  skipped (pass --launchd to install launchd jobs)", r.stdout)
        self.assertNotIn(LABEL, r.stdout)
        self.assertEqual([c for c in self.s.shim_calls() if c.startswith("launchctl")], [])

    def test_ac5_skip_when_path_absent_and_repo_not_cloneable(self):  # AC 5
        self.job(False, None, req_exists=False, repo="nowhere")
        r = self.boot("--dry-run", "--launchd")
        self.assertRegex(r.stdout, r"SKIP     %s" % re.escape(LABEL))
        self.assertIn("launchd skipped: " + LABEL, r.stdout)

    def test_sec10_dry_run_listed_repo_counts_ok_real_run_skips(self):  # section 10 note, AC 5
        s = self.s
        self.job(False, None, req_exists=False, repo="req")
        s.ow("repos.tsv", "__HOME__/CodeBase/req\trepo\t/nonexistent/req.git\tmain\t\n")
        r = self.boot("--dry-run", "--launchd")
        self.assertNotIn("SKIP     " + LABEL, r.stdout)
        r = self.boot("--no-repos", "--no-plugins", "--launchd")
        self.assertIn("SKIP     " + LABEL, r.stdout)

    def test_ac11_summary_placeholders(self):  # AC 11 (+48 union)
        s = self.s
        s.rw("claude/placeholders.txt", "ZED\n")
        s.ow("claude/placeholders.txt", "FOO_TOKEN\nENV_BAR\nZED\n")
        r = self.boot("--dry-run")
        self.assertIn("  Secret placeholders to fill in ~/.claude/settings.json:", r.stdout)
        names = re.findall(r"^    __SECRET:(\w+)__$", r.stdout, re.M)
        self.assertEqual(names, ["ENV_BAR", "FOO_TOKEN", "ZED"])
        self.s.cleanup(); self.setUp()
        r = self.boot("--dry-run")
        self.assertIn("  Secret placeholders: none (settings.json has no secret values)", r.stdout)


class TestPlugins(BootBase):
    def test_ac8_plugin_idempotency(self):  # AC 8
        s = self.s
        s.rw("claude/plugins.json", plugins_json([("foo@mk", True), ("bar@mk", True),
                                                   ("baz@mk", False), ("x@builtin", True)], ["mk"]))
        s.set_state("plugin_list.txt", "Installed plugins:\n\n  > foo@mk\n    Version: 1\n")
        s.set_state("mk_list.txt", "Configured marketplaces:\n\n  > mk\n    Source: GitHub (a/b)\n")
        r = self.boot("--dry-run")
        self.assertIn("plugin already installed: foo@mk", r.stdout)
        self.assertIn("claude plugin install bar@mk   (state: enabled)", r.stdout)
        self.assertIn("claude plugin install baz@mk   (state: disabled)", r.stdout)
        self.assertIn("marketplace present: mk", r.stdout)
        self.assertNotIn("x@builtin", r.stdout)
        self.assertNotIn("claude plugin install foo@mk", r.stdout)
        r = self.boot("--no-repos")
        calls = s.shim_calls()
        self.assertFalse([c for c in calls if c.startswith("claude plugin install foo@mk")])
        self.assertTrue([c for c in calls if c.startswith("claude plugin install bar@mk")])
        self.assertFalse([c for c in calls if c.startswith("claude plugin marketplace add")])

    def test_sec31_no_plugins_flag_and_defaults(self):  # section 3.1
        r = self.boot("--dry-run", "--no-plugins", "--no-repos")
        self.assertEqual(r.stdout.count("  skipped (--no-plugins)"), 1)
        self.assertIn("  skipped (pass --launchd to install launchd jobs)", r.stdout)
        self.assertIn("  skipped (--no-repos)", r.stdout)

    def test_sec31_no_plugins_json(self):  # section 3.1 / 11.4
        r = self.boot("--dry-run")
        self.assertIn("  skipped (no plugins.json)", r.stdout)

    def test_sec32_plugin_install_failure_exit1(self):  # section 3.2
        s = self.s
        s.rw("claude/plugins.json", plugins_json([("bar@mk", True)], ["mk"]))
        fail = os.path.join(s.shims, "claude")
        with open(fail, "w") as f:
            f.write('#!/bin/bash\necho "claude $*" >> "$SHIM_LOG"\n'
                    '[ "$2" = "install" ] && exit 1\nexit 0\n')
        r = self.boot("--no-repos")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)


class TestRealRun(BootBase):
    def test_ac6_loaded_identical_untouched(self):  # AC 6
        self.job(True, "same")
        r = self.boot("--no-repos", "--no-plugins", "--launchd")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(LABEL + ": loaded, unchanged", r.stdout)
        self.assertEqual([c for c in self.s.shim_calls()
                          if re.match(r"launchctl (bootstrap|bootout)", c) and LABEL in c], [])

    def test_sec31_real_run_launchd_actions(self):  # section 3.1 (differs)
        self.job(True, "diff")
        r = self.boot("--no-repos", "--no-plugins", "--launchd")
        self.assertIn("loaded, plist differs -> backup, bootout, copy, lint, bootstrap", r.stdout)
        calls = self.s.shim_calls()
        self.assertTrue([c for c in calls if c.startswith("launchctl bootout") and LABEL in c])
        self.assertTrue([c for c in calls if c.startswith("launchctl bootstrap") and LABEL in c])
        installed = open(os.path.join(self.s.home, "Library/LaunchAgents", LABEL + ".plist")).read()
        self.assertEqual(installed, render(PLIST % (LABEL_TOKEN, "__HOME__", "x"), self.s.home))

    def test_sec31_plutil_failure(self):  # section 3.1, 3.2
        self.job(False, None)
        self.s.ow("launchd/t1.plist", "not a plist at all\n")
        r = self.boot("--no-repos", "--no-plugins", "--launchd")
        self.assertEqual(r.returncode, 1)
        self.assertEqual([c for c in self.s.shim_calls() if c.startswith("launchctl bootstrap")], [])

    def test_ac7_install_backup_idempotent(self):  # AC 7 (+ section 3.2 modes, chmod 700)
        s = self.s
        s.ow("claude/CLAUDE.md", "home __HOME__\n")
        s.rw("claude/settings.template.json", '{"new": true}\n')
        s.w(s.repo, "claude/hooks/h.sh", "#!/bin/sh\necho __HOME__\n", mode=0o755)
        s.hw(".claude/settings.json", '{"old": true}\n')
        r = self.boot("--no-repos", "--no-plugins")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        h = s.home
        self.assertEqual(open(h + "/.claude/CLAUDE.md").read(), "home %s\n" % h)
        self.assertEqual(json.loads(open(h + "/.claude/settings.json").read()), {"new": True})
        self.assertEqual(open(h + "/.claude/hooks/h.sh").read(), "#!/bin/sh\necho %s\n" % h)
        self.assertTrue(os.stat(h + "/.claude/hooks/h.sh").st_mode & stat.S_IXUSR)
        bk = h + "/.machine-setup-backup"
        stamps = os.listdir(bk)
        self.assertEqual(len(stamps), 1)
        self.assertEqual(open("%s/%s/.claude/settings.json" % (bk, stamps[0])).read(), '{"old": true}\n')
        self.assertEqual(stat.S_IMODE(os.stat(h + "/.local/state/token-budget").st_mode), 0o700)
        r2 = self.boot("--no-repos", "--no-plugins")
        self.assertEqual(r2.returncode, 0)
        for f in ("CLAUDE.md", "settings.json", "hooks/h.sh"):
            self.assertIn("unchanged  .claude/" + f, r2.stdout)
        self.assertNotRegex(r2.stdout, r"(install|overwrite)\s.*\.claude/")
        self.assertEqual(os.listdir(bk), stamps)

    def test_sec31_symlinks(self):  # section 3.1 links.tsv
        s = self.s
        tgt = os.path.join(s.home, "elsewhere")
        os.makedirs(tgt)
        s.ow("claude/skills.links.tsv", "lnk\t__HOME__/elsewhere\n")
        self.boot("--no-repos", "--no-plugins")
        p = s.home + "/.claude/skills/lnk"
        self.assertTrue(os.path.islink(p))
        self.assertEqual(os.readlink(p), tgt)
        self.assertNotIn("symlink    ", self.boot("--dry-run").stdout)

    def test_sec31_hook_deps(self):  # section 3.1 hook-script deps, 3.2 exit 1
        s = self.s
        s.ow("claude/hook-deps.tsv", "__HOME__/.claude/hooks/zz.py\trepo:ghost\n")
        r = self.boot("--dry-run", "--no-plugins")
        self.assertIn("WARN: hook script missing", r.stdout)
        self.assertIn("ghost is not cloneable", r.stdout)
        self.assertEqual(r.returncode, 1)
        s.ow("repos.tsv", "__HOME__/CodeBase/ghost\trepo\t/nonexistent/g.git\tmain\t\n")
        r = self.boot("--dry-run", "--no-plugins")
        self.assertIn("will come from repo ghost (cloned in step 3)", r.stdout)
        self.assertEqual(r.returncode, 0, r.stdout)


class TestRepos(BootBase):
    def test_ac9_repo_handling(self):  # AC 9
        s = self.s
        os.makedirs(s.home + "/CodeBase/have/.git")
        s.ow("repos.tsv",
             "__HOME__/CodeBase/have\trepo\t/nonexistent/have.git\tmain\t\n"
             "__HOME__/CodeBase/wt1\tworktree\t\tmain\thave\n"
             "__HOME__/CodeBase/opt\trepo\t/nonexistent/opt.git\tmain\t\n"
             "__HOME__/CodeBase/fresh\trepo\t/nonexistent/fresh.git\tmain\t\n")
        s.ow("repos.optional", "opt\n")
        r = self.boot("--dry-run")
        self.assertIn("present  have", r.stdout)
        self.assertNotIn("wt1", r.stdout)
        self.assertRegex(r.stdout, r"git clone /nonexistent/fresh\.git CodeBase/fresh")
        self.assertNotRegex(r.stdout, r"git clone \S*opt")
        r = self.boot("--dry-run", "--all-repos")
        self.assertRegex(r.stdout, r"git clone /nonexistent/opt\.git CodeBase/opt")
        r = self.boot("--dry-run", "--no-repos")
        self.assertIn("  skipped (--no-repos)", r.stdout)
        self.assertNotIn("git clone", r.stdout)

    def test_ac9_no_overlay_repos_tsv(self):  # AC 9 / 40
        r = self.boot("--dry-run")
        self.assertIn("  skipped (no overlay repos.tsv)", r.stdout)
        self.s.use_overlay()
        r = self.boot("--dry-run")
        self.assertIn("  skipped (no overlay repos.tsv)", r.stdout)


class TestFlags(BootBase):
    def test_ac10_unknown_flag(self):  # AC 10
        for flag in ("--bogus", "--no-launchd"):
            with self.subTest(flag):
                r = self.boot(flag)
                self.assertEqual(r.returncode, 2)
                self.assertIn("unknown flag: " + flag, r.stderr)
                self.assertNotIn("== ", r.stdout)

    def test_ac10_help(self):  # AC 10
        before = self.s.snapshot(self.s.home)
        for flag in ("--help", "-h"):
            r = self.boot(flag)
            self.assertEqual(r.returncode, 0)
            self.assertTrue(r.stdout.strip())
            self.assertNotIn("== 1.", r.stdout)
        self.assertEqual(before, self.s.snapshot(self.s.home))


if __name__ == "__main__":
    unittest.main()
