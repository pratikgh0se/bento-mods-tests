"""F36 canary: ACs 70-71 of specs/handoff-hooks-spec.md (run.sh against a FAKE `claude` on PATH, launchd template,
deps.tsv, --catch-up). Never calls the real claude, the network, or real state dirs: HOME, TMPDIR and PATH are temp.
The fake claude runs the REAL hooks (HOOKS_DIR) on a synthetic transcript to emulate PreCompact/SessionStart."""
import json, os, plistlib, re, shutil, signal, stat, subprocess, sys, tempfile, time, unittest
from helpers import HOOKS_DIR

REPO = os.environ.get("MACHINE_SETUP_DIR") or os.path.abspath(os.path.join(HOOKS_DIR, "..", ".."))
RUN = os.path.join(REPO, "tools", "handoff-canary", "run.sh")
TMPL = os.path.join(REPO, "launchd", "handoff-canary.plist.tmpl")
DEPS = os.path.join(REPO, "launchd", "deps.tsv")
HOOK_WRAPPER = os.path.join(REPO, "claude", "hooks", "handoff-canary.sh")
PRE = os.path.join(HOOKS_DIR, "precompact-handoff.py")
POST = os.path.join(HOOKS_DIR, "postcompact-inject.py")

SHIM = r'''#!%(py)s
import os, sys, json, re, subprocess, time
D = os.path.dirname(os.path.realpath(__file__))
argv = sys.argv[1:]
def log(rec):
    with open(D + "/calls.jsonl", "a") as f:
        f.write(json.dumps(rec) + "\n")
mode = {}
if os.path.exists(D + "/mode.json"):
    mode = json.load(open(D + "/mode.json"))
if os.environ.get("HANDOFF_HOOK_CHILD"):
    data = sys.stdin.read()
    log({"child": True})
    toks = sorted(set(re.findall(r"[AB]-[0-9a-f]{10}", data)))
    print("Haiku summary of the session. " + " ".join(toks) + " " + "padding " * 20)
    sys.exit(0)
st_null = os.path.samestat(os.fstat(0), os.stat("/dev/null"))
sid = None
for i, a in enumerate(argv):
    if a in ("--session-id", "--resume") and i + 1 < len(argv):
        sid = argv[i + 1]
prompt = argv[-1] if argv else ""
cwd = os.getcwd()
settings = None
try:
    settings = json.load(open(os.path.join(cwd, ".claude", "settings.json")))
except Exception:
    pass
sd = os.environ.get("HANDOFF_STATE_DIR", "")
sf = D + "/state-%%s.json" %% sid
st = json.load(open(sf)) if os.path.exists(sf) else {"turns": 0, "prompt1": "", "compacted": False, "answered": False}
st["turns"] += 1
if st["turns"] == 1:
    st["prompt1"] = prompt
turns = st["turns"]
cost = round(mode.get("cost_step", 0.01) * turns, 4)
rec = {"argv": argv, "sid": sid, "turn": turns, "cwd": cwd, "listing": sorted(os.listdir(cwd)), "settings": settings,
       "stdin_null": st_null, "cost": cost,
       "env": {k: os.environ.get(k) for k in ("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "HANDOFF_STATE_DIR", "HANDOFF_CANARY",
                                              "TMPDIR", "HOME")}}
log(rec)
if mode.get("hang"):
    time.sleep(600)
text = "done"
tokb = re.search(r"B-[0-9a-f]{10}", st["prompt1"])
if st["compacted"] and not st["answered"]:
    st["answered"] = True
    latest = os.path.join(sd, "%%s-latest.md" %% sid)
    toks = re.findall(r"[AB]-[0-9a-f]{10}", open(latest).read()) if os.path.exists(latest) else []
    text = "no idea" if mode.get("wrong_answer") else ("create done.txt containing " + (toks[0] if toks else "?"))
elif (not st["compacted"]) and (not mode.get("no_compact")) and turns >= 3 and (tokb or os.path.exists(os.path.join(sd, "%%s-agent.md" %% sid))):
    tr = D + "/tr-%%s.jsonl" %% sid
    with open(tr, "w") as f:
        f.write(json.dumps({"type": "user", "message": {"content": st["prompt1"]}}) + "\n")
        f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "working"}]}}) + "\n")
    payload = json.dumps({"session_id": sid, "cwd": cwd, "trigger": "auto", "transcript_path": tr})
    env = dict(os.environ)
    env["PATH"] = D + "/bin" + os.pathsep + env.get("PATH", "")
    subprocess.run([sys.executable, %(pre)r], input=payload, text=True, env=env, capture_output=True, timeout=120)
    subprocess.run([sys.executable, %(post)r], input=json.dumps({"session_id": sid}), text=True, env=env,
                   capture_output=True, timeout=30)
    st["compacted"] = True
json.dump(st, open(sf, "w"))
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text, "session_id": sid,
                  "total_cost_usd": cost}))
'''


class CanaryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="cn-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        self.tmpdir = os.path.join(self.tmp, "tmpdir")
        self.shimdir = os.path.join(self.tmp, "shim")
        for d in (self.home, self.tmpdir, os.path.join(self.shimdir, "bin")):
            os.makedirs(d)
        self.real_hd = os.path.join(self.home, ".local", "state", "claude-handoffs")
        self.cstate = os.path.join(self.home, ".local", "state", "handoff-canary")
        self.health_file = os.path.join(self.real_hd, "health.jsonl")
        self.shim_path = os.path.join(self.shimdir, "bin", "claude")
        with open(os.path.join(self.shimdir, "claude"), "w") as f:
            f.write(SHIM % {"py": sys.executable, "pre": PRE, "post": POST})
        os.chmod(os.path.join(self.shimdir, "claude"), 0o755)
        os.symlink(os.path.join(self.shimdir, "claude"), self.shim_path)
        self.set_mode({})

    def set_mode(self, m):
        with open(os.path.join(self.shimdir, "mode.json"), "w") as f:
            json.dump(m, f)

    def sys_path(self):
        parts = [os.path.dirname(sys.executable), "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
        g = shutil.which("git")
        if g:
            parts.append(os.path.dirname(g))
        out = []
        for p in parts:
            if p not in out:
                out.append(p)
        return out

    def env(self, shim=True, extra=None):
        path = (([os.path.join(self.shimdir, "bin")] if shim else []) + self.sys_path())
        e = {"HOME": self.home, "PATH": os.pathsep.join(path), "TMPDIR": self.tmpdir, "LANG": "C.UTF-8", "TZ": "UTC",
             "HANDOFF_CANARY_NOTIFY": "0"}
        e.update(extra or {})
        return e

    def run_canary(self, args=(), shim=True, extra=None, timeout=180):
        p = subprocess.Popen(["/bin/bash", RUN, *args], env=self.env(shim, extra), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            out, err = p.communicate()
            self.fail("run.sh did not finish in %ss" % timeout)
        finally:
            try:
                os.killpg(p.pid, signal.SIGKILL)  # reap leftovers (hung shims)
            except Exception:
                pass
        return subprocess.CompletedProcess(p.args, p.returncode, out, err)

    def reset(self):
        for f in os.listdir(self.shimdir):
            if f.startswith(("state-", "tr-")) or f == "calls.jsonl":
                os.remove(os.path.join(self.shimdir, f))
        shutil.rmtree(os.path.join(self.home, ".local"), ignore_errors=True)

    def calls(self):
        p = os.path.join(self.shimdir, "calls.jsonl")
        if not os.path.exists(p):
            return []
        return [json.loads(l) for l in open(p).read().split("\n") if l]

    def main_calls(self):
        return [c for c in self.calls() if not c.get("child")]

    def health_lines(self):
        if not os.path.exists(self.health_file):
            return []
        return [json.loads(l) for l in open(self.health_file).read().split("\n") if l]

    def session_costs(self):
        last = {}
        for c in self.main_calls():
            last[c["sid"]] = c["cost"]
        return last

    def assert_result(self, p, code, result, reason=None):
        lines = self.health_lines()
        self.assertEqual(p.returncode, code, (p.stdout, p.stderr))
        self.assertEqual(len(lines), 1, lines)
        h = lines[0]
        self.assertEqual(h["trigger"], "canary")
        self.assertEqual(h["result"], result, h)
        if reason is not None:
            self.assertEqual(h["reason"], reason, h)
        return h


class Healthy(CanaryCase):
    def test_ac70_pass(self):
        p = self.run_canary()
        h = self.assert_result(p, 0, "pass")
        self.assertEqual(list(h.keys()), ["ts", "sid", "trigger", "result", "reason", "variants", "duration_ms",
                                          "est_cost_usd", "hook_version", "canary_child"])
        self.assertIsNone(h["reason"])
        self.assertEqual(h["variants"], {"A": "pass", "B": "pass"})
        self.assertRegex(h["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(len(h["sid"]), 8)
        self.assertIsInstance(h["duration_ms"], int)
        self.assertIsInstance(h["hook_version"], str)
        self.assertIs(h["canary_child"], False)
        for k in ("agent_file", "fallback", "stale_sections", "output_chars", "truncated", "errors"):
            self.assertNotIn(k, h)
        costs = self.session_costs()
        self.assertEqual(len(costs), 2)  # two sessions: A then B
        self.assertAlmostEqual(h["est_cost_usd"], sum(costs.values()), places=4)

    def test_ac70_last_run_json_and_run_dir_removed(self):
        p = self.run_canary()
        self.assert_result(p, 0, "pass")
        lr = json.load(open(os.path.join(self.cstate, "last-run.json")))
        for k in ("ts", "result", "reason", "next_run_hint"):
            self.assertIn(k, lr)
        self.assertEqual(lr["result"], "pass")
        runs = os.path.join(self.cstate, "runs")
        self.assertEqual(os.listdir(runs) if os.path.isdir(runs) else [], [])
        self.assertNotIn("NOTIFY:", p.stdout)

    def test_ac70_isolation_and_argv(self):
        p = self.run_canary()
        self.assert_result(p, 0, "pass")
        cs = self.main_calls()
        self.assertGreaterEqual(len(cs), 4)
        first = cs[0]
        for c in cs:
            a = c["argv"]
            j = " ".join(a)
            self.assertIn("--setting-sources project", j)
            self.assertIn("--model haiku", j)
            self.assertIn("--strict-mcp-config", a)
            self.assertIn("-p", a)
            self.assertTrue(c["stdin_null"], "claude stdin must be /dev/null")
            self.assertTrue(c["cwd"].startswith(self.tmpdir + os.sep), c["cwd"])
            self.assertTrue(c["env"]["HANDOFF_STATE_DIR"].startswith(self.tmpdir + os.sep), c["env"])
            self.assertEqual(c["env"]["HANDOFF_CANARY"], "1")
            self.assertEqual(c["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "60000")
            self.assertNotEqual(c["env"]["HANDOFF_STATE_DIR"], self.real_hd)
        # first turn of each session: temp project holds .claude plus generated padding/task files only (padding names are unspecified: ambiguity resolved loosely)
        for c in cs:
            if c["turn"] == 1:
                self.assertIn(".claude", c["listing"])
                for n in c["listing"]:  # settings dir plus generated task/padding files only
                    self.assertTrue(n == ".claude" or re.fullmatch(r"(pad\w*|s\d|done|step\w*)\.txt", n), c["listing"])
        s = json.dumps(first["settings"])
        for needle in ("PreCompact", "SessionStart", "precompact-handoff.py", "postcompact-inject.py", "compact"):
            self.assertIn(needle, s)
        timeouts = []

        def walk(o):
            if isinstance(o, dict):
                if "timeout" in o:
                    timeouts.append(o["timeout"])
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(first["settings"])
        # F37.6: the canary registers postcompact-inject.py --part 1, 2 and 3 (three 10 s hooks) plus the PreCompact hook (90 s)
        self.assertEqual(sorted(timeouts), [10, 10, 10, 90])
        for k in (1, 2, 3):
            self.assertRegex(s, r"postcompact-inject\.py\s+--part[ =]%d" % k)
        self.assertEqual(sorted(first["settings"]["hooks"].keys()), ["PreCompact", "SessionStart"])
        # real handoffs dir got exactly the canary line and no hook lines
        self.assertEqual(len(self.health_lines()), 1)
        self.assertEqual([n for n in os.listdir(self.real_hd) if n != "health.jsonl"], [])

    def test_ac70_cost_is_last_cumulative_value_per_session(self):
        self.set_mode({"cost_step": 0.01})
        p = self.run_canary()
        h = self.assert_result(p, 0, "pass")
        per = {}
        for c in self.main_calls():
            per.setdefault(c["sid"], []).append(c["cost"])
        self.assertEqual(len(per), 2)
        for vals in per.values():
            self.assertEqual(vals, sorted(vals))
            self.assertGreaterEqual(len(vals), 3)
        want = sum(v[-1] for v in per.values())
        self.assertAlmostEqual(h["est_cost_usd"], want, places=4)
        self.assertLess(h["est_cost_usd"], sum(sum(v) for v in per.values()))  # never a sum over turns

    def test_ac70_default_cap_is_0_25(self):
        p = self.run_canary()
        self.assert_result(p, 0, "pass")
        per = {}
        for c in self.main_calls():
            per[c["sid"]] = c["turn"]
        n = sum(per.values())
        # just under the cap: pass
        self.reset()
        self.set_mode({"cost_step": 0.24 / n})
        p = self.run_canary()
        self.assert_result(p, 0, "pass")
        # just over: cost_cap
        self.reset()
        self.set_mode({"cost_step": 0.26 / n})
        p = self.run_canary()
        self.assert_result(p, 1, "fail", "cost_cap")

    def test_ac70_hook_wrapper_exists_and_executable(self):
        self.assertTrue(os.path.isfile(HOOK_WRAPPER))
        self.assertTrue(os.access(HOOK_WRAPPER, os.X_OK))
        self.assertTrue(os.access(RUN, os.X_OK))


class Failures(CanaryCase):
    def test_ac70_window_below_40000_exits_2_without_claude(self):
        p = self.run_canary(extra={"HANDOFF_CANARY_WINDOW": "30000"})
        self.assertEqual(p.returncode, 2, (p.stdout, p.stderr))
        self.assertEqual(self.calls(), [])

    def test_ac70_window_override_accepted_and_passed(self):
        p = self.run_canary(extra={"HANDOFF_CANARY_WINDOW": "50000"})
        self.assert_result(p, 0, "pass")
        self.assertEqual({c["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] for c in self.main_calls()}, {"50000"})

    def test_ac70_no_compaction_fails_with_notify(self):
        self.set_mode({"no_compact": True})
        p = self.run_canary()
        self.assert_result(p, 1, "fail", "no_compaction")
        notify = [l for l in p.stdout.split("\n") if l.startswith("NOTIFY: ")]
        self.assertEqual(len(notify), 1, p.stdout)
        self.assertIn("Handoff canary FAILED (no_compaction)", notify[0])
        # run dir kept on failure
        runs = os.path.join(self.cstate, "runs")
        self.assertTrue(os.path.isdir(runs) and os.listdir(runs))
        lr = json.load(open(os.path.join(self.cstate, "last-run.json")))
        self.assertEqual((lr["result"], lr["reason"]), ("fail", "no_compaction"))
        # at most 12 padding turns per compaction attempt (+ the /compact fallback turn)
        per = {}
        for c in self.main_calls():
            per[c["sid"]] = per.get(c["sid"], 0) + 1
        self.assertTrue(all(v <= 14 for v in per.values()), per)

    def test_ac70_cost_above_cap_stops_further_turns(self):
        self.set_mode({"cost_step": 0.3})
        p = self.run_canary()
        self.assert_result(p, 1, "fail", "cost_cap")
        self.assertEqual(len(self.main_calls()), 1)
        self.assertEqual(len([l for l in p.stdout.split("\n") if l.startswith("NOTIFY: ")]), 1)

    def test_ac70_max_usd_override(self):
        self.set_mode({"cost_step": 0.05})
        p = self.run_canary(extra={"HANDOFF_CANARY_MAX_USD": "0.07"})
        self.assert_result(p, 1, "fail", "cost_cap")

    def test_ac70_hang_is_killed_by_watchdog(self):
        self.set_mode({"hang": True})
        t0 = time.time()
        p = self.run_canary(extra={"HANDOFF_CANARY_TIMEOUT_S": "2"}, timeout=90)
        self.assert_result(p, 1, "fail", "timeout")
        self.assertLess(time.time() - t0, 60)

    def test_ac70_answer_lacks_token_is_c5(self):
        self.set_mode({"wrong_answer": True})
        p = self.run_canary()
        h = self.assert_result(p, 1, "fail", "c5")
        self.assertIn("fail", h["variants"].values())
        self.assertEqual(len([l for l in p.stdout.split("\n") if l.startswith("NOTIFY: ")]), 1)

    def test_ac70_missing_claude_is_skip(self):
        if shutil.which("claude", path=os.pathsep.join(self.sys_path())):
            self.skipTest("a real claude is on the system PATH used for the test")
        p = self.run_canary(shim=False)
        h = self.assert_result(p, 0, "skip", "claude_missing")
        self.assertEqual(self.calls(), [])
        lr = json.load(open(os.path.join(self.cstate, "last-run.json")))
        self.assertEqual((lr["result"], lr["reason"]), ("skip", "claude_missing"))
        self.assertNotIn("NOTIFY:", p.stdout)


class CatchUp(CanaryCase):
    NOW = "2026-10-16T12:00:00Z"  # most recent 03:30 (TZ=UTC) is 2026-10-16T03:30:00Z

    def last_run(self, ts):
        os.makedirs(self.cstate, exist_ok=True)
        json.dump({"ts": ts, "result": "pass", "reason": None, "next_run_hint": "x"},
                  open(os.path.join(self.cstate, "last-run.json"), "w"))

    def test_ac71_newer_last_run_is_noop(self):
        self.last_run("2026-10-16T03:45:00Z")
        before = open(os.path.join(self.cstate, "last-run.json")).read()
        p = self.run_canary(["--catch-up"], extra={"HANDOFF_CANARY_NOW": self.NOW})
        self.assertEqual(p.returncode, 0, (p.stdout, p.stderr))
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.health_lines(), [])
        self.assertEqual(open(os.path.join(self.cstate, "last-run.json")).read(), before)

    def test_ac71_older_last_run_runs(self):
        self.last_run("2026-10-16T03:00:00Z")
        p = self.run_canary(["--catch-up"], extra={"HANDOFF_CANARY_NOW": self.NOW})
        self.assert_result(p, 0, "pass")
        self.assertGreater(len(self.main_calls()), 0)

    def test_ac71_missing_last_run_runs(self):
        p = self.run_canary(["--catch-up"], extra={"HANDOFF_CANARY_NOW": self.NOW})
        self.assert_result(p, 0, "pass")


class Launchd(unittest.TestCase):
    def render(self, prefix="com.machine-setup"):
        text = open(TMPL).read()
        return (text.replace("__LABEL_PREFIX__", prefix).replace("__REPO__", REPO)
                .replace("__HOME__", "/Users/test"))

    def test_ac71_plist(self):
        d = tempfile.mkdtemp(prefix="pl-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        out = os.path.join(d, "x.plist")
        open(out, "w").write(self.render())
        if shutil.which("plutil"):
            lint = subprocess.run(["plutil", "-lint", out], capture_output=True, text=True)
            self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)
        pl = plistlib.load(open(out, "rb"))
        self.assertEqual(pl["Label"], "com.machine-setup.handoff-canary")
        sci = pl["StartCalendarInterval"]
        if isinstance(sci, list):
            self.assertEqual(len(sci), 1)
            sci = sci[0]
        self.assertEqual(sci, {"Hour": 3, "Minute": 30})
        self.assertIs(pl["RunAtLoad"], True)
        self.assertEqual(set(pl["EnvironmentVariables"].keys()), {"HOME", "PATH"})
        args = pl["ProgramArguments"]
        self.assertEqual(args[:2], ["/bin/bash", "-lc"])
        self.assertTrue(args[-1].rstrip("'\" ").endswith("tools/handoff-canary/run.sh --catch-up"), args)
        self.assertTrue(pl["StandardOutPath"].endswith(".local/state/handoff-canary/logs/launchd.out"))
        self.assertTrue(pl["StandardErrorPath"].endswith(".local/state/handoff-canary/logs/launchd.err"))
        self.assertNotIn("__", open(out).read())

    def test_ac71_label_prefix_override(self):
        pl = plistlib.loads(self.render("com.example.me").encode())
        self.assertEqual(pl["Label"], "com.example.me.handoff-canary")

    def test_ac71_deps_row(self):
        rows = [l for l in open(DEPS).read().split("\n") if "handoff-canary" in l]
        self.assertEqual(len(rows), 1, rows)
        cols = rows[0].split("\t")
        self.assertEqual(cols, ["__LABEL_PREFIX__.handoff-canary", "-", "-", "-"])


if __name__ == "__main__":
    unittest.main()
