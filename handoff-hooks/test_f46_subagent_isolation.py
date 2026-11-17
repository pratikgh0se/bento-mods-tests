"""F46 (hooks 1.10.0) ACs 181-188 of specs/handoff-hooks-spec.md (code-blind: written from the spec only).
Subagent isolation (agent_id hook inputs) and always-on managed hooks. Temp HOME, shim `claude`."""
import hashlib, json, os, re, shutil, subprocess, sys, time, unittest

from helpers import HOOKS_DIR, PRE, POST, PLAIN, user, asst
from test_f45_no_silent_miss import (F45Base, BOUNDARY, SETTINGS_TPL, REPO_DIR, RECOVERED_HEAD, CHECK_TAIL, iso)

SID = "S"
AID = "a1"
KEY = "S-a-a1"
PARENT_MSG = "Parent session last request: tidy the changelog PARENT-MARK"
SUB_OLD = "Subagent first instruction: survey the parser module SUBOLD-MARK"
SUB_MSG = "Subagent last request: list every TODO in the parser SUBLAST-MARK"
SUB_POST = "Subagent later message after its compaction SUBPOST-MARK"
HANDOFF_EVENTS = ("PreCompact", "SessionStart", "SessionEnd")


class F46Base(F45Base):
    LEDGER_ENV = None  # ledger enabled: "subagents never merge the ledger" is then observable

    def sub_path(self, sid=SID, agent=AID):
        return os.path.join(os.path.dirname(self.tpath), sid, "subagents", "agent-%s.jsonl" % agent)

    def write_sub_transcript(self, entries, agent=AID, sid=SID):
        p = self.sub_path(sid, agent)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            for e in entries:
                f.write(json.dumps(dict(e, isSidechain=True, agentId=agent)) + "\n")

    def sub_payload(self, agent=AID, atype="general-purpose", **kw):
        p = self.payload(**kw)
        p["agent_id"] = agent
        p["agent_type"] = atype
        p["hook_event_name"] = "PreCompact"
        return p

    def sub_compact_payload(self, agent=AID):
        p = self.compact_payload(sid=SID)
        p["agent_id"] = agent
        p["agent_type"] = "general-purpose"
        return p

    def parent_snapshot(self):
        """Bytes of every state file that is not a subagent twin and not an append-only log."""
        out = {}
        for root, dirs, files in os.walk(self.hd):
            dirs[:] = [x for x in dirs if x != "recall"]  # the detached indexer writes there
            for n in files:
                if "-a-" in n or n in ("health.jsonl", "hooks-error.jsonl"):
                    continue
                p = os.path.join(root, n)
                with open(p, "rb") as f:
                    out[os.path.relpath(p, self.hd)] = f.read()
        return out

    def main_run(self):
        self.write_transcript([user(PARENT_MSG), asst("ok")])
        r = self.run_pre(self.payload(), fallback="0")
        self.assertEqual(r.returncode, 0, r.stderr)

    def sub_files(self):
        return sorted(n for n in (os.listdir(self.hd) if os.path.exists(self.hd) else []) if n.startswith(KEY))


# ---------------------------------------------------------------- AC 181, 182
class SubagentPreCompact(F46Base):
    def setUp(self):
        super().setUp()
        self.install_shim(out="")
        self.main_run()
        self.before = self.parent_snapshot()
        self.merges_before = self.merge_calls()
        self.assertTrue(self.before, "main run should have created parent files")

    def test_ac181_subagent_handoff_is_its_own(self):
        self.write_sub_transcript([user(SUB_OLD), asst("surveying"), user(SUB_MSG), asst("listing")])
        r = self.run_pre(self.sub_payload(), fallback="0")
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        latest = os.path.join(self.hd, KEY + "-latest.md")
        self.assertTrue(os.path.exists(latest), os.listdir(self.hd))
        txt = open(latest).read()
        self.assertIn("SUBLAST-MARK", txt)
        self.assertNotIn("PARENT-MARK", txt)
        self.assertEqual(self.parent_snapshot(), self.before, "parent files must be byte-identical")
        self.assertEqual(self.merge_calls(), self.merges_before, "subagent must not merge the ledger")
        row = self.health()
        self.assertEqual(row.get("agent_id"), AID)
        self.assertEqual(row.get("agent_type"), "general-purpose")
        self.assertEqual(row.get("sid"), SID)
        self.assertFalse(os.path.exists(os.path.join(self.hd, KEY + "-pending.json")))

    def test_ac182_missing_subagent_transcript_is_degraded(self):
        r = self.run_pre(self.sub_payload(), fallback="0")
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        row = self.health()
        self.assertEqual(row.get("agent_id"), AID)
        self.assertEqual(row.get("status"), "degraded")
        self.assertIn("agent_transcript_missing", json.dumps(row))
        self.assertFalse(os.path.exists(os.path.join(self.hd, KEY + "-latest.md")))
        self.assertEqual(self.parent_snapshot(), self.before)


# ---------------------------------------------------------------- AC 183, 184
class SubagentInject(F46Base):
    def setUp(self):
        super().setUp()
        self.install_shim(out="SHOULD-NOT-BE-CALLED")
        self.put_latest("PARENT-HANDOFF-TEXT\n", sid=SID)
        self.put_sidecar(sid=SID, status="ok", age_s=30)
        self.add_health_row(SID, ts=iso(-30))

    def test_ac183_subagent_gets_its_own_handoff(self):
        self.put_latest("SUBAGENT-HANDOFF-TEXT\n", sid=KEY)
        self.put_sidecar(sid=KEY, status="ok", age_s=30)
        self.add_health_row(SID, ts=iso(-30), agent_id=AID)
        pl = self.sub_compact_payload()
        outs = [self.part_ctx(k, pl) for k in (1, 2, 3)]
        joined = "\n".join(o for o in outs if o)
        self.assertIn("SUBAGENT-HANDOFF-TEXT", outs[0])
        self.assertNotIn("PARENT-HANDOFF-TEXT", joined)
        self.assertNotIn("RECOVERED", joined)
        main_pl = self.compact_payload(sid=SID)
        for k in (1, 2, 3):
            a = self.run_post(pl, args=("--ledger", "--part", str(k)))
            b = self.run_post(main_pl, args=("--ledger", "--part", str(k)))
            self.assertEqual((a.returncode, a.stderr), (0, ""))
            self.assertEqual(a.stdout, b.stdout, "ledger part %d differs for the subagent" % k)

    def test_ac184_subagent_recovery_from_its_transcript(self):
        self.write_transcript([user(PARENT_MSG), asst("ok")])
        self.write_sub_transcript([user(SUB_OLD), asst("x"), user(SUB_MSG), asst("y"),
                                   dict(BOUNDARY, timestamp=iso(-60)), user(SUB_POST), asst("z")])
        before = self.parent_snapshot()
        ctx = self.part_ctx(1, self.sub_compact_payload())
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx.startswith("HANDOFF RECOVERED:"), ctx[:200])
        self.assertIn(SUB_MSG, ctx)
        self.assertNotIn("SUBPOST-MARK", ctx)
        self.assertNotIn("PARENT-MARK", ctx)
        self.assertNotIn("PARENT-HANDOFF-TEXT", ctx)
        rows = [r for r in self.health_rows() if r.get("trigger") == "recovered"]
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0].get("agent_id"), AID)
        self.assertEqual(self.parent_snapshot(), before, "parent handoff files and sidecar must be untouched")
        self.assertTrue(os.path.exists(os.path.join(self.hd, KEY + "-latest.md")), os.listdir(self.hd))
        self.assertFalse(self.shim_invoked())


# ---------------------------------------------------------------- AC 185
class MainUnaffected(F46Base):
    LEDGER_ENV = "0"

    @staticmethod
    def norm(t):
        return re.sub(r"(?m)^time:.*$", "time: X", t)

    def run_main(self):
        self.write_transcript([user(PARENT_MSG), asst("ok")])
        r = self.run_pre(self.payload(), fallback="0")
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        latest = self.norm(self.latest())
        ctx = self.part_ctx(1, self.compact_payload(sid=SID))
        return latest, ctx

    def test_ac185_subagent_files_do_not_change_main_runs(self):
        self.install_shim(out="")
        base_latest, base_ctx = self.run_main()
        self.assertIn("PARENT-MARK", base_latest)
        # now a subagent twin exists
        self.put_latest("SUBAGENT-HANDOFF-TEXT\n", sid=KEY)
        self.put_sidecar(sid=KEY, status="ok", age_s=10)
        sub_before = {n: open(os.path.join(self.hd, n), "rb").read() for n in self.sub_files()}
        latest, ctx = self.run_main()
        self.assertEqual(latest, base_latest)
        self.assertEqual(ctx, base_ctx)
        self.assertNotIn("SUBAGENT-HANDOFF-TEXT", latest + (ctx or ""))
        self.assertEqual({n: open(os.path.join(self.hd, n), "rb").read() for n in self.sub_files()}, sub_before)


# ---------------------------------------------------------------- AC 186
class ReconcileSubagents(F46Base):
    def test_ac186_subagent_compactions_counted_per_agent(self):
        sid = "5e55a000-0000-4000-8000-000000000001"
        d = os.path.join(self.home, ".claude", "projects", "-proj-sub")
        sub = os.path.join(d, sid, "subagents")
        os.makedirs(sub)
        day = 86400

        def write(path, offsets, **kw):
            with open(path, "w") as f:
                f.write(json.dumps(dict(user("A user message long enough to be real text here"), entrypoint="cli",
                                        timestamp=iso(-20 * day), sessionId=sid, **kw)) + "\n")
                for off in offsets:
                    f.write(json.dumps(dict(BOUNDARY, timestamp=iso(off), sessionId=sid, **kw)) + "\n")

        write(os.path.join(d, sid + ".jsonl"), [-2 * day])
        write(os.path.join(sub, "agent-a1.jsonl"), [-2 * day, -day], isSidechain=True, agentId="a1")
        write(os.path.join(sub, "agent-a2.jsonl"), [-day], isSidechain=True, agentId="a2")
        os.makedirs(self.hd)
        self.add_health_row(sid)                      # the main handoff
        self.add_health_row(sid, agent_id="a1")       # one subagent handoff
        r = subprocess.run([sys.executable, PRE, "--reconcile", "--days", "7"], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, env=self.env(None), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.rstrip("\n").split("\n")
        self.assertEqual(lines[0], "compactions 1 · handoffs 1 · recovered 0 · missed 0 "
                                   "(interactive 0, headless 0) · killed 0", r.stdout)
        self.assertEqual(lines[1], "subagent compactions 3 · missed 2", r.stdout)
        a2 = [l for l in lines[2:] if l.startswith("missed ") and "agent a2" in l]
        self.assertEqual(len(a2), 1, r.stdout)
        self.assertIn(sid[:8], a2[0])
        self.assertIn("-proj-sub", a2[0])


# ---------------------------------------------------------------- AC 187
class ManagedHooks(F46Base):
    def setUp(self):
        super().setUp()
        self.sys_path = os.path.join(self.tmp, "etc", "managed-settings.json")
        self.fakebin = os.path.join(self.tmp, "fakebin")
        os.makedirs(self.fakebin)
        self.sudo_log = os.path.join(self.tmp, "sudo.log")
        with open(os.path.join(self.fakebin, "sudo"), "w") as f:
            f.write('#!/bin/sh\necho "$@" >> "%s"\nexit 1\n' % self.sudo_log)
        os.chmod(os.path.join(self.fakebin, "sudo"), 0o755)

    def template(self):
        return json.loads(open(SETTINGS_TPL).read().replace("__HOME__", "<H>"))

    def triples(self, d):
        out = []
        for ev in HANDOFF_EVENTS:
            for g in d.get("hooks", {}).get(ev, []):
                for h in g.get("hooks", []):
                    out.append((ev, g.get("matcher"), h.get("command", "").replace(self.home, "<H>")))
        return sorted(out, key=repr)

    def run_bootstrap(self):
        env = {"HOME": self.home, "PATH": self.fakebin + ":/usr/bin:/bin", "LANG": "C.UTF-8",
               "HANDOFF_MANAGED_SETTINGS_PATH": self.sys_path}
        r = subprocess.run(["bash", os.path.join(REPO_DIR, "setup", "bootstrap.sh"), "--managed-hooks"],
                           cwd=REPO_DIR, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.sudo_log), "bootstrap must never run sudo")
        found = []
        for root, _, files in os.walk(self.home):
            if "managed-settings.json" in files and os.path.basename(root) == "machine-setup":
                found.append(os.path.join(root, "managed-settings.json"))
        self.assertEqual(len(found), 1, (found, r.stdout))
        self.out_file = found[0]
        sudo_lines = [l for l in r.stdout.split("\n") if l.startswith("sudo install -m 644")]
        self.assertEqual(len(sudo_lines), 1, r.stdout)
        self.assertIn(self.out_file, sudo_lines[0])
        return json.load(open(self.out_file))

    def test_ac187_writes_exactly_the_handoff_entries(self):
        self.assertFalse(os.path.exists(self.sys_path))
        d = self.run_bootstrap()
        self.assertEqual(set(d), {"hooks"}, list(d))
        self.assertEqual(set(d["hooks"]), set(HANDOFF_EVENTS))
        self.assertEqual({g.get("matcher") for g in d["hooks"]["SessionStart"]}, {"compact", "startup", "resume"})
        self.assertEqual(self.triples(d), self.triples(self.template()))
        self.assertFalse(os.path.exists(self.sys_path), "the system file must not be created by bootstrap")

    def test_ac187_keeps_existing_system_keys(self):
        os.makedirs(os.path.dirname(self.sys_path))
        orig = json.dumps({"permissions": {"deny": ["X"]}})
        open(self.sys_path, "w").write(orig)
        d = self.run_bootstrap()
        self.assertEqual(d.get("permissions"), {"deny": ["X"]})
        self.assertEqual(set(d["hooks"]), set(HANDOFF_EVENTS))
        self.assertEqual(open(self.sys_path).read(), orig, "system file is read-only for bootstrap")

    def test_ac187_check_accepts_precompact_in_managed_file_only(self):
        hooks_home = os.path.join(self.home, ".claude", "hooks")
        os.makedirs(hooks_home)
        for n in os.listdir(HOOKS_DIR):
            p = os.path.join(HOOKS_DIR, n)
            if n.endswith(".py") and os.path.isfile(p):
                shutil.copy2(p, hooks_home)
        tpl = json.loads(open(SETTINGS_TPL).read().replace("__HOME__", self.home))
        managed = {"hooks": {"PreCompact": tpl["hooks"]["PreCompact"]}}
        user_settings = json.loads(json.dumps(tpl))
        user_settings["hooks"].pop("PreCompact")
        json.dump(user_settings, open(os.path.join(self.home, ".claude", "settings.json"), "w"))
        os.makedirs(os.path.dirname(self.sys_path))
        json.dump(managed, open(self.sys_path, "w"))
        files = {n: hashlib.sha256(open(os.path.join(hooks_home, n), "rb").read()).hexdigest()
                 for n in ("precompact-handoff.py", "postcompact-inject.py", "recall.py")
                 if os.path.exists(os.path.join(hooks_home, n))}
        json.dump({"version": "1.10.0", "installed_at": iso(), "files": files},
                  open(os.path.join(hooks_home, ".handoff-manifest.json"), "w"))
        env = self.env(None, {"HANDOFF_MANAGED_SETTINGS_PATH": self.sys_path})
        run = lambda: subprocess.run([sys.executable, os.path.join(hooks_home, "postcompact-inject.py"), "--check"],
                                     input="", capture_output=True, text=True, env=env, timeout=30)
        r = run()
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        # control: without the managed file the same settings are reported
        os.remove(self.sys_path)
        r = run()
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.startswith("HANDOFF CHECK: ") and "PreCompact" in r.stdout, r.stdout)
        self.assertTrue(r.stdout.rstrip("\n").endswith(CHECK_TAIL))


# ---------------------------------------------------------------- AC 188
class Version(unittest.TestCase):
    def test_ac188_hook_version_in_both_hooks(self):
        for path in (PRE, POST):
            with self.subTest(os.path.basename(path)):
                self.assertRegex(open(path).read(), r"""HOOK_VERSION\s*=\s*["']1\.10\.0["']""")


class VersionInHealth(F46Base):
    LEDGER_ENV = "0"

    def test_ac188_health_and_sidecar_report_1_10_0(self):
        self.write_transcript([user(PARENT_MSG), asst("ok")])
        r = self.run_pre(self.payload())
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.health()["hook_version"], "1.10.0")
        self.assertEqual(self.sidecar("S")["hook_version"], "1.10.0")


if __name__ == "__main__":
    unittest.main()
