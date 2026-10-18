"""AC 86: launchd entry scripts export USER and LOGNAME (= `id -un`) when unset/empty, never override non-empty.

Black-box: each script is run under `env -i` with a fake HOME and a PATH whose first dir holds recording stubs
(claude, ccusage, gh, git, osascript, launchctl, npx, gitleaks). Every stub appends the USER/LOGNAME it sees to a
log, then exits non-zero (git/claude) or 0, so the scripts stop fast. Only child-process env is observable.
The scripts run from a temp COPY of the public tree; state dirs are redirected into the temp dir.
Observable children: canary -> `claude`; token-budget -> `claude`/`ccusage` (via *_BIN vars); autosync -> `git`
(with a temp non-git overlay dir so it is not the no-overlay no-op).
"""
import os, shutil, subprocess, tempfile, unittest

MS_REPO = os.environ.get("MACHINE_SETUP_REPO", os.path.expanduser("~/CodeBase/machine-setup"))
COPY = ["setup", "tools", "claude", "launchd"]
STUBS = ["claude", "ccusage", "gh", "git", "osascript", "launchctl", "npx", "gitleaks"]
STUB = '''#!/bin/bash
printf '%s|USER=<%s>|LOGNAME=<%s>|USER_SET=%s|LOGNAME_SET=%s\\n' "$(basename "$0")" "$USER" "$LOGNAME" \\
  "${USER+y}" "${LOGNAME+y}" >> "$ENVLOG"
exit @RC@
'''
SCRIPTS = {
    "canary": "tools/handoff-canary/run.sh",
    "token-budget": "tools/token-budget/run.sh",
    "autosync": "setup/autosync.sh",
}


def idun():
    return subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()


class TestEntryEnv(unittest.TestCase):
    def setUp(self):
        self.sb = os.path.realpath(tempfile.mkdtemp(prefix="msenv."))
        self.addCleanup(shutil.rmtree, self.sb, True)
        self.home = os.path.join(self.sb, "home")
        self.repo = os.path.join(self.sb, "work", "machine-setup")
        self.stubs = os.path.join(self.sb, "stubs")
        self.ov = os.path.join(self.sb, "overlay")
        self.tmp = os.path.join(self.sb, "tmp")
        self.log = os.path.join(self.sb, "env.log")
        for d in (self.home, self.repo, self.stubs, self.ov, self.tmp):
            os.makedirs(d, exist_ok=True)
        open(self.log, "w").close()
        for item in COPY:
            src = os.path.join(MS_REPO, item)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(self.repo, item), symlinks=True,
                                ignore=shutil.ignore_patterns("__pycache__", ".git"))
        for n in STUBS:
            p = os.path.join(self.stubs, n)
            with open(p, "w") as f:
                f.write(STUB.replace("@RC@", "0" if n in ("osascript", "launchctl", "npx", "gitleaks", "gh") else "1"))
            os.chmod(p, 0o755)
        self.expected = idun()
        self.assertTrue(self.expected)

    def run_script(self, which, extra_env):
        env = {"HOME": self.home, "PATH": self.stubs + ":/usr/bin:/bin", "ENVLOG": self.log, "TMPDIR": self.tmp,
               "MACHINE_SETUP_PRIVATE": self.ov,
               "HANDOFF_CANARY_STATE_DIR": os.path.join(self.sb, "canary-state"),
               "HANDOFF_CANARY_NOTIFY": "0", "TOKEN_BUDGET_NOTIFY": "0",
               "TOKEN_BUDGET_STATE_DIR": os.path.join(self.sb, "tb-state"),
               "CLAUDE_HOME": os.path.join(self.home, ".claude"),
               "CLAUDE_SETTINGS_FILE": os.path.join(self.home, ".claude", "settings.json"),
               "OBSIDIAN_VAULT_PATH": os.path.join(self.sb, "vault"),
               "TOKEN_BUDGET_CLAUDE_BIN": os.path.join(self.stubs, "claude"),
               "TOKEN_BUDGET_CCUSAGE_BIN": os.path.join(self.stubs, "ccusage"),
               "LANG": "C.UTF-8", "TZ": "UTC"}
        env.update(extra_env)
        r = subprocess.run(["/usr/bin/env", "-i"] + [f"{k}={v}" for k, v in env.items()]
                           + ["/bin/bash", os.path.join(self.repo, SCRIPTS[which])],
                           capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, cwd=self.sb)
        with open(self.log) as f:
            lines = [l for l in f.read().splitlines() if l]
        return r, lines

    def check(self, which, extra_env, want_user, want_logname):
        r, lines = self.run_script(which, extra_env)
        self.assertTrue(lines, "no stub child was observed for %s (rc=%s)\nstdout=%s\nstderr=%s"
                        % (which, r.returncode, r.stdout, r.stderr))
        for l in lines:
            self.assertIn("|USER=<%s>|" % want_user, l, (which, lines))
            self.assertIn("|LOGNAME=<%s>|" % want_logname, l, (which, lines))

    def _each(self, extra_env, wu, wl):
        for which in SCRIPTS:
            with self.subTest(script=which):
                open(self.log, "w").close()
                self.check(which, extra_env, wu, wl)

    def test_ac86_unset_both(self):  # AC 86
        self._each({}, self.expected, self.expected)

    def test_ac86_empty_both(self):  # AC 86
        self._each({"USER": "", "LOGNAME": ""}, self.expected, self.expected)

    def test_ac86_unset_user_only_keeps_logname(self):  # AC 86
        self._each({"LOGNAME": "keepme"}, self.expected, "keepme")

    def test_ac86_empty_logname_only_keeps_user(self):  # AC 86
        self._each({"USER": "someone-else", "LOGNAME": ""}, "someone-else", self.expected)

    def test_ac86_nonempty_never_overridden(self):  # AC 86
        self._each({"USER": "someone-else", "LOGNAME": "other-login"}, "someone-else", "other-login")

    def test_ac86_user_only_set(self):  # AC 86
        self._each({"USER": "someone-else"}, "someone-else", self.expected)


if __name__ == "__main__":
    unittest.main()
