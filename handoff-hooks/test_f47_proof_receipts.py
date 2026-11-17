"""F47 (hooks 1.10.0) ACs 189-195 of specs/handoff-hooks-spec.md (code-blind: written from the spec only).
Receipts written by the SessionStart part 1 inject, and `precompact-handoff.py --prove`. Temp HOME, keyword-only recall."""
import hashlib, json, os, re, shutil, subprocess, sys, time, unittest

from helpers import HOOKS_DIR, PRE, POST, PLAIN, user, asst, no_recall
from test_f45_no_silent_miss import F45Base, BOUNDARY, SETTINGS_TPL, REPO_DIR, RECOVERED_HEAD, CHECK_TAIL, iso
from test_f44_recall import RecallBase, RECALL

SID = "f47aaaaa-0000-4000-8000-000000000001"
AID = "a1"
KEY = SID + "-a-" + AID
RECEIPT_KEYS = ("ts", "sid", "agent_id", "key", "transcript", "boundary_ts", "kind", "handoff_sha256",
                "part1_sha256", "part1_head")
BTS = "2026-03-09T12:00:00.000Z"


def sha(b):
    return hashlib.sha256(b if isinstance(b, bytes) else b.encode()).hexdigest()


def jl(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path).read().split("\n") if l.strip()]


class ProofBase(F45Base):
    LEDGER_ENV = "0"
    _n = 0

    def compact_payload(self, sid=SID, transcript=None):
        return super().compact_payload(sid=sid, transcript=transcript)

    def derived(self, agent=AID, sid=SID):
        return os.path.join(os.path.dirname(self.tpath), sid, "subagents", "agent-%s.jsonl" % agent)

    def write_jsonl(self, path, recs):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            for r in recs:
                f.write(json.dumps(r) + "\n")

    def attach(self, text, ts):
        return {"type": "attachment", "timestamp": ts, "attachment": {
            "type": "hook_additional_context", "hookName": "SessionStart", "hookEvent": "SessionStart",
            "toolUseID": "SessionStart", "content": [text]}}

    def receipt(self, transcript, key=SID, sid=SID, agent_id=None, kind="normal", handoff_sha=None, head="HEAD", **kw):
        ProofBase._n += 1
        r = {"ts": iso(-100 - ProofBase._n), "sid": sid, "agent_id": agent_id, "key": key, "transcript": transcript,
             "boundary_ts": BTS, "kind": kind, "handoff_sha256": handoff_sha or ("0" * 64),
             "part1_sha256": "1" * 64, "part1_head": head}
        r.update(kw)
        os.makedirs(self.hd, exist_ok=True)
        with open(os.path.join(self.hd, "receipts.jsonl"), "a") as f:
            f.write(json.dumps(r) + "\n")
        return r

    def prove(self, *extra, env=None, pre=None):
        r = subprocess.run([sys.executable, pre or PRE, *(extra or ("--prove",))], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, env=env or self.env(None), timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def verdicts(self):
        return jl(os.path.join(self.hd, "proofs.jsonl"))

    def verdict(self, rc):
        v = [x for x in self.verdicts() if x.get("receipt_ts") == rc["ts"]]
        self.assertEqual(len(v), 1, self.verdicts())
        return v[0]


# ---------------------------------------------------------------- AC 189
class Receipts(ProofBase):
    def setUp(self):
        super().setUp()
        self.install_shim(out="SHOULD-NOT-BE-CALLED")
        self.rpath = os.path.join(self.hd, "receipts.jsonl")

    def fresh(self, key, body):
        self.put_latest(body, sid=key)
        self.put_sidecar(sid=key, status="ok", age_s=30)
        self.add_health_row(SID, ts=iso(-30))

    def tr(self, path):
        self.write_jsonl(path, [user("First instruction for the receipt fixture to remember"),
                                dict(BOUNDARY, timestamp=BTS), user("A later message after the boundary here ok")])

    def test_ac189_normal_inject_appends_one_full_receipt(self):
        self.fresh(SID, "RECEIPT-BODY text\n")
        self.tr(self.tpath)
        ctx = self.part_ctx(1, self.compact_payload())
        self.assertEqual(ctx, PLAIN + "RECEIPT-BODY text")
        rows = jl(self.rpath)
        self.assertEqual(len(rows), 1, rows)
        r = rows[0]
        for k in RECEIPT_KEYS:
            self.assertIn(k, r)
        self.assertIn(r["sid"], (SID, SID[:8]))
        self.assertIsNone(r["agent_id"])
        self.assertEqual(r["key"], SID)
        self.assertEqual(os.path.realpath(r["transcript"]), os.path.realpath(self.tpath))
        self.assertEqual(r["boundary_ts"], BTS)
        self.assertEqual(r["kind"], "normal")
        self.assertEqual(r["part1_head"], ctx[:300])
        self.assertEqual(r["handoff_sha256"], sha(open(os.path.join(self.hd, SID + "-latest.md"), "rb").read()))
        self.assertEqual(len(r["part1_sha256"]), 64)

    def test_ac189_recovered_inject_writes_kind_recovered(self):
        self.tr(self.tpath)
        ctx = self.part_ctx(1, self.compact_payload())
        self.assertTrue(ctx.startswith("HANDOFF RECOVERED:"), ctx[:100])
        rows = jl(self.rpath)
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["kind"], "recovered")
        self.assertEqual(rows[0]["part1_head"], ctx[:300])

    def test_ac189_subagent_inject_names_agent_and_derived_transcript(self):
        self.fresh(KEY, "SUBAGENT-RECEIPT-BODY\n")
        self.tr(self.tpath)
        self.tr(self.derived())
        pl = self.compact_payload()
        pl["agent_id"], pl["agent_type"] = AID, "general-purpose"
        ctx = self.part_ctx(1, pl)
        self.assertIn("SUBAGENT-RECEIPT-BODY", ctx)
        rows = jl(self.rpath)
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["agent_id"], AID)
        self.assertEqual(rows[0]["key"], KEY)
        self.assertEqual(os.path.realpath(rows[0]["transcript"]), os.path.realpath(self.derived()))

    def test_ac189_receipt_failure_never_changes_output(self):
        self.fresh(SID, "RECEIPT-BODY text\n")
        self.tr(self.tpath)
        os.mkdir(self.rpath)  # appending must fail
        ctx = self.part_ctx(1, self.compact_payload())
        self.assertEqual(ctx, PLAIN + "RECEIPT-BODY text")
        self.assertGreaterEqual(len(self.errors_lines()), 1)


# ---------------------------------------------------------------- AC 190
class Lossless(RecallBase, ProofBase):
    LEDGER_ENV = "0"
    SESS = "f47b1111-0000-4000-8000-000000000009"

    def setUp(self):
        super().setUp()
        self.msgs = ["Message number %d about the quarterly invoice reconciliation LOSS%d-unique words and details here" % (i, i)
                     for i in range(1, 8)]
        self.tpath2 = os.path.join(self.tdir(self.proj), self.SESS + ".jsonl")
        self.write_t(self.msgs)
        self.ok("index")

    def write_t(self, msgs):
        recs = [self.rec("user", m, sid=self.SESS, cwd=self.proj, day=8, minute=i) for i, m in enumerate(msgs)]
        recs.append(dict(BOUNDARY, timestamp=BTS, sessionId=self.SESS, cwd=self.proj))
        recs.append(self.rec("user", "A later message after the boundary exists here ok", sid=self.SESS,
                             cwd=self.proj, day=10, minute=1))
        self.write_jsonl(self.tpath2, recs)

    def penv(self):
        return self.renv(embed=self.down)

    def test_ac190_lossless_pass_when_index_and_transcript_agree(self):
        rc = self.receipt(self.tpath2, sid=self.SESS)
        self.prove(env=self.penv())
        v = self.verdict(rc)
        self.assertEqual(v["checks"]["lossless"], "pass", v)

    FAKE_RECALL = """#!/usr/bin/env python3
import json, re, sys
T = %r
SID8 = %r
args = sys.argv[1:]
rows = [json.loads(l) for l in open(T) if l.strip()]
def text(r):
    c = r.get("message", {}).get("content")
    return c if isinstance(c, str) else ""
if args and args[0] == "search":
    phrase = args[1]
    hits = [(i + 1, r) for i, r in enumerate(rows) if phrase in text(r)]
    for i, r in hits:
        print("%%s:%%d 2026-03-08 12:00 %%s: %%s" %% (SID8, i, r.get("type", "user"), text(r)[:150]))
    print("%%d hits shown of %%d (1 sessions searched)" %% (len(hits), len(hits)))
elif args and args[0] == "open":
    line = int(args[1].split(":")[1])
    r = rows[line - 1]
    print("--- %%s:%%d 2026-03-08 12:00 %%s" %% (SID8, line, r.get("type", "user")))
    print(text(r) + " ALTERED-BY-FAKE-RECALL")
"""

    def test_ac190_lossless_fails_when_recall_returns_different_text(self):
        """Spec route: recall returning different text. A fake recall.py sits in a temp COPY of the hooks dir."""
        hooks = os.path.join(self.tmp, "hooks-fake")
        shutil.copytree(HOOKS_DIR, hooks, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        with open(os.path.join(hooks, "recall.py"), "w") as f:
            f.write(self.FAKE_RECALL % (self.tpath2, self.SESS[:8]))
        rc = self.receipt(self.tpath2, sid=self.SESS)
        self.prove(env=self.penv(), pre=os.path.join(hooks, "precompact-handoff.py"))
        v = self.verdict(rc)
        self.assertEqual(v["checks"]["lossless"], "fail", v)
        self.assertTrue(v["details"].get("lossless"), v)

    def test_ac190_lossless_skips_with_too_few_messages(self):
        self.write_t(self.msgs[:3])
        rc = self.receipt(self.tpath2, sid=self.SESS)
        self.prove(env=self.penv())
        self.assertEqual(self.verdict(rc)["checks"]["lossless"], "skip")


class LosslessNoRecall(ProofBase):
    @no_recall
    def test_ac190_lossless_skips_without_recall(self):
        recs = [user("Message number %d about the quarterly invoice reconciliation words" % i) for i in range(7)]
        recs.append(dict(BOUNDARY, timestamp=BTS))
        recs.append(user("A later message after the boundary exists here ok"))
        self.write_jsonl(self.tpath, [dict(r, timestamp=iso(-1000 + i)) if r.get("type") == "user" else r
                                     for i, r in enumerate(recs)])
        rc = self.receipt(self.tpath)
        import helpers
        self.prove(pre=helpers.PRE)
        self.assertEqual(self.verdict(rc)["checks"]["lossless"], "skip")


# ---------------------------------------------------------------- AC 191
class RightAgent(ProofBase):
    PARENT_ONLY = "Parent only request about the nightly billing export PARENTONLY-LINE"
    SUB_LINE = "Subagent request about the parser grammar tests SUBONLY-LINE"

    def make_handoff(self, msg_for_handoff):
        """Run the PreCompact hook over a one-message transcript to get a real handoff file; returns its path."""
        self.write_transcript([user(msg_for_handoff), asst("noted")])
        r = self.run_pre(self.payload(), fallback="0")
        self.assertEqual(r.returncode, 0, r.stderr)
        return os.path.join(self.hd, "S-latest.md")

    def test_ac191_pass_when_all_lines_are_in_own_transcript(self):
        h = self.make_handoff(self.PARENT_ONLY)
        self.write_jsonl(self.tpath, [user(self.PARENT_ONLY), asst("noted"), dict(BOUNDARY, timestamp=BTS),
                                      user("after the boundary a later message ok")])
        rc = self.receipt(self.tpath, key="S", sid="S", handoff_sha=sha(open(h, "rb").read()))
        self.prove()
        v = self.verdict(rc)
        self.assertEqual(v["checks"]["right_agent"], "pass", v)

    def test_ac191_fail_when_subagent_handoff_quotes_parent_line(self):
        h = self.make_handoff(self.PARENT_ONLY)
        key = "S-a-a1"
        shutil.copy(h, os.path.join(self.hd, key + "-latest.md"))
        sub = self.derived(sid="S")
        self.write_jsonl(sub, [user(self.SUB_LINE), asst("ok"), dict(BOUNDARY, timestamp=BTS),
                               user("after the boundary a later message ok")])
        rc = self.receipt(sub, key=key, sid="S", agent_id="a1", handoff_sha=sha(open(h, "rb").read()))
        self.prove()
        v = self.verdict(rc)
        self.assertEqual(v["checks"]["right_agent"], "fail", v)
        self.assertIn("Parent only", json.dumps(v["details"]))
        self.assertTrue(v["details"].get("right_agent"))

    def test_ac191_skip_when_handoff_file_is_gone(self):
        self.write_jsonl(self.tpath, [user(self.PARENT_ONLY), dict(BOUNDARY, timestamp=BTS), user("later message here ok ok")])
        rc = self.receipt(self.tpath, key="S", sid="S")
        self.prove()
        self.assertEqual(self.verdict(rc)["checks"]["right_agent"], "skip")


# ---------------------------------------------------------------- AC 192
class Delivered(ProofBase):
    HEAD = "Pre-compaction handoff (auto-saved):\n## Last user messages\n- keep   the   whitespace flexible DELIVERED-HEAD"

    def run_case(self, after):
        recs = [user("Some earlier user message long enough to count here"), dict(BOUNDARY, timestamp=BTS)]
        recs += after
        self.write_jsonl(self.tpath, recs)
        rc = self.receipt(self.tpath, key="S", sid="S", head=self.HEAD)
        self.prove()
        return self.verdict(rc)["checks"]["delivered"]

    def test_ac192_pass_with_part1_head_in_attachment(self):
        flat = " ".join(self.HEAD.split())
        self.assertEqual(self.run_case([self.attach(flat, "2026-03-09T12:00:05.000Z")]), "pass")

    def test_ac192_fail_when_record_after_boundary_lacks_head(self):
        self.assertEqual(self.run_case([self.attach("some unrelated hook context", "2026-03-09T12:00:05.000Z")]), "fail")

    def test_ac192_skip_when_nothing_after_boundary(self):
        self.assertEqual(self.run_case([]), "skip")


# ---------------------------------------------------------------- AC 193
class DecisionsSafe(ProofBase):
    def case(self, **ledger):
        self.write_jsonl(self.tpath, [user("Some earlier user message long enough to count here"),
                                      dict(BOUNDARY, timestamp=BTS), user("later message after the boundary ok ok")])
        rc = self.receipt(self.tpath, key="S", sid="S")
        row = {"ts": rc["ts"], "sid": "S", "trigger": "auto", "status": "ok"}
        row.update(ledger)
        os.makedirs(self.hd, exist_ok=True)
        with open(self.health_path(), "a") as f:
            f.write(json.dumps(row) + "\n")
        self.prove()
        return self.verdict(rc)

    def test_ac193_pass_when_ids_only_grow(self):
        v = self.case(ledger_ids_before=["D1", "D2", "D3"], ledger_ids_after=["D1", "D2", "D3", "D4"],
                      superseded_before=[], superseded_after=[])
        self.assertEqual(v["checks"]["decisions_safe"], "pass", v)

    def test_ac193_fail_names_the_lost_id(self):
        v = self.case(ledger_ids_before=["D1", "D2", "D3"], ledger_ids_after=["D1", "D3"],
                      superseded_before=[], superseded_after=[])
        self.assertEqual(v["checks"]["decisions_safe"], "fail", v)
        self.assertIn("D2", v["details"].get("decisions_safe", ""))

    def test_ac193_skip_without_ledger_fields(self):
        self.assertEqual(self.case()["checks"]["decisions_safe"], "skip")


# ---------------------------------------------------------------- AC 194
class Report(ProofBase):
    HEAD = "REPORT-HEAD-TEXT unique"

    def fixture(self):
        good = [user("Some earlier user message long enough to count here"), dict(BOUNDARY, timestamp=BTS)]
        self.write_jsonl(self.tpath, good + [self.attach(self.HEAD, "2026-03-09T12:00:05.000Z")])
        bad = os.path.join(os.path.dirname(self.tpath), "bad.jsonl")
        self.write_jsonl(bad, good + [self.attach("something else entirely", "2026-03-09T12:00:05.000Z")])
        self.rcs = [self.receipt(self.tpath, key="S", sid="S", head=self.HEAD),
                    self.receipt(self.tpath, key="S", sid="S", head=self.HEAD),
                    self.receipt(bad, key="S", sid="S", head=self.HEAD)]

    def test_ac194_output_line_report_and_idempotence(self):
        self.fixture()
        r = self.prove()
        want = ("proof 7d: receipts 3 · lossless 0/0 · right-agent 0/0 · delivered 2/3 · "
                "decisions-safe 0/0 · failed 1")
        self.assertEqual(r.stdout.split("\n")[0], want, r.stdout)
        rep = open(os.path.join(self.hd, "proof-report.md")).read().split("\n")
        self.assertEqual(rep[0], want)
        fails = [l for l in rep[1:] if "delivered" in l and "S" in l and not l.startswith("proof ")]
        self.assertGreaterEqual(len(fails), 1, rep)
        self.assertEqual(len(self.verdicts()), 3)
        self.assertTrue(any("skip" in l.lower() for l in rep[1:]), rep)
        self.prove()
        self.assertEqual(len(self.verdicts()), 3, "a proven receipt is not re-proven")

    def test_ac194_reconcile_lines_come_first_when_combined(self):
        self.fixture()
        r = self.prove("--reconcile", "--prove")
        lines = r.stdout.split("\n")
        i = next(k for k, l in enumerate(lines) if l.startswith("proof 7d:"))
        self.assertTrue(lines[0].startswith("compactions "), r.stdout)
        self.assertGreater(i, 0)
        rep = open(os.path.join(self.hd, "proof-report.md")).read()
        self.assertIn("compactions ", rep)


# ---------------------------------------------------------------- AC 195
class Alert(ProofBase):
    def setUp(self):
        super().setUp()
        self.hooks_home = os.path.join(self.home, ".claude", "hooks")
        os.makedirs(self.hooks_home)
        for n in os.listdir(HOOKS_DIR):
            p = os.path.join(HOOKS_DIR, n)
            if n.endswith(".py") and os.path.isfile(p):
                shutil.copy2(p, self.hooks_home)
        json.dump(json.loads(open(SETTINGS_TPL).read().replace("__HOME__", self.home)),
                  open(os.path.join(self.home, ".claude", "settings.json"), "w"))
        files = {n: sha(open(os.path.join(self.hooks_home, n), "rb").read())
                 for n in ("precompact-handoff.py", "postcompact-inject.py", "recall.py")
                 if os.path.exists(os.path.join(self.hooks_home, n))}
        json.dump({"version": "1.10.0", "installed_at": iso(), "files": files},
                  open(os.path.join(self.hooks_home, ".handoff-manifest.json"), "w"))

    def check(self):
        r = subprocess.run([sys.executable, os.path.join(self.hooks_home, "postcompact-inject.py"), "--check"],
                           input="", capture_output=True, text=True, env=self.env(None), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_ac195_check_shows_proof_failure_once(self):
        good = [user("Some earlier user message long enough to count here"), dict(BOUNDARY, timestamp=BTS)]
        self.write_jsonl(self.tpath, good + [self.attach("something else entirely", "2026-03-09T12:00:05.000Z")])
        self.receipt(self.tpath, key="S", sid="S", head="HEAD-NOT-DELIVERED")
        self.prove()
        out = self.check()
        self.assertTrue(out.startswith("HANDOFF CHECK: "), out)
        self.assertIn("proof failed: 1 checks", out)
        self.assertIn("proof-report.md", out)
        self.assertEqual(self.check(), "")

    def test_ac195_plist_runs_reconcile_and_prove(self):
        import plistlib
        p = os.path.join(REPO_DIR, "launchd", "handoff-reconcile.plist.tmpl")
        with open(p, "rb") as f:
            d = plistlib.load(f)
        args = d["ProgramArguments"]
        self.assertIn("--reconcile", args)
        self.assertIn("--prove", args)
        self.assertIn("--days", args)
        sched = d.get("StartCalendarInterval")
        self.assertEqual((sched.get("Hour"), sched.get("Minute")), (4, 15), sched)


if __name__ == "__main__":
    unittest.main()
