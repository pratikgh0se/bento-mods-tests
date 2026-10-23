import json, os, re, subprocess, unittest
from helpers import *

FRESH_META = {"agentWrittenAt": 100, "lastNudgeAt": 100}
BODY = "AGENTBODY " * 40  # 400 bytes


def body_n(n):
    return ("B" * n)


class IO(HookCase):
    def test_ac1_exit_stdout_stderr_empty(self):
        self.write_transcript([user("hi")])
        cases = [json.dumps(self.payload()), "{}", "[]", "garbage", ""]
        for raw in cases:
            r = self.run_pre(raw=raw)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""), raw)

    def test_ac2_files_written(self):
        self.write_transcript([user("hi")])
        r = self.run_pre(self.payload("S"))
        self.assertEqual(r.returncode, 0)
        names = os.listdir(self.hd)
        stamped = [n for n in names if re.fullmatch(r"S-\d{8}T\d{6}Z\.md", n)]
        self.assertEqual(len(stamped), 1, names)
        self.assertIn("S-latest.md", names)
        a = open(os.path.join(self.hd, stamped[0]), "rb").read()
        b = open(os.path.join(self.hd, "S-latest.md"), "rb").read()
        self.assertEqual(a, b)

    def test_ac3_garbage_writes_unknown(self):
        self.run_pre(raw="garbage")
        self.assertIn("- session: unknown", self.latest("unknown"))

    def test_ac4_child_guard(self):
        for fb in ("0", "1"):
            self.install_shim(out="x" * 100)
            r = self.run_pre(self.payload(), fallback=fb, extra={"HANDOFF_HOOK_CHILD": "1"})
            self.assertEqual(r.returncode, 0)
            self.assertFalse(os.path.exists(self.hd))
            self.assertFalse(self.shim_invoked())


class Freshness(HookCase):
    def setUp(self):
        super().setUp()
        self.write_transcript([user("hello there"), asst("ok")])
        self.install_shim(out="H" * 120)

    def has_agent(self, text):
        return AGENT_H in text

    def test_ac5_fresh_no_meta(self):
        self.agent_file(BODY)
        t = self.run_and_read(fallback="1")
        i, j, k = t.index(AGENT_H), t.index(BODY.strip()), t.index(FACTS_H)
        self.assertTrue(i < j < k)
        # F38.1 amends AC 5 "shim not invoked when fresh": the summary runs for a fresh agent file too
        self.assertTrue(self.shim_invoked())
        self.assertTrue(t.index(AGENT_H) < t.index(SUMMARY_H) < t.index(FACTS_H))

    # AC 46: stale cases (6, 8, 9, 10, 11) now yield warning line + agent section (Haiku per fallback setting; "0" -> none)
    def assert_stale(self, t, reason=None):
        self.assertTrue(self.has_agent(t))
        w = warn_line(t)
        self.assertIsNotNone(w)
        if reason:
            self.assertIn(reason, w)
        self.assertEqual(t.index(w) + len(w) + 1, t.index(AGENT_H))  # bare line directly above the agent heading
        self.assertNotIn(SUMMARY_H, t)  # fallback "0"
        self.assertFalse(self.shim_invoked())

    def assert_fresh(self, t):
        self.assertTrue(self.has_agent(t))
        self.assertIsNone(warn_line(t))

    def test_ac6_mtime_boundaries(self):
        self.agent_file(BODY, age_min=29)
        self.assert_fresh(self.run_and_read())
        self.agent_file(BODY, age_min=31)
        self.assert_stale(self.run_and_read(), "not updated since the last nudge")

    def test_ac7_size_boundary(self):
        self.agent_file(body_n(299), meta=FRESH_META)
        t = self.run_and_read()
        self.assertFalse(self.has_agent(t))
        self.assertIsNone(warn_line(t))
        self.agent_file(body_n(300), meta=FRESH_META)
        self.assert_fresh(self.run_and_read())

    def test_ac8_meta_rules(self):
        def check(meta, stale):
            self.agent_file(body_n(400), meta=meta)
            t = self.run_and_read()
            if stale:
                self.assert_stale(t)
            else:
                self.assert_fresh(t)
        check({"agentWrittenAt": 100, "lastNudgeAt": 100}, False)
        base = {"agentWrittenAt": 99, "lastNudgeAt": 100, "ctxTokens": 60000}
        check(dict(base, agentWrittenAtTokens=10001), False)
        check(dict(base, agentWrittenAtTokens=10000), False)
        check(dict(base, agentWrittenAtTokens=9999), True)

    def test_ac9_no_agentWrittenAt_stale(self):
        self.agent_file(body_n(400), meta={"lastNudgeAt": 100, "ctxTokens": 5, "agentWrittenAtTokens": 5})
        self.assert_stale(self.run_and_read())

    def test_ac10_valid_stale_meta_ignores_mtime(self):
        self.agent_file(body_n(400), meta={"agentWrittenAt": 50, "lastNudgeAt": 100})
        self.assert_stale(self.run_and_read())

    def test_ac11_invalid_meta_is_no_meta(self):
        self.agent_file(body_n(400), raw_meta="{not json", age_min=5)
        self.assert_fresh(self.run_and_read())
        self.agent_file(body_n(400), raw_meta="{not json", age_min=40)
        self.assert_stale(self.run_and_read(), "not updated since the last nudge")

    def test_ac12_body_cap_5000(self):
        self.agent_file("Q" * 6000, meta=FRESH_META)
        t = self.run_and_read()
        self.assertIn("Q" * 4997 + "...", t)
        self.assertNotIn("Q" * 4998, t)


class Fallback(HookCase):
    def setUp(self):
        super().setUp()
        self.write_transcript([user("please do the thing"), asst("done")])

    def test_ac13_haiku_success_and_invocation(self):
        text = "HAIKU-SUMMARY " + "y" * 80
        self.install_shim(out=text)
        r = self.run_pre(self.payload(), fallback="1",
                         extra={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "123"})
        self.assertEqual(r.returncode, 0)
        t = self.latest()
        self.assertIn(SUMMARY_H, t)
        self.assertIn(text, t)
        args = self.shim_file("args").split("\n")
        for a in ("-p", "--model", "sonnet", "--tools"):  # F38.3: sonnet by default (was haiku)
            self.assertIn(a, args)
        self.assertNotIn("haiku", args)
        self.assertIn("USER: please do the thing", self.shim_file("stdin"))
        env = self.shim_file("env")
        self.assertIn("HANDOFF_HOOK_CHILD=1", env)
        self.assertNotIn("CLAUDE_CODE_AUTO_COMPACT_WINDOW", env)

    def test_ac14_failures(self):
        self.install_shim(rc=3, out="")
        t = self.run_and_read(fallback="1")
        self.assertIn("Fresh summary failed: claude exited 3", t)
        self.assertIn(FACTS_H, t)

    def test_ac14_short_output(self):
        self.install_shim(out="short")
        t = self.run_and_read(fallback="1")
        self.assertIn("Fresh summary failed: empty or too-short output", t)
        self.assertIn(FACTS_H, t)

    def test_ac14_no_binary(self):
        t = self.run_and_read(fallback="1")
        self.assertIn("Fresh summary failed: claude binary not found", t)
        self.assertIn(FACTS_H, t)

    def test_ac14_no_transcript(self):
        self.install_shim(out="x" * 100)
        t = self.run_and_read(fallback="1", transcript=False)
        self.assertIn("Fresh summary failed: no transcript excerpt", t)
        self.assertIn(FACTS_H, t)
        self.assertFalse(self.shim_invoked())

    def test_ac15_summary_cap_6000(self):  # F38.4 amends the 4,000-char Haiku cap
        self.install_shim(out="Z" * 9000)
        t = self.run_and_read(fallback="1")
        runs = max(len(m) for m in re.findall(r"Z+", t))
        self.assertTrue(5997 <= runs <= 6000, runs)

    def test_ac16_fallback_disabled(self):
        # AC 46: amended to the stale-lead layout of AC 35 (warning + agent section, no Haiku, Facts present)
        self.install_shim(out="x" * 100)
        self.agent_file(body_n(400), meta={"agentWrittenAt": 1})
        t = self.run_and_read(fallback="0")
        self.assertFalse(self.shim_invoked())
        self.assertIsNotNone(warn_line(t))
        self.assertIn(AGENT_H, t)
        for s in (SUMMARY_H, "Fresh summary failed"):
            self.assertNotIn(s, t)
        self.assertIn(FACTS_H, t)

    def test_ac16_fallback_disabled_no_agent_file(self):
        self.install_shim(out="x" * 100)
        t = self.run_and_read(fallback="0")
        self.assertFalse(self.shim_invoked())
        self.assertNotIn(AGENT_H, t)
        self.assertNotIn(SUMMARY_H, t)
        self.assertNotIn("Fresh summary failed", t)

    def test_ac16_other_values_enable(self):
        for v in ("1", ""):
            self.install_shim(out="x" * 100)
            if os.path.exists(os.path.join(self.shimdir, "invoked")):
                os.remove(os.path.join(self.shimdir, "invoked"))
            self.run_and_read(fallback=v)
            self.assertTrue(self.shim_invoked(), repr(v))

    def test_ac17_fresh_still_runs_summary(self):  # F38.1 amends AC 17 "Haiku not invoked when fresh"
        self.install_shim(out="x" * 100)
        self.agent_file(body_n(400), meta=FRESH_META)
        t = self.run_and_read(fallback="1")
        self.assertTrue(self.shim_invoked())
        self.assertIn(SUMMARY_H, t)


def body_n(n):
    return "B" * n


if __name__ == "__main__":
    unittest.main()
