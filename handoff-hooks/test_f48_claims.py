"""F48 (hooks 1.10.0) ACs 196-200 of specs/handoff-hooks-spec.md (code-blind: written from the spec only).
Claims register: evaluation by `--prove`, `--claims`, `--claims-lint`, `--check` alert, privacy. Temp HOME; the hooks
are run from a temp COPY of the hooks dir so a custom claims.json can sit next to them."""
import json, os, re, shutil, subprocess, sys, time, unittest

from helpers import HOOKS_DIR, user
from test_f45_no_silent_miss import F45Base, SETTINGS_TPL, iso
from test_f47_proof_receipts import sha, jl

REAL_REGISTER = os.path.join(HOOKS_DIR, "claims.json")


def claim(cid, text, source, **kw):
    d = {"id": cid, "text": text, "source": source, "window_days": 30, "refresh_days": 2, "min_rate": 1.0}
    d.update(kw)
    return d


class ClaimsBase(F45Base):
    LEDGER_ENV = "0"

    def setUp(self):
        super().setUp()
        self.hooks_home = os.path.join(self.home, ".claude", "hooks")
        os.makedirs(self.hooks_home)
        for n in os.listdir(HOOKS_DIR):
            p = os.path.join(HOOKS_DIR, n)
            if n.endswith(".py") and os.path.isfile(p):
                shutil.copy2(p, self.hooks_home)
        shutil.copy2(REAL_REGISTER, os.path.join(self.hooks_home, "claims.json")) if os.path.exists(REAL_REGISTER) else None
        self.pre = os.path.join(self.hooks_home, "precompact-handoff.py")
        self.post = os.path.join(self.hooks_home, "postcompact-inject.py")
        os.makedirs(self.hd, exist_ok=True)

    def set_register(self, claims):
        json.dump({"claims": claims}, open(os.path.join(self.hooks_home, "claims.json"), "w"))

    def add_proof(self, check, result, detail="", n=0, sid=None, ts=None):
        row = {"ts": iso(-10), "receipt_ts": ts or iso(-3600 - n), "sid": sid or "f48aaaaa-0000-4000-8000-000000000001",
               "agent_id": None, "checks": {check: result}, "details": ({check: detail} if detail else {})}
        with open(os.path.join(self.hd, "proofs.jsonl"), "a") as f:
            f.write(json.dumps(row) + "\n")

    def set_reconcile(self, interactive=10, covered=9):
        json.dump({"ts": iso(-10), "days": 30, "compactions": interactive, "handoffs": covered, "recovered": 0,
                   "missed": interactive - covered, "missed_interactive": interactive - covered, "missed_headless": 0,
                   "killed": 0, "sessions": []}, open(os.path.join(self.hd, "reconcile.json"), "w"))

    def run_pre(self, *args):
        r = subprocess.run([sys.executable, self.pre, *args], stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, env=self.env(None), timeout=120)
        return r

    def prove(self):
        r = self.run_pre("--prove")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def status(self):
        d = json.load(open(os.path.join(self.hd, "claims-status.json")))
        return {c["id"]: c for c in d["claims"]}

    def report(self):
        return open(os.path.join(self.hd, "claims-report.md")).read()


# ---------------------------------------------------------------- AC 196
class Evaluate(ClaimsBase):
    def test_ac196_c1_pass_and_c2_fail_with_denominators(self):
        for i in range(10):
            self.add_proof("lossless", "pass", n=i)
        self.set_reconcile(10, 9)
        self.prove()
        st = self.status()
        self.assertEqual(st["C1"]["value"], "10/10")
        self.assertEqual(st["C1"]["status"], "pass")
        self.assertAlmostEqual(st["C1"]["rate"], 1.0)
        self.assertEqual(st["C2"]["value"], "9/10")
        self.assertEqual(st["C2"]["status"], "fail")
        self.assertAlmostEqual(st["C2"]["rate"], 0.9)
        rep = self.report()
        row1 = [l for l in rep.split("\n") if re.search(r"\bC1\b", l)]
        row2 = [l for l in rep.split("\n") if re.search(r"\bC2\b", l)]
        self.assertTrue(row1 and "10/10" in row1[0] and "pass" in row1[0], rep)
        self.assertTrue(row2 and "9/10" in row2[0] and "fail" in row2[0], rep)
        d = json.load(open(os.path.join(self.hd, "claims-status.json")))
        self.assertIn("ts", d)
        for c in d["claims"]:
            self.assertIn("as_of", c)

    def test_ac196_claims_flag_prints_the_report_table(self):
        for i in range(10):
            self.add_proof("lossless", "pass", n=i)
        self.set_reconcile(10, 9)
        self.prove()
        r = self.run_pre("--claims")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("9/10", r.stdout)
        self.assertIn("C1", r.stdout)
        self.assertEqual(r.stdout.strip(), self.report().strip())


# ---------------------------------------------------------------- AC 197
class Statuses(ClaimsBase):
    def test_ac197_static_stale_vs_pass_and_no_data(self):
        today = time.strftime("%Y-%m-%d", time.gmtime())
        old = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 40 * 86400))
        self.set_register([
            claim("C1", "old study", "static", refresh_days=30, evidence={"date": old, "value": "62% to 98%", "how": "quiz"}),
            claim("C2", "fresh study", "static", refresh_days=30, evidence={"date": today, "value": "19% lower", "how": "measured"}),
            claim("C3", "never proven", "proof:right_agent"),
        ])
        self.prove()
        st = self.status()
        self.assertEqual(st["C1"]["status"], "stale")
        self.assertEqual(st["C2"]["status"], "pass")
        self.assertEqual(st["C3"]["status"], "no-data")


# ---------------------------------------------------------------- AC 198
class Lint(ClaimsBase):
    def setUp(self):
        super().setUp()
        for i in range(3):
            self.add_proof("lossless", "pass", n=i)
            self.add_proof("right_agent", "pass", n=i)
        self.set_reconcile(10, 9)
        self.prove()
        self.md = os.path.join(self.tmp, "README.md")

    def lint(self, text):
        open(self.md, "w").write(text)
        return self.run_pre("--claims-lint", self.md)

    def test_ac198_all_pass(self):
        r = self.lint("Nothing is lost [C1] and subagents stay isolated [C3].\n")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "claims ok (2 cited)"), r.stderr)

    def test_ac198_unknown_claim(self):
        r = self.lint("A claim [C9] that does not exist.\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown claim C9", r.stdout)

    def test_ac198_failing_claim_named_with_value(self):
        r = self.lint("Every compaction gets a handoff [C2].\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("C2 fail 9/10", r.stdout)
        self.assertNotIn("claims ok", r.stdout)


# ---------------------------------------------------------------- AC 199
class Alert(ClaimsBase):
    def setUp(self):
        super().setUp()
        json.dump(json.loads(open(SETTINGS_TPL).read().replace("__HOME__", self.home)),
                  open(os.path.join(self.home, ".claude", "settings.json"), "w"))
        files = {n: sha(open(os.path.join(self.hooks_home, n), "rb").read())
                 for n in ("precompact-handoff.py", "postcompact-inject.py", "recall.py")
                 if os.path.exists(os.path.join(self.hooks_home, n))}
        json.dump({"version": "1.10.0", "installed_at": iso(), "files": files},
                  open(os.path.join(self.hooks_home, ".handoff-manifest.json"), "w"))
        self.set_register([claim("C1", "lossless", "proof:lossless"),
                           claim("C2", "coverage", "reconcile:coverage", min_rate=0.99)])
        for i in range(5):
            self.add_proof("lossless", "pass", n=i)
        self.set_reconcile(10, 9)

    def check(self):
        r = subprocess.run([sys.executable, self.post, "--check"], input="", capture_output=True, text=True,
                           env=self.env(None), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_ac199_shown_once_per_change_of_set(self):
        self.prove()
        out = self.check()
        self.assertIn("claims: 1 failing or stale", out)
        self.assertIn("claims-report.md", out)
        self.assertEqual(self.check(), "", "unchanged set must not be shown again")
        self.prove()
        self.assertEqual(self.check(), "", "unchanged set after a re-run")
        self.add_proof("lossless", "fail", "mismatch in a message", n=99)
        self.prove()
        self.assertIn("claims: 2 failing or stale", self.check())


# ---------------------------------------------------------------- AC 200
class Privacy(ClaimsBase):
    SECRET = "PRIVATE-MESSAGE-TEXT-DO-NOT-LEAK"
    SID = "f48cccc0-1111-4222-8333-444455556666"

    def test_ac200_outputs_hold_no_paths_sids_or_message_text(self):
        for i in range(4):
            self.add_proof("lossless", "pass", n=i, sid=self.SID)
        self.add_proof("lossless", "fail", "mismatch at %s in /Users/someone/secret-project/x.jsonl" % self.SECRET, n=50,
                       sid=self.SID)
        self.add_proof("right_agent", "fail", "line not found: %s" % self.SECRET, n=51, sid=self.SID)
        self.set_reconcile(10, 9)
        self.prove()
        for name in ("claims-status.json", "claims-report.md"):
            txt = open(os.path.join(self.hd, name)).read()
            self.assertNotIn(self.SECRET, txt, name)
            self.assertNotIn(self.SID, txt, name)
            self.assertNotIn(self.SID[:8], txt, name)
            self.assertNotIn("secret-project", txt, name)
            self.assertNotIn("/Users", txt, name)
            self.assertNotRegex(txt, r"/[A-Za-z_.~][\w.-]*/", name)
            self.assertNotIn(self.home, txt, name)
            self.assertNotIn(self.tmp, txt, name)


if __name__ == "__main__":
    unittest.main()
