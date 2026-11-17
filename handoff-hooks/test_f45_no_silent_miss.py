"""F45 (hooks 1.9.0) ACs 172-180 of specs/handoff-hooks-spec.md (code-blind: written from the spec only).
Write early (pending file), recover at SessionStart compact, reconcile, install check. Temp HOME, shim `claude`."""
import hashlib, json, os, plistlib, re, shutil, signal, subprocess, sys, time, unittest

from helpers import (HookCase, HOOKS_DIR, PRE, POST, PLAIN, user, asst)

BOUNDARY = {"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted"}
TEMPLATE_DIR = os.path.dirname(HOOKS_DIR)
REPO_DIR = os.path.dirname(TEMPLATE_DIR)
SETTINGS_TPL = os.path.join(TEMPLATE_DIR, "settings.template.json")
CHECK_TAIL = " Run the installer again, then restart Claude Code."
RECOVERED_HEAD = ("HANDOFF RECOVERED: the pre-compaction hook did not run for this compaction; this handoff was "
                  "rebuilt from the transcript without a model summary. Use recall for detail.")
DEGRADED_MISSING = ("HANDOFF DEGRADED: no handoff file for this session. Read the transcript (see session metadata) "
                    "before acting.")
SID = "f45aaaaa-0000-4000-8000-000000000001"
PRE_MSG = "Please refactor the billing module and keep the public API stable PREBOUNDARY-MARK"
OLD_MSG = "Earlier I asked you to look at the invoice rounding bug in detail OLDMSG-MARK"
POST_MSG = "After the compaction I only said this later message POSTBOUNDARY-MARK"


def iso(offset_s=0):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset_s))


def killpg(p):
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


class F45Base(HookCase):
    def read_json(self, p):
        with open(p) as f:
            return json.load(f)

    def health_rows(self):
        p = self.health_path()
        if not os.path.exists(p):
            return []
        return [json.loads(l) for l in open(p).read().split("\n") if l.strip()]

    def add_health_row(self, sid, trigger="auto", ts=None, **kw):
        os.makedirs(self.hd, exist_ok=True)
        row = {"ts": ts or iso(), "sid": sid[:8], "trigger": trigger, "status": "ok"}
        row.update(kw)
        with open(self.health_path(), "a") as f:
            f.write(json.dumps(row) + "\n")

    def errors_lines(self):
        p = os.path.join(self.hd, "hooks-error.jsonl")
        return [l for l in open(p).read().split("\n") if l.strip()] if os.path.exists(p) else []

    def compact_payload(self, sid=SID, transcript=None):
        return {"session_id": sid, "cwd": self.tmp, "hook_event_name": "SessionStart", "source": "compact",
                "transcript_path": transcript if transcript is not None else self.tpath}

    def part_ctx(self, k, payload):
        t = time.time()
        r = self.run_post(payload, args=("--part", str(k)))
        self.elapsed = time.time() - t
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        if r.stdout.strip() == "":
            return None
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]

    def boundary_transcript(self):
        self.write_transcript([user(OLD_MSG), asst("looking at it"), user(PRE_MSG), asst("on it"),
                               dict(BOUNDARY, timestamp=iso(-60)), user(POST_MSG), asst("ok")])

    def all_hd_text(self):
        out = []
        for root, _, files in os.walk(self.hd):
            for n in files:
                try:
                    out.append((os.path.join(root, n), open(os.path.join(root, n), errors="replace").read()))
                except OSError:
                    pass
        return out


# ---------------------------------------------------------------- AC 172
class WriteEarly(F45Base):
    def test_ac172_killed_run_leaves_pending_and_handoff(self):
        self.write_transcript([user(PRE_MSG), asst("working on it")])
        self.install_shim(out="SUMMARY")
        self.set_shim("summary", sleepx=60)
        p = subprocess.Popen([sys.executable, PRE], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, env=self.env(None), start_new_session=True)
        self.addCleanup(lambda: (killpg(p), p.wait()))
        p.stdin.write(json.dumps(self.payload()).encode())
        p.stdin.close()
        time.sleep(3)
        self.assertIsNone(p.poll(), "hook should still be waiting on the fake model call")
        killpg(p)
        p.wait()
        pend = os.path.join(self.hd, "S-pending.json")
        self.assertTrue(os.path.exists(pend), os.listdir(self.hd))
        d = self.read_json(pend)
        for k in ("ts", "trigger", "hook_version"):
            self.assertIn(k, d)
        self.assertEqual(d["trigger"], "auto")
        self.assertEqual(d["hook_version"], "1.9.0")
        self.assertIn("PREBOUNDARY-MARK", self.latest())
        found = [pth for pth, txt in self.all_hd_text() if "PREBOUNDARY-MARK" in txt and pth.endswith(".md")]
        self.assertGreaterEqual(len(found), 1)

    def test_ac172_normal_run_leaves_no_pending(self):
        self.write_transcript([user(PRE_MSG), asst("working on it")])
        self.install_shim(out="SUMMARY-TEXT-FROM-FAKE-MODEL " * 3)
        r = self.run_pre(self.payload(), fallback=None)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertTrue(self.shim_invoked())
        self.assertFalse(os.path.exists(os.path.join(self.hd, "S-pending.json")), os.listdir(self.hd))
        self.assertEqual(self.health()["sid"], "S")


# ---------------------------------------------------------------- AC 173-176
class Recover(F45Base):
    def setUp(self):
        super().setUp()
        self.boundary_transcript()
        self.install_shim(out="SHOULD-NOT-BE-CALLED")

    def check_recovered(self, ctx):
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx.startswith("HANDOFF RECOVERED:"), ctx[:200])
        self.assertEqual(ctx.split("\n")[0], RECOVERED_HEAD)
        self.assertIn(PRE_MSG, ctx)
        self.assertNotIn("POSTBOUNDARY-MARK", ctx)
        self.assertLess(len(ctx), 10000)
        self.assertLess(self.elapsed, 6)
        self.assertFalse(self.shim_invoked(), "recovery must not call the model")
        self.assertEqual(self.merge_calls(), 0)
        row = self.health_rows()[-1]
        self.assertEqual((row["trigger"], row["status"]), ("recovered", "recovered"))
        pl = self.compact_payload()
        self.assertIsNone(self.part_ctx(2, pl))
        self.assertIsNone(self.part_ctx(3, pl))

    def test_ac173_no_handoff_file_is_recovered(self):
        self.assertFalse(os.path.exists(self.hd))
        ctx = self.part_ctx(1, self.compact_payload())
        self.check_recovered(ctx)

    def test_ac174_old_handoff_is_recovered_and_archived(self):
        self.put_latest("OLDHANDOFF-MARKER-BODY\n", sid=SID)
        self.put_sidecar(sid=SID, status="ok", age_s=2 * 3600)
        self.add_health_row(SID, ts=iso(-2 * 3600))
        ctx = self.part_ctx(1, self.compact_payload())
        self.check_recovered(ctx)
        self.assertTrue(any("OLDHANDOFF-MARKER-BODY" in t for _, t in self.all_hd_text()),
                        "the older handoff must remain as an archive")

    def test_ac175_fresh_handoff_is_untouched(self):
        self.put_latest("BODY\n", sid=SID)
        self.put_sidecar(sid=SID, status="ok", age_s=60)
        self.add_health_row(SID, ts=iso(-60))
        ctx = self.part_ctx(1, self.compact_payload())
        self.assertEqual(ctx, PLAIN + "BODY")
        self.assertNotIn("RECOVERED", ctx)
        self.assertNotIn("DEGRADED", ctx)
        self.assertFalse([r for r in self.health_rows() if r.get("trigger") == "recovered"])
        self.assertFalse(self.shim_invoked())

    def test_ac176_missing_transcript_falls_back_to_degraded(self):
        pl = self.compact_payload(transcript=os.path.join(self.tmp, "nope.jsonl"))
        ctx = self.part_ctx(1, pl)
        self.assertEqual(ctx, DEGRADED_MISSING)
        self.assertEqual(len(self.errors_lines()), 1, self.errors_lines())
        self.assertFalse(self.shim_invoked())


# ---------------------------------------------------------------- AC 177
class Reconcile(F45Base):
    def sess(self, folder, sid, boundaries, entrypoint="cli", subagent=False):
        d = os.path.join(self.home, ".claude", "projects", folder)
        if subagent:
            d = os.path.join(d, "parent-session", "subagents")
        os.makedirs(d, exist_ok=True)
        recs = [dict(user("A user message long enough to be real text here"), entrypoint=entrypoint,
                     timestamp=iso(-86400 * 20), sessionId=sid)]
        for off in boundaries:
            recs.append(dict(BOUNDARY, timestamp=iso(off), sessionId=sid))
        with open(os.path.join(d, sid + ".jsonl"), "w") as f:
            for r in recs:
                f.write(json.dumps(r) + "\n")

    def test_ac177_reconcile_counts_and_report(self):
        A, B, C, D, E, F, G = ("%s0000000-0000-4000-8000-00000000000%d" % (c, i) for i, c in enumerate("abcdefg", 1))
        day = 86400
        self.sess("-proj-alpha", A, [-2 * day, -day])
        self.sess("-proj-bravo", B, [-3 * day])
        self.sess("-proj-charlie", C, [-3 * day], entrypoint="sdk-cli")
        self.sess("-proj-delta", D, [-10 * day])
        self.sess("-proj-echo", E, [-2 * day])
        self.sess("-proj-foxtrot", F, [-day])
        self.sess("-proj-golf", G, [-day, -day + 5, -day + 10], subagent=True)
        os.makedirs(self.hd)
        for _ in range(2):
            self.add_health_row(A)
        self.add_health_row(E, trigger="recovered", status="recovered")
        for _ in range(2):  # canary_child rows must not count (sid chosen so they would hide B's miss)
            self.add_health_row(B, canary_child=True)
        pend = os.path.join(self.hd, F + "-pending.json")
        json.dump({"ts": iso(-300), "trigger": "auto", "hook_version": "1.9.0"}, open(pend, "w"))
        os.utime(pend, (time.time() - 300, time.time() - 300))
        r = subprocess.run([sys.executable, PRE, "--reconcile", "--days", "7"], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, env=self.env(None), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.rstrip("\n").split("\n")
        self.assertEqual(lines[0], "compactions 6 · handoffs 2 · recovered 1 · missed 3 "
                                   "(interactive 2, headless 1) · killed 1", r.stdout)
        missed = [l for l in lines[1:] if l.startswith("missed ")]
        self.assertEqual(len(missed), 2, r.stdout)
        joined = "\n".join(missed)
        self.assertIn(B[:8], joined)
        self.assertIn(F[:8], joined)
        self.assertNotIn(C[:8], r.stdout.split("\n", 1)[1])
        self.assertIn("bravo", joined)
        j = self.read_json(os.path.join(self.hd, "reconcile.json"))
        want = {"days": 7, "compactions": 6, "handoffs": 2, "recovered": 1, "missed": 3, "missed_interactive": 2,
                "missed_headless": 1, "killed": 1}
        for k, v in want.items():
            self.assertEqual(j.get(k), v, (k, j))
        self.assertIn("ts", j)
        self.assertIsInstance(j.get("sessions"), list)

    def test_ac177_reconcile_keeps_noticed_ts_and_survives_garbage(self):
        os.makedirs(self.hd)
        json.dump({"ts": iso(-10), "noticed_ts": "2026-01-01T00:00:00Z"},
                  open(os.path.join(self.hd, "reconcile.json"), "w"))
        d = os.path.join(self.home, ".claude", "projects", "-proj-x")
        os.makedirs(d)
        open(os.path.join(d, "bad.jsonl"), "w").write("{not json\n\x00\xff\n")
        r = subprocess.run([sys.executable, PRE, "--reconcile"], stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, env=self.env(None), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        j = self.read_json(os.path.join(self.hd, "reconcile.json"))
        self.assertEqual(j["noticed_ts"], "2026-01-01T00:00:00Z")
        self.assertEqual(j["days"], 7)
        self.assertEqual(j["compactions"], 0)


# ---------------------------------------------------------------- AC 178
class Check(F45Base):
    def setUp(self):
        super().setUp()
        self.hooks_home = os.path.join(self.home, ".claude", "hooks")
        os.makedirs(self.hooks_home)
        for n in os.listdir(HOOKS_DIR):
            p = os.path.join(HOOKS_DIR, n)
            if n.endswith(".py") and os.path.isfile(p):
                shutil.copy2(p, self.hooks_home)
        self.settings = os.path.join(self.home, ".claude", "settings.json")
        self.write_settings()
        self.write_manifest()

    def write_settings(self, drop=None):
        d = json.loads(open(SETTINGS_TPL).read().replace("__HOME__", self.home))
        if drop:
            d["hooks"].pop(drop, None)
        json.dump(d, open(self.settings, "w"))

    def write_manifest(self, override=None):
        files = {}
        for n in ("precompact-handoff.py", "postcompact-inject.py", "recall.py"):
            p = os.path.join(self.hooks_home, n)
            if os.path.exists(p):
                files[n] = hashlib.sha256(open(p, "rb").read()).hexdigest()
        files.update(override or {})
        json.dump({"version": "1.9.0", "installed_at": iso(), "files": files},
                  open(os.path.join(self.hooks_home, ".handoff-manifest.json"), "w"))

    def check(self):
        t = time.time()
        r = subprocess.run([sys.executable, os.path.join(self.hooks_home, "postcompact-inject.py"), "--check"],
                           input="", capture_output=True, text=True, env=self.env(None), timeout=30)
        self.elapsed = time.time() - t
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def one_line(self, out, needle):
        self.assertTrue(out.startswith("HANDOFF CHECK: "), out)
        self.assertEqual(out.rstrip("\n").count("\n"), 0, out)
        self.assertTrue(out.rstrip("\n").endswith(CHECK_TAIL), out)
        self.assertIn(needle, out)

    def test_ac178_all_well_prints_nothing(self):
        out = self.check()
        self.assertEqual(out, "")
        self.assertLess(self.elapsed, 1.0)

    def test_ac178_missing_precompact_entry(self):
        self.write_settings(drop="PreCompact")
        self.one_line(self.check(), "PreCompact")

    def test_ac178_version_mismatch(self):
        p = os.path.join(self.hooks_home, "precompact-handoff.py")
        src = open(p).read()
        new, n = re.subn(r"""(HOOK_VERSION\s*=\s*["'])[^"']+(["'])""", r"\g<1>0.0.1\g<2>", src, count=1)
        self.assertEqual(n, 1, "HOOK_VERSION constant not found")
        open(p, "w").write(new)
        os.remove(os.path.join(self.hooks_home, ".handoff-manifest.json"))
        self.one_line(self.check(), "version mismatch")

    def test_ac178_manifest_hash_mismatch_names_file(self):
        self.write_manifest(override={"recall.py": "0" * 64})
        self.one_line(self.check(), "recall.py")

    def test_ac178_unparseable_settings(self):
        open(self.settings, "w").write("{ this is not json")
        self.one_line(self.check(), "settings.json unreadable")

    def test_ac178_reconcile_notice_shows_once(self):
        os.makedirs(self.hd, exist_ok=True)
        rp = os.path.join(self.hd, "reconcile.json")
        json.dump({"ts": iso(), "days": 2, "compactions": 5, "handoffs": 3, "recovered": 0, "missed": 2,
                   "missed_interactive": 2, "missed_headless": 0, "killed": 0, "sessions": []}, open(rp, "w"))
        out = self.check()
        self.one_line(out, "2 compactions without a handoff")
        self.assertIn("precompact-handoff.py --reconcile", out)
        self.assertIn("noticed_ts", self.read_json(rp))
        self.assertEqual(self.check(), "")


# ---------------------------------------------------------------- AC 179, 180
class Wiring(unittest.TestCase):
    def test_ac179_settings_template_has_check_in_startup_and_resume(self):
        d = json.load(open(SETTINGS_TPL))
        groups = d["hooks"]["SessionStart"]
        for matcher in ("startup", "resume"):
            with self.subTest(matcher):
                cmds = [h.get("command", "") for g in groups if g.get("matcher") == matcher for h in g.get("hooks", [])]
                mine = [c for c in cmds if re.search(r"postcompact-inject\.py\s+--check(\s|$)", c)]
                self.assertEqual(len(mine), 1, cmds)
                to = [h.get("timeout") for g in groups if g.get("matcher") == matcher for h in g.get("hooks", [])
                      if "--check" in h.get("command", "")]
                self.assertTrue(to[0] is None or to[0] <= 10, to)

    def test_ac179_reconcile_plist_valid(self):
        p = os.path.join(REPO_DIR, "launchd", "handoff-reconcile.plist.tmpl")
        self.assertTrue(os.path.isfile(p), p)
        if shutil.which("plutil"):
            r = subprocess.run(["plutil", "-lint", p], capture_output=True, text=True, timeout=20)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(p, "rb") as f:
            d = plistlib.load(f)
        args = d["ProgramArguments"]
        self.assertIn("--reconcile", args)
        self.assertTrue(any("precompact-handoff.py" in a for a in args), args)

    def test_ac180_hook_version_in_both_hooks(self):
        for path in (PRE, POST):
            with self.subTest(os.path.basename(path)):
                src = open(path).read()
                self.assertRegex(src, r"""HOOK_VERSION\s*=\s*["']1\.9\.0["']""")


class VersionInHealth(F45Base):
    def test_ac180_health_and_sidecar_report_1_9_0(self):
        self.write_transcript([user(PRE_MSG), asst("ok")])
        r = self.run_pre(self.payload())
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.health()["hook_version"], "1.9.0")
        self.assertEqual(self.sidecar("S")["hook_version"], "1.9.0")


if __name__ == "__main__":
    unittest.main()
