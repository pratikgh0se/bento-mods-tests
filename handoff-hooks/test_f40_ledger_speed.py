"""F40 ledger speed and freshness fixes: ACs 117-124 of specs/handoff-hooks-spec.md "F40".
Black-box (temp HOME, `claude` shim on PATH; merge knobs `set_shim("merge", ...)`). Ledger and summary enabled.
Reuses the F39 fixtures (seed, ledger_lines, state, health ...). F40.1 supersedes the F39.3 output contract: the merge
call prints CHANGES (new `- D<n> ...` lines, `SUPERSEDE D<old> BY D<new>: <reason>`, or `NO CHANGES`)."""
import json, os, re, shutil, subprocess, sys, time, unittest
from helpers import *
import test_f35 as f35
import test_f39_ledger as f39
from test_f39_ledger import (F39, SEED3, LEAN, KEEP, MERGE_PROMPT, LEDGER2, L1, L2, LEDGER_KEYS, ts, parse_ts,
                             today_dates, SUMMARY_TEXT)

D4 = "- D4 [2026-10-27] x | why: y"
BODY_AGENT = "AGENTBODY " * 40
SYNTHETIC = ["<artifact-content-authored-by-others/> pasted by a tool", "<bash-input>ls -la</bash-input>",
             "<bash-stdout>total 0</bash-stdout>", "<bash-stderr>warn</bash-stderr>",
             "<command-name>/clear</command-name>", "<local-command-stdout>out</local-command-stdout>",
             "<task-notification>\n<status>completed</status>\n</task-notification>"]


class F40(F39):
    def sup_re(self, old, new, reason):
        return re.compile(r"^- D%d \[(\d{4}-\d\d-\d\d)\] SUPERSEDED by D%d \[(\d{4}-\d\d-\d\d)\]: .* \| because: %s$"
                          % (old, new, re.escape(reason)))

    def assert_superseded(self, line, old, new, reason, old_text=None):
        m = self.sup_re(old, new, reason).match(line)
        self.assertIsNotNone(m, line)
        self.assertTrue(set(m.groups()) & today_dates(), line)  # "dated today": which date is not pinned
        if old_text:
            self.assertIn(old_text, line)

    def reset_shim(self, **merge):
        shutil.rmtree(self.hd, ignore_errors=True)
        shutil.rmtree(self.shimdir)
        os.makedirs(self.shimdir)
        self.install_shim(out=SUMMARY_TEXT)
        self.set_shim("merge", **merge)


# ---------------------------------------------------------------- AC 117, 119 (F40.1 apply rules)
class DeltaApply(F40):
    def test_ac117_new_entry_and_supersede(self):
        d, text = self.seed(SEED3)
        self.set_shim("merge", out=D4 + "\nSUPERSEDE D2 BY D4: replaced\n")
        self.go()
        lines = self.ledger_lines()
        self.assertEqual(self.ids(lines), [1, 2, 3, 4])
        self.assertEqual(lines[0], SEED3[0])
        self.assert_superseded(lines[1], 2, 4, "replaced", "Keep API v1")
        self.assertEqual(lines[2], SEED3[2])
        self.assertEqual(lines[3], D4)
        h = self.health()
        self.assertEqual((h["ledger"], h["ledger_active"], h["ledger_superseded"], h["ledger_restored"]), ("ok", 3, 1, 0))
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(open(os.path.join(d, self.backups()[0])).read(), text)

    def test_supersede_by_an_existing_id(self):
        self.seed(SEED3)
        self.set_shim("merge", out="SUPERSEDE D1 BY D3: narrowed\n")
        self.go()
        lines = self.ledger_lines()
        self.assert_superseded(lines[0], 1, 3, "narrowed", "Use tabs")
        self.assertEqual(lines[1:], SEED3[1:])
        h = self.health()
        self.assertEqual((h["ledger"], h["ledger_active"], h["ledger_superseded"]), ("ok", 2, 1))

    def test_supersede_line_before_the_addition_it_names(self):
        self.seed(SEED3)
        self.set_shim("merge", out="SUPERSEDE D1 BY D4: replaced\n" + D4 + "\n")  # D4 exists after applying additions
        self.go()
        lines = self.ledger_lines()
        self.assert_superseded(lines[0], 1, 4, "replaced")
        self.assertEqual(lines[-1], D4)

    def test_entries_are_never_removed_ledger_restored_always_0(self):
        self.seed(SEED3)
        self.set_shim("merge", out="- D4 [2026-10-27] only the new one | why: z\n")
        self.go()
        self.assertEqual(self.ledger_lines()[:3], SEED3)
        self.assertEqual(self.health()["ledger_restored"], 0)

    def test_ac119_invalid_lines_ignored_valid_applied(self):
        seed = [SEED3[0], "- D2 [2026-10-21] SUPERSEDED by D3 [2026-10-22]: Keep API v1 | because: v2 shipped", SEED3[2]]
        self.seed(seed)
        out = "\n".join([
            "Here are the changes:",
            "SUPERSEDE D9 BY D4: unknown old id",
            "SUPERSEDE D1 BY D7: new id that never appears",
            "SUPERSEDE D2 BY D3: old id is not active",
            "- D2 [2026-10-27] Sneaky reuse of an old id | why: none",
            "- D3 [2026-10-27] Sneaky duplicate id | why: none",
            "D5 is not a line",
            "- D4 [2026-10-27] x | why: y",
            "SUPERSEDE D3 BY D4: replaced",
            "Thanks!"]) + "\n"
        self.set_shim("merge", out=out)
        self.go()
        lines = self.ledger_lines()
        self.assertEqual(self.ids(lines), [1, 2, 3, 4])
        self.assertEqual(lines[0], seed[0])
        self.assertEqual(lines[1], seed[1])
        self.assert_superseded(lines[2], 3, 4, "replaced", "No new deps")
        self.assertEqual(lines[3], D4)
        txt = self.ledger_text()
        for junk in ("Sneaky", "Here are the changes", "Thanks!", "never appears", "unknown old id"):
            self.assertNotIn(junk, txt)
        self.assertEqual(self.health()["ledger"], "ok")

    def test_only_invalid_lines_means_unchanged(self):
        d, text = self.seed(SEED3)
        self.set_shim("merge", out="SUPERSEDE D9 BY D4: nope\n- D2 [2026-10-27] reuse | why: none\nprose\n")
        self.go()
        self.assertEqual(open(os.path.join(d, "decisions.md")).read(), text)
        self.assertEqual(self.health()["ledger"], "unchanged")
        self.assertEqual(self.backups(), [])

    def test_first_merge_without_ledger_applies_additions(self):
        self.set_shim("merge", out="- D1 [2026-10-27] First | why: a\n- D2 [2026-10-27] Second | why: b\nSUPERSEDE D1 BY D2: merged\n")
        self.go()
        lines = self.ledger_lines()
        self.assertEqual(self.ids(lines), [1, 2])
        self.assert_superseded(lines[0], 1, 2, "merged", "First")
        self.assertEqual(self.health()["ledger"], "ok")

    def test_f40_1_prompt_is_the_delta_prompt(self):
        self.go()
        last = self.merge_argv()[-1]
        self.assertEqual(last, MERGE_PROMPT)
        self.assertIn("Output only the changes, one per line, nothing else:", last)
        self.assertIn('"SUPERSEDE D<old> BY D<new>: <reason>"', last)
        self.assertIn('Output "NO CHANGES" if nothing qualifies.', last)
        self.assertNotIn("Output the complete updated ledger", last)
        self.assertTrue(last.endswith(LEAN + " " + KEEP))  # F39.10/F39.11 sentences stay, in this order


# ---------------------------------------------------------------- AC 118
class NoChanges(F40):
    def test_ac118_no_changes_is_byte_identical_and_state_advances(self):
        d, text = self.seed(SEED3)
        self.set_shim("merge", out="NO CHANGES\n")
        self.go()
        self.assertEqual(open(os.path.join(d, "decisions.md")).read(), text)
        self.assertEqual(self.backups(), [])
        h = self.health()
        self.assertEqual((h["ledger"], h["ledger_restored"], h["ledger_error"]), ("unchanged", 0, ""))
        self.assertEqual(parse_ts(self.state()["lastEntryTs"]), parse_ts(ts(5)))  # was ts(-60)
        self.assertEqual(self.merge_calls(), 1)

    def test_ac118_prose_only_exit_0_is_unchanged_and_state_advances(self):
        d, text = self.seed(SEED3)
        self.set_shim("merge", out="Nothing in this conversation is a decision.\n")
        self.go()
        self.assertEqual(open(os.path.join(d, "decisions.md")).read(), text)
        self.assertEqual(self.health()["ledger"], "unchanged")
        self.assertEqual(parse_ts(self.state()["lastEntryTs"]), parse_ts(ts(5)))

    def test_no_changes_then_next_run_has_no_input(self):
        self.seed(SEED3)
        self.set_shim("merge", out="NO CHANGES\n")
        self.go()
        self.go()
        self.assertEqual(self.merge_calls(), 1)  # state advanced: nothing newer, no second call

    def test_no_changes_with_empty_ledger_creates_no_entries(self):
        self.set_shim("merge", out="NO CHANGES")
        self.go()
        self.assertEqual(self.health()["ledger"], "unchanged")
        self.assertEqual(self.health()["ledger_active"], 0)


# ---------------------------------------------------------------- AC 120, 124 (F40.2 timeout, F40.4 ledger_error)
class OwnTimeout(F40):
    def test_ac120_ledger_timeout_fails_merge_only(self):
        self.fresh_agent()
        d, text = self.seed(SEED3)
        self.set_shim("merge", sleepx=10)
        t0 = time.time()
        self.go(extra={"HANDOFF_LEDGER_TIMEOUT": "2"})
        dt = time.time() - t0
        self.assertLess(dt, 8, dt)
        self.assertGreaterEqual(dt, 1.5, dt)
        h = self.health()
        self.assertEqual((h["ledger"], h["ledger_error"]), ("failed", "timeout"))  # AC 124
        self.assertEqual((h["fallback"], h["status"]), ("ok", "ok"))
        self.assertIn(SUMMARY_H, self.latest())
        self.assertIn(SUMMARY_TEXT, self.latest())
        self.assertEqual(open(os.path.join(d, "decisions.md")).read(), text)
        self.assertEqual(json.load(open(os.path.join(d, "decisions.state.json")))["lastEntryTs"], ts(-60))
        self.assertEqual(self.backups(), [])

    def test_ac120_summary_timeout_does_not_limit_the_merge(self):
        self.set_shim("merge", sleep=4)
        t0 = time.time()
        self.go(extra={"HANDOFF_SUMMARY_TIMEOUT": "2", "HANDOFF_LEDGER_TIMEOUT": "20"})
        self.assertLess(time.time() - t0, 12)
        h = self.health()
        self.assertEqual((h["ledger"], h["ledger_error"]), ("ok", ""))
        self.assertEqual(self.ledger_lines(), [L1, L2])

    def test_summary_timeout_does_not_limit_the_merge_by_default_either(self):
        # no HANDOFF_LEDGER_TIMEOUT at all: the merge keeps its own (default 100 s) budget
        self.set_shim("merge", sleep=3)
        self.go(extra={"HANDOFF_SUMMARY_TIMEOUT": "1"})
        self.assertEqual((self.health()["ledger"], self.health()["ledger_error"]), ("ok", ""))

    def test_ledger_timeout_does_not_limit_the_summary(self):
        self.fresh_agent()
        self.set_shim("summary", sleep=4)
        self.go(extra={"HANDOFF_LEDGER_TIMEOUT": "2"})
        h = self.health()
        self.assertEqual((h["fallback"], h["ledger"]), ("ok", "ok"))
        self.assertIn(SUMMARY_TEXT, self.latest())

    def test_invalid_ledger_timeout_values_fall_back_to_the_default(self):
        # not an integer 1..300: the default (100 s) applies, so a 2 s merge succeeds
        for v in ("0", "301", "abc", "", "-5", "1.5"):
            self.reset_shim(out=LEDGER2, sleep=2)
            self.go(extra={"HANDOFF_LEDGER_TIMEOUT": v})
            self.assertEqual(self.health()["ledger"], "ok", repr(v))

    def test_valid_boundary_values_accepted(self):
        for v in ("1", "300"):
            self.reset_shim(out=LEDGER2)
            self.go(extra={"HANDOFF_LEDGER_TIMEOUT": v})
            self.assertEqual(self.health()["ledger"], "ok", v)

    def test_lock_wait_counts_inside_the_merge_timeout(self):
        d, text = self.seed(SEED3)
        lock = os.path.join(d, "decisions.lock")
        code = ("import fcntl,sys,time\nf=open(sys.argv[1],'a+')\nfcntl.flock(f,fcntl.LOCK_EX)\n"
                "print('held',flush=True)\ntime.sleep(15)\n")
        holder = subprocess.Popen([sys.executable, "-c", code, lock], stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        t0 = time.time()
        self.go(extra={"HANDOFF_LEDGER_TIMEOUT": "3"})
        dt = time.time() - t0
        self.assertLess(dt, 7, dt)
        h = self.health()
        self.assertEqual((h["ledger"], h["ledger_error"]), ("locked", "locked"))
        self.assertEqual(open(os.path.join(d, "decisions.md")).read(), text)

    def test_ac124_ledger_error_values(self):
        self.go()
        h = self.health()
        self.assertEqual((h["ledger"], h["ledger_error"]), ("ok", ""))
        self.assertIs(type(h["ledger_error"]), str)
        self.set_shim("merge", rc=3)
        self.seed(SEED3, last_ts=ts(-60))
        self.go()
        h = self.health()
        self.assertEqual((h["ledger"], h["ledger_error"]), ("failed", "exit 3"))
        self.set_shim("merge", rc=0, out="NO CHANGES")
        self.go()
        h = self.health()
        self.assertEqual((h["ledger"], h["ledger_error"]), ("unchanged", ""))

    def test_ac124_ledger_error_empty_when_disabled_or_no_cwd(self):
        self.go(extra={"HANDOFF_LEDGER": "0"})
        self.assertEqual((self.health()["ledger"], self.health()["ledger_error"]), ("disabled", ""))
        p = {"session_id": "S2", "trigger": "auto", "transcript_path": self.tpath}
        self.go(payload=p)
        self.assertEqual((self.health()["ledger"], self.health()["ledger_error"]), ("none", ""))

    def test_ac124_field_order(self):
        self.go()
        keys = list(self.health().keys())
        i = keys.index("ledger_chars")
        self.assertEqual(keys[i + 1], "ledger_error", keys)
        j = keys.index("summary_model")
        self.assertEqual(keys[j + 1:j + 7], LEDGER_KEYS)
        self.assertEqual(keys[i + 2], "duration_ms", keys)


# ---------------------------------------------------------------- AC 121
class Backlog(F40):
    N = 300

    def msgs(self):
        return [user("P%03d " % i + "u" * 394, timestamp=ts(i)) for i in range(self.N)]

    def sent(self, stdin):
        items = [l for l in self.conv_part(stdin).split("\n") if l.strip()]
        for l in items:
            self.assertRegex(l, r"^USER \S+: P\d{3} u{394}$")
        return [int(re.match(r"^USER \S+: P(\d{3}) ", l).group(1)) for l in items]

    def test_ac121_first_run_sends_oldest_up_to_40000(self):
        self.write_transcript(self.msgs())
        self.set_shim("merge", out="NO CHANGES")
        self.go()
        s = self.merge_stdin()
        new = self.conv_part(s)
        self.assertLessEqual(len(new), 40000)
        nums = self.sent(s)
        self.assertEqual(nums, list(range(len(nums))))  # starts with the OLDEST, contiguous
        self.assertTrue(85 <= len(nums) <= 98, len(nums))
        self.assertGreater(len(new), 38000)  # whole items, as many as fit
        self.assertEqual(parse_ts(self.state()["lastEntryTs"]), parse_ts(ts(len(nums) - 1)))

    def test_ac121_backlog_is_caught_up_over_several_compactions(self):
        self.write_transcript(self.msgs())
        self.set_shim("merge", out="NO CHANGES")
        seen = []
        for run in range(1, 8):
            self.go()
            if self.merge_calls() < run:
                break
            nums = self.sent(self.merge_stdin(run))
            self.assertEqual(nums[0], len(seen), (run, nums[:3], len(seen)))  # the next pending message first
            seen += nums
            self.assertEqual(parse_ts(self.state()["lastEntryTs"]), parse_ts(ts(seen[-1])))
            time.sleep(1.1)  # one-second backup/state resolution
        self.assertEqual(seen, list(range(self.N)))  # nothing dropped, nothing sent twice
        self.assertGreaterEqual(self.merge_calls(), 3)
        self.assertLessEqual(self.merge_calls(), 4)
        self.go()
        self.assertEqual(self.health()["ledger"], "unchanged")  # backlog consumed: no further call

    def test_ac121_large_items_only_whole_items_sent(self):
        e = [user("Q%02d " % i + "v" * 3900, timestamp=ts(i)) for i in range(20)]  # 78,000 chars
        self.write_transcript(e)
        self.set_shim("merge", out="NO CHANGES")
        self.go()
        new = self.conv_part(self.merge_stdin())
        self.assertLessEqual(len(new), 40000)
        lines = [l for l in new.split("\n") if l.strip()]
        self.assertTrue(all(re.match(r"^USER \S+: Q\d\d v{3900}$", l) for l in lines), [l[:40] for l in lines])
        self.assertEqual([int(l.split(": Q")[1][:2]) for l in lines], list(range(len(lines))))
        self.assertEqual(parse_ts(self.state()["lastEntryTs"]), parse_ts(ts(len(lines) - 1)))


# ---------------------------------------------------------------- AC 122 (F40.3)
class SyntheticUserEntries(F40):
    def test_ac122_not_in_merge_input_nor_last_user_messages(self):
        for i, syn in enumerate(SYNTHETIC):
            self.reset_shim(out="NO CHANGES")
            tag = "SYNTH%d" % i
            tagged = syn.replace(">", "> " + tag, 1) if ">" in syn else syn + tag
            e = [user("REAL-ONE genuine words", timestamp=ts(0)),
                 user(tagged, timestamp=ts(1)),
                 user("  \n" + tagged + "ws", timestamp=ts(2)),  # leading whitespace is stripped before the check
                 user("REAL-TWO genuine words", timestamp=ts(3))]
            self.write_transcript(e)
            t = self.go_text()
            sec = f35.section(t, EIGHT[0])
            self.assertIn("REAL-ONE", sec, syn)
            self.assertIn("REAL-TWO", sec, syn)
            self.assertNotIn(tag, sec, syn)
            s = self.conv_part(self.merge_stdin())
            self.assertRegex(s, r"(?m)^USER \S+: REAL-ONE genuine words$")
            self.assertNotIn(tag, s, syn)

    def test_ac122_synthetic_only_news_means_no_merge_call(self):
        self.seed(SEED3, last_ts=ts(5))  # the genuine convo is already merged
        e = self.convo() + [user(syn, timestamp=ts(10 + i)) for i, syn in enumerate(SYNTHETIC)]
        self.write_transcript(e)
        self.go()
        self.assertEqual(self.merge_calls(), 0)
        self.assertEqual(self.health()["ledger"], "unchanged")

    def test_ac122_does_not_count_for_the_freshness_grace_rule(self):
        for syn in SYNTHETIC:
            shutil.rmtree(self.hd, ignore_errors=True)
            a = self.agent_file(BODY_AGENT, age_min=1)
            m = float(int(os.path.getmtime(a)))
            far = f35.iso(m + 3600)
            self.write_transcript([user("genuine", timestamp=f35.iso(m)), user(syn, timestamp=far), asst("ok")])
            t = self.go_text()
            self.assertIsNone(warn_line(t), syn)
            self.assertIn(AGENT_H, t)

    def test_ac122_control_a_genuine_late_message_still_triggers_the_warning(self):
        a = self.agent_file(BODY_AGENT, age_min=1)
        m = float(int(os.path.getmtime(a)))
        self.write_transcript([user("genuine", timestamp=f35.iso(m)),
                               user("late genuine message", timestamp=f35.iso(m + 3600)), asst("ok")])
        t = self.go_text()
        self.assertIn("older than the last user message", warn_line(t) or "")

    def test_ac122_control_tag_text_in_the_middle_is_genuine(self):
        self.set_shim("merge", out="NO CHANGES")
        self.write_transcript([user("please explain what <bash-input> means in the transcript", timestamp=ts(0))])
        t = self.go_text()
        self.assertIn("please explain what <bash-input> means", f35.section(t, EIGHT[0]))
        self.assertIn("please explain what <bash-input> means", self.merge_stdin())


# ---------------------------------------------------------------- AC 123
class Template(F40):
    def test_ac123_precompact_timeout_150(self):
        tpl = os.path.join(os.path.dirname(HOOKS_DIR), "settings.template.json")
        with open(tpl) as fh:
            d = json.load(fh)
        cmds = [h for ent in d["hooks"]["PreCompact"] for h in ent.get("hooks", [])
                if "precompact-handoff.py" in h.get("command", "")]
        self.assertEqual(len(cmds), 1, cmds)
        self.assertEqual(cmds[0].get("timeout"), 150)


if __name__ == "__main__":
    unittest.main()
