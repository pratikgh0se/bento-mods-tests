"""F35 handoff quality: ACs 31-48 of specs/handoff-hooks-spec.md "F35 additions" (fixtures per "F35 transcript shapes").
The hook scripts under test are located by HANDOFF_HOOKS_DIR (see helpers.py). Haiku fallback is disabled
(HANDOFF_HAIKU_FALLBACK=0, the helpers default) unless a test passes fallback="1" together with a `claude` shim.
F38 amendments: the Haiku section/line/argv/skip-when-fresh ACs are now the F38 fresh summary (SUMMARY_H, "Fresh summary failed")."""
import calendar, hashlib, json, os, re, time, unittest
from helpers import *

HEAD6 = ["Goal", "Decisions and why", "Done", "In progress", "Dead ends", "Exact next step"]
IP, NS = "In progress", "Exact next step"
NUDGE_T = "2026-10-16 10:32:00Z"
NUDGE_MS = calendar.timegm((2026, 10, 16, 10, 32, 0)) * 1000


def doc(o=None, omit=(), pad=0):
    base = {"Goal": "Ship F35.", "Decisions and why": "Hash section bodies.", "Done": "Spec approved.",
            "In progress": "Writing tests.", "Dead ends": "mtime only.", "Exact next step": "Run the suite."}
    base.update(o or {})
    out = ""
    for n in HEAD6:
        if n not in omit:
            out += "## %s\n%s\n\n" % (n, base[n])
    return out + ("P" * pad if pad else "")


def h12(text, name):
    lines = text.replace("\r\n", "\n").split("\n")
    try:
        i = lines.index("## " + name)
    except ValueError:
        return "absent"
    j = i + 1
    while j < len(lines) and not lines[j].startswith("## "):
        j += 1
    body = "\n".join(lines[i + 1:j]).rstrip()
    return hashlib.sha256(body.encode()).hexdigest()[:12]


def iso(sec):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(sec)) + ".000Z"


def utc(sec):
    return time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(sec))


def asst_ts(t, ts):
    d = asst(t)
    d["timestamp"] = ts
    return d


def tu(id_, name, inp, ts=None):
    d = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": id_, "name": name, "input": inp}]}}
    if ts:
        d["timestamp"] = ts
    return d


def tres(id_, content="", extra=None, is_error=False, ts=None):
    blk = {"type": "tool_result", "tool_use_id": id_, "content": content}
    if is_error:
        blk["is_error"] = True
    d = {"type": "user", "message": {"role": "user", "content": [blk]}}
    if extra is not None:
        d["toolUseResult"] = extra
    if ts:
        d["timestamp"] = ts
    return d


def ask(id_, qs):
    """AskUserQuestion tool_use; qs = [(question, header, [labels])]"""
    return tu(id_, "AskUserQuestion", {"questions": [
        {"question": q, "header": h, "options": [{"label": l, "description": "d"} for l in ls], "multiSelect": False}
        for q, h, ls in qs]})


def answer(id_, answers, notes=None):
    extra = {"questions": [], "answers": answers}
    if notes:
        extra["annotations"] = {q: {"notes": n} for q, n in notes.items()}
    text = "User has answered your questions: " + ", ".join('"%s"="%s"' % (q, a) for q, a in answers.items())
    return tres(id_, text, extra)


def notif(task_id, status="completed"):
    return user("<task-notification>\n<task-id>%s</task-id>\n<status>%s</status>\n</task-notification>" % (task_id, status))


def section(text, heading):
    """Body of one '## ' section (None when absent)."""
    i = text.find(heading + "\n")
    if i < 0:
        return None
    j = text.find("\n## ", i + len(heading))
    return text[i + len(heading) + 1: j if j >= 0 else len(text)]


class F35(HookCase):
    def put_agent(self, body, meta=None, mtime=None, age_min=0, raw_meta=None):
        a = self.agent_file(body, meta=meta, age_min=age_min, raw_meta=raw_meta)
        if mtime is not None:
            os.utime(a, (mtime, mtime))
        return os.path.getmtime(a)

    def invocations(self):
        p = os.path.join(self.shimdir, "invoked")
        return len(open(p).read().split()) if os.path.exists(p) else 0

    def text_with(self, entries, **kw):
        self.write_transcript(entries)
        return self.run_and_read(**kw)


# ---------------------------------------------------------------- Freshness v2 and staleness (AC 31-38)
class Staleness(F35):
    def setUp(self):
        super().setUp()
        self.body400 = "AGENTBODY " * 40

    def test_ac31_grace_boundary(self):
        m = self.put_agent(self.body400, age_min=1)
        m = float(int(m))
        os.utime(os.path.join(self.hd, "S-agent.md"), (m, m))
        t = self.text_with([user("late message", timestamp=iso(m + 11 * 60)), asst("ok")])
        w = warn_line(t)
        self.assertEqual(w, WARN_PFX + "file written %s is older than the last user message by more than 10 min" % utc(m))
        self.assertEqual(t.index(w) + len(w) + 1, t.index(AGENT_H))
        self.assertIn(self.body400.strip(), t)
        t = self.text_with([user("on the edge", timestamp=iso(m + 10 * 60)), asst("ok")])
        self.assertIsNone(warn_line(t))
        self.assertIn(AGENT_H, t)
        self.assertIn(self.body400.strip(), t)

    def test_ac32_no_timestamps_skips_grace(self):
        self.put_agent(self.body400, age_min=1)
        t = self.text_with([user("hello"), asst("ok")])
        self.assertIsNone(warn_line(t))
        self.assertIn(AGENT_H, t)

    def test_ac32_tool_results_and_noise_are_not_last_user_message(self):
        m = float(int(self.put_agent(self.body400, age_min=1)))
        os.utime(os.path.join(self.hd, "S-agent.md"), (m, m))
        far = iso(m + 3600)
        t = self.text_with([
            user("genuine", timestamp=iso(m)),
            tres("x1", "result text", {"k": 1}, ts=far),
            user("<system-reminder>noise", timestamp=far),
            user("<task-notification>x", timestamp=far),
            user("<artifact-content-authored-by-others/> y", timestamp=far),  # F40.3
            user("<bash-input>ls</bash-input>", timestamp=far),
            asst("ok")])
        self.assertIsNone(warn_line(t))
        self.assertIn(AGENT_H, t)

    def _stale_meta(self, **kw):
        m = {"agentWrittenAt": NUDGE_MS, "lastNudgeAt": NUDGE_MS, "stale_sections": [IP, NS]}
        m.update(kw)
        return m

    def test_ac33_order_with_shim(self):
        self.install_shim(out="HAIKU-TEXT " + "h" * 80)
        self.put_agent(self.body400, meta=self._stale_meta())
        self.write_transcript([user("hello"), asst("ok")])
        t = self.run_and_read(fallback="1")
        w = WARN_PFX + "In progress, Exact next step unchanged since " + NUDGE_T
        pos = [t.index(x) for x in (w, AGENT_H, self.body400.strip(), SUMMARY_H, "HAIKU-TEXT", FACTS_H)]
        self.assertEqual(pos, sorted(pos))
        self.assertEqual(len(set(pos)), 6)
        self.assertEqual(warn_line(t), w)
        self.assertEqual(t.index(w) + len(w) + 1, t.index(AGENT_H))
        self.assertEqual(self.invocations(), 1)

    def test_ac34_old_file_no_meta_with_shim(self):
        self.install_shim(out="HAIKU-TEXT " + "h" * 80)
        self.put_agent(self.body400, age_min=40)
        self.write_transcript([user("hello"), asst("ok")])
        t = self.run_and_read(fallback="1")
        self.assertIn("not updated since the last nudge", warn_line(t))
        self.assertTrue(t.index(AGENT_H) < t.index(SUMMARY_H) < t.index(FACTS_H))
        self.assertEqual(self.invocations(), 1)

    def test_ac34_twenty_minute_old_file_is_fresh(self):
        self.install_shim(out="HAIKU-TEXT " + "h" * 80)
        self.put_agent(self.body400, age_min=20)
        self.write_transcript([user("hello"), asst("ok")])
        t = self.run_and_read(fallback="1")
        self.assertIsNone(warn_line(t))
        self.assertIn(AGENT_H, t)
        # F38.1 amends F35.B "Haiku NOT invoked when fresh": the summary runs for a fresh agent file too
        self.assertTrue(t.index(AGENT_H) < t.index(SUMMARY_H) < t.index(FACTS_H))
        self.assertTrue(self.shim_invoked())

    def test_ac35_stale_with_fallback_disabled(self):
        self.install_shim(out="HAIKU-TEXT " + "h" * 80)
        self.put_agent(self.body400, meta=self._stale_meta())
        t = self.text_with([user("hello"), asst("ok")], fallback="0")
        self.assertIsNotNone(warn_line(t))
        self.assertIn(AGENT_H, t)
        self.assertFalse(self.shim_invoked())
        self.assertNotIn(SUMMARY_H, t)
        self.assertNotIn("Fresh summary failed", t)
        self.assertNotIn("## Model-written handoff (Haiku fallback", t)
        self.assertIn(FACTS_H, t)

    def test_ac35_byte_layout(self):
        self.install_shim(out="HAIKU-TEXT " + "h" * 80)
        self.put_agent(self.body400, meta=self._stale_meta())
        self.write_transcript([user("hello"), asst("ok")])
        t = self.run_and_read(fallback="1")
        w = warn_line(t)
        haiku = "HAIKU-TEXT " + "h" * 80
        want = "%s\n%s\n%s\n\n%s\n%s\n\n%s\n" % (w, AGENT_H, self.body400.strip(), SUMMARY_H, haiku, FACTS_H)
        self.assertIn(want, t)

    def test_ac36_shim_fails(self):
        self.install_shim(rc=3, out="")
        self.put_agent(self.body400, meta=self._stale_meta())
        self.write_transcript([user("hello"), asst("ok")])
        t = self.run_and_read(fallback="1")
        self.assertIsNotNone(warn_line(t))
        i, j, k = t.index(AGENT_H), t.index("Fresh summary failed: claude exited 3"), t.index(FACTS_H)
        self.assertTrue(i < j < k)
        self.assertNotIn(SUMMARY_H, t)

    def test_ac37_both_reasons_joined(self):
        m = float(int(self.put_agent(self.body400, meta=self._stale_meta(), age_min=1)))
        os.utime(os.path.join(self.hd, "S-agent.md"), (m, m))
        t = self.text_with([user("late", timestamp=iso(m + 11 * 60)), asst("ok")])
        a = "In progress, Exact next step unchanged since " + NUDGE_T
        b = "file written %s is older than the last user message by more than 10 min" % utc(m)
        self.assertEqual(warn_line(t), WARN_PFX + a + "; " + b)
        self.assertEqual(len([l for l in t.split("\n") if l.startswith(WARN_PFX)]), 1)

    def test_ac37_299_bytes_stale_meta_is_not_present(self):
        self.put_agent("B" * 299, meta=self._stale_meta())
        t = self.text_with([user("hello"), asst("ok")])
        self.assertNotIn(AGENT_H, t)
        self.assertIsNone(warn_line(t))

    def test_ac37_stale_meta_without_lastNudgeAt_uses_file_mtime(self):
        m = float(int(self.put_agent(self.body400, meta={"agentWrittenAt": 100, "stale_sections": [IP, NS]}, age_min=1)))
        os.utime(os.path.join(self.hd, "S-agent.md"), (m, m))
        t = self.text_with([user("hello"), asst("ok")])
        # section 4: agentWrittenAt present, lastNudgeAt absent -> rule is the existing one; reason (a) must still be named
        w = warn_line(t)
        self.assertIsNotNone(w)
        self.assertIn("In progress, Exact next step unchanged since " + utc(m), w)

    # ---- hookStale (AC 38)
    def _hook_stale_world(self, sections_ok=(True, True)):
        t0 = int(time.time()) - 3600
        text = doc({"Goal": "G" * 300})
        meta = {"agentWrittenAt": t0 * 1000, "lastNudgeAt": t0 * 1000,
                "sections": {IP: h12(text, IP) if sections_ok[0] else "0" * 12,
                             NS: h12(text, NS) if sections_ok[1] else "f" * 12}}
        self.put_agent(text, meta=meta)
        return t0

    def _entries_after(self, t0, users, tool_uses, untimed_tools=0, before_users=2):
        e = [user("before-%d" % i, timestamp=iso(t0 - 100 + i)) for i in range(before_users)]
        e += [tu("old%d" % i, "Bash", {"command": "ls"}, iso(t0 - 50 + i % 10)) for i in range(60)]  # before T0: not counted
        for i in range(users):
            e.append(user("after-%d" % i, timestamp=iso(t0 + 10 + i)))
        for i in range(tool_uses):
            e.append(tu("n%d" % i, "Bash", {"command": "echo %d" % i}, iso(t0 + 100 + i)))
        for i in range(untimed_tools):
            e.append(tu("u%d" % i, "Bash", {"command": "echo untimed"}))
        return e

    def test_ac38_three_user_messages_after_nudge(self):
        t0 = self._hook_stale_world()
        t = self.text_with(self._entries_after(t0, 3, 0))
        self.assertEqual(warn_line(t), WARN_PFX + "In progress, Exact next step unchanged since " + utc(t0))
        self.assertIn(AGENT_H, t)

    def test_ac38_two_users_and_39_tool_uses_no_warning(self):
        t0 = self._hook_stale_world()
        t = self.text_with(self._entries_after(t0, 2, 39))
        self.assertIsNone(warn_line(t))
        self.assertIn(AGENT_H, t)

    def test_ac38_40_tool_uses_warns(self):
        t0 = self._hook_stale_world()
        t = self.text_with(self._entries_after(t0, 0, 40))
        self.assertEqual(warn_line(t), WARN_PFX + "In progress, Exact next step unchanged since " + utc(t0))

    def test_ac38_untimed_entries_not_counted(self):
        t0 = self._hook_stale_world()
        t = self.text_with(self._entries_after(t0, 2, 39, untimed_tools=30))
        self.assertIsNone(warn_line(t))

    def test_ac38_only_one_hash_matches_no_warning(self):
        for ok in ((True, False), (False, True), (False, False)):
            t0 = self._hook_stale_world(ok)
            t = self.text_with(self._entries_after(t0, 5, 100))
            self.assertIsNone(warn_line(t), ok)

    def test_ac38_no_sections_or_no_lastNudgeAt_is_not_hookstale(self):
        t0 = int(time.time()) - 3600
        text = doc({"Goal": "G" * 300})
        hs = {IP: h12(text, IP), NS: h12(text, NS)}
        self.put_agent(text, meta={"agentWrittenAt": t0 * 1000, "lastNudgeAt": t0 * 1000})  # no sections
        self.assertIsNone(warn_line(self.text_with(self._entries_after(t0, 5, 100))))
        self.put_agent(text, raw_meta=json.dumps({"agentWrittenAt": t0 * 1000, "sections": hs}))  # no lastNudgeAt
        w = warn_line(self.text_with(self._entries_after(t0, 5, 100)))
        self.assertTrue(w is None or "unchanged since" not in w, w)


# ---------------------------------------------------------------- Size (AC 39; F39.6: cap 14,000, summary cap 4,000)
class Size(F35):
    def _facts_transcript(self, ntasks=0):
        e = [user(("U%02d" % i) + "u" * 300) for i in range(4)]
        e += [tool("Edit", file_path="/f/file%02d.py" % i) for i in range(6)]
        e += [tool("Bash", command="echo c%d" % i) for i in range(3)]
        e += [tool("TaskCreate", subject=("s%03d" % i) + "s" * 150) for i in range(ntasks)]
        e.append(asst("A" * 400))
        return e

    def test_ac39_facts_dropped_before_summary_shortened(self):
        # F38.5 amends F35.C ("Haiku shortened first"): whole facts sections go first, the summary stays whole
        self.install_shim(out="Y" * 4000)
        self.put_agent("L" * 5000, meta={"agentWrittenAt": 1})
        # calibrate: facts large enough that agent + 4000 summary chars exceed the cap but the no-summary file fits
        n, ref = self.fit(lambda n: self._facts_transcript(3 + n), 11500)  # F39.6: cap 14,000
        t = self.run_and_read(fallback="1")
        self.assertLessEqual(len(t), CAP)
        self.assertIn("L" * 5000, t)
        self.assertIsNotNone(warn_line(t))
        self.assertIn(SUMMARY_H, t)
        run = max(len(m) for m in re.findall(r"Y+", t))
        self.assertEqual(run, 4000)  # not shortened while facts sections could still be dropped
        self.assertLess(len(heads9(t)), len(heads9(ref)))  # some facts section was dropped instead
        gone = dropped37(t, heads9(ref))
        self.assertEqual(gone, [h for h in DROP37 if h in heads9(ref)][:len(gone)])  # F37.2 order
        self.assertTrue(t.rstrip().endswith(FOOTER_FMT.format(p=self.tpath)))

    def _tight_cwd(self):
        """cwd length (header only; nonexistent dir) so the no-summary file is ~13,900 chars: < 200 chars of summary fit."""
        self.write_transcript(self._facts_transcript())
        c0 = 1000
        t0 = self.run_and_read(fallback="0", cwd="/" + "d" * c0)
        c = c0 + (CAP - 100 - len(t0))
        cwd = "/" + "d" * c
        t = self.run_and_read(fallback="0", cwd=cwd)
        self.assertLessEqual(len(t), CAP)
        self.assertGreaterEqual(len(t), CAP - 200)
        return cwd

    def test_ac39_tight_file_summary_shortened_or_omitted_never_failure_line(self):
        # F38.5 amends F35.C: facts go first; the summary is then cut (ending `...`, >= 200 chars) or omitted entirely
        self.install_shim(out="Y" * 4000)
        self.put_agent("L" * 5000, meta={"agentWrittenAt": 1})
        cwd = self._tight_cwd()
        t = self.run_and_read(fallback="1", cwd=cwd)
        self.assertLessEqual(len(t), CAP)
        sec = section(t, SUMMARY_H)
        if sec is not None:
            self.assertTrue(sec.rstrip().endswith("..."))
            self.assertGreaterEqual(len(sec.rstrip()), 200)
        else:
            self.assertNotIn("Y" * 20, t)
        self.assertIn("L" * 5000, t)
        self.assertIsNotNone(warn_line(t))
        self.assertIn(AGENT_H, t)
        self.assertNotIn("Fresh summary failed", t)  # the shim succeeded; only the oversize text is cut
        self.assertTrue(t.rstrip().endswith(FOOTER_FMT.format(p=self.tpath)))

    def test_ac39_haiku_failure_line_is_kept_even_when_tight(self):
        self.install_shim(rc=3, out="")
        self.put_agent("L" * 5000, meta={"agentWrittenAt": 1})
        cwd = self._tight_cwd()
        t = self.run_and_read(fallback="1", cwd=cwd)
        self.assertLessEqual(len(t), CAP)
        self.assertIn("Fresh summary failed: claude exited 3", t)
        self.assertIn(AGENT_H, t)


# ---------------------------------------------------------------- Facts (AC 40-45)
class Decisions(F35):
    """F39.6 amends AC 40-45: `## Decisions via questions` is no longer emitted (the pairs now feed the F39.3 ledger
    merge, see test_f39_ledger.py for the ANSWER lines). Every AC 40/41 fixture is kept and now asserts absence."""

    def absent(self, entries):
        t = self.text_with(entries)
        self.assertNotIn(DECISIONS_H, t)
        return t

    def test_ac40_two_questions_answers_section_gone(self):
        qs = [("Which file name?", "Name", ["alpha", "beta"]), ("Which colour?", "Colour", ["red", "blue"])]
        t = self.absent([user("start the work"), ask("q1", qs),
                         answer("q1", {"Which file name?": "alpha", "Which colour?": "blue"}), asst("ok")])
        self.assertEqual(heads9(t)[0], EIGHT[0])
        last = section(t, "## Last user messages (oldest first)")
        self.assertIn("- start the work", last)
        self.assertNotIn("alpha", last)
        self.assertNotIn("blue", last)
        self.assertNotIn("User has answered", last)
        self.assertNotIn("- [Name] Which file name? -> alpha", t)

    def test_ac41_multiselect_notes_and_missing_header(self):
        e = [user("go"),
             tu("q1", "AskUserQuestion", {"questions": [
                 {"question": "Pick many", "header": "Many", "options": [{"label": "A"}, {"label": "B"}], "multiSelect": True},
                 {"question": "No header here", "options": [{"label": "x"}]}]}),
             answer("q1", {"Pick many": ["A", "B"], "No header here": "x"}, notes={"Pick many": "because reasons"}),
             asst("ok")]
        t = self.absent(e)
        self.assertNotIn("because reasons", t)

    def test_ac41_truncation_fixture(self):
        q, a, n = "Q" * 250, "A" * 250, "N" * 250
        t = self.absent([user("go"), ask("q1", [(q, "H", ["x"])]), answer("q1", {q: a}, notes={q: n}), asst("ok")])
        self.assertNotIn("Q" * 100, t)

    def test_ac41_twelve_pairs_no_section(self):
        e = [user("go")]
        for i in range(12):
            q = "Question %02d?" % i
            e += [ask("q%d" % i, [(q, "H%02d" % i, ["x"])]), answer("q%d" % i, {q: "ans%02d" % i})]
        e.append(asst("ok"))
        t = self.absent(e)
        self.assertNotIn("ans11", t)

    def test_ac41_unanswered_and_errored_no_section(self):
        e = [user("go"),
             ask("e1", [("Errored?", "E", ["x"])]), tres("e1", "rejected by user", is_error=True),
             ask("n1", [("Never answered?", "N", ["x"])]),
             ask("k1", [("Kept?", "K", ["x"])]), answer("k1", {"Kept?": "yes"}), asst("ok")]
        t = self.absent(e)
        self.assertNotIn("Errored?", t)

    def test_ac41_result_text_pattern_fixture(self):
        e = [user("go"), ask("q1", [("Pick one?", "P", ["a", "b"]), ("And two?", "T", ["c"])]),
             tres("q1", 'User has answered your questions: "Pick one?"="b", "And two?"="c". You can now continue.'),
             asst("ok")]
        t = self.absent(e)
        self.assertNotIn("Pick one?", t)

    def test_ac41_no_notes_marker(self):
        e = [user("go"), ask("q1", [("Alpha?", "A", ["x"])]), answer("q1", {"Alpha?": "x"}), asst("ok")]
        t = self.absent(e)
        self.assertNotIn("(notes:", t)


class OpenTasks(F35):
    def _tasks(self, completed=()):
        e = [user("go"), tool("TaskCreate", subject="s1"), tool("TaskCreate", subject="s2"), tool("TaskCreate", subject="s3")]
        for i in completed:
            e.append(tool("TaskUpdate", taskId=str(i), status="completed"))
        e.append(asst("ok"))
        return e

    def test_ac42_open_tasks_exclude_completed(self):
        t = self.text_with(self._tasks([2]))
        op = section(t, "## Open tasks")
        self.assertIsNotNone(op)
        self.assertEqual([l for l in op.split("\n") if l.strip()], ["- [pending] s1", "- [pending] s3"])
        ts = section(t, "## Task state")
        for s in ("s1", "s2", "s3"):
            self.assertIn(s, ts)
        self.assertIn("- [completed] s2", ts)

    def test_ac42_all_completed_no_section(self):
        t = self.text_with(self._tasks([1, 2, 3]))
        self.assertNotIn("## Open tasks", t)
        self.assertIn("## Task state", t)
        self.assertIn("- [completed] s1", section(t, "## Task state"))

    def test_ac43_todowrite_last_call_replaces(self):
        first = [{"content": "OLD item", "status": "pending", "activeForm": "x"}]
        second = [{"content": "Pending item", "status": "pending", "activeForm": "x"},
                  {"content": "Doing item", "status": "in_progress", "activeForm": "x"},
                  {"content": "Finished item", "status": "completed", "activeForm": "x"}]
        t = self.text_with([user("go"), tool("TodoWrite", todos=first), tool("TodoWrite", todos=second), asst("ok")])
        op = section(t, "## Open tasks")
        self.assertEqual([l for l in op.split("\n") if l.strip()], ["- [pending] Pending item", "- [in_progress] Doing item"])
        self.assertNotIn("OLD item", t)

    def test_ac43_cap_20_lines_plus_more(self):
        todos = [{"content": "item %02d" % i, "status": "pending", "activeForm": "x"} for i in range(25)]
        t = self.text_with([user("go"), tool("TodoWrite", todos=todos), asst("ok")])
        lines = [l for l in section(t, "## Open tasks").split("\n") if l.strip()]
        self.assertEqual(len(lines), 21)
        self.assertEqual(lines[0], "- [pending] item 00")
        self.assertEqual(lines[19], "- [pending] item 19")
        self.assertEqual(lines[20], "- ... +5 more")

    def test_ac43_content_cut_at_150(self):
        todos = [{"content": "c" * 300, "status": "pending", "activeForm": "x"}]
        t = self.text_with([user("go"), tool("TodoWrite", todos=todos), asst("ok")])
        self.assertIn("- [pending] " + "c" * 147 + "...", section(t, "## Open tasks"))

    def test_ac43_all_todos_completed_no_section(self):
        todos = [{"content": "done", "status": "completed", "activeForm": "x"}]
        t = self.text_with([user("go"), tool("TodoWrite", todos=todos), asst("ok")])
        self.assertNotIn("## Open tasks", t)

    def test_ac43_task_state_lines_come_before_todo_lines(self):
        todos = [{"content": "todo-item", "status": "pending", "activeForm": "x"}]
        t = self.text_with([user("go"), tool("TaskCreate", subject="task-item"), tool("TodoWrite", todos=todos), asst("ok")])
        op = section(t, "## Open tasks")
        self.assertLess(op.index("task-item"), op.index("todo-item"))


class BackgroundAgents(F35):
    def _launch(self, id_, desc, aid, model=None, bg=True, prompt="SECRET-PROMPT-TEXT", name="Agent", **extra):
        inp = {"description": desc, "prompt": prompt + " " + id_, "subagent_type": "general-purpose"}
        if model:
            inp["model"] = model
        if bg is not None:
            inp["run_in_background"] = bg
        inp.update(extra)
        res = tres(id_, "Async agent launched successfully.\nagentId: %s (internal ID)" % aid,
                   {"agentId": aid, "isAsync": True, "description": desc, "resolvedModel": model or "x",
                    "status": "async_launched", "outputFile": "/tmp/out"}) if bg else tres(id_, "foreground result")
        return [tu(id_, name, inp), res]

    def test_ac44_finished_agent_is_dropped(self):
        e = [user("go")]
        e += self._launch("tA", "D1 research", "agent-id-one-7f3", model="haiku")
        e += self._launch("tB", "D2 build", "agent-id-two-9c1")
        e += [notif("agent-id-one-7f3"), asst("ok")]
        t = self.text_with(e)
        sec = section(t, "## Background agents")
        self.assertEqual([l for l in sec.split("\n") if l.strip()], ["- D2 build (model: default)"])
        for bad in ("SECRET-PROMPT-TEXT", "agent-id-one-7f3", "agent-id-two-9c1", "general-purpose", "D1 research"):
            self.assertNotIn(bad, t)

    NOTE = "<task-notification>\n<task-id>%s</task-id>\n<status>%s</status>\n</task-notification>"

    def test_ac44_completion_in_attachment_and_queue_operation_lines(self):
        # spec amendment: completion lines may be of ANY type (mostly attachment / queue-operation, some user)
        e = [user("go")]
        e += self._launch("tA", "done via attachment", "agent-id-att")
        e += self._launch("tB", "done via queue", "agent-id-que")
        e += self._launch("tC", "done via user", "agent-id-usr")
        e += self._launch("tD", "still open", "agent-id-opn")
        e += [{"type": "attachment", "attachment": {"type": "queued_command", "prompt": self.NOTE % ("agent-id-att", "completed")}},
              {"type": "queue-operation", "operation": "enqueue", "content": self.NOTE % ("agent-id-que", "completed")},
              notif("agent-id-usr"), asst("ok")]
        t = self.text_with(e)
        self.assertEqual([l for l in section(t, "## Background agents").split("\n") if l.strip()],
                         ["- still open (model: default)"])

    def test_ac44_failed_status_in_queue_operation_finishes(self):
        e = [user("go")] + self._launch("tA", "dies", "agent-id-die")
        e += [{"type": "queue-operation", "operation": "enqueue", "content": self.NOTE % ("agent-id-die", "failed")}, asst("ok")]
        self.assertNotIn("## Background agents", self.text_with(e))

    def test_ac44_attachment_completion_before_launch_does_not_count(self):
        e = [user("go"), {"type": "attachment", "attachment": {"prompt": self.NOTE % ("agent-id-x", "completed")}}]
        e += self._launch("tA", "launched later", "agent-id-x") + [asst("ok")]
        self.assertIn("launched later", self.text_with(e))

    def test_ac44_attachment_lines_never_become_user_messages(self):
        e = [user("real msg"), {"type": "attachment", "attachment": {"prompt": self.NOTE % ("zz", "completed")}},
             {"type": "queue-operation", "operation": "enqueue", "content": "queued text QOP"}, asst("ok")]
        t = self.text_with(e)
        self.assertIn("- real msg", t)
        self.assertNotIn("QOP", t)

    def test_ac44_model_shown(self):
        e = [user("go")] + self._launch("tA", "D1 research", "agent-id-one-7f3", model="haiku") + [asst("ok")]
        t = self.text_with(e)
        self.assertEqual([l for l in section(t, "## Background agents").split("\n") if l.strip()],
                         ["- D1 research (model: haiku)"])

    def test_ac44_foreground_never_listed(self):
        e = [user("go")]
        e += self._launch("tF", "Foreground one", "agent-id-fg", bg=None)
        e += self._launch("tG", "Foreground two", "agent-id-fg2", bg=False)
        e.append(asst("ok"))
        t = self.text_with(e)
        self.assertNotIn("## Background agents", t)
        self.assertNotIn("Foreground", t)

    def test_ac44_failed_and_killed_also_finish(self):
        e = [user("go")]
        e += self._launch("tA", "will fail", "agent-id-f1")
        e += self._launch("tB", "will be killed", "agent-id-k1")
        e += self._launch("tC", "still running", "agent-id-r1")
        e += [notif("agent-id-f1", "failed"), notif("agent-id-k1", "killed"), asst("ok")]
        t = self.text_with(e)
        self.assertEqual([l for l in section(t, "## Background agents").split("\n") if l.strip()],
                         ["- still running (model: default)"])

    def test_ac44_notification_before_launch_does_not_finish(self):
        e = [user("go"), notif("agent-id-one-7f3")] + self._launch("tA", "later launch", "agent-id-one-7f3") + [asst("ok")]
        t = self.text_with(e)
        self.assertIn("- later launch (model: default)", section(t, "## Background agents"))

    def test_ac44_task_tool_with_subagent_type_counts(self):
        e = [user("go")] + self._launch("tA", "via Task tool", "agent-id-t1", name="Task") + [asst("ok")]
        t = self.text_with(e)
        self.assertIn("- via Task tool (model: default)", section(t, "## Background agents"))

    def test_ac44_no_id_found_matches_by_description(self):
        def no_id(id_, desc):
            return [tu(id_, "Agent", {"description": desc, "prompt": "p", "subagent_type": "x", "run_in_background": True}),
                    tres(id_, "launched, no identifier here")]
        e = [user("go")] + no_id("tA", "Unlisted by description") + no_id("tB", "Open by description") + \
            [user("<task-notification>\n<status>completed</status>\nUnlisted by description finished\n</task-notification>"),
             asst("ok")]
        t = self.text_with(e)
        self.assertEqual([l for l in section(t, "## Background agents").split("\n") if l.strip()],
                         ["- Open by description (model: default)"])

    def test_ac44_all_finished_no_section_and_max_10(self):
        e = [user("go")] + self._launch("tA", "gone", "agent-id-g1") + [notif("agent-id-g1"), asst("ok")]
        self.assertNotIn("## Background agents", self.text_with(e))
        e = [user("go")]
        for i in range(13):
            e += self._launch("t%d" % i, "bg job %02d" % i, "agent-id-%02d" % i)
        e.append(asst("ok"))
        t = self.text_with(e)
        lines = [l for l in section(t, "## Background agents").split("\n") if l.strip()]
        self.assertEqual(len(lines), 10)
        self.assertTrue(lines[0].startswith("- bg job 00"))

    def test_ac44_description_cut_at_100(self):
        e = [user("go")] + self._launch("tA", "d" * 150, "agent-id-d1") + [asst("ok")]
        t = self.text_with(e)
        self.assertIn("- " + "d" * 97 + "... (model: default)", section(t, "## Background agents"))


# ---------------------------------------------------------------- Order and trim (AC 45)
class OrderAndTrim(F35):
    def _repo(self):
        from test_content import git
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        git(repo, "init", "-q")
        open(os.path.join(repo, "dirty.txt"), "w").write("x")
        return repo

    def _rich(self, pad=0, path_len=100, ntasks=0):
        qs = [("Which name?", "Name", ["alpha", "beta"])]
        e = [user(("U%02d" % i) + "u" * pad) for i in range(8)]
        e += [ask("q1", qs), answer("q1", {"Which name?": "alpha"})]
        e += [tool("Edit", file_path="/" + ("p%02d" % i) + "d" * path_len) for i in range(30)]
        e += [tool("TaskCreate", subject="s" * 150), tool("TaskCreate", subject="t" * 150)]
        e += [tool("TaskCreate", subject=("n%03d" % i) + "q" * 150) for i in range(ntasks)]
        e += [tool("TodoWrite", todos=[{"content": "todo " + "z" * 140, "status": "pending", "activeForm": "x"}])]
        e += [tool("Bash", command=("c%d" % i) + "x" * pad) for i in range(5)]
        e += [tu("bg1", "Agent", {"description": "background job", "prompt": "p", "subagent_type": "g", "run_in_background": True}),
              tres("bg1", "agentId: bgid1", {"agentId": "bgid1", "isAsync": True})]
        e.append(asst("A" * (pad + 50)))
        return e

    def test_ac45_all_eight_sections_in_order(self):
        repo = self._repo()
        self.write_transcript(self._rich(pad=40))
        t = self.run_and_read(cwd=repo)
        pos = [t.index(h) for h in EIGHT]
        self.assertEqual(pos, sorted(pos))
        self.assertEqual(heads9(t), EIGHT)
        self.assertNotIn(DECISIONS_H, t)  # F39.6

    def _drop_order_ok(self, t):
        """F37.2 order: dropped sections must be a prefix of DROP37 (Last user messages last of all)."""
        present = [h in t for h in DROP37]
        seen = False
        for p in present:
            if p:
                seen = True
            elif seen:
                return False, present
        return True, present

    def test_ac45_trim_order_new_three_last(self):
        # F37.2 supersedes F35.D: Files touched first, Last user messages last (F39.6: no Decisions via questions).
        repo = self._repo()
        for pad, plen, nt in ((700, 100, 130), (1000, 250, 400)):
            self.write_transcript(self._rich(pad=pad, path_len=plen, ntasks=nt))
            t = self.run_and_read(cwd=repo)
            self.assertLessEqual(len(t), CAP)
            ok, present = self._drop_order_ok(t)
            self.assertTrue(ok, present)
            self.assertFalse(present[0], "pressure expected: first-dropped section (Files touched) should be gone")
            self.assertTrue(present[-1], "Last user messages must outlive everything else")
            self.assertNotIn(DECISIONS_H, t)
            self.assertTrue(t.rstrip().endswith(FOOTER_FMT.format(p=self.tpath)))

    def test_ac45_six_old_sections_keep_relative_order(self):
        repo = self._repo()
        self.write_transcript(self._rich(pad=40))
        t = self.run_and_read(cwd=repo)
        pos = [t.index(h) for h in SECTIONS]
        self.assertEqual(pos, sorted(pos))


# ---------------------------------------------------------------- Unchanged behaviour (AC 47)
class Unchanged(F35):
    STALE = {"agentWrittenAt": 1, "lastNudgeAt": 1, "stale_sections": [IP, NS]}

    def _big(self):
        e = [user(("U%02d" % i) + "u" * 700) for i in range(8)]
        e += [ask("q1", [("Which?", "H", ["a"])]), answer("q1", {"Which?": "a"})]
        e += [tool("Edit", file_path="/" + "d" * 200 + str(i)) for i in range(30)]
        e.append(asst("A" * 2000))
        return e

    def test_ac47_exit_and_silence_with_f35_fixtures(self):
        self.put_agent_ = self.agent_file("L" * 6000, meta=self.STALE)
        self.write_transcript(self._big())
        for raw in (json.dumps(self.payload()), "{}", "garbage", ""):
            r = self.run_pre(raw=raw)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""), raw)

    def test_ac47_child_guard_with_stale_file(self):
        self.install_shim(out="x" * 100)
        self.agent_file("L" * 400, meta=self.STALE)
        self.write_transcript(self._big())
        r = self.run_pre(self.payload(), fallback="1", extra={"HANDOFF_HOOK_CHILD": "1"})
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertFalse(self.shim_invoked())
        self.assertFalse(os.path.exists(os.path.join(self.hd, "S-latest.md")))

    def test_ac47_header_and_footer(self):
        self.agent_file("L" * 400, meta=self.STALE)
        self.write_transcript(self._big())
        t = self.run_and_read(cwd=self.tmp)
        lines = t.rstrip("\n").split("\n")
        self.assertEqual(lines[0], "# Handoff (pre-compaction)")
        self.assertEqual(lines[-1], FOOTER_FMT.format(p=self.tpath))

    def test_ac47_cleanup_still_runs(self):
        os.makedirs(self.hd)
        old = os.path.join(self.hd, "x-agent.md")
        open(old, "w").write("x")
        t = time.time() - 15 * 86400
        os.utime(old, (t, t))
        self.agent_file("L" * 400, meta=self.STALE)
        self.write_transcript(self._big())
        self.run_pre(self.payload("S"))
        self.assertFalse(os.path.exists(old))

    def test_ac47_inject_of_stale_lead_file(self):
        self.agent_file("L" * 6000, meta=self.STALE)
        self.write_transcript(self._big())
        r = self.run_pre(self.payload("S"))
        self.assertEqual(r.returncode, 0)
        content = self.latest("S")
        self.assertIsNotNone(warn_line(content))
        p = self.run_post({"session_id": "S"})
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        ctx = json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"]
        full = "Pre-compaction handoff (auto-saved):\n" + content.strip()
        if len(full) < 10000:
            self.assertTrue(ctx.endswith(full))  # F36: degraded prefix allowed
        else:  # F37.3: inline cut; the inlined part is a prefix of the content and the continuation line ends it
            self.assertIn("Pre-compaction handoff (auto-saved):\n" + content.strip()[:200], ctx)
            self.assertTrue(ctx.rstrip().split("\n")[-1].startswith("[Handoff continues in "))
        self.assertLess(len(ctx), 10000)


# ---------------------------------------------------------------- Robustness (AC 48)
class Robustness(F35):
    def assert_clean(self, payload=None):
        r = self.run_pre(payload or self.payload())
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        return self.latest()

    def test_ac48_invalid_timestamps(self):
        self.agent_file("B" * 400, age_min=1)
        for bad in ("not-a-date", "", 12345, None, [], {"a": 1}, "2026-13-45T99:99:99Z"):
            self.write_transcript([user("hello", timestamp=bad), asst("ok")])
            t = self.assert_clean()
            self.assertIn(AGENT_H, t, bad)
            self.assertIsNone(warn_line(t), bad)  # no parseable timestamp: grace skipped

    def test_ac48_non_array_stale_sections_is_absent(self):
        self.write_transcript([user("hello"), asst("ok")])
        for bad in ("In progress", {"a": 1}, 5, None, True):
            self.agent_file("B" * 400, meta={"agentWrittenAt": 100, "lastNudgeAt": 100, "stale_sections": bad})
            t = self.assert_clean()
            self.assertIn(AGENT_H, t, bad)
            self.assertIsNone(warn_line(t), bad)

    def test_ac48_non_string_members_are_absent(self):
        self.write_transcript([user("hello"), asst("ok")])
        self.agent_file("B" * 400, meta={"agentWrittenAt": 100, "lastNudgeAt": 100, "stale_sections": [1, None, {"a": 1}]})
        t = self.assert_clean()
        self.assertIn(AGENT_H, t)
        self.assertIsNone(warn_line(t))

    def test_ac48_non_string_section_hashes(self):
        t0 = int(time.time()) - 3600
        self.agent_file(doc({"Goal": "G" * 300}), meta={"agentWrittenAt": t0 * 1000, "lastNudgeAt": t0 * 1000,
                                                  "sections": {IP: 5, NS: ["x"]}, "prevSections": "junk",
                                                  "lastUserMsgAt": "soon"})
        e = [user("m%d" % i, timestamp=iso(t0 + 10 + i)) for i in range(5)]
        self.write_transcript(e)
        t = self.assert_clean()
        self.assertIn(AGENT_H, t)
        self.assertIsNone(warn_line(t))

    def test_ac48_sections_not_an_object(self):
        t0 = int(time.time()) - 3600
        for bad in ("x", 5, [1, 2], None):
            self.agent_file(doc({"Goal": "G" * 300}), meta={"agentWrittenAt": t0 * 1000, "lastNudgeAt": t0 * 1000, "sections": bad})
            self.write_transcript([user("m%d" % i, timestamp=iso(t0 + 10 + i)) for i in range(5)])
            t = self.assert_clean()
            self.assertIn(AGENT_H, t, bad)
            self.assertIsNone(warn_line(t), bad)

    def test_ac48_toolUseResult_shapes(self):
        for bad in (None, "just a string", ["a"], 5, {"answers": "nope"}, {"answers": ["x"]}, {"answers": {"Q?": {"x": 1}}}):
            r = tres("q1", "no pattern here")
            if bad is not None:
                r["toolUseResult"] = bad
            self.write_transcript([user("go"), ask("q1", [("Q?", "H", ["a"])]), r, asst("ok")])
            t = self.assert_clean()
            self.assertNotIn("## Decisions via questions", t, bad)
            self.assertIn("- go", t)

    def test_ac48_questions_not_a_list(self):
        for bad in ("a string", {"question": "Q?"}, None, 7, [None, 5, "x", {"question": 5}]):
            self.write_transcript([user("go"), tu("q1", "AskUserQuestion", {"questions": bad}),
                                   tres("q1", '"Q?"="a"', {"answers": {"Q?": "a"}}), asst("ok")])
            t = self.assert_clean()
            self.assertNotIn("- Q? -> a", t, bad)
            self.assertIn("- go", t)

    def test_ac48_input_not_an_object(self):
        for bad in (None, "str", [1], 5):
            self.write_transcript([user("go"), {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "q1", "name": "AskUserQuestion", "input": bad},
                {"type": "tool_use", "id": "b1", "name": "Agent", "input": bad},
                {"type": "tool_use", "id": "t1", "name": "TodoWrite", "input": bad}]}}, asst("ok")])
            t = self.assert_clean()
            self.assertIn("- go", t)

    def test_ac48_todos_not_a_list(self):
        for bad in ("x", {"a": 1}, None, 3, [None, "x", {"status": "pending"}, {"content": 5}]):
            self.write_transcript([user("go"), tool("TodoWrite", todos=bad), asst("ok")])
            t = self.assert_clean()
            self.assertIn("- go", t)

    def test_ac48_truncated_jsonl_lines(self):
        e = [user("before"), ask("q1", [("Cut?", "H", ["a"])])]
        self.write_transcript(e, extra_lines=[
            json.dumps(answer("q1", {"Cut?": "a"}))[:60],            # truncated answer line: question stays unanswered
            '{"type":"user","message":{"content":"<task-notif',
            json.dumps(tu("b1", "Agent", {"description": "cut", "run_in_background": True}))[:40],
            json.dumps(user("after"))])
        t = self.assert_clean()
        self.assertIn("- before", t)
        self.assertIn("- after", t)
        self.assertNotIn("## Decisions via questions", t)

    def test_ac48_run_in_background_non_bool(self):
        for bad in ("true", 1, None, [], {}):
            self.write_transcript([user("go"), tu("b1", "Agent", {"description": "d", "run_in_background": bad}),
                                   tres("b1", "agentId: x1", {"agentId": "x1"}), asst("ok")])
            t = self.assert_clean()
            self.assertIn("- go", t)


if __name__ == "__main__":
    unittest.main()
