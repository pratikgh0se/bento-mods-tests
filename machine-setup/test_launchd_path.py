"""AC 85: every public launchd template sets HOME and PATH in EnvironmentVariables."""
import glob, os, plistlib, re, subprocess
from msharness import Base, DEFAULT_PREFIX

WANT_PATH = "%s/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


class TestLaunchdPath(Base):
    def install(self, *extra):
        s = self.s
        s.ow("claude/CLAUDE.md", "x\n")           # overlay present so overlay-needing jobs are eligible
        r = s.run("bootstrap.sh", "--no-repos", "--no-plugins", "--launchd", *extra)
        files = sorted(glob.glob(os.path.join(s.home, "Library/LaunchAgents/*.plist")))
        return r, files

    def test_ac85_rendered_env_and_lint(self):  # AC 85
        s = self.s
        r, files = self.install()
        self.assertTrue(files, r.stdout + r.stderr)
        tmpls = glob.glob(os.path.join(s.repo, "launchd", "*.plist.tmpl"))
        self.assertTrue(tmpls)
        self.assertGreaterEqual(len(files), len(tmpls) - 1, (files, r.stdout))
        for f in files:
            with self.subTest(plist=os.path.basename(f)):
                self.assertEqual(subprocess.run(["plutil", "-lint", f], capture_output=True).returncode, 0)
                with open(f, "rb") as fh:
                    raw = fh.read()
                self.assertNotIn(b"__", raw)
                env = plistlib.loads(raw).get("EnvironmentVariables")
                self.assertIsInstance(env, dict)
                self.assertEqual(env.get("HOME"), s.home)
                self.assertEqual(env.get("PATH"), WANT_PATH % s.home)

    def test_ac85_custom_prefix_still_has_env(self):  # AC 85
        s = self.s
        s.ow("claude/CLAUDE.md", "x\n")
        r = s.run("bootstrap.sh", "--no-repos", "--no-plugins", "--launchd", LABEL_PREFIX="com.other")
        files = glob.glob(os.path.join(s.home, "Library/LaunchAgents/*.plist"))
        for f in files:
            with open(f, "rb") as fh:
                raw = fh.read()
            self.assertNotIn(b"__", raw)
            self.assertEqual(plistlib.loads(raw)["EnvironmentVariables"]["PATH"], WANT_PATH % s.home)

    def test_ac85_installed_plist_without_path_differs(self):  # AC 85
        s = self.s
        r, files = self.install()
        self.assertTrue(files, r.stdout + r.stderr)
        victim = files[0]
        label = os.path.basename(victim)[:-len(".plist")]
        with open(victim, "rb") as fh:
            d = plistlib.load(fh)
        d["EnvironmentVariables"].pop("PATH", None)
        with open(victim, "wb") as fh:
            plistlib.dump(d, fh)
        s.set_state("loaded.txt", label + "\n")
        r = s.run("bootstrap.sh", "--dry-run", "--no-repos", "--no-plugins", "--launchd")
        self.assertIn(label + ": loaded, plist differs", r.stdout)
        # not loaded variant
        s.set_state("loaded.txt", "")
        r = s.run("bootstrap.sh", "--dry-run", "--no-repos", "--no-plugins", "--launchd")
        self.assertIn(label + ": not loaded, plist differs", r.stdout)
