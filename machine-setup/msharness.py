"""Shared sandbox harness for machine-setup contract tests (code-blind, spec only).

Layout of one sandbox (all under a temp dir):
  work/machine-setup            temp copy of the PUBLIC tree  (self.repo)
  work/machine-setup-private    sibling overlay location (only if the test calls sibling())
  overlay/                      explicit overlay dir          (self.ov, when use_overlay())
  home/                         fake $HOME
  shims/                        PATH shims (claude, launchctl, osascript, npx, gh, gitleaks, git)
The public tree location comes from env MACHINE_SETUP_REPO.
"""
import os, re, shutil, stat, subprocess, tempfile, unittest

MS_REPO = os.environ.get("MACHINE_SETUP_REPO", os.path.expanduser("~/CodeBase/machine-setup"))
COPY = ["setup", "claude", "launchd", ".secret-scan-allow", ".leak-scan-allow",
        ".gitignore", ".github"]
REAL_GIT = "/usr/bin/git"
DEFAULT_PREFIX = "com.machine-setup"

SHIMS = {
 "claude": '''#!/bin/bash
echo "claude $*" >> "$SHIM_LOG"
case "$*" in
  "plugin marketplace list") cat "$SB/mk_list.txt" 2>/dev/null ;;
  "plugin list") cat "$SB/plugin_list.txt" 2>/dev/null ;;
esac
exit 0
''',
 "launchctl": '''#!/bin/bash
echo "launchctl $*" >> "$SHIM_LOG"
if [ "$1" = "print" ]; then
  lbl="${2##*/}"
  grep -qx "$lbl" "$SB/loaded.txt" 2>/dev/null && exit 0
  exit 1
fi
exit 0
''',
 "osascript": '''#!/bin/bash
echo "osascript $*" >> "$SHIM_LOG"
[ -f "$SB/osascript_fail" ] && exit 1
exit 0
''',
 "npx": '#!/bin/bash\necho "npx $*" >> "$SHIM_LOG"\nexit 0\n',
 "gh": '#!/bin/bash\necho "gh $*" >> "$SHIM_LOG"\nexit 0\n',
 "gitleaks": '#!/bin/bash\nexit 0\n',
 "git": '#!/bin/bash\necho "git $*" >> "$SHIM_LOG"\nexec %s "$@"\n' % REAL_GIT,
}

PLIST = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
         '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>'
         '<key>Label</key><string>%s</string><key>ProgramArguments</key><array>'
         '<string>%s/bin/%s</string></array></dict></plist>\n')


class Sandbox:
    def __init__(self):
        self.sb = os.path.realpath(tempfile.mkdtemp(prefix="mstest."))
        self.home = os.path.join(self.sb, "home")
        self.work = os.path.join(self.sb, "work")
        self.repo = os.path.join(self.work, "machine-setup")
        self.ov = os.path.join(self.sb, "overlay")
        self.shims = os.path.join(self.sb, "shims")
        self.tmpdir = os.path.join(self.sb, "tmp")
        self.log = os.path.join(self.sb, "shim.log")
        self.has_overlay = False
        for d in (self.home, self.repo, self.shims, self.tmpdir):
            os.makedirs(d, exist_ok=True)
        open(self.log, "w").close()
        for name, body in SHIMS.items():
            p = os.path.join(self.shims, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, 0o755)
        self.gitconfig = os.path.join(self.sb, "gitconfig")
        with open(self.gitconfig, "w") as f:
            f.write("[user]\n name = T\n email = 1+t@users.noreply.github.com\n"
                    "[init]\n defaultBranch = main\n[commit]\n gpgsign = false\n"
                    "[protocol \"file\"]\n allow = always\n")
        for item in COPY:
            src = os.path.join(MS_REPO, item)
            dst = os.path.join(self.repo, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, symlinks=True,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
            elif os.path.exists(src):
                shutil.copy2(src, dst)

    def cleanup(self):
        shutil.rmtree(self.sb, ignore_errors=True)

    # ---- public tree / overlay control
    def pub_reset(self, claude=True, launchd=True):
        """Empty the generic claude/ and launchd/ trees of the copy so a test controls content."""
        for d, on in (("claude", claude), ("launchd", launchd)):
            if on:
                shutil.rmtree(os.path.join(self.repo, d), ignore_errors=True)
                os.makedirs(os.path.join(self.repo, d))

    def use_overlay(self):
        os.makedirs(self.ov, exist_ok=True)
        self.has_overlay = True
        return self.ov

    def sibling(self):
        p = os.path.join(self.work, "machine-setup-private")
        os.makedirs(p, exist_ok=True)
        return p

    # ---- running
    def env(self, priv="auto", **extra):
        e = {k: v for k, v in os.environ.items()
             if not k.startswith(("GIT_", "CLAUDE", "MACHINE_SETUP", "LABEL_PREFIX"))}
        e.update(HOME=self.home, TMPDIR=self.tmpdir, SB=self.sb, SHIM_LOG=self.log,
                 PATH=self.shims + ":" + os.environ.get("PATH", ""),
                 GIT_CONFIG_GLOBAL=self.gitconfig, GIT_CONFIG_NOSYSTEM="1",
                 GIT_TERMINAL_PROMPT="0")
        if priv == "auto":
            e["MACHINE_SETUP_PRIVATE"] = self.ov if self.has_overlay else "none"
        elif priv is not None:
            e["MACHINE_SETUP_PRIVATE"] = priv
        e.update(extra)
        return e

    def run(self, script, *args, cwd=None, env=None, timeout=120, priv="auto", **extra):
        """script: bare name resolved under setup/ (or absolute path)."""
        if os.path.isabs(script):
            path = script
        else:
            path = os.path.join(self.repo, "setup", script)
        return subprocess.run([path, *args], cwd=cwd or self.repo,
                              env=env or self.env(priv=priv, **extra),
                              capture_output=True, text=True, timeout=timeout)

    def lib(self, script, *args, check=True):
        r = subprocess.run(["python3", os.path.join(self.repo, "setup", "lib", script), *args],
                           capture_output=True, text=True, env=self.env())
        return r

    def sh(self, *cmd, cwd=None, check=True, env=None):
        r = subprocess.run(cmd, cwd=cwd or self.repo, env=env or self.env(),
                           capture_output=True, text=True)
        if check and r.returncode:
            raise RuntimeError("%s failed: %s %s" % (cmd, r.stdout, r.stderr))
        return r

    # ---- fixture helpers
    def w(self, base, rel, content="", mode=None):
        p = os.path.join(base, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(content)
        if mode is not None:
            os.chmod(p, mode)
        return p

    def hw(self, rel, content=""):
        return self.w(self.home, rel, content)

    def rw(self, rel, content="", mode=None):      # public repo file
        return self.w(self.repo, rel, content, mode)

    def ow(self, rel, content=""):                  # overlay file (enables overlay)
        self.use_overlay()
        return self.w(self.ov, rel, content)

    def read(self, base, rel):
        with open(os.path.join(base, rel)) as f:
            return f.read()

    def shim_calls(self):
        with open(self.log) as f:
            return f.read().splitlines()

    def set_state(self, name, content):
        with open(os.path.join(self.sb, name), "w") as f:
            f.write(content)

    def snapshot(self, root, skip_git=True):
        snap = {}
        for dp, dn, fn in os.walk(root):
            if skip_git and ".git" in dn:
                dn.remove(".git")
            dn[:] = [d for d in dn if d != "__pycache__"]
            fn = [f for f in fn if not f.endswith(".pyc")]
            for n in dn + fn:
                p = os.path.join(dp, n)
                rel = os.path.relpath(p, root)
                if os.path.islink(p):
                    snap[rel] = ("link", os.readlink(p))
                elif os.path.isdir(p):
                    snap[rel] = ("dir",)
                else:
                    with open(p, "rb") as f:
                        snap[rel] = ("file", f.read())
        return snap

    def tree_has_text(self, root, needle):
        nb = needle.encode()
        for dp, dn, fn in os.walk(root):
            if ".git" in dn:
                dn.remove(".git")
            for n in fn:
                p = os.path.join(dp, n)
                if os.path.islink(p):
                    continue
                with open(p, "rb") as f:
                    if nb in f.read():
                        return p
        return None

    # ---- standard HOME fixture for export
    def basic_home(self):
        self.hw(".claude/settings.json", '{"theme": "dark", "cmd": "%s/bin/x"}\n' % self.home)
        self.hw(".claude/CLAUDE.md", "# hi\nhome is %s\n" % self.home)
        self.hw(".claude/hooks/a.sh", "#!/bin/sh\necho %s\n" % self.home)
        self.hw(".claude/plugins/installed_plugins.json", '{"version": 2, "plugins": {}}\n')
        self.hw(".claude/plugins/known_marketplaces.json", "{}\n")

    def git_init(self, path=None, commit=True, email="1+t@users.noreply.github.com"):
        path = path or self.repo
        self.sh("git", "init", "-q", cwd=path)
        self.sh("git", "config", "user.email", email, cwd=path)
        self.sh("git", "config", "user.name", "T", cwd=path)
        if commit:
            self.sh("git", "add", "-A", cwd=path)
            self.sh("git", "commit", "-q", "-m", "init", cwd=path)

    def git_init_repo(self):
        self.git_init(self.repo)


class Base(unittest.TestCase):
    def setUp(self):
        self.s = Sandbox()
        self.addCleanup(self.s.cleanup)
