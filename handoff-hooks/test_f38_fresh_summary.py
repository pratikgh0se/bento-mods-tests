"""F38 fresh summary at compaction: ACs 81-92 of specs/handoff-hooks-spec.md "F38".
Hook scripts located by HANDOFF_HOOKS_DIR (helpers.py). The summary is ENABLED in these tests unless stated: the
runs below pass fallback=None (HANDOFF_HAIKU_FALLBACK unset) together with a `claude` shim on PATH."""
import json, os, re, shutil, subprocess, sys, time, unittest
from helpers import *
from test_content import git
import test_f35 as f35

SYSTEM = ("You write handoff notes for an AI coding agent that will resume this session after its context is "
          "compacted. Output only the note.")
PROMPT = ("The conversation since the last compaction is on stdin. Write the handoff with exactly these headings: "
          "## Goal, ## Decisions and why, ## Done, ## In progress, ## Dead ends, ## Exact next step. Describe the "
          "state at the END of the conversation, including the user's latest request and any rules they set (what "
          "needs their approval, what not to touch). Under Done list only work confirmed by a tool result; put "
          "anything started but unconfirmed under In progress prefixed \"unverified:\". Keep it under 3500 chars. "
          "Use real paths, commands and ids; no secrets.")  # F39.7 (F38.3 text amended)


def expected_argv(model="sonnet"):
    return ["-p", "--model", model, "--output-format", "text", "--no-session-persistence", "--setting-sources", "",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands", "--tools", "",
            "--system-prompt", SYSTEM, PROMPT]


def head_for(model):
    return "## Fresh summary at compaction (%s; verify against facts)" % model


BODY = "AGENTBODY " * 40  # 400 bytes
SUMMARY_TEXT = "SUMMARY-300 " + "s" * 288  # 300 chars
BOUNDARY = {"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted"}


class F38(HookCase):
    # F39.7 amends F38.2/F38.3 (stdin starts with STANDING DECISIONS, new prompt, tool-line outcomes): these tests run
    # with the ledger ENABLED, because F39.1 ties F39.7 to the ledger switch (see SPEC-GAPS.md F39). No merge output is
    # configured, so the merge call (separate shim role) yields nothing and the ledger stays empty.
    LEDGER_ENV = None

    def setUp(self):
        super().setUp()
        self.write_transcript([user("please do the thing"), asst("done")])

    # --- fixtures / runs ---
    def fresh(self, body=BODY):
        self.agent_file(body, age_min=1)

    def stale(self, body=BODY):
        self.agent_file(body, age_min=40)

    def go(self, extra=None, fallback=None, shim=True, out=SUMMARY_TEXT, rc=None, **kw):
        """Run the hook with the summary enabled (HANDOFF_HAIKU_FALLBACK unset unless `fallback` given)."""
        if shim:
            self.install_shim(out=out, rc=rc)
        r = self.run_pre(self.payload(**kw), fallback=fallback, extra=extra)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        return self.latest()

    def sec(self, t, head):
        return f35.section(t, head)

    def no_old(self, t):
        self.assertNotIn("## Model-written handoff (Haiku fallback", t)
        self.assertNotIn("Haiku fallback failed:", t)

    def order(self, t, *needles):
        pos = [t.index(n) for n in needles]
        self.assertEqual(pos, sorted(pos), needles)
        self.assertEqual(len(set(pos)), len(pos))


# ---------------------------------------------------------------- AC 81
class Placement(F38):
    def test_ac81_fresh_agent_summary_between_agent_and_facts(self):
        self.fresh()
        t = self.go()
        self.no_old(t)
        self.order(t, AGENT_H, BODY.strip(), SUMMARY_H, SUMMARY_TEXT, FACTS_H)
        self.assertIn("%s\n%s\n\n%s" % (SUMMARY_H, SUMMARY_TEXT, FACTS_H), t)
        self.assertIsNone(warn_line(t))
        self.assertTrue(self.shim_invoked())
        self.assertEqual(self.invocations_count(), 1)

    def invocations_count(self):
        return len(self.shim_file("invoked").split())

    def test_ac81_health_fields(self):
        self.fresh()
        self.go()
        h = self.health()
        self.assertEqual((h["fallback"], h["summary_model"], h["status"]), ("ok", "sonnet", "ok"))
        self.assertEqual(h["agent_file"], "fresh")

    def test_ac81_summary_is_only_one_section_of_its_kind(self):
        self.fresh()
        t = self.go()
        self.assertEqual(t.count("## Fresh summary at compaction"), 1)


# ---------------------------------------------------------------- AC 82
class Call(F38):
    def test_ac82_argv_exact(self):
        self.fresh()
        self.go()
        argv = self.shim_argv()
        self.assertEqual(argv, expected_argv("sonnet"))
        self.assertEqual(argv.count(""), 2)

    def test_ac82_argv_with_absent_and_stale_agent(self):
        for setup in (lambda: None, self.stale):
            shutil.rmtree(self.hd, ignore_errors=True)
            setup()
            self.go()
            self.assertEqual(self.shim_argv(), expected_argv("sonnet"))

    def test_ac82_child_env(self):
        self.fresh()
        self.go(extra={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "123"})
        env = self.shim_file("env").split("\n")
        self.assertIn("HANDOFF_HOOK_CHILD=1", env)
        self.assertFalse([l for l in env if l.startswith("CLAUDE_CODE_AUTO_COMPACT_WINDOW")], env)

    def test_ac82_excerpt_on_stdin_and_not_in_argv(self):
        self.go()
        self.assertIn("USER: please do the thing", self.shim_file("stdin"))
        self.assertNotIn("please do the thing", " ".join(self.shim_argv()))

    def test_ac82_runs_in_fresh_dir_not_cwd_of_session(self):
        # F38.3 "cwd a fresh temp dir": the shim records nothing about cwd, so only check the hook still works
        # when the session cwd is the temp tree and that the session cwd gained no new files from the child.
        before = set(os.listdir(self.tmp))
        self.go()
        self.assertEqual(set(os.listdir(self.tmp)) - before, set())


# ---------------------------------------------------------------- AC 83
class Model(F38):
    def test_ac83_haiku(self):
        self.fresh()
        t = self.go(extra={"HANDOFF_SUMMARY_MODEL": "haiku"})
        self.assertEqual(self.shim_argv(), expected_argv("haiku"))
        self.assertIn(head_for("haiku"), t)
        self.assertNotIn(SUMMARY_H, t)
        self.assertEqual(self.health()["summary_model"], "haiku")

    def test_ac83_bad_model_falls_back_to_sonnet(self):
        for bad in ("bad model;", "a b", "x/y", "m;rm", "$(x)", "", "é"):
            shutil.rmtree(self.hd, ignore_errors=True)
            self.fresh()
            t = self.go(extra={"HANDOFF_SUMMARY_MODEL": bad})
            self.assertEqual(self.shim_argv(), expected_argv("sonnet"), repr(bad))
            self.assertIn(SUMMARY_H, t, repr(bad))
            self.assertEqual(self.health()["summary_model"], "sonnet", repr(bad))

    def test_ac83_allowed_charset(self):
        self.fresh()
        t = self.go(extra={"HANDOFF_SUMMARY_MODEL": "claude-sonnet-4.5_x"})
        self.assertEqual(self.shim_argv(), expected_argv("claude-sonnet-4.5_x"))
        self.assertIn(head_for("claude-sonnet-4.5_x"), t)
        self.assertEqual(self.health()["summary_model"], "claude-sonnet-4.5_x")


# ---------------------------------------------------------------- AC 84
class Disabled(F38):
    SWITCHES = [("HANDOFF_SUMMARY=0", None, {"HANDOFF_SUMMARY": "0"}),
                ("HANDOFF_HAIKU_FALLBACK=0", "0", None)]

    def check_off(self, t):
        self.assertFalse(self.shim_invoked())
        self.assertNotIn("## Fresh summary at compaction", t)
        self.assertNotIn("Fresh summary failed", t)
        self.no_old(t)
        h = self.health()
        self.assertEqual((h["fallback"], h["summary_model"]), ("disabled", ""))
        return h

    def test_ac84_fresh_agent_status_ok(self):
        for name, fb, extra in self.SWITCHES:
            with self.subTest(name):
                shutil.rmtree(self.hd, ignore_errors=True)
                self.fresh()
                t = self.go(fallback=fb, extra=extra)
                h = self.check_off(t)
                self.assertEqual(h["status"], "ok")
                self.assertIn(AGENT_H, t)
                self.assertIn(FACTS_H, t)

    def test_ac84_absent_agent_degraded_no_facts_heading(self):
        for name, fb, extra in self.SWITCHES:
            with self.subTest(name):
                shutil.rmtree(self.hd, ignore_errors=True)
                t = self.go(fallback=fb, extra=extra)
                h = self.check_off(t)
                self.assertEqual(h["status"], "degraded")
                self.assertNotIn(FACTS_H, t.split("\n"))
                self.assertNotIn(AGENT_H, t)

    def test_ac84_stale_agent_degraded(self):
        for name, fb, extra in self.SWITCHES:
            with self.subTest(name):
                shutil.rmtree(self.hd, ignore_errors=True)
                self.stale()
                t = self.go(fallback=fb, extra=extra)
                h = self.check_off(t)
                self.assertEqual(h["status"], "degraded")
                self.assertIsNotNone(warn_line(t))

    def test_ac84_only_exact_zero_disables(self):
        for extra, fb in (({"HANDOFF_SUMMARY": "1"}, None), ({"HANDOFF_SUMMARY": ""}, None),
                          ({"HANDOFF_SUMMARY": "00"}, None), ({"HANDOFF_SUMMARY": "false"}, None),
                          (None, "1"), (None, ""), (None, "false")):
            with self.subTest(extra=extra, fb=fb):
                shutil.rmtree(self.hd, ignore_errors=True)
                shutil.rmtree(self.shimdir, ignore_errors=True)
                os.makedirs(self.shimdir)
                self.fresh()
                t = self.go(fallback=fb, extra=extra)
                self.assertTrue(self.shim_invoked())
                self.assertIn(SUMMARY_H, t)

    def test_ac84_either_switch_disables_even_if_other_enables(self):
        self.fresh()
        t = self.go(fallback="1", extra={"HANDOFF_SUMMARY": "0"})
        self.check_off(t)
        shutil.rmtree(self.hd)
        t = self.go(fallback="0", extra={"HANDOFF_SUMMARY": "1"})
        self.check_off(t)


# ---------------------------------------------------------------- AC 85
def mixed_asst(text, name, **inp):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text},
                                                         {"type": "tool_use", "name": name, "input": inp}]}}


class Excerpt(F38):
    def stdin_for(self, entries):
        self.write_transcript(entries)
        self.go()
        return self.shim_file("stdin")

    def test_ac85_after_last_boundary_only(self):
        e = [user("PRE-ONE-USER"), asst("PRE-ONE-ASSISTANT"), BOUNDARY, user("PRE-TWO-USER"), asst("PRE-TWO-ASSISTANT"),
             BOUNDARY,
             user("MSG-A-user"), asst("MSG-B-assistant"), user("MSG-C-user"), asst("MSG-D-assistant"),
             user("MSG-E-user")]
        s = self.stdin_for(e)
        for pre in ("PRE-ONE", "PRE-TWO"):
            self.assertNotIn(pre, s)
        for x in ("USER: MSG-A-user", "ASSISTANT: MSG-B-assistant", "USER: MSG-C-user", "ASSISTANT: MSG-D-assistant",
                  "USER: MSG-E-user"):
            self.assertIn(x, s)
        self.order(s, "MSG-A", "MSG-B", "MSG-C", "MSG-D", "MSG-E")
        # messages separated by a blank line
        self.assertIn("USER: MSG-A-user\n\nASSISTANT: MSG-B-assistant\n\nUSER: MSG-C-user", s)

    def test_ac85_no_boundary_means_all_entries(self):
        s = self.stdin_for([user("FIRST-ONE"), asst("SECOND-ONE"), user("THIRD-ONE")])
        self.assertIn("USER: FIRST-ONE", s)
        self.assertIn("ASSISTANT: SECOND-ONE", s)
        self.assertIn("USER: THIRD-ONE", s)

    def test_ac85_only_noise_after_boundary_means_no_excerpt(self):
        # empty excerpt after the last boundary: reason `no transcript excerpt`, claude not run
        self.write_transcript([user("OLD-STUFF"), asst("OLD-REPLY"), BOUNDARY])
        t = self.go()
        self.assertFalse(self.shim_invoked())
        self.assertIn(SUMMARY_FAIL + "no transcript excerpt\n\n", t)

    def test_ac85_tool_results_and_noise_omitted(self):
        e = [user("MSG-A-user"),
             {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Read",
                                                           "input": {"file_path": "/x/y.py"}}]}},
             f35.tres("t1", "TOOLRESULT-SECRET-TEXT"),
             {"type": "user", "message": {"content": [{"type": "tool_result", "content": "TOOLRES-RAW-TEXT"}]}},
             user("META-TEXT-ZZ", isMeta=True),
             user("COMPACT-SUMMARY-ZZ", isCompactSummary=True),
             asst("MSG-B-assistant")]
        s = self.stdin_for(e)
        for gone in ("TOOLRESULT-SECRET-TEXT", "TOOLRES-RAW-TEXT", "META-TEXT-ZZ", "COMPACT-SUMMARY-ZZ"):
            self.assertNotIn(gone, s)
        self.assertIn("USER: MSG-A-user", s)
        self.assertIn("ASSISTANT: MSG-B-assistant", s)

    def test_ac85_bash_tool_use_line(self):
        e = [user("MSG-A-user"), mixed_asst("MSG-B-text", "Bash", command="echo hello-85 && ls /tmp"), user("MSG-C-user")]
        s = self.stdin_for(e)
        self.assertIn("\n[tool Bash: echo hello-85 && ls /tmp] -> no result\n", s)  # own line; F39.7 outcome suffix
        self.assertIn("ASSISTANT: MSG-B-text", s)

    def test_ac85_tool_only_assistant_message_still_renders_tool_line(self):
        s = self.stdin_for([user("MSG-A-user"), tool("Bash", command="echo only-tool-85"), user("MSG-C-user")])
        self.assertRegex(s, r"(?m)^(ASSISTANT: )?\[tool Bash: echo only-tool-85\] -> no result$")

    def test_ac85_tool_key_input_cut_at_300(self):
        s = self.stdin_for([user("MSG-A-user"), mixed_asst("x", "Bash", command="C" * 1000), user("MSG-C-user")])
        m = re.search(r"\[tool Bash: (C+)", s)
        self.assertIsNotNone(m, s[:500])
        self.assertTrue(297 <= len(m.group(1)) <= 300, len(m.group(1)))

    def test_ac85_user_message_cut_to_4000(self):
        s = self.stdin_for([user("MSG-A-user"), user("U" * 10000), asst("MSG-B-assistant")])
        run = max(len(m) for m in re.findall(r"U+", s.replace("USER", "")))
        self.assertTrue(3997 <= run <= 4000, run)

    def test_ac85_assistant_message_cut_to_4000(self):
        s = self.stdin_for([user("MSG-A-user"), asst("W" * 10000), user("MSG-C-user")])
        run = max(len(m) for m in re.findall(r"W+", s))
        self.assertTrue(3997 <= run <= 4000, run)

    def test_ac85_large_transcript_fits_120k_and_keeps_tail(self):
        e = [user("PRE-BOUNDARY-MARK"), BOUNDARY]
        texts = []
        for i in range(200):
            tx = ("%03d" % i) + "x" * 1997  # 2000 chars
            texts.append(tx)
            e.append(user(tx) if i % 2 == 0 else asst(tx))
        s = self.stdin_for(e)
        self.assertLessEqual(len(s), 120000)
        self.assertGreater(len(s), 115000)  # whole messages dropped only as needed
        self.assertTrue(s.rstrip("\n").endswith(texts[-1]))
        self.assertTrue(s.startswith("STANDING DECISIONS (do not contradict"))  # F39.7; 120,000 bound is on the whole stdin
        first = s.split("CONVERSATION:\n", 1)[1].split("\n")[0]
        self.assertRegex(first, r"^(USER|ASSISTANT): \d{3}x")  # starts at a whole message, with its prefix
        self.assertNotIn("PRE-BOUNDARY-MARK", s)
        self.assertNotIn(texts[0], s)

    def test_ac85_single_huge_last_message_keeps_its_end(self):
        # with 4,000-char message truncation the last message cannot exceed 120,000; the cap still holds
        s = self.stdin_for([user("MSG-A-user"), asst("MSG-B-assistant")])
        self.assertLessEqual(len(s), 120000)


# ---------------------------------------------------------------- AC 86 and 87
class Failures(F38):
    def fail_line(self, t, reason):
        line = SUMMARY_FAIL + reason
        self.assertEqual(t.split("\n").count(line), 1, t)
        self.assertIn(line + "\n\n", t)
        self.no_old(t)
        self.assertNotIn("## Fresh summary at compaction", t)

    def test_ac86_exit_code(self):
        self.fresh()
        t = self.go(rc=3, out="")
        self.fail_line(t, "claude exited 3")
        self.order(t, AGENT_H, SUMMARY_FAIL + "claude exited 3", FACTS_H)
        h = self.health()
        self.assertEqual((h["fallback"], h["status"]), ("failed", "ok"))

    def test_ac86_exit_code_nonzero_with_long_stdout_still_fails(self):
        self.fresh()
        t = self.go(rc=3, out="o" * 400)
        self.fail_line(t, "claude exited 3")
        self.assertNotIn("o" * 100, t)

    def test_ac86_absent_agent_degraded(self):
        t = self.go(rc=3, out="")
        self.fail_line(t, "claude exited 3")
        h = self.health()
        self.assertEqual((h["fallback"], h["status"], h["agent_file"]), ("failed", "degraded", "absent"))
        self.assertNotIn(AGENT_H, t)

    def test_ac86_too_short(self):
        self.fresh()
        t = self.go(out="x" * 20)
        self.fail_line(t, "empty or too-short output")
        self.assertEqual(self.health()["fallback"], "failed")

    def test_ac86_empty_and_whitespace_only(self):
        for out in ("", "   \n\n  "  + "\n" * 80):
            shutil.rmtree(self.hd, ignore_errors=True)
            self.fresh()
            t = self.go(out=out)
            self.fail_line(t, "empty or too-short output")

    def test_ac86_threshold_is_stripped_50(self):
        self.fresh()
        t = self.go(out="\n\n" + "a" * 49 + "\n\n")
        self.fail_line(t, "empty or too-short output")
        shutil.rmtree(self.hd)
        self.fresh()
        t = self.go(out="\n\n" + "b" * 50 + "\n\n")
        self.assertIn(SUMMARY_H + "\n" + "b" * 50, t)
        self.assertNotIn(SUMMARY_FAIL, t)

    def test_ac86_no_binary(self):
        self.fresh()
        t = self.go(shim=False)
        self.fail_line(t, "claude binary not found")
        h = self.health()
        self.assertEqual((h["fallback"], h["status"]), ("failed", "ok"))

    def test_ac86_failure_line_when_agent_absent_is_first_section(self):
        t = self.go(rc=3, out="")
        self.assertEqual(sec_names(t)[0], FACTS_H)  # failure line is a bare line, not a '## ' section
        self.assertLess(t.index(SUMMARY_FAIL), t.index(FACTS_H))

    def test_ac87_timeout(self):
        self.fresh()
        self.install_shim(out=SUMMARY_TEXT)
        open(os.path.join(self.shimdir, "sleepx"), "w").write("10")
        t0 = time.time()
        r = self.run_pre(self.payload(), fallback=None, extra={"HANDOFF_SUMMARY_TIMEOUT": "2"})
        dt = time.time() - t0
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertLess(dt, 6, dt)
        self.assertGreaterEqual(dt, 1.5, dt)  # it did wait for the timeout
        t = self.latest()
        self.fail_line(t, "timeout after 2s")
        h = self.health()
        self.assertEqual((h["fallback"], h["status"]), ("timeout", "ok"))
        self.assertIn(AGENT_H, t)
        self.assertIn(FACTS_H, t)
        self.assertTrue(t.rstrip().endswith(FOOTER_FMT.format(p=self.tpath)))

    def test_ac87_timeout_absent_agent_degraded(self):
        self.install_shim(out=SUMMARY_TEXT)
        open(os.path.join(self.shimdir, "sleepx"), "w").write("10")
        r = self.run_pre(self.payload(), fallback=None, extra={"HANDOFF_SUMMARY_TIMEOUT": "1"})
        self.assertEqual(r.returncode, 0)
        self.fail_line(self.latest(), "timeout after 1s")
        h = self.health()
        self.assertEqual((h["fallback"], h["status"]), ("timeout", "degraded"))


# ---------------------------------------------------------------- AC 88
class Cap(F38):
    def test_ac88_cut_to_4000_with_ellipsis(self):
        self.fresh()
        t = self.go(out="X" * 9000)
        body = self.sec(t, SUMMARY_H).rstrip("\n")
        self.assertEqual(len(body), 4000)
        self.assertTrue(body.endswith("..."))
        self.assertEqual(body, "X" * 3997 + "...")
        self.assertLessEqual(len(t), CAP)

    def test_ac88_exactly_4000_is_kept_whole(self):
        self.fresh()
        t = self.go(out="Y" * 4000)
        self.assertEqual(self.sec(t, SUMMARY_H).rstrip("\n"), "Y" * 4000)

    def test_ac88_under_cap_kept_whole(self):
        self.fresh()
        t = self.go(out="Z" * 3500)
        self.assertEqual(self.sec(t, SUMMARY_H).rstrip("\n"), "Z" * 3500)


# ---------------------------------------------------------------- AC 89
class Layout(F38):
    def test_ac89_stale_agent_order_and_reduced(self):
        self.stale()
        t = self.go()
        w = warn_line(t)
        self.assertIsNotNone(w)
        self.order(t, w, AGENT_H, BODY.strip(), SUMMARY_H, SUMMARY_TEXT, FACTS_H)
        self.assertEqual(t.index(w) + len(w) + 1, t.index(AGENT_H))
        h = self.health()
        self.assertEqual((h["agent_file"], h["fallback"], h["status"]), ("stale", "ok", "reduced"))

    def test_ac89_absent_agent_summary_first_section(self):
        t = self.go()
        names = sec_names(t)
        self.assertEqual(names[0], SUMMARY_H)
        self.assertEqual(names[1], FACTS_H)
        self.assertNotIn(AGENT_H, t)
        h = self.health()
        self.assertEqual((h["agent_file"], h["fallback"], h["status"]), ("absent", "ok", "reduced"))
        self.assertIn(SUMMARY_TEXT, t)

    def test_ac89_header_first_then_summary(self):
        t = self.go()
        self.assertEqual(t.split("\n")[0], "# Handoff (pre-compaction)")
        self.assertLess(t.index("# Handoff (pre-compaction)"), t.index(SUMMARY_H))


# ---------------------------------------------------------------- AC 90
class OverCap(F38):
    """Calibration knob: the length of a (nonexistent) cwd, which lands in the never-trimmed header. The agent body is
    capped at 5,000 chars, so the agent size cannot be the knob. No git repo is used, hence `## Git` is absent; the
    'eight non-user facts sections' are then the seven that exist (logged in SPEC-GAPS.md).
    F39.6: cap 14,000 and summary cap 4,000, so the fixture is shrunk (agent AGENT chars) and the sweep ranges retuned."""
    AGENT = 3000
    HI = 9000
    LO_USERS, HI_USERS = 5000, 9000

    def setUp(self):
        super().setUp()
        qs = [("Which name?", "Name", ["alpha", "beta"])]
        e = [user(("U%02d" % i) + "u" * 700) for i in range(8)]  # each cut to 600 in the section
        e += [f35.ask("q1", qs), f35.answer("q1", {"Which name?": "alpha"})]
        e += [tool("Edit", file_path="/" + ("p%02d" % i) + "d" * 100) for i in range(30)]
        e += [tool("TaskCreate", subject="s" * 150), tool("TaskCreate", subject="t" * 150)]
        e += [tool("TodoWrite", todos=[{"content": "todo " + "z" * 140, "status": "pending", "activeForm": "x"}])]
        e += [tool("Bash", command=("c%d" % i) + "x" * 40) for i in range(5)]
        e += [f35.tu("bg1", "Agent", {"description": "background job", "prompt": "p", "subagent_type": "g",
                                      "run_in_background": True}),
              f35.tres("bg1", "agentId: bgid1", {"agentId": "bgid1", "isAsync": True})]
        e.append(asst("A" * 400))
        self.write_transcript(e)
        self.install_shim(out="S" * 4000)
        self.base = self.run_c(0, summary=False)
        self.non_user = [h for h in DROP37 if h != EIGHT[0] and h in self.base]

    def run_c(self, c, summary=True):
        shutil.rmtree(self.hd, ignore_errors=True)
        self.agent_file("L" * self.AGENT, meta={"agentWrittenAt": 1})  # stale agent: never trimmed
        r = self.run_pre(self.payload(cwd="/" + "d" * c if c else self.tmp), fallback=None if summary else "0")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        return self.latest()

    def state(self, t):
        sec = self.sec(t, SUMMARY_H)
        return {"present": sec is not None, "len": 0 if sec is None else len(sec.rstrip("\n")),
                "ends_dots": sec is not None and sec.rstrip("\n").endswith("...")}

    def check_invariants(self, c, t):
        st = self.state(t)
        self.assertLessEqual(len(t), CAP, c)
        self.assertIn("L" * self.AGENT, t)  # agent section never trimmed
        self.assertTrue(t.rstrip().endswith(FOOTER_FMT.format(p=self.tpath)), c)
        self.assertIsNotNone(warn_line(t), c)
        self.no_old(t)
        non_user_gone = all(h not in t for h in self.non_user)
        if st["present"] and st["len"] < 4000:
            self.assertTrue(non_user_gone, c)  # summary shortened only after every non-user facts section is dropped
            self.assertTrue(st["ends_dots"], c)
            self.assertGreaterEqual(st["len"], 200 - 3, c)
        if EIGHT[0] not in t:
            self.assertFalse(st["present"], c)  # Last user messages dropped only after the summary is gone
            self.assertTrue(non_user_gone, c)
        if st["present"] and st["len"] == 4000:
            gone = [h for h in DROP37 if h not in t and h in self.base]
            self.assertEqual(gone, [h for h in DROP37 if h in self.base][:len(gone)], c)  # F37.2 order
        return st

    def scan(self, lo=0, hi=None, step=100):
        hi = hi or self.HI
        seen = {}
        for c in range(lo, hi, step):
            t = self.run_c(c)
            seen[c] = (t, self.check_invariants(c, t))
        return seen

    def test_ac90_baseline_has_the_facts_sections_and_full_summary(self):
        self.assertEqual(len(self.non_user), 6, self.non_user)  # F39.6: no Decisions section; no Git (nonexistent cwd)
        self.assertIn(EIGHT[0], self.base)
        t = self.run_c(0)
        self.assertEqual(self.sec(t, SUMMARY_H).rstrip("\n"), "S" * 4000)
        self.assertLessEqual(len(t), CAP)

    def test_ac90_facts_dropped_then_summary_shortened_user_messages_kept(self):
        seen = self.scan()
        hit = [c for c, (t, st) in seen.items() if st["present"] and 200 <= st["len"] < 4000 and st["ends_dots"]]
        self.assertTrue(hit, "no cwd length produced a shortened summary: %s"
                        % sorted({(st["present"], st["len"] // 1000) for t, st in seen.values()}))
        for c in hit:
            t = seen[c][0]
            self.assertEqual([h for h in EIGHT if h in t], [EIGHT[0]], c)
            self.assertLessEqual(len(t), CAP)
        full = [c for c, (t, st) in seen.items() if st["present"] and st["len"] == 4000]
        self.assertTrue(full)
        self.assertLess(max(full), min(hit))  # facts went (one by one) BEFORE any summary shortening
        # facts sections really were dropped during the sweep while the summary was still whole
        self.assertTrue(any(any(h not in t for h in self.non_user) for t, st in seen.values() if st["len"] == 4000))

    def test_ac90_summary_disappears_before_user_messages_are_dropped(self):
        seen = self.scan()
        vanished = [c for c, (t, st) in seen.items() if not st["present"]]
        self.assertTrue(vanished, "summary never vanished within the sweep")
        first = min(vanished)
        keep = [c for c in vanished if EIGHT[0] in seen[c][0]]
        if not keep:  # window narrower than the sweep step: refine around the first disappearance
            for c in range(max(first - 100, 0), first + 400, 10):
                t = self.run_c(c)
                st = self.check_invariants(c, t)
                if not st["present"] and EIGHT[0] in t:
                    keep.append(c)
        self.assertTrue(keep, "summary never vanished while `Last user messages` was kept")
        for c in keep:
            t = self.run_c(c)
            self.assertNotIn("## Fresh summary at compaction", t)
            self.assertNotIn(SUMMARY_FAIL, t)  # removed silently, not reported as a failure
            self.assertEqual([h for h in EIGHT if h in t], [EIGHT[0]])
            self.assertLessEqual(len(t), CAP)
            self.assertIn(AGENT_H, t)

    def test_ac90_last_user_messages_dropped_only_last(self):
        seen = self.scan(lo=self.LO_USERS, hi=self.HI_USERS, step=100)
        for c, (t, st) in seen.items():
            if EIGHT[0] not in t:
                self.assertFalse(st["present"], c)


# ---------------------------------------------------------------- AC 91 and 92
class NeverOld(F38):
    def test_ac91_old_heading_never_emitted_in_any_state(self):
        states = [("fresh-ok", self.fresh, {}), ("stale-ok", self.stale, {}), ("absent-ok", lambda: None, {}),
                  ("fresh-fail", self.fresh, {"rc": 3, "out": ""}), ("absent-fail", lambda: None, {"rc": 3, "out": ""}),
                  ("fresh-short", self.fresh, {"out": "short"})]
        for name, setup, kw in states:
            with self.subTest(name):
                shutil.rmtree(self.hd, ignore_errors=True)
                setup()
                t = self.go(**kw)
                self.no_old(t)
                self.assertNotIn("Haiku", t)
        for fb in ("0", "1"):
            shutil.rmtree(self.hd, ignore_errors=True)
            self.no_old(self.go(fallback=fb))

    def test_ac91_fault_fallback_section_in_summary_place(self):
        self.fresh()
        base = self.go()
        shutil.rmtree(self.hd)
        shutil.rmtree(self.shimdir)
        os.makedirs(self.shimdir)
        self.fresh()
        t = self.go(extra={"HANDOFF_TEST_FAULT": "fallback"})
        line = "(section fallback unavailable: RuntimeError)"
        self.assertEqual(t.split("\n").count(line), 1, t)
        self.assertNotIn("## Fresh summary at compaction", t)
        self.assertNotIn(SUMMARY_TEXT, t)
        self.order(t, AGENT_H, BODY.strip(), line, FACTS_H)
        self.assertTrue(t.index(AGENT_H) < t.index(line) < t.index(FACTS_H))
        # other sections intact
        footer = FOOTER_FMT.format(p=self.tpath)
        for h in [AGENT_H] + EIGHT + [FACTS_H]:
            a = (self.sec(base, h) or "").replace(footer, "").strip()
            b = (self.sec(t, h) or "").replace(line, "").replace(footer, "").strip()
            self.assertEqual(b, a, h)
        hl = self.health()
        self.assertEqual(hl["errors"], ["fallback"])
        self.assertEqual(hl["status"], "degraded")

    def test_ac91_fault_fallback_absent_agent_where_summary_would_be(self):
        t = self.go(extra={"HANDOFF_TEST_FAULT": "fallback"})
        line = "(section fallback unavailable: RuntimeError)"
        self.assertEqual(t.split("\n").count(line), 1, t)
        self.assertLess(t.index(line), t.index(FACTS_H))
        self.assertEqual(sec_names(t)[0], FACTS_H)

    def test_ac92_child_guard(self):
        self.install_shim(out=SUMMARY_TEXT)
        for setup in (self.fresh, self.stale, lambda: None):
            shutil.rmtree(self.hd, ignore_errors=True)
            setup()
            had = os.path.exists(self.hd)
            snapshot = sorted(os.listdir(self.hd)) if had else None
            r = self.run_pre(self.payload(), fallback=None, extra={"HANDOFF_HOOK_CHILD": "1"})
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
            self.assertFalse(self.shim_invoked())
            self.assertFalse(os.path.exists(os.path.join(self.hd, "S-latest.md")))
            self.assertFalse(os.path.exists(self.health_path()))
            self.assertEqual(sorted(os.listdir(self.hd)) if os.path.exists(self.hd) else None, snapshot)

    def test_ac92_health_field_order(self):
        for setup, kw in ((self.fresh, {}), (lambda: None, {"fallback": "0"}), (lambda: None, {"rc": 3, "out": ""})):
            shutil.rmtree(self.hd, ignore_errors=True)
            setup()
            self.go(**kw)
            keys = list(self.health().keys())
            i = keys.index("fallback")
            self.assertEqual(keys[i + 1], "summary_model", keys)
            self.assertEqual(keys.count("summary_model"), 1)

    def test_ac92_summary_model_types(self):
        self.go()
        self.assertIsInstance(self.health()["summary_model"], str)
        self.assertEqual(self.sidecar()["summary_model"], "sonnet")


if __name__ == "__main__":
    unittest.main()
