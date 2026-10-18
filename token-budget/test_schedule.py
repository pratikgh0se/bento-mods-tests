"""install.sh / uninstall.sh contract tests: AC 39, 42."""
import os
import plistlib
import shutil
import subprocess
import unittest

from tbharness import *  # noqa

LABEL = "com.machine-setup.token-budget"
CUSTOM_PREFIX = "com.example.me"
CUSTOM_LABEL = CUSTOM_PREFIX + ".token-budget"


class ScheduleBase(Base):
    def launch_agents(self):
        return os.path.join(self.env.home, "Library", "LaunchAgents")

    def plist_path(self):
        return os.path.join(self.launch_agents(), LABEL + ".plist")


class TestInstall(ScheduleBase):
    def render(self):
        out = os.path.join(self.env.root, "rendered.plist")
        p = self.env.run("install.sh", ["--render-only", out])
        return p, out

    def test_ac39_render_only_plist_valid(self):
        """AC39"""
        p, out = self.render()
        self.assertExit(p, 0)
        self.assertTrue(os.path.isfile(out))
        if shutil.which("plutil"):
            lint = subprocess.run(["plutil", "-lint", out], capture_output=True, text=True)
            self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)
        with open(out, "rb") as f:
            d = plistlib.load(f)
        self.assertEqual(d["Label"], LABEL)
        sci = d["StartCalendarInterval"]
        if isinstance(sci, list):
            self.assertEqual(len(sci), 1)
            sci = sci[0]
        self.assertEqual(sci, {"Weekday": 1, "Hour": 9, "Minute": 0})
        self.assertIs(d["RunAtLoad"], True)

    def test_ac39_program_arguments_login_shell_runs_run_sh(self):
        """5: /bin/bash -lc '<repo>/tools/token-budget/run.sh'"""
        p, out = self.render()
        self.assertExit(p, 0)
        with open(out, "rb") as f:
            d = plistlib.load(f)
        args = d["ProgramArguments"]
        self.assertEqual(args[0], "/bin/bash")
        self.assertEqual(args[1], "-lc")
        self.assertIn("/tools/token-budget/run.sh", args[2])
        self.assertIn("--catch-up", args[2], "both triggers run `run.sh --catch-up`")
        self.assertTrue(args[2].lstrip("'\" ").startswith("/"), "absolute repo path expected")

    def test_ac39_log_paths_and_no_secret_env(self):
        """5: StandardOut/ErrorPath -> logs/launchd.{out,err}; EnvironmentVariables has no secrets"""
        p, out = self.render()
        self.assertExit(p, 0)
        with open(out, "rb") as f:
            d = plistlib.load(f)
        self.assertTrue(d["StandardOutPath"].endswith("logs/launchd.out"))
        self.assertTrue(d["StandardErrorPath"].endswith("logs/launchd.err"))
        self.assertTrue(d["StandardOutPath"].startswith("/"))
        for k, v in d.get("EnvironmentVariables", {}).items():
            blob = (k + str(v)).lower()
            for w in ("key", "token", "secret", "password", "bearer"):
                self.assertNotIn(w, blob)

    def test_ac39_placeholders_substituted(self):
        """5: install.sh substitutes absolute repo path and $HOME"""
        p, out = self.render()
        self.assertExit(p, 0)
        text = read(out).decode()
        for bad in ("$HOME", "${HOME}", "{{", "}}", "__REPO", "@REPO@", "<repo>"):
            self.assertNotIn(bad, text)

    def test_ac39_render_only_does_not_touch_launchctl_or_launchagents(self):
        """AC39: no launchctl"""
        p, out = self.render()
        self.assertExit(p, 0)
        self.assertEqual([c for c in self.env.shim_calls() if c.startswith("launchctl")], [])
        self.assertFalse(os.path.exists(self.plist_path()))


class TestLabelPrefix(ScheduleBase):
    """AC 56: LABEL_PREFIX overrides the label prefix."""

    def test_ac56_install_custom_prefix(self):
        out = os.path.join(self.env.root, "custom.plist")
        p = self.env.run("install.sh", ["--render-only", out], extra={"LABEL_PREFIX": CUSTOM_PREFIX})
        self.assertExit(p, 0)
        with open(out, "rb") as f:
            d = plistlib.load(f)
        self.assertEqual(d["Label"], CUSTOM_LABEL)

    def test_ac56_install_default_prefix_when_unset(self):
        out = os.path.join(self.env.root, "default.plist")
        p = self.env.run("install.sh", ["--render-only", out], unset=("LABEL_PREFIX",))
        self.assertExit(p, 0)
        with open(out, "rb") as f:
            d = plistlib.load(f)
        self.assertEqual(d["Label"], "com.machine-setup.token-budget")

    def test_ac56_uninstall_dry_mode_custom_prefix(self):
        p = self.env.run("uninstall.sh", ["--render-only"], extra={"LABEL_PREFIX": CUSTOM_PREFIX})
        self.assertExit(p, 0)
        txt = p.stdout + p.stderr
        self.assertIn(CUSTOM_LABEL, txt)
        self.assertIn(os.path.join("Library", "LaunchAgents", CUSTOM_LABEL + ".plist"), txt)
        self.assertNotIn("com.machine-setup.token-budget", txt)

    def test_ac56_uninstall_dry_mode_default_prefix(self):
        p = self.env.run("uninstall.sh", ["--render-only"], unset=("LABEL_PREFIX",))
        self.assertExit(p, 0)
        txt = p.stdout + p.stderr
        self.assertIn("com.machine-setup.token-budget", txt)
        self.assertIn(os.path.join("Library", "LaunchAgents", "com.machine-setup.token-budget.plist"), txt)

    def test_ac56_uninstall_real_custom_prefix_targets_custom_plist(self):
        la = self.launch_agents()
        os.makedirs(la)
        write(os.path.join(la, CUSTOM_LABEL + ".plist"), "<plist/>")
        p = self.env.run("uninstall.sh", [], extra={"LABEL_PREFIX": CUSTOM_PREFIX})
        self.assertExit(p, 0)
        self.assertFalse(os.path.exists(os.path.join(la, CUSTOM_LABEL + ".plist")))
        calls = [c for c in self.env.shim_calls() if c.startswith("launchctl")]
        self.assertTrue(any("bootout" in c and CUSTOM_LABEL in c for c in calls), calls)


class TestUninstall(ScheduleBase):
    def seed(self):
        os.makedirs(self.launch_agents())
        write(self.plist_path(), "<plist/>")
        os.makedirs(self.env.p("logs"))
        write(self.env.p("ledger.jsonl"), '{"x":1}\n')
        write(self.env.p("manifests", "m.json"), "{}")

    def test_ac42_render_only_lists_removal_and_changes_nothing(self):
        """AC42"""
        self.seed()
        before = file_tree(self.env.state)
        p = self.env.run("uninstall.sh", ["--render-only"])
        self.assertExit(p, 0)
        self.assertIn(LABEL, p.stdout + p.stderr)
        self.assertTrue(os.path.exists(self.plist_path()))
        self.assertEqual(file_tree(self.env.state), before)
        self.assertEqual([c for c in self.env.shim_calls() if c.startswith("launchctl")], [])

    def test_ac42_plain_uninstall_removes_plist_keeps_state(self):
        """AC42 + 5: bootout via launchctl (shimmed), plist removed, state intact"""
        self.seed()
        before = file_tree(self.env.state)
        p = self.env.run("uninstall.sh", [])
        self.assertExit(p, 0)
        self.assertFalse(os.path.exists(self.plist_path()))
        self.assertEqual(file_tree(self.env.state), before)
        calls = [c for c in self.env.shim_calls() if c.startswith("launchctl")]
        self.assertTrue(any("bootout" in c and LABEL in c for c in calls), calls)

    def test_ac42_purge_is_the_only_way_state_is_deleted(self):
        """AC42"""
        self.seed()
        p = self.env.run("uninstall.sh", ["--purge"])
        self.assertExit(p, 0)
        self.assertFalse(os.path.exists(self.plist_path()))
        self.assertFalse(os.path.exists(self.env.p("ledger.jsonl")))
        self.assertFalse(os.path.exists(self.env.p("manifests", "m.json")))


if __name__ == "__main__":
    unittest.main()
