"""F36 handoff reliability: ACs 49-68 (hooks) of specs/handoff-hooks-spec.md "F36 Handoff reliability".
Hook scripts located by HANDOFF_HOOKS_DIR (helpers.py). Haiku fallback is disabled unless a test passes fallback="1"
together with a `claude` shim. Canary (AC 69-71) tests live in test_f36_canary.py."""
import json, os, re, shutil, stat, subprocess, sys, time, unittest
from helpers import *
import test_f35 as f35
from test_content import git

KEYS = ["ts", "sid", "trigger", "agent_file", "stale_sections", "fallback", "summary_model", "ledger", "ledger_active",
        "ledger_superseded", "ledger_restored", "ledger_chars", "duration_ms",
        "output_chars", "truncated", "errors", "status", "hook_version", "canary_child"]
# F37.4 adds `inline_cut` (bool); its position is not specified: tests require KEYS in order plus inline_cut anywhere.
KEYS37 = set(KEYS) | {"inline_cut"}


def keys_ok(tc, h):
    tc.assertEqual(set(h.keys()), KEYS37)
    tc.assertEqual([k for k in h.keys() if k != "inline_cut"], KEYS)
    tc.assertIsInstance(h["inline_cut"], bool)
TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
IP, NS = f35.IP, f35.NS
STALE_META = {"agentWrittenAt": f35.NUDGE_MS, "lastNudgeAt": f35.NUDGE_MS, "stale_sections": [IP, NS]}
BODY400 = "AGENTBODY " * 40

# F39.6: the `decisions` facts section is gone (its fault name is no longer exercised; see SPEC-GAPS.md F39).
SECTION_HEADS = {"user_messages": EIGHT[0], "files": EIGHT[1], "tasks": EIGHT[2],
                 "open_tasks": EIGHT[3], "background_agents": EIGHT[4], "git": EIGHT[5], "bash": EIGHT[6],
                 "assistant": EIGHT[7]}
ALL_SECTIONS = ["agent", "warning", "fallback"] + list(SECTION_HEADS)
FACT_ORDER = list(SECTION_HEADS)
REASON_TEXT = {"agent_absent": "no agent handoff", "agent_stale": "agent handoff stale",
               "fallback_failed": "Haiku fallback failed", "fallback_timeout": "Haiku fallback timed out",
               "no_health": "no health record for this compaction", "handoff_missing": "no handoff file for this session",
               "handoff_old": "handoff not refreshed for this compaction"}
PLAIN = "Pre-compaction handoff (auto-saved):\n"
TAIL = " Verify the handoff against the transcript before acting.\n"


def fault(*names):
    return {"HANDOFF_TEST_FAULT": ",".join(names)}


def flat_strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from flat_strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from flat_strings(v)


class F36(f35.F35):
    def setUp(self):
        super().setUp()
        self.write_transcript([user("hello there"), asst("ok")])

    def run_ok(self, sid="S", fallback="0", extra=None, **kw):
        r = self.run_pre(self.payload(sid, **kw), fallback=fallback, extra=extra)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        return r

    def fresh_agent(self):
        self.put_agent(BODY400, age_min=1)

    def repo(self, branch=None):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo, exist_ok=True)
        git(repo, "init", "-q")
        if branch:
            git(repo, "checkout", "-q", "-b", branch)
        open(os.path.join(repo, "dirty.txt"), "w").write("x")
        return repo


# ---------------------------------------------------------------- AC 49-55 health log
class HealthLog(F36):
    def test_ac49_line_shape(self):
        self.fresh_agent()
        self.run_ok(sid="ABCDEFGHIJKL")
        lines = self.health_lines()
        self.assertEqual(len(lines), 1)
        h = json.loads(lines[0])
        self.assertIsInstance(h, dict)
        keys_ok(self, h)
        self.assertEqual(h["sid"], "ABCDEFGH")
        self.assertRegex(h["ts"], TS_RE)
        self.assertIsInstance(h["duration_ms"], int)
        self.assertNotIsInstance(h["duration_ms"], bool)
        self.assertGreaterEqual(h["duration_ms"], 0)
        self.assertEqual(h["output_chars"], len(self.latest("ABCDEFGHIJKL")))
        self.assertIn(h["status"], ("ok", "reduced", "degraded"))
        self.assertIsInstance(h["hook_version"], str)
        self.assertTrue(h["hook_version"])
        self.assertIs(h["canary_child"], False)
        self.assertIsInstance(h["truncated"], bool)
        self.assertIsInstance(h["errors"], list)
        self.assertIsInstance(h["stale_sections"], list)
        self.assertEqual(lines[0], json.dumps(h))  # json.dumps default separators

    def test_ac49_hook_version_is_semver(self):
        self.run_ok()
        self.assertRegex(self.health()["hook_version"], r"^\d+\.\d+\.\d+")

    def test_ac49_two_runs_two_lines(self):
        self.run_ok()
        self.run_ok()
        self.assertEqual(len(self.health_lines()), 2)

    def test_ac49_sid_unknown_for_empty_or_garbage(self):
        for raw in ("{}", "garbage", ""):
            r = self.run_pre(raw=raw)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""), raw)
        lines = self.health_lines()
        self.assertEqual(len(lines), 3)
        for l in lines:
            h = json.loads(l)
            self.assertEqual(h["sid"], "unknown")
            keys_ok(self, h)

    def test_ac49_sid_is_sanitised_prefix(self):
        self.run_ok(sid="a/b/c/d/e/f")
        self.assertEqual(self.health()["sid"], "a_b_c_d_")

    def test_ac49_short_sid(self):
        self.run_ok(sid="xy")
        self.assertEqual(self.health()["sid"], "xy")

    def test_ac50_no_marker_no_paths(self):
        M = "ZQMARKERZQ"
        cwd = os.path.join(self.tmp, "cwd" + M)
        os.makedirs(cwd)
        self.fresh_agent()
        self.write_transcript([user("msg " + M), asst("reply " + M), tool("Edit", file_path="/p/" + M + "/f.py"),
                               tool("Bash", command="echo " + M)])
        self.run_ok(cwd=cwd)
        self.run_ok(cwd=cwd, extra=fault("git"))
        for l in self.health_lines():
            self.assertNotIn(M, l)
            for s in flat_strings(json.loads(l)):
                self.assertNotIn("/", s, l)

    def test_ac50_no_exception_message_or_paths_under_toplevel(self):
        self.run_ok(extra=fault("toplevel"))
        l = self.health_lines()[0]
        self.assertNotIn("injected", l)
        for s in flat_strings(json.loads(l)):
            self.assertNotIn("/", s)

    # AC 51 classification matrix
    def row(self, setup, fallback="0", shim=None, expect=None, extra=None, trigger="auto"):
        if shim is not None:
            self.install_shim(**shim)
        setup()
        self.run_ok(fallback=fallback, extra=extra)
        h = self.health()
        for k, v in (expect or {}).items():
            self.assertEqual(h[k], v, (k, h))
        return h

    def test_ac51_fresh(self):
        # F38.6: `skipped` is no longer produced; the default helper run has the summary disabled
        h = self.row(self.fresh_agent, expect={"agent_file": "fresh", "fallback": "disabled", "summary_model": "",
                                               "status": "ok", "errors": [], "stale_sections": []})
        s = self.sidecar()
        self.assertEqual((s["reasons"], s["degraded"]), ([], False))

    def test_ac51_fresh_with_fallback_enabled_runs_summary(self):  # F38.1/F38.6 amend "skipped"
        self.install_shim(out="H" * 100)
        self.fresh_agent()
        self.run_ok(fallback="1")
        h = self.health()
        self.assertEqual((h["agent_file"], h["fallback"], h["status"]), ("fresh", "ok", "ok"))
        self.assertEqual(h["summary_model"], "sonnet")
        self.assertTrue(self.shim_invoked())

    def test_ac51_stale_disabled_with_sections(self):
        self.row(lambda: self.put_agent(BODY400, meta=STALE_META),
                 expect={"agent_file": "stale", "fallback": "disabled", "stale_sections": [IP, NS], "status": "degraded"})

    def test_ac51_stale_disabled_without_sections_is_degraded(self):
        self.row(lambda: self.put_agent(BODY400, age_min=40),
                 expect={"agent_file": "stale", "fallback": "disabled", "stale_sections": [], "status": "degraded"})

    def test_ac51_stale_with_sections_and_shim_ok_is_degraded(self):
        self.row(lambda: self.put_agent(BODY400, meta=STALE_META), fallback="1", shim={"out": "HAIKU " + "h" * 80},
                 expect={"agent_file": "stale", "fallback": "ok", "stale_sections": [IP, NS], "status": "degraded"})

    def test_ac51_stale_without_sections_and_shim_ok_is_reduced(self):
        self.row(lambda: self.put_agent(BODY400, age_min=40), fallback="1", shim={"out": "HAIKU " + "h" * 80},
                 expect={"agent_file": "stale", "fallback": "ok", "stale_sections": [], "status": "reduced"})
        s = self.sidecar()
        self.assertEqual((s["reasons"], s["degraded"]), (["agent_stale"], False))

    def test_ac51_absent_shim_ok_is_reduced(self):
        self.row(lambda: None, fallback="1", shim={"out": "HAIKU " + "h" * 80},
                 expect={"agent_file": "absent", "fallback": "ok", "status": "reduced", "stale_sections": []})

    def test_ac51_absent_shim_fails_is_degraded(self):
        self.row(lambda: None, fallback="1", shim={"rc": 3, "out": ""},
                 expect={"agent_file": "absent", "fallback": "failed", "status": "degraded"})

    def test_ac51_absent_disabled_is_degraded(self):
        self.row(lambda: None, fallback="0", expect={"agent_file": "absent", "fallback": "disabled", "status": "degraded"})

    def test_ac51_agent_below_300_bytes_counts_as_absent(self):
        self.row(lambda: self.put_agent("short", age_min=1), fallback="0",
                 expect={"agent_file": "absent", "fallback": "disabled", "status": "degraded"})

    @unittest.skipUnless(os.environ.get("HANDOFF_SLOW") == "1", "75 s shim sleep; set HANDOFF_SLOW=1")
    def test_ac51_absent_timeout(self):
        self.install_shim(out="x")
        open(os.path.join(self.shimdir, "sleep"), "w").write("90")
        self.run_ok(fallback="1")
        h = self.health()
        self.assertEqual((h["agent_file"], h["fallback"], h["status"]), ("absent", "timeout", "degraded"))

    def test_ac51_fresh_plus_each_fault_is_degraded_and_toplevel(self):
        for name in ALL_SECTIONS + ["toplevel"]:
            with self.subTest(name):
                shutil.rmtree(self.hd, ignore_errors=True)
                self.fresh_agent()
                self.run_ok(extra=fault(name))
                self.assertEqual(self.health()["status"], "degraded", name)

    def test_ac51_trigger_passthrough(self):
        for trig, want in (("auto", "auto"), ("manual", "manual"), ("weird", "unknown"), (None, "unknown"), (5, "unknown")):
            p = self.payload("S", trigger=trig)
            if trig is None:
                p.pop("trigger")
            self.assertEqual(self.run_pre(p).returncode, 0)
            self.assertEqual(self.health()["trigger"], want, trig)

    def test_ac52_truncated_and_errors(self):
        self.write_transcript([user("small"), asst("ok")])
        self.fresh_agent()
        self.run_ok()
        h = self.health()
        self.assertIs(h["truncated"], False)
        self.assertEqual(h["errors"], [])
        # AC 39 over-cap fixture
        shutil.rmtree(self.hd)
        self.install_shim(out="Y" * 4000)
        self.put_agent("L" * 5000, meta={"agentWrittenAt": 1})
        e = [user(("U%02d" % i) + "u" * 300) for i in range(4)]
        e += [tool("Edit", file_path="/f/file%02d.py" % i) for i in range(6)]
        e += [tool("Bash", command="echo c%d" % i) for i in range(3)]
        e += [tool("TaskCreate", subject=("s%03d" % i) + "s" * 150) for i in range(400)]  # F39.6: pushes past 14,000
        e.append(asst("A" * 400))
        self.write_transcript(e)
        self.run_ok(fallback="1")
        h = self.health()
        self.assertIs(h["truncated"], True)
        self.assertEqual(h["errors"], [])
        self.assertLessEqual(h["output_chars"], CAP)

    def test_ac53_child_guard_no_health_no_sidecar(self):
        self.install_shim(out="x" * 100)
        r = self.run_pre(self.payload(), fallback="1", extra={"HANDOFF_HOOK_CHILD": "1"})
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertFalse(os.path.exists(self.hd))

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores permissions")
    def test_ac53_unwritable_dir(self):
        os.makedirs(self.hd)
        os.chmod(self.hd, 0o500)
        self.addCleanup(os.chmod, self.hd, 0o700)
        r = self.run_pre(self.payload())
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_ac53_dir_path_blocked_by_file(self):
        os.makedirs(os.path.dirname(self.hd))
        open(self.hd, "w").write("not a dir")
        r = self.run_pre(self.payload())
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    # AC 54 rotation
    def seed(self, n):
        os.makedirs(self.hd, exist_ok=True)
        lines = ['{"seed": %d, "pad": "%s"}' % (i, "x" * (i % 7)) for i in range(n)]
        with open(self.health_path(), "w") as f:
            f.write("\n".join(lines) + "\n")
        return lines

    def test_ac54_5000_plus_one(self):
        old = self.seed(5000)
        self.run_ok()
        new = self.health_lines()
        self.assertEqual(len(new), 5000)
        self.assertEqual(new[:-1], old[1:])
        keys_ok(self, json.loads(new[-1]))

    def test_ac54_4999_plus_one(self):
        old = self.seed(4999)
        self.run_ok()
        new = self.health_lines()
        self.assertEqual(len(new), 5000)
        self.assertEqual(new[:-1], old)

    def test_ac54_7000(self):
        old = self.seed(7000)
        self.run_ok()
        new = self.health_lines()
        self.assertEqual(len(new), 5000)
        self.assertEqual(new[:-1], old[2001:])
        keys_ok(self, json.loads(new[-1]))

    # AC 55 sidecar
    def test_ac55_sidecar_equals_line_plus(self):
        self.fresh_agent()
        self.run_ok()
        h, s = self.health(), self.sidecar()
        self.assertEqual(s.pop("reasons"), [])
        self.assertIs(s.pop("degraded"), False)
        self.assertEqual(s, h)
        self.assertEqual(h["status"], "ok")

    def test_ac55_absent_ok_reduced(self):
        self.install_shim(out="HAIKU " + "h" * 80)
        self.run_ok(fallback="1")
        s = self.sidecar()
        self.assertEqual((s["status"], s["reasons"], s["degraded"]), ("reduced", ["agent_absent"], False))
        h = dict(s)
        h.pop("reasons"), h.pop("degraded")
        self.assertEqual(h, self.health())

    def test_ac55_absent_failed_degraded(self):
        self.install_shim(rc=3, out="")
        self.run_ok(fallback="1")
        s = self.sidecar()
        self.assertEqual((s["status"], s["reasons"], s["degraded"]), ("degraded", ["agent_absent", "fallback_failed"], True))

    def test_ac55_sidecar_overwritten_each_run(self):
        self.fresh_agent()
        self.run_ok()
        self.assertEqual(self.sidecar()["status"], "ok")
        os.remove(os.path.join(self.hd, "S-agent.md"))
        self.run_ok()
        self.assertEqual(self.sidecar()["status"], "degraded")

    def test_ac55_sidecar_uses_full_sanitised_sid(self):
        self.fresh_agent_sid = None
        self.run_ok(sid="a/b/c/d/e/f/g")
        self.assertTrue(os.path.exists(os.path.join(self.hd, "a_b_c_d_e_f_g-last-health.json")))

    def test_ac55_stale_sections_reasons(self):
        self.put_agent(BODY400, meta=STALE_META)
        self.run_ok()
        s = self.sidecar()
        self.assertTrue(s["degraded"])
        self.assertIn("agent_stale", s["reasons"])


# ---------------------------------------------------------------- AC 56-60 fail-safe
class FailSafe(F36):
    def rich(self, pad=40, path_len=100):
        qs = [("Which name?", "Name", ["alpha", "beta"])]
        e = [user(("U%02d" % i) + "u" * pad) for i in range(8)]
        e += [f35.ask("q1", qs), f35.answer("q1", {"Which name?": "alpha"})]
        e += [tool("Edit", file_path="/" + ("p%02d" % i) + "d" * path_len) for i in range(30)]
        e += [tool("TaskCreate", subject="s" * 150), tool("TaskCreate", subject="t" * 150)]
        e += [tool("TodoWrite", todos=[{"content": "todo " + "z" * 140, "status": "pending", "activeForm": "x"}])]
        e += [tool("Bash", command=("c%d" % i) + "x" * pad) for i in range(5)]
        e += [f35.tu("bg1", "Agent", {"description": "background job", "prompt": "p", "subagent_type": "g",
                                     "run_in_background": True}),
              f35.tres("bg1", "agentId: bgid1", {"agentId": "bgid1", "isAsync": True})]
        e.append(asst("A" * (pad + 50)))
        return e

    def full_world(self):
        self.repo_dir = self.repo()
        self.install_shim(out="HAIKU-TEXT " + "h" * 80)
        self.put_agent(BODY400, meta=STALE_META)
        self.write_transcript(self.rich())

    def full_run(self, extra=None, sid="S"):
        r = self.run_pre(self.payload(sid, cwd=self.repo_dir), fallback="1", extra=extra)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        return self.latest(sid)

    def test_ac56_each_section(self):
        self.full_world()
        base = self.full_run()
        self.assertEqual(heads9(base), EIGHT, "fixture must contain all eight facts sections")
        for h in (AGENT_H, SUMMARY_H):
            self.assertIn(h, base)
        self.assertIsNotNone(warn_line(base))
        footer = FOOTER_FMT.format(p=self.tpath)
        for name in ALL_SECTIONS:
            with self.subTest(name):
                shutil.rmtree(self.hd)
                self.install_shim(out="HAIKU-TEXT " + "h" * 80)
                self.put_agent(BODY400, meta=STALE_META)
                t = self.full_run(extra=fault(name))
                line = "(section %s unavailable: RuntimeError)" % name
                self.assertEqual(t.split("\n").count(line), 1, t)
                self.assertEqual(t.count("unavailable"), 1)
                lines = t.rstrip("\n").split("\n")
                self.assertEqual(lines[0], "# Handoff (pre-compaction)")
                self.assertEqual(lines[-1], footer)
                li = t.index(line)
                if name == "warning":
                    self.assertEqual(li + len(line) + 1, t.index(AGENT_H))
                    self.assertIsNone(warn_line(t))
                elif name == "agent":
                    self.assertNotIn(BODY400.strip(), t)
                    self.assertNotIn(AGENT_H, t)
                    self.assertLess(li, t.index(FACTS_H))
                elif name == "fallback":
                    self.assertNotIn(SUMMARY_H, t)
                    self.assertNotIn("HAIKU-TEXT", t)
                    self.assertGreater(li, t.index(AGENT_H))
                    self.assertLess(li, t.index(FACTS_H))
                else:
                    head = SECTION_HEADS[name]
                    self.assertNotIn(head, t)
                    i = FACT_ORDER.index(name)
                    prev = AGENT_H if i == 0 else SECTION_HEADS[FACT_ORDER[i - 1]]
                    nxt = footer if i == len(FACT_ORDER) - 1 else SECTION_HEADS[FACT_ORDER[i + 1]]
                    self.assertGreater(li, t.index(prev))
                    self.assertLess(li, t.index(nxt))
                # all other sections intact
                others = [h for h in EIGHT if SECTION_HEADS.get(name) != h]
                if name != "agent":
                    others.append(AGENT_H)
                if name not in ("fallback", "agent"):
                    others.append(SUMMARY_H)
                for h in others:
                    a = (f35.section(base, h) or "").replace(footer, "").strip()
                    b = (f35.section(t, h) or "").replace(line, "").replace(footer, "").strip()
                    self.assertEqual(b, a, h)
                hl = self.health()
                self.assertEqual(hl["errors"], [name])
                self.assertEqual(hl["status"], "degraded")
                s = self.sidecar()
                self.assertIs(s["degraded"], True)
                self.assertIn("section_errors", s["reasons"])

    def test_ac57_two_faults(self):
        self.full_world()
        base = self.full_run()
        shutil.rmtree(self.hd)
        self.install_shim(out="HAIKU-TEXT " + "h" * 80)
        self.put_agent(BODY400, meta=STALE_META)
        t = self.full_run(extra=fault("git", "bash"))
        self.assertIn("(section git unavailable: RuntimeError)", t.split("\n"))
        self.assertIn("(section bash unavailable: RuntimeError)", t.split("\n"))
        self.assertEqual(self.health()["errors"], ["git", "bash"])
        for h in EIGHT:
            if h in (EIGHT[5], EIGHT[6]):
                self.assertNotIn(h, t)
            else:
                self.assertEqual((f35.section(t, h) or "").replace("(section git unavailable: RuntimeError)", "")
                                 .replace("(section bash unavailable: RuntimeError)", "").strip(),
                                 f35.section(base, h).strip(), h)

    def test_ac57_fault_order_is_assembly_order(self):
        self.fresh_agent()
        self.run_ok(extra=fault("bash", "git"))  # given reversed; assembly order wins
        self.assertEqual(self.health()["errors"], ["git", "bash"])

    def test_ac57_replacement_survives_cap_trimming(self):
        self.repo_dir = self.repo()
        for name in ("user_messages", "files", "assistant", "open_tasks"):
            with self.subTest(name):
                shutil.rmtree(self.hd, ignore_errors=True)
                self.write_transcript(self.rich(pad=1000, path_len=250) + [tool("TaskCreate", subject=("n%03d" % i) + "q" * 150) for i in range(400)])
                self.put_agent("L" * 5000, meta={"agentWrittenAt": 1})
                t = self.run_and_read(cwd=self.repo_dir)  # unfaulted reference size
                r = self.run_pre(self.payload(cwd=self.repo_dir), extra=fault(name))
                self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
                t = self.latest()
                self.assertLessEqual(len(t), CAP)
                self.assertIn("(section %s unavailable: RuntimeError)" % name, t.split("\n"))
                self.assertEqual(self.health()["errors"], [name])

    def test_ac58_agent_fault(self):
        self.install_shim(out="HAIKU-TEXT " + "h" * 80)
        self.fresh_agent()
        r = self.run_pre(self.payload(), fallback="1", extra=fault("agent"))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        t = self.latest()
        self.assertNotIn(BODY400.strip(), t)
        self.assertIn("(section agent unavailable: RuntimeError)", t.split("\n"))
        self.assertEqual(self.health()["errors"], ["agent"])

    # AC 59 / 60 top-level
    def minimal(self, t, cwd, trigger, branch=None, sid="S", cwd_in_file=True):
        lines = t.rstrip("\n").split("\n")
        self.assertEqual(lines[0], "# Handoff (minimal: hook failed with RuntimeError)")
        self.assertEqual(lines[1], "- session: " + sid)
        self.assertEqual(lines[2], "- cwd: " + cwd)
        self.assertEqual(lines[3], "- trigger: " + trigger)
        self.assertTrue(lines[4].startswith("- time: ") and len(lines[4]) > 10, lines[4])
        self.assertEqual(lines[5], "- transcript: " + self.tpath)
        if branch:
            self.assertEqual(lines[6], "- git branch: " + branch)
            self.assertEqual(len(lines), 8, lines)
        else:
            self.assertEqual(len(lines), 7, lines)
            self.assertFalse(any(l.startswith("- git branch:") for l in lines))
        self.assertEqual(lines[-1], FOOTER_FMT.format(p=self.tpath))

    def stamped(self, sid="S"):
        names = [n for n in os.listdir(self.hd) if re.fullmatch(re.escape(sid) + r"-\d{8}T\d{6}Z\.md", n)]
        self.assertEqual(len(names), 1, os.listdir(self.hd))
        return os.path.join(self.hd, names[0])

    def test_ac59_toplevel_git_repo(self):
        repo = self.repo(branch="zbranch")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "init")
        r = self.run_pre(self.payload(cwd=repo, trigger="manual"), extra=fault("toplevel"))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        t = self.latest()
        self.minimal(t, repo, "manual", branch="zbranch")
        self.assertEqual(open(self.stamped(), "rb").read(), open(os.path.join(self.hd, "S-latest.md"), "rb").read())
        h = self.health()
        self.assertEqual(h["errors"], ["toplevel"])
        self.assertEqual(h["status"], "degraded")
        s = self.sidecar()
        self.assertIs(s["degraded"], True)
        self.assertIn("section_errors", s["reasons"])

    def test_ac59_toplevel_non_repo_and_missing_cwd(self):
        for cwd in (self.tmp, os.path.join(self.tmp, "does-not-exist")):
            shutil.rmtree(self.hd, ignore_errors=True)
            r = self.run_pre(self.payload(cwd=cwd), extra=fault("toplevel"))
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
            self.minimal(self.latest(), cwd, "auto")
            self.assertEqual(self.health()["errors"], ["toplevel"])

    def test_ac59_toplevel_ignores_other_faults_value_combo(self):
        self.run_ok(extra=fault("toplevel", "git"))
        self.assertTrue(self.latest().startswith("# Handoff (minimal: hook failed with RuntimeError)"))

    def test_ac60_garbage_stdin_toplevel(self):
        r = self.run_pre(raw="garbage", extra=fault("toplevel"))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        t = self.latest("unknown")
        self.assertTrue(t.startswith("# Handoff (minimal: hook failed with RuntimeError)"))
        self.assertIn("- session: unknown", t)

    def test_fault_seam_ignores_unknown_values_and_changes_nothing(self):
        self.full_world = FailSafe.full_world.__get__(self)
        self.full_world()
        a = self.full_run()
        shutil.rmtree(self.hd)
        self.install_shim(out="HAIKU-TEXT " + "h" * 80)
        self.put_agent(BODY400, meta=STALE_META)
        b = self.full_run(extra={"HANDOFF_TEST_FAULT": "bogus,Git, ,nonsense"})
        strip = lambda x: "\n".join(l for l in x.split("\n") if not l.startswith("- time:"))
        self.assertEqual(strip(a), strip(b))
        self.assertEqual(self.health()["errors"], [])


# ---------------------------------------------------------------- AC 61-65 inject
class Inject(F36):
    def test_ac61_plain_with_fresh_sidecar(self):
        self.put_latest("\n  hello handoff\nline2  \n\n")
        self.put_sidecar(status="reduced", reasons=["agent_absent"])
        ctx = self.post_ctx()
        self.assertEqual(ctx, PLAIN + "hello handoff\nline2")
        self.assertIsNone(self.degraded_file())
        r = self.run_post({"session_id": "S"})
        self.assertEqual(json.loads(r.stdout), {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                                        "additionalContext": ctx}})
        self.assertEqual(len(r.stdout.strip().splitlines()), 1)

    def test_ac61_ok_sidecar(self):
        self.put_latest("BODY\n")
        self.put_sidecar(status="ok")
        self.assertEqual(self.post_ctx(), PLAIN + "BODY")
        self.assertIsNone(self.degraded_file())

    def test_ac62_degraded_sidecar(self):
        self.put_latest("HANDOFF-BODY\nmore\n")
        self.put_sidecar(status="degraded", reasons=["agent_absent", "fallback_failed"], trigger="manual")
        ctx = self.post_ctx()
        self.assertEqual(ctx, "HANDOFF DEGRADED: no agent handoff; Haiku fallback failed." + TAIL + PLAIN + "HANDOFF-BODY\nmore")
        self.assertLess(len(ctx), 10000)
        d = self.degraded_file()
        self.assertEqual(d["v"], 1)
        self.assertEqual(d["sid"], "S")
        self.assertRegex(d["ts"], TS_RE)
        self.assertEqual(d["reasons"], ["agent_absent", "fallback_failed"])
        self.assertEqual(d["trigger"], "manual")
        self.assertEqual(d["detected_by"], "inject")
        self.assertNotIn("clearedAt", d)

    def test_ac62_each_code_text(self):
        for code, text in REASON_TEXT.items():
            if code in ("no_health", "handoff_missing", "handoff_old"):
                continue
            with self.subTest(code):
                shutil.rmtree(self.hd, ignore_errors=True)
                self.put_latest("B\n")
                self.put_sidecar(status="degraded", reasons=[code])
                ctx = self.post_ctx()
                self.assertEqual(ctx, "HANDOFF DEGRADED: " + text + "." + TAIL + PLAIN + "B")
                self.assertEqual(self.degraded_file()["reasons"], [code])

    def test_ac62_section_errors_lists_names(self):
        self.put_latest("B\n")
        self.put_sidecar(status="degraded", reasons=["section_errors"], errors=["git", "bash", "toplevel"])
        ctx = self.post_ctx()
        self.assertEqual(ctx, "HANDOFF DEGRADED: sections unavailable: git, bash, toplevel." + TAIL + PLAIN + "B")
        self.assertEqual(self.degraded_file()["reasons"], ["section_errors"])

    def test_ac62_all_reasons_joined_in_order(self):
        self.put_latest("B\n")
        codes = ["agent_absent", "agent_stale", "fallback_failed", "fallback_timeout", "section_errors"]
        self.put_sidecar(status="degraded", reasons=codes, errors=["files"])
        ctx = self.post_ctx()
        want = "; ".join(["no agent handoff", "agent handoff stale", "Haiku fallback failed", "Haiku fallback timed out",
                          "sections unavailable: files"])
        self.assertTrue(ctx.startswith("HANDOFF DEGRADED: " + want + "." + TAIL + PLAIN))
        self.assertEqual(self.degraded_file()["reasons"], codes)

    def test_ac62_size_bound(self):
        self.put_latest("x" * 9500)
        self.put_sidecar(status="degraded", reasons=["agent_absent", "agent_stale", "fallback_failed", "fallback_timeout",
                                                     "section_errors"], errors=["user_messages", "background_agents"])
        ctx = self.post_ctx()
        self.assertLess(len(ctx), 10000)
        first = ctx.split("\n")[0]
        self.assertLessEqual(len(first), 300)

    def test_ac63_missing_or_empty_latest(self):
        msg = "HANDOFF DEGRADED: no handoff file for this session. Read the transcript (see session metadata) before acting."
        for content in (None, "", "  \n\t\n"):
            with self.subTest(repr(content)):
                shutil.rmtree(self.hd, ignore_errors=True)
                os.makedirs(self.hd)
                if content is not None:
                    self.put_latest(content)
                self.put_sidecar(status="ok")
                self.assertEqual(self.post_ctx(), msg)
                self.assertEqual(self.degraded_file()["reasons"], ["handoff_missing"])

    def test_ac63_missing_latest_without_sidecar(self):
        os.makedirs(self.hd)
        ctx = self.post_ctx()
        self.assertTrue(ctx.startswith("HANDOFF DEGRADED: no handoff file for this session."))
        self.assertEqual(self.degraded_file()["reasons"], ["handoff_missing"])

    def test_ac63_no_health(self):
        for variant in ("missing", "invalid", "array", "number"):
            with self.subTest(variant):
                shutil.rmtree(self.hd, ignore_errors=True)
                self.put_latest("BODY\n")
                if variant == "invalid":
                    self.put_sidecar(raw="{not json")
                elif variant == "array":
                    self.put_sidecar(raw="[1,2]")
                elif variant == "number":
                    self.put_sidecar(raw="5")
                ctx = self.post_ctx()
                self.assertEqual(ctx, "HANDOFF DEGRADED: no health record for this compaction." + TAIL + PLAIN + "BODY")
                self.assertEqual(self.degraded_file()["reasons"], ["no_health"])

    def test_ac63_handoff_old_boundary(self):
        self.put_latest("BODY\n")
        self.put_sidecar(status="ok", age_s=16 * 60)
        ctx = self.post_ctx()
        self.assertEqual(ctx, "HANDOFF DEGRADED: handoff not refreshed for this compaction." + TAIL + PLAIN + "BODY")
        self.assertEqual(self.degraded_file()["reasons"], ["handoff_old"])
        shutil.rmtree(self.hd)
        self.put_latest("BODY\n")
        self.put_sidecar(status="ok", age_s=14 * 60)
        self.assertEqual(self.post_ctx(), PLAIN + "BODY")
        self.assertIsNone(self.degraded_file())

    def test_ac63_unparseable_ts_is_old(self):
        self.put_latest("BODY\n")
        self.put_sidecar(status="ok", ts="not a time")
        self.assertTrue(self.post_ctx().startswith("HANDOFF DEGRADED: handoff not refreshed"))
        self.assertEqual(self.degraded_file()["reasons"], ["handoff_old"])

    def test_ac64_no_sid_stays_silent(self):
        self.put_latest("BODY\n")
        self.put_sidecar()
        for raw in ('{"foo":1}', '{"session_id":""}', '{"session_id":5}', '{"session_id":null}', "not json", "", "[]", "5"):
            r = self.run_post(raw=raw)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""), raw)
        self.assertEqual([n for n in os.listdir(self.hd) if n.endswith("-degraded.json")], [])

    def test_ac64_no_sid_no_dir_no_files(self):
        r = self.run_post(raw="garbage")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertFalse(os.path.exists(self.hd) and os.listdir(self.hd))

    # AC 65 end to end
    def test_ac65_reduced_then_inject_is_plain(self):
        self.install_shim(out="HAIKU " + "h" * 80)
        self.run_ok(fallback="1")
        content = self.latest()
        self.assertEqual(self.health()["status"], "reduced")
        ctx = self.post_ctx()
        self.assertEqual(ctx, PLAIN + content.strip())
        self.assertIsNone(self.degraded_file())

    def test_ac65_degraded_then_inject_warns(self):
        self.install_shim(rc=3, out="")
        self.run_ok(fallback="1")
        content = self.latest()
        ctx = self.post_ctx()
        self.assertTrue(ctx.startswith("HANDOFF DEGRADED: no agent handoff; Haiku fallback failed."))
        self.assertTrue(ctx.endswith(PLAIN + content.strip()))
        self.assertEqual(self.degraded_file()["reasons"], ["agent_absent", "fallback_failed"])

    def test_ac65_fresh_then_inject_plain(self):
        self.fresh_agent()
        self.run_ok()
        content = self.latest()
        self.assertEqual(self.health()["status"], "ok")
        self.assertEqual(self.post_ctx(), PLAIN + content.strip())
        self.assertIsNone(self.degraded_file())

    def test_ac65_existing_degraded_file_semantics(self):
        os.makedirs(self.hd, exist_ok=True)
        path = os.path.join(self.hd, "S-degraded.json")
        old = {"v": 1, "sid": "S", "ts": "2026-01-01T00:00:00Z", "reasons": ["agent_stale"], "trigger": "auto",
               "detected_by": "inject", "clearedAt": "2026-01-01T01:00:00Z"}
        # ok / reduced inject leaves it untouched
        for setup in (self.fresh_agent, None):
            shutil.rmtree(self.hd, ignore_errors=True)
            os.makedirs(self.hd)
            raw = json.dumps(old, indent=1)
            open(path, "w").write(raw)
            if setup:
                setup()
            else:
                self.install_shim(out="HAIKU " + "h" * 80)
            self.run_ok(fallback="1" if not setup else "0")
            self.assertEqual(open(path).read(), raw)
            self.assertEqual(self.post_ctx().split("\n")[0], PLAIN.strip())
            self.assertEqual(open(path).read(), raw)
        # degraded inject overwrites, losing clearedAt
        shutil.rmtree(self.hd, ignore_errors=True)
        os.makedirs(self.hd)
        open(path, "w").write(json.dumps(old))
        self.run_ok(fallback="0")  # absent + disabled -> degraded
        self.post_ctx()
        d = self.degraded_file()
        self.assertNotIn("clearedAt", d)
        self.assertEqual(d["reasons"], ["agent_absent"])
        self.assertNotEqual(d["ts"], old["ts"])


# ---------------------------------------------------------------- AC 66-68
class Misc(F36):
    def age(self, name, days, content="x"):
        os.makedirs(self.hd, exist_ok=True)
        p = os.path.join(self.hd, name)
        open(p, "w").write(content)
        t = time.time() - days * 86400
        os.utime(p, (t, t))
        return p

    def test_ac66_cleanup(self):
        gone = [self.age("x-degraded.json", 15), self.age("x-last-health.json", 15)]
        kept = [self.age("y-degraded.json", 13), self.age("y-last-health.json", 13),
                self.age("health.jsonl", 400, '{"old":1}\n'), self.age("notes.txt", 15),
                self.age("x-agent.meta.json", 15)]
        self.fresh_agent()
        self.run_ok()
        for p in gone:
            self.assertFalse(os.path.exists(p), p)
        for p in kept:
            self.assertTrue(os.path.exists(p), p)
        self.assertEqual(self.health_lines()[0], '{"old":1}')

    def test_ac67_state_dir_override(self):
        d2 = os.path.join(self.tmp, "state2")
        ex = {"HANDOFF_STATE_DIR": d2}
        self.fresh_agent_path = None
        self.run_ok(extra=ex)
        for n in ("S-latest.md", "health.jsonl", "S-last-health.json"):
            self.assertTrue(os.path.exists(os.path.join(d2, n)), n)
        self.assertTrue([n for n in os.listdir(d2) if re.fullmatch(r"S-\d{8}T\d{6}Z\.md", n)])
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local")), os.listdir(self.home))
        # degraded inject writes the degraded file there only
        ctx = self.post_ctx(extra=ex)
        self.assertTrue(ctx.startswith("HANDOFF DEGRADED: no agent handoff"))
        self.assertTrue(os.path.exists(os.path.join(d2, "S-degraded.json")))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local")))

    def test_ac67_unset_or_empty_uses_home(self):
        self.run_ok(extra={"HANDOFF_STATE_DIR": ""})
        self.assertTrue(os.path.exists(os.path.join(self.hd, "S-latest.md")))
        self.assertTrue(os.path.exists(os.path.join(self.hd, "health.jsonl")))

    def test_ac68_canary_child_flag_only(self):
        norm = lambda x: "\n".join(l for l in x.split("\n") if not l.startswith("- time:"))
        self.put_agent(BODY400, age_min=1)
        self.run_ok()
        a_text, a_h = self.latest(), self.health()
        shutil.rmtree(self.hd)
        self.put_agent(BODY400, age_min=1)
        self.run_ok(extra={"HANDOFF_CANARY": "1"})
        b_text, b_h = self.latest(), self.health()
        self.assertIs(b_h["canary_child"], True)
        self.assertIs(a_h["canary_child"], False)
        self.assertEqual(norm(a_text), norm(b_text))
        for h in (a_h, b_h):
            for k in ("ts", "duration_ms", "canary_child"):
                h.pop(k)
        self.assertEqual(a_h, b_h)

    def test_ac68_child_guard_still_wins(self):
        self.run_ok(extra={"HANDOFF_CANARY": "1", "HANDOFF_HOOK_CHILD": "1"})
        self.assertFalse(os.path.exists(self.hd))


if __name__ == "__main__":
    unittest.main()
