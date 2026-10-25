import json, os, re, shutil, stat, subprocess, sys, tempfile, unittest

# Hook scripts under test: the PUBLIC repo copy by default; override with HANDOFF_HOOKS_DIR (legacy: HOOKS_DIR).
HOOKS_DIR = (os.environ.get("HANDOFF_HOOKS_DIR") or os.environ.get("HOOKS_DIR")
             or os.path.expanduser("~/CodeBase/machine-setup/claude/hooks"))
PRE = os.path.join(HOOKS_DIR, "precompact-handoff.py")
POST = os.path.join(HOOKS_DIR, "postcompact-inject.py")
CAP = 14000  # F39.6 (F37.1: 20,000; was 9,500)
OLD_CAP37 = 20000
OLD_CAP = 9500
FOOTER_FMT = "Full transcript: {p}. Read it for exact details before guessing."
AGENT_H = "## Agent handoff (written by the working agent)"
HAIKU_H = "## Model-written handoff (Haiku fallback; verify against facts)"  # F38: never emitted any more (used in NotIn asserts)
SUMMARY_H = "## Fresh summary at compaction (sonnet; verify against facts)"  # F38.4 with the default model
SUMMARY_FAIL = "Fresh summary failed: "
FACTS_H = "## Facts (auto-extracted)"
WARN_PFX = "Agent handoff may be stale: "
# F35.D order of the facts sections minus `## Decisions via questions` (no longer emitted since F39.6): EIGHT.
# (Old name NINE removed: indexes shifted, NINE[0] -> EIGHT[0], NINE[k>=2] -> EIGHT[k-1].)
DECISIONS_H = "## Decisions via questions"  # F39.6: never emitted any more (used in NotIn asserts)
EIGHT = ["## Last user messages (oldest first)", "## Files touched (last 30)",
         "## Task state", "## Open tasks", "## Background agents", "## Git", "## Last Bash commands",
         "## Last assistant message"]
AUTHORITY = ("- authority: the user's latest words > Project decisions > Agent handoff > Fresh summary > Claude Code's "
             "summary > Facts. If two disagree, the newer statement from the user wins; if unsure, ask.")  # F39.5
PROJECT_H_PFX = "## Project decisions (active; full ledger: "
SECTIONS = ["## Last user messages (oldest first)", "## Files touched (last 30)",
            "## Task state", "## Git", "## Last Bash commands", "## Last assistant message"]

# F37.2 drop order (first dropped first); the Last user messages section is dropped only after all eight others.
DROP37 = ["## Files touched (last 30)", "## Last Bash commands", "## Git", "## Task state", "## Last assistant message",
          "## Background agents", "## Open tasks", "## Last user messages (oldest first)"]  # F39.6: no Decisions via questions
PLAIN = "Pre-compaction handoff (auto-saved):\n"
PLAIN2 = "Pre-compaction handoff (auto-saved, part 2):\n"


def dropped37(text, expected):
    """Sections of `expected` (subset of DROP37) missing from text, in F37.2 order."""
    return [h for h in DROP37 if h in expected and h not in text]


def sec_names(text):
    return [l for l in text.split("\n") if l.startswith("## ")]

SHIM = """#!/bin/sh
D="$(dirname "$0")"
# F39: the role is decided by the --system-prompt value: the ledger merge call vs the summary call (and anything else).
role=summary; prev=""
for a in "$@"; do
  if [ "$prev" = "--system-prompt" ]; then
    case "$a" in "You maintain a project's decisions ledger"*) role=merge;; esac
  fi
  prev="$a"
done
if [ "$role" = "merge" ]; then
  P="$D/merge."
  echo invoked >> "$D/merge.invoked"
  n="$(wc -l < "$D/merge.invoked" | tr -d ' ')"
else
  P="$D/"
  echo invoked >> "$D/invoked"
  n="$(wc -l < "$D/invoked" | tr -d ' ')"
fi
printf '%s\\n' "$@" > "${P}args"
printf '%s\\0' "$@" > "${P}argv0"
env > "${P}env"
cat > "${P}stdin"
cp "${P}stdin" "${P}stdin.$n"
if [ -f "${P}sleepx" ]; then exec sleep "$(cat "${P}sleepx")"; fi
if [ -f "${P}sleep" ]; then sleep "$(cat "${P}sleep")"; fi
if [ -f "${P}out.$n" ]; then cat "${P}out.$n"; elif [ -f "${P}out" ]; then cat "${P}out"; fi
if [ -f "${P}rc" ]; then exit "$(cat "${P}rc")"; fi
exit 0
"""


class HookCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hh-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.hd = os.path.join(self.home, ".local", "state", "claude-handoffs")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        git = shutil.which("git")
        for tool_name in ("git", "cat", "env", "sleep", "dirname", "sh", "wc", "tr", "cp"):
            w = shutil.which(tool_name)
            if w:
                os.symlink(w, os.path.join(self.bin, tool_name))
        self.shimdir = os.path.join(self.tmp, "shim")
        os.makedirs(self.shimdir)
        self.tpath = os.path.join(self.tmp, "t.jsonl")

    # --- shim ---
    def install_shim(self, out=None, rc=None):
        p = os.path.join(self.bin, "claude")
        # the shim logs next to itself: put real script in shimdir, symlink-free wrapper in bin
        real = os.path.join(self.shimdir, "claude")
        with open(real, "w") as f:
            f.write(SHIM)
        os.chmod(real, 0o755)
        with open(p, "w") as f:
            f.write('#!/bin/sh\nexec "%s" "$@"\n' % real)
        os.chmod(p, 0o755)
        if out is not None:
            open(os.path.join(self.shimdir, "out"), "w").write(out)
        if rc is not None:
            open(os.path.join(self.shimdir, "rc"), "w").write(str(rc))

    def set_shim(self, role="merge", out=None, rc=None, sleep=None, sleepx=None, nth=None):
        """Configure the shim for one role: files `<role>.<knob>` (role `summary` = the unprefixed legacy names).
        `nth` makes `out` apply to the n-th call of that role only. A None knob is left untouched; clear_shim() removes."""
        pre = "merge." if role == "merge" else ""
        for knob, val in (("out" if nth is None else "out.%d" % nth, out), ("rc", rc), ("sleep", sleep), ("sleepx", sleepx)):
            if val is not None:
                with open(os.path.join(self.shimdir, pre + knob), "w") as f:
                    f.write(str(val))

    def clear_shim(self, role="merge", *knobs):
        pre = "merge." if role == "merge" else ""
        for knob in knobs or ("out", "rc", "sleep", "sleepx"):
            path = os.path.join(self.shimdir, pre + knob)
            if os.path.exists(path):
                os.remove(path)

    def shim_invoked(self):
        return os.path.exists(os.path.join(self.shimdir, "invoked"))

    def merge_calls(self):
        p = os.path.join(self.shimdir, "merge.invoked")
        return len(open(p).read().split()) if os.path.exists(p) else 0

    def merge_stdin(self, n=None):
        """stdin of the last (or n-th, 1-based) ledger merge call."""
        return open(os.path.join(self.shimdir, "merge.stdin" if n is None else "merge.stdin.%d" % n)).read()

    def merge_argv(self):
        raw = open(os.path.join(self.shimdir, "merge.argv0"), "rb").read().decode()
        parts = raw.split("\0")
        assert parts[-1] == "", parts[-1]
        return parts[:-1]

    def summary_stdin(self, n=None):
        return open(os.path.join(self.shimdir, "stdin" if n is None else "stdin.%d" % n)).read()

    def shim_file(self, n):
        return open(os.path.join(self.shimdir, n)).read()

    def shim_argv(self):
        """Exact argv the shim received (excluding argv[0]); empty-string elements preserved (NUL-separated record)."""
        raw = open(os.path.join(self.shimdir, "argv0"), "rb").read().decode()
        parts = raw.split("\0")
        assert parts[-1] == "", parts[-1]
        return parts[:-1]

    # --- running ---
    # F39: the ledger merge would call the `claude` shim and perturb every pre-F39 test that counts shim calls, so the
    # ledger is OFF by default for old tests (HANDOFF_LEDGER=0). F39 tests set LEDGER_ENV = None (ledger enabled).
    LEDGER_ENV = "0"

    def env(self, fallback="0", extra=None):
        e = {"HOME": self.home, "PATH": self.bin, "LANG": "C.UTF-8"}
        if self.LEDGER_ENV is not None:
            e["HANDOFF_LEDGER"] = self.LEDGER_ENV
        if fallback is not None:
            e["HANDOFF_HAIKU_FALLBACK"] = fallback
        e.update(extra or {})
        return e

    def run_pre(self, payload=None, raw=None, fallback="0", extra=None):
        if raw is None:
            raw = json.dumps(payload)
        r = subprocess.run([sys.executable, PRE], input=raw, capture_output=True,
                           text=True, env=self.env(fallback, extra), timeout=120)
        return r

    def run_post(self, payload=None, raw=None, extra=None, args=()):
        if raw is None:
            raw = json.dumps(payload)
        return subprocess.run([sys.executable, POST, *args], input=raw, capture_output=True,
                              text=True, env=self.env(None, extra), timeout=30)

    # --- F36 health / sidecar helpers ---
    def health_path(self):
        return os.path.join(self.hd, "health.jsonl")

    def health_lines(self):
        with open(self.health_path()) as f:
            return [l for l in f.read().split("\n") if l != ""]

    def health(self, i=-1):
        return json.loads(self.health_lines()[i])

    def sidecar(self, sid="S"):
        with open(os.path.join(self.hd, sid + "-last-health.json")) as f:
            return json.load(f)

    def put_sidecar(self, sid="S", status="ok", reasons=None, degraded=None, age_s=0, ts=None, errors=None,
                    trigger="auto", raw=None):
        """Write a sidecar as the precompact hook would (for inject-only fixtures)."""
        os.makedirs(self.hd, exist_ok=True)
        path = os.path.join(self.hd, sid + "-last-health.json")
        if raw is not None:
            open(path, "w").write(raw)
            return path
        import time as _t
        if ts is None:
            ts = _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(_t.time() - age_s))
        if degraded is None:
            degraded = status == "degraded"
        d = {"ts": ts, "sid": sid[:8], "trigger": trigger, "agent_file": "absent", "stale_sections": [],
             "fallback": "failed" if degraded else "ok", "duration_ms": 5, "output_chars": 10, "truncated": False,
             "errors": errors or [], "status": status, "hook_version": "1.0.0", "canary_child": False,
             "reasons": reasons or [], "degraded": degraded}
        json.dump(d, open(path, "w"))
        return path

    def put_latest(self, content="HANDOFF-BODY\n", sid="S"):
        os.makedirs(self.hd, exist_ok=True)
        open(os.path.join(self.hd, sid + "-latest.md"), "w").write(content)

    def post_ctx(self, sid="S", extra=None, args=()):
        r = self.run_post({"session_id": sid}, extra=extra, args=args)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        if r.stdout.strip() == "":
            return None
        o = json.loads(r.stdout)
        return o["hookSpecificOutput"]["additionalContext"]

    def degraded_file(self, sid="S"):
        p = os.path.join(self.hd, sid + "-degraded.json")
        return json.load(open(p)) if os.path.exists(p) else None

    def payload(self, sid="S", cwd=None, transcript=True, trigger="auto"):
        p = {"session_id": sid, "cwd": cwd or self.tmp, "trigger": trigger}
        if transcript:
            p["transcript_path"] = self.tpath
        else:
            p["transcript_path"] = os.path.join(self.tmp, "missing.jsonl")
        return p

    def latest(self, sid="S"):
        return open(os.path.join(self.hd, sid + "-latest.md")).read()

    def run_and_read(self, sid="S", **kw):
        fb = kw.pop("fallback", "0")
        r = self.run_pre(self.payload(sid, **kw), fallback=fb)
        self.assertEqual(r.returncode, 0)
        return self.latest(sid)

    def fit(self, build, target, hi=600, **kw):
        """Find the largest task count n (build(n) -> transcript entries) whose handoff file (fallback off) is still
        un-trimmed (same facts sections as n=0) and at least `target` chars long. Leaves that transcript written.
        Black-box calibration: the file grows ~160 chars per task until the hook starts dropping sections."""
        def run(n):
            self.write_transcript(build(n))
            return self.run_and_read(**dict(kw, fallback="0"))
        base = heads9(run(0))
        self.assertGreaterEqual(len(base), 1)
        def pred(n):
            t = run(n)
            return len(t) >= target or heads9(t) != base
        lo, h = 0, hi
        self.assertTrue(pred(h), "calibration fixture cannot reach %d chars" % target)
        while lo < h:
            m = (lo + h) // 2
            if pred(m):
                h = m
            else:
                lo = m + 1
        t = run(lo)
        if heads9(t) != base:
            lo -= 1
            t = run(lo)
        self.assertEqual(heads9(t), base)
        self.assertGreaterEqual(len(t), target - 400, "calibration undershoot")
        self.assertLessEqual(len(t), CAP)
        return lo, t

    # --- fixtures ---
    def write_transcript(self, entries, extra_lines=()):
        with open(self.tpath, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
            for l in extra_lines:
                f.write(l + "\n")

    def agent_file(self, body, sid="S", meta=None, age_min=0, raw_meta=None):
        os.makedirs(self.hd, exist_ok=True)
        a = os.path.join(self.hd, sid + "-agent.md")
        with open(a, "w") as f:
            f.write(body)
        if meta is not None:
            raw_meta = json.dumps(meta)
        if raw_meta is not None:
            with open(os.path.join(self.hd, sid + "-agent.meta.json"), "w") as f:
                f.write(raw_meta)
        if age_min:
            t = __import__("time").time() - age_min * 60
            os.utime(a, (t, t))
        return a


def user(t, **kw):
    d = {"type": "user", "message": {"content": t}}
    d.update(kw)
    return d


def asst(t):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": t}]}}


def tool(name, **inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


def warn_line(text):
    """The F35 warning line (bare line starting WARN_PFX), or None."""
    for l in text.split("\n"):
        if l.startswith(WARN_PFX):
            return l
    return None


def heads9(text):
    return [h for h in EIGHT if h in text]


def heads(text):
    return [h for h in SECTIONS if h in text]
