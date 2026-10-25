"""F39 project decisions ledger: ACs 93-110 of specs/handoff-hooks-spec.md "F39".
Black-box (temp HOME, `claude` shim on PATH). The shim (helpers.py) tells the merge call from the summary call by the
`--system-prompt` value; merge knobs are `set_shim("merge", ...)`, summary knobs are the legacy ones. Both the ledger and
the summary are ENABLED unless a test says otherwise (LEDGER_ENV = None: no HANDOFF_LEDGER in the env)."""
import calendar, glob, hashlib, json, os, re, shutil, subprocess, sys, time, unittest
from helpers import *
from test_content import git
import test_f35 as f35

LEAN = ("Keep the ledger lean: when a new decision changes, narrows or repeats an older one, rewrite the older entry "
        "as SUPERSEDED by the new id (because: replaced, narrowed or merged). Two active entries must never say the "
        "same thing or contradict each other.")
KEEP = ("When you merge or narrow entries, keep every concrete value from both (names, numbers, paths, limits, "
        "schedules).")  # F39.11
MERGE_SYSTEM = "You maintain a project's decisions ledger for an AI coding agent. Output only the ledger."
MERGE_PROMPT = (
    "Stdin has the CURRENT LEDGER, then NEW CONVERSATION since it was last updated. Output the complete updated "
    "ledger in exactly the same format. Rules: keep every existing entry and its id. Add an entry only for a decision "
    "the user made or explicitly approved (a choice, a rule, a constraint, a permission, a rejected option), dated "
    "with the day it was made. When the user replaces an earlier decision, rewrite that entry as SUPERSEDED by the new "
    "id with the reason; never delete entries. Do not record plans, progress or the assistant's own unapproved "
    "proposals. Format of active lines: \"- D<n> [YYYY-MM-DD] <decision> | why: <reason>\". Format of superseded "
    "lines: \"- D<n> [YYYY-MM-DD] SUPERSEDED by D<m> [YYYY-MM-DD]: <old decision> | because: <reason>\". "
    + LEAN + " " + KEEP)
LEDGER_KEYS = ["ledger", "ledger_active", "ledger_superseded", "ledger_restored", "ledger_chars"]
SUMMARY_PROMPT_BITS = ('prefixed "unverified:"', "under 3500 chars")
STANDING = "STANDING DECISIONS (do not contradict"
SUMMARY_TEXT = "SUMMARY-F39 " + "s" * 288
BODY = "AGENTBODY " * 40

L1 = "- D1 [2026-10-25] Use SQLite for storage | why: simple deploy"
L2 = "- D2 [2026-10-25] Never touch the legacy directory | why: user rule"
LEDGER2 = L1 + "\n" + L2 + "\n"
SEED3 = ["- D1 [2026-10-20] Use tabs | why: style", "- D2 [2026-10-21] Keep API v1 | why: compat",
         "- D3 [2026-10-22] No new deps | why: size"]
SUP_RE = re.compile(r"^- D(\d+) \[\d{4}-\d\d-\d\d\] SUPERSEDED by D(\d+) \[\d{4}-\d\d-\d\d\]: .* \| because: .*$")
ACT_RE = re.compile(r"^- D(\d+) \[\d{4}-\d\d-\d\d\] (?!SUPERSEDED).* \| why: .*$")
TRAILER_RE = re.compile(r"^- \((\d+) older active decisions in the full ledger\)$")
BASE = calendar.timegm((2026, 10, 25, 10, 0, 0))


def ts(n):
    return f35.iso(BASE + n * 60)


def key_for(root):
    return re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(root))[:40] + "-" + hashlib.sha1(root.encode()).hexdigest()[:8]


def parse_ts(s):
    """ISO timestamp -> epoch ms (accepts Z / +00:00, optional fraction)."""
    m = re.match(r"^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d+))?(?:Z|\+00:00)?$", s)
    assert m, s
    sec = calendar.timegm(tuple(int(x) for x in m.groups()[:6]))
    return sec * 1000 + int((m.group(7) or "0")[:3].ljust(3, "0"))


def asst_ts(t, when):
    return f35.asst_ts(t, when)


def ask_ts(id_, qs, when):
    d = f35.ask(id_, qs)
    d["timestamp"] = when
    return d


def answer_ts(id_, answers, when, notes=None):
    d = f35.answer(id_, answers, notes=notes)
    d["timestamp"] = when
    return d


def ledger_line(n, width=200, day=20):
    head = "- D%d [2026-10-%02d] " % (n, day)
    tail = " | why: r"
    return head + "x" * (width - len(head) - len(tail)) + tail


class F39(HookCase):
    LEDGER_ENV = None  # ledger enabled

    def setUp(self):
        super().setUp()
        self.rt = os.path.realpath(self.tmp)
        self.repo_root = os.path.join(self.rt, "repo")
        self.cwd = os.path.join(self.repo_root, "sub")
        os.makedirs(self.cwd)
        git(self.repo_root, "init", "-q")
        self.install_shim(out=SUMMARY_TEXT)
        self.set_shim("merge", out=LEDGER2)
        self.write_transcript(self.convo())

    # ---------------------------------------------------------------- fixtures
    def convo(self, start=0, tag="", qid="q1"):
        t = lambda n: ts(start + n)
        q = "Which database engine?"
        return [user("DECISION-A%s: use SQLite for storage" % tag, timestamp=t(0)),
                asst_ts("ack", t(1)),
                ask_ts(qid, [(q, "DB", ["sqlite", "postgres"])], t(2)),
                answer_ts(qid, {q: "sqlite"}, t(3)),
                asst_ts("H" * 1500 + "T" * 1500, t(4)),
                user("DECISION-B%s: never touch the legacy dir" % tag, timestamp=t(5))]

    def pdir(self, root=None):
        return os.path.join(self.hd, "projects", key_for(root or self.repo_root))

    def projects(self):
        p = os.path.join(self.hd, "projects")
        return sorted(os.listdir(p)) if os.path.isdir(p) else []

    def seed(self, lines, root=None, state=True, last_ts=None):
        root = root or self.repo_root
        d = self.pdir(root)
        os.makedirs(d, exist_ok=True)
        text = "# Project decisions: %s\n%s\n" % (root, "\n".join(lines))
        with open(os.path.join(d, "decisions.md"), "w") as f:
            f.write(text)
        if state:
            with open(os.path.join(d, "decisions.state.json"), "w") as f:
                json.dump({"v": 1, "root": root, "updatedAt": int(time.time() * 1000), "lastSid": "S",
                           "lastEntryTs": last_ts or ts(-60)}, f)
        return d, text

    def ledger_text(self, root=None):
        return open(os.path.join(self.pdir(root), "decisions.md")).read()

    def ledger_lines(self, root=None):
        return [l for l in self.ledger_text(root).split("\n") if l.startswith("- D")]

    def state(self, root=None):
        return json.load(open(os.path.join(self.pdir(root), "decisions.state.json")))

    def backups(self, root=None):
        d = self.pdir(root)
        if not os.path.isdir(d):
            return []
        return sorted(n for n in os.listdir(d) if re.match(r"^decisions\.\d{8}T\d{6}Z\.md$", n))

    def go(self, sid="S", cwd=None, extra=None, fallback=None, payload=None):
        p = payload if payload is not None else self.payload(sid, cwd=cwd or self.cwd)
        r = self.run_pre(p, fallback=fallback, extra=extra)
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        return r

    def go_text(self, **kw):
        self.go(**kw)
        return self.latest(kw.get("sid", "S"))

    def fresh_agent(self, body=BODY):
        self.agent_file(body, age_min=1)

    def conv_part(self, stdin):
        return stdin.split("NEW CONVERSATION:\n", 1)[1]

    def proj_section(self, t):
        """(heading line, entry/trailer lines) of the `## Project decisions` section, or (None, [])."""
        lines = t.split("\n")
        for i, l in enumerate(lines):
            if l.startswith(PROJECT_H_PFX):
                j = i + 1
                body = []
                while j < len(lines) and not lines[j].startswith("## ") and not lines[j].startswith("Full transcript:"):
                    if lines[j].strip():
                        body.append(lines[j])
                    j += 1
                return l, body
        return None, []

    def ids(self, lines):
        return [int(re.match(r"^- D(\d+) ", l).group(1)) for l in lines]


# ---------------------------------------------------------------- AC 93
class ProjectKey(F39):
    def test_git_root_and_subdir_share_the_key(self):
        self.go(sid="S", cwd=self.repo_root)
        self.go(sid="S2", cwd=self.cwd)
        want = "repo-" + hashlib.sha1(self.repo_root.encode()).hexdigest()[:8]
        self.assertEqual(self.projects(), [want])
        self.assertTrue(re.match(r"^repo-[0-9a-f]{8}$", want))
        self.assertTrue(os.path.isfile(os.path.join(self.hd, "projects", want, "decisions.md")))

    def test_subdir_alone_uses_the_repo_root(self):
        self.go(cwd=self.cwd)
        self.assertEqual(self.projects(), [key_for(self.repo_root)])
        self.assertEqual(self.ledger_text().split("\n")[0], "# Project decisions: " + self.repo_root)

    def test_non_git_cwd_uses_the_cwd_itself(self):
        d = os.path.join(self.rt, "my proj@v1")
        os.makedirs(d)
        self.go(cwd=d)
        self.assertEqual(self.projects(), [key_for(d)])
        self.assertTrue(self.projects()[0].startswith("my_proj_v1-"))
        self.assertEqual(self.ledger_text(d).split("\n")[0], "# Project decisions: " + d)

    def test_basename_cut_to_40_chars(self):
        d = os.path.join(self.rt, "n" * 50)
        os.makedirs(d)
        self.go(cwd=d)
        self.assertEqual(self.projects(), ["n" * 40 + "-" + hashlib.sha1(d.encode()).hexdigest()[:8]])

    def test_same_basename_different_roots_different_keys(self):
        roots = []
        for side in ("a", "b"):
            r = os.path.join(self.rt, side, "proj")
            os.makedirs(r)
            git(r, "init", "-q")
            roots.append(r)
            self.go(sid="S" + side, cwd=r)
        keys = self.projects()
        self.assertEqual(len(keys), 2, keys)
        self.assertEqual(sorted(key_for(r) for r in roots), keys)
        self.assertTrue(all(k.startswith("proj-") for k in keys))


# ---------------------------------------------------------------- AC 94 (+ F39.1-F39.3 details)
class FirstMerge(F39):
    def test_ac94_first_compaction_writes_ledger_state_and_health(self):
        self.go()
        self.assertEqual(self.ledger_text().split("\n")[0], "# Project decisions: " + self.repo_root)
        self.assertEqual(self.ledger_lines(), [L1, L2])
        st = self.state()
        self.assertEqual(st["v"], 1)
        self.assertEqual(st["root"], self.repo_root)
        self.assertEqual(st["lastSid"], "S")
        self.assertEqual(parse_ts(st["lastEntryTs"]), parse_ts(ts(5)))
        self.assertIsInstance(st["updatedAt"], int)
        self.assertLess(abs(st["updatedAt"] - time.time() * 1000), 60000)
        h = self.health()
        self.assertEqual((h["ledger"], h["ledger_active"]), ("ok", 2))

    def test_ledger_dir_has_lock_and_no_stray_files(self):
        self.go()
        names = set(os.listdir(self.pdir()))
        self.assertIn("decisions.md", names)
        self.assertIn("decisions.state.json", names)
        self.assertEqual([n for n in names if n.endswith(".tmp") or ".tmp" in n], [])

    def test_non_ledger_model_lines_are_ignored(self):
        self.set_shim("merge", out="Here is the updated ledger:\n# Project decisions: whatever\n" + L1 + "\n\nnote: done\n" + L2 + "\nThanks!\n")
        self.go()
        self.assertEqual(self.ledger_lines(), [L1, L2])
        txt = self.ledger_text()
        for junk in ("Here is the updated", "note: done", "Thanks!", "whatever"):
            self.assertNotIn(junk, txt)

    def test_superseded_form_is_parsed(self):
        sup = "- D1 [2026-10-20] SUPERSEDED by D2 [2026-10-25]: Use tabs | because: user switched"
        new = "- D2 [2026-10-25] Use spaces | why: user said so"
        self.set_shim("merge", out=sup + "\n" + new + "\n")
        self.go()
        self.assertEqual(self.ledger_lines(), [sup, new])

    def test_summary_switch_does_not_disable_the_ledger(self):
        for fb, extra in (("0", None), (None, {"HANDOFF_SUMMARY": "0"})):
            shutil.rmtree(self.hd, ignore_errors=True)
            shutil.rmtree(self.shimdir)
            os.makedirs(self.shimdir)
            self.install_shim(out=SUMMARY_TEXT)
            self.set_shim("merge", out=LEDGER2)
            self.go(fallback=fb, extra=extra)
            self.assertFalse(self.shim_invoked(), (fb, extra))
            self.assertEqual(self.merge_calls(), 1, (fb, extra))
            self.assertEqual(self.ledger_lines(), [L1, L2])
            self.assertEqual(self.health()["ledger"], "ok")

    def test_merge_argv_is_the_f38_argv_with_ledger_prompts(self):
        self.go()
        want = ["-p", "--model", "sonnet", "--output-format", "text", "--no-session-persistence", "--setting-sources", "",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands", "--tools", "",
                "--system-prompt", MERGE_SYSTEM, MERGE_PROMPT]
        self.assertEqual(self.merge_argv(), want)

    def test_merge_model_override(self):
        self.go(extra={"HANDOFF_LEDGER_MODEL": "haiku"})
        self.assertEqual(self.merge_argv()[2], "haiku")
        self.assertEqual(self.shim_argv()[2], "sonnet")  # the summary keeps its own model
        shutil.rmtree(self.hd)
        shutil.rmtree(self.shimdir)
        os.makedirs(self.shimdir)
        self.install_shim(out=SUMMARY_TEXT)
        self.set_shim("merge", out=LEDGER2)
        self.go(extra={"HANDOFF_LEDGER_MODEL": "bad model;"})
        self.assertEqual(self.merge_argv()[2], "sonnet")

    def test_merge_child_env(self):
        self.go(extra={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "123"})
        env = self.shim_file("merge.env").split("\n")
        self.assertIn("HANDOFF_HOOK_CHILD=1", env)
        self.assertFalse([l for l in env if l.startswith("CLAUDE_CODE_AUTO_COMPACT_WINDOW")], env)

    def test_ac115_long_line_kept_at_700_why_cut_first(self):
        # F39.11: cap 700; parse first, cut the why text first, then the decision text; form always preserved
        line = "- D1 [2026-10-25] " + "d" * 900 + " | why: " + "w" * 300
        self.set_shim("merge", out=line + "\n" + L2 + "\n")
        self.go()
        got = [l for l in self.ledger_lines() if l.startswith("- D1 ")]
        self.assertEqual(len(got), 1, self.ledger_lines())
        self.assertLessEqual(len(got[0]), 700)
        self.assertGreater(len(got[0]), 600)  # cut to fit, not dropped or cut to 400
        self.assertRegex(got[0], ACT_RE.pattern)
        self.assertNotIn("w" * 300, got[0])
        self.assertTrue(got[0].endswith("..."))
        dec = re.match(r"^- D1 \[[^\]]+\] (.*) \| why: (.*)$", got[0])
        self.assertIsNotNone(dec, got[0])
        if "d" * 900 not in dec.group(1):  # decision text was cut: the why text must already be gone
            self.assertLessEqual(len(dec.group(2)), 3, dec.group(2))
            self.assertTrue(dec.group(1).endswith("..."))
        self.assertEqual(self.health()["ledger"], "ok")

    def test_ac115_long_why_cut_decision_kept(self):
        line = "- D1 [2026-10-25] " + "d" * 300 + " | why: " + "w" * 900
        self.set_shim("merge", out=line + "\n" + L2 + "\n")
        self.go()
        got = [l for l in self.ledger_lines() if l.startswith("- D1 ")][0]
        self.assertLessEqual(len(got), 700)
        self.assertIn("d" * 300, got)
        self.assertRegex(got, ACT_RE.pattern)
        self.assertTrue(got.endswith("..."))
        self.assertGreater(len(got), 600)

    def test_ac115_line_between_400_and_700_kept_whole(self):
        line = "- D1 [2026-10-25] " + "d" * 400 + " | why: " + "w" * 150
        self.set_shim("merge", out=line + "\n" + L2 + "\n")
        self.go()
        self.assertIn(line, self.ledger_lines())

    def test_ac115_long_superseded_line_keeps_its_form(self):
        sup = "- D1 [2026-10-20] SUPERSEDED by D2 [2026-10-25]: " + "o" * 900 + " | because: " + "b" * 300
        new = "- D2 [2026-10-25] Use spaces | why: user said so"
        self.set_shim("merge", out=sup + "\n" + new + "\n")
        self.go()
        got = [l for l in self.ledger_lines() if l.startswith("- D1 ")][0]
        self.assertLessEqual(len(got), 700)
        self.assertRegex(got, SUP_RE.pattern)
        self.assertEqual(self.health()["ledger_superseded"], 1)


# ---------------------------------------------------------------- AC 95
class MergeInput(F39):
    def test_first_merge_stdin_shape(self):
        self.go()
        s = self.merge_stdin()
        self.assertTrue(s.startswith("CURRENT LEDGER:\n(empty)\n\nNEW CONVERSATION:\n"), s[:120])
        self.assertRegex(s, r"(?m)^USER \S+: DECISION-A: use SQLite for storage$")
        self.assertRegex(s, r"(?m)^USER \S+: DECISION-B: never touch the legacy dir$")
        self.assertRegex(s, r"(?m)^ANSWER \S+: Which database engine\? -> sqlite$")
        self.assertEqual(self.merge_calls(), 1)

    def test_timestamps_are_the_transcript_iso_instants(self):
        self.go()
        for n in (0, 5, 3):
            m = re.search(r"(?m)^(?:USER|ANSWER) (\S+): ", self.merge_stdin())
            self.assertTrue(parse_ts(m.group(1)) >= parse_ts(ts(0)))
        users = re.findall(r"(?m)^USER (\S+): ", self.merge_stdin())
        self.assertEqual([parse_ts(u) for u in users], [parse_ts(ts(0)), parse_ts(ts(5))])

    def test_preceding_assistant_text_cut_to_last_1500(self):
        self.go()
        s = self.merge_stdin()
        self.assertIn("ASSISTANT: " + "T" * 1500, s)
        self.assertNotIn("H" * 10, s)
        self.assertLess(s.index("ASSISTANT: "), s.index("DECISION-B"))

    def test_user_message_cut_to_4000(self):
        e = self.convo()
        e.append(user("U" * 6000, timestamp=ts(6)))
        self.write_transcript(e)
        self.go()
        runs = [len(m) for m in re.findall(r"U{50,}", self.merge_stdin())]
        self.assertEqual(len(runs), 1, runs)
        self.assertTrue(3997 <= runs[0] <= 4000, runs)

    def test_answer_notes_multiselect_and_unanswered(self):
        e = [user("go", timestamp=ts(0)),
             ask_ts("m1", [("Pick many?", "M", ["A", "B"])], ts(1)),
             answer_ts("m1", {"Pick many?": ["A", "B"]}, ts(2), notes={"Pick many?": "because reasons"}),
             ask_ts("e1", [("Errored?", "E", ["x"])], ts(3)),
             f35.tres("e1", "rejected by user", is_error=True, ts=ts(4)),
             ask_ts("n1", [("Never answered?", "N", ["x"])], ts(5)),
             user("stop", timestamp=ts(6))]
        self.write_transcript(e)
        self.go()
        s = self.merge_stdin()
        self.assertRegex(s, r"(?m)^ANSWER \S+: Pick many\? -> A, B \(notes: because reasons\)$")
        self.assertNotIn("Errored?", s)
        self.assertNotIn("Never answered?", s)

    def test_noise_and_tool_results_are_not_user_items(self):
        e = [user("<system-reminder>NOISE-1", timestamp=ts(0)), user("meta-text", isMeta=True, timestamp=ts(1)),
             f35.tu("t1", "Read", {"file_path": "/x"}, ts=ts(2)), f35.tres("t1", "TOOLRESULT-SECRET", ts=ts(3)),
             user("REAL-ONE", timestamp=ts(4))]
        self.write_transcript(e)
        self.go()
        s = self.merge_stdin()
        for bad in ("NOISE-1", "meta-text", "TOOLRESULT-SECRET"):
            self.assertNotIn(bad, s)
        self.assertRegex(s, r"(?m)^USER \S+: REAL-ONE$")

    def test_second_compaction_merges_only_newer_entries(self):
        self.set_shim("merge", out=LEDGER2, nth=1)
        self.set_shim("merge", out=LEDGER2 + "- D3 [2026-10-25] Second batch rule | why: later\n", nth=2)
        self.go()
        self.write_transcript(self.convo() + self.convo(start=30, tag="-2", qid="q2"))
        self.go()
        self.assertEqual(self.merge_calls(), 2)
        s = self.merge_stdin(2)
        cur = s.split("\n\nNEW CONVERSATION:\n", 1)[0]
        self.assertTrue(cur.startswith("CURRENT LEDGER:\n"))
        self.assertIn(L1, cur)
        self.assertIn(L2, cur)
        new = self.conv_part(s)
        self.assertIn("DECISION-A-2: use SQLite", new)
        self.assertIn("DECISION-B-2: never touch", new)
        for old in ("DECISION-A: use SQLite", "DECISION-B: never touch"):
            self.assertNotIn(old, new)
        self.assertEqual(len(re.findall(r"(?m)^ANSWER ", new)), 1)
        self.assertEqual(self.ledger_lines()[-1], "- D3 [2026-10-25] Second batch rule | why: later")
        self.assertEqual(parse_ts(self.state()["lastEntryTs"]), parse_ts(ts(35)))

    def test_merge_input_fits_60000_dropping_whole_items_from_the_start(self):
        e = [user(("M%02d " % i) + "u" * 3900, timestamp=ts(i)) for i in range(30)]  # ~117,000 chars
        self.write_transcript(e)
        self.go()
        new = self.conv_part(self.merge_stdin())
        self.assertLessEqual(len(new), 60000)
        self.assertGreater(len(new), 50000)
        self.assertIn("M29 ", new)
        self.assertNotIn("M00 ", new)
        first = new.split("\n")[0]
        self.assertRegex(first, r"^USER \S+: M\d\d u")  # a whole item, starting at its own prefix


# ---------------------------------------------------------------- AC 96
class Validation(F39):
    def test_missing_ids_restored_verbatim_and_new_id_added(self):
        self.seed(SEED3)
        d4 = "- D4 [2026-10-25] Ship Friday | why: deadline"
        self.set_shim("merge", out=SEED3[0] + "\n" + d4 + "\n")
        self.go()
        lines = self.ledger_lines()
        self.assertEqual(self.ids(lines), [1, 2, 3, 4])
        self.assertEqual(lines, SEED3 + [d4])
        h = self.health()
        self.assertEqual((h["ledger"], h["ledger_restored"], h["ledger_active"]), ("ok", 2, 4))

    def test_superseded_entry_cannot_become_active(self):
        seed = ["- D1 [2026-10-20] Use tabs | why: style",
                "- D2 [2026-10-21] SUPERSEDED by D3 [2026-10-22]: Keep API v1 | because: v2 shipped",
                "- D3 [2026-10-22] Use API v2 | why: shipped"]
        self.seed(seed)
        d4 = "- D4 [2026-10-25] Ship Friday | why: deadline"
        self.set_shim("merge", out="\n".join([seed[0], "- D2 [2026-10-21] Keep API v1 | why: compat", seed[2], d4]) + "\n")
        self.go()
        lines = self.ledger_lines()
        self.assertEqual(lines, seed + [d4])
        h = self.health()
        self.assertEqual((h["ledger_active"], h["ledger_superseded"]), (3, 1))

    def test_new_entry_with_an_id_not_above_the_previous_max_is_discarded(self):
        seed = [SEED3[0], SEED3[2]]  # D1, D3 (D2 never existed)
        self.seed(seed)
        bogus = "- D2 [2026-10-25] Sneaky late id | why: none"
        d4 = "- D4 [2026-10-25] Ship Friday | why: deadline"
        self.set_shim("merge", out="\n".join([seed[0], bogus, seed[1], d4]) + "\n")
        self.go()
        lines = self.ledger_lines()
        self.assertEqual(self.ids(lines), [1, 3, 4])
        self.assertNotIn("Sneaky", self.ledger_text())

    def test_garbage_output_keeps_ledger_and_backups(self):
        d, text = self.seed(SEED3)
        before = self.backups()
        self.set_shim("merge", out="I am sorry, I cannot produce a ledger.\nNothing to see here.\n")
        self.go()
        self.assertEqual(open(os.path.join(d, "decisions.md")).read(), text)
        self.assertEqual(self.backups(), before)
        self.assertEqual(self.health()["ledger"], "failed")

    def test_ids_in_result_are_in_id_order(self):
        self.seed(SEED3)
        self.set_shim("merge", out="- D5 [2026-10-25] Five | why: a\n" + SEED3[2] + "\n- D4 [2026-10-25] Four | why: b\n" + SEED3[1] + "\n" + SEED3[0] + "\n")
        self.go()
        lines = self.ledger_lines()
        self.assertEqual(self.ids(lines), sorted(self.ids(lines)))
        self.assertEqual(self.ids(lines), [1, 2, 3, 4, 5])


# ---------------------------------------------------------------- AC 97
class MergeFailures(F39):
    def check_unchanged(self, d, text, seeded_state):
        self.assertEqual(open(os.path.join(d, "decisions.md")).read(), text)
        self.assertEqual(json.load(open(os.path.join(d, "decisions.state.json")))["lastEntryTs"], seeded_state)
        self.assertEqual(self.backups(), [])
        self.assertEqual(self.health()["ledger"], "failed")
        t = self.latest()
        self.assertIn(AGENT_H, t)
        self.assertIn(FACTS_H, t)
        self.assertTrue(t.rstrip().endswith(FOOTER_FMT.format(p=self.tpath)))
        self.assertEqual(self.health()["status"], "ok")  # the ledger outcome never changes status

    def test_merge_exit_1(self):
        self.fresh_agent()
        d, text = self.seed(SEED3)
        self.set_shim("merge", out=LEDGER2, rc=1)
        self.go()
        self.check_unchanged(d, text, ts(-60))

    def test_merge_timeout(self):
        self.fresh_agent()
        d, text = self.seed(SEED3)
        self.set_shim("merge", sleepx=10)
        t0 = time.time()
        self.go(extra={"HANDOFF_SUMMARY_TIMEOUT": "2"})
        dt = time.time() - t0
        self.assertLess(dt, 8, dt)
        self.check_unchanged(d, text, ts(-60))

    def test_merge_failure_with_no_previous_ledger_still_writes_handoff(self):
        self.fresh_agent()
        self.set_shim("merge", out=LEDGER2, rc=1)
        self.go()
        h = self.health()
        self.assertEqual(h["ledger"], "failed")
        self.assertEqual(h["status"], "ok")
        self.assertIn(AGENT_H, self.latest())
        self.assertNotIn(PROJECT_H_PFX, self.latest())

    def test_merge_and_summary_run_concurrently(self):
        # both calls sleep 3 s: sequential would need > 6 s, concurrent ~3 s (spec: within timeout + 5 s)
        self.set_shim("merge", sleep=3)
        self.set_shim("summary", sleep=3)
        t0 = time.time()
        self.go()
        dt = time.time() - t0
        self.assertLess(dt, 5.8, dt)
        self.assertEqual(self.health()["ledger"], "ok")
        self.assertEqual(self.health()["fallback"], "ok")


# ---------------------------------------------------------------- AC 98
class EmptyInput(F39):
    def test_nothing_newer_than_last_entry_ts_means_no_call(self):
        d, text = self.seed(SEED3, last_ts=ts(5))  # the newest entry of the default transcript
        self.go()
        self.assertEqual(self.merge_calls(), 0)
        self.assertEqual(self.health()["ledger"], "unchanged")
        self.assertEqual(open(os.path.join(d, "decisions.md")).read(), text)
        self.assertEqual(self.backups(), [])

    def test_second_run_on_the_same_transcript_is_unchanged(self):
        self.go()
        self.assertEqual(self.merge_calls(), 1)
        before = self.ledger_text()
        self.go()
        self.assertEqual(self.merge_calls(), 1)
        self.assertEqual(self.health()["ledger"], "unchanged")
        self.assertEqual(self.ledger_text(), before)
        self.assertTrue(self.shim_invoked())  # the summary still runs


# ---------------------------------------------------------------- AC 99
class Locked(F39):
    def test_lock_held_by_another_process(self):
        d, text = self.seed(SEED3)
        lock = os.path.join(d, "decisions.lock")
        code = ("import fcntl,sys,time\nf=open(sys.argv[1],'a+')\nfcntl.flock(f,fcntl.LOCK_EX)\n"
                "print('held',flush=True)\ntime.sleep(15)\n")
        holder = subprocess.Popen([sys.executable, "-c", code, lock], stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        self.set_shim("merge", out=LEDGER2)
        t0 = time.time()
        self.go()
        dt = time.time() - t0
        self.assertLess(dt, 14, dt)  # waits at most 10 s for the lock, then skips
        self.assertEqual(self.health()["ledger"], "locked")
        self.assertEqual(open(os.path.join(d, "decisions.md")).read(), text)
        self.assertEqual(self.backups(), [])
        self.assertIn(FACTS_H, self.latest())


# ---------------------------------------------------------------- AC 100
class Disabled(F39):
    def test_ledger_0_does_nothing(self):
        r = self.go(extra={"HANDOFF_LEDGER": "0"})
        self.assertFalse(os.path.exists(os.path.join(self.hd, "projects")))
        self.assertEqual(self.merge_calls(), 0)
        t = self.latest()
        self.assertNotIn("## Project decisions", t)
        self.assertEqual(self.health()["ledger"], "disabled")
        self.assertTrue(self.shim_invoked())  # the summary is a separate switch

    def test_ledger_0_leaves_an_existing_ledger_alone_and_out_of_the_handoff(self):
        d, text = self.seed(SEED3)
        mt = os.path.getmtime(os.path.join(d, "decisions.md"))
        names = sorted(os.listdir(d))
        self.go(extra={"HANDOFF_LEDGER": "0"})
        self.assertNotIn("## Project decisions", self.latest())
        self.assertEqual(self.merge_calls(), 0)
        self.assertEqual(open(os.path.join(d, "decisions.md")).read(), text)
        self.assertEqual(os.path.getmtime(os.path.join(d, "decisions.md")), mt)
        self.assertEqual(sorted(os.listdir(d)), names)
        self.assertEqual(self.health()["ledger"], "disabled")

    def test_ledger_0_no_inject_output(self):
        self.seed(SEED3)
        r = self.run_post({"cwd": self.cwd, "session_id": "N"}, extra={"HANDOFF_LEDGER": "0"}, args=("--ledger",))
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_only_exact_zero_disables(self):
        for v in ("1", "", "false"):
            shutil.rmtree(self.hd, ignore_errors=True)
            self.go(extra={"HANDOFF_LEDGER": v})
            self.assertEqual(self.health()["ledger"], "ok", repr(v))


# ---------------------------------------------------------------- AC 101 (amended by F39.10: no section in latest.md) and 112
class Layout(F39):
    SEED = ["- D1 [2026-10-20] Use tabs | why: style",
            "- D2 [2026-10-21] SUPERSEDED by D3 [2026-10-22]: Keep API v1 | because: v2 shipped",
            "- D3 [2026-10-22] Use API v2 | why: shipped",
            "- D4 [2026-10-23] No new deps | why: size"]

    def test_ac101_order_header_authority_agent_summary_facts(self):
        self.fresh_agent()
        self.seed(self.SEED)
        self.set_shim("merge", out="\n".join(self.SEED) + "\n")
        t = self.go_text()
        lines = t.split("\n")
        self.assertEqual(lines[0], "# Handoff (pre-compaction)")
        self.assertEqual(lines.count(AUTHORITY), 1)
        ai = lines.index(AUTHORITY)
        self.assertTrue(all(l.startswith("- ") for l in lines[1:ai]), lines[:ai])
        self.assertEqual(lines[ai + 1], "")
        names = sec_names(t)
        self.assertEqual(names[:3], [AGENT_H, SUMMARY_H, FACTS_H])
        self.assertEqual(t.index(AUTHORITY) < t.index(AGENT_H), True)

    def test_ac112_no_project_decisions_section_in_latest_md(self):
        for seeded in (False, True):
            shutil.rmtree(self.hd, ignore_errors=True)
            if seeded:
                self.seed(self.SEED)
                self.set_shim("merge", out="\n".join(self.SEED) + "\n")
            t = self.go_text()
            self.assertNotIn("## Project decisions", t, seeded)
            self.assertNotIn("Project decisions (active", t, seeded)
            self.assertEqual(t.split("\n").count(AUTHORITY), 1, seeded)
            for l in self.SEED:
                self.assertNotIn(l, t)

    def test_ac112_no_section_with_stale_agent_or_when_cap_pressed(self):
        self.agent_file(BODY, meta={"agentWrittenAt": 1})
        seed = [ledger_line(n, 200) for n in range(1, 61)]
        self.seed(seed)
        self.set_shim("merge", out="\n".join(seed) + "\n")
        t = self.go_text()
        self.assertNotIn("## Project decisions", t)
        self.assertNotIn(ledger_line(60, 200), t)
        self.assertIsNotNone(warn_line(t))
        self.assertIn(AUTHORITY, t)
        # cap pressure does not bring it back and the cap holds
        self.agent_file("L" * 5000, age_min=1)
        e = [user(("U%02d" % i) + "u" * 300, timestamp=ts(i)) for i in range(4)]
        e += [tool("Edit", file_path="/f/file%02d.py" % i) for i in range(6)]
        e += [tool("TaskCreate", subject=("s%03d" % i) + "s" * 150) for i in range(400)]
        e.append(asst("A" * 400))
        self.write_transcript(e)
        t = self.go_text()
        self.assertLessEqual(len(t), CAP)
        self.assertNotIn("## Project decisions", t)
        self.assertIn(AUTHORITY, t)


# ---------------------------------------------------------------- AC 103
class ShorterHandoff(F39):
    def test_ac103_cap_14000_no_decisions_via_questions_f38_5_order(self):
        self.fresh_agent("L" * 5000)
        e = [user(("U%02d" % i) + "u" * 300, timestamp=ts(i)) for i in range(4)]
        e += [ask_ts("q1", [("Which?", "W", ["a"])], ts(5)), answer_ts("q1", {"Which?": "a"}, ts(6))]
        e += [tool("Edit", file_path="/f/file%02d.py" % i) for i in range(6)]
        e += [tool("Bash", command="echo c%d" % i) for i in range(3)]
        e += [tool("TaskCreate", subject=("s%03d" % i) + "s" * 150) for i in range(400)]
        e.append(asst("A" * 400))
        self.write_transcript(e)
        self.set_shim("summary", out="Y" * 9000)
        t = self.go_text(cwd=self.repo_root)
        self.assertLessEqual(len(t), CAP)
        self.assertGreater(len(t), 8000)  # whole-section drops leave slack; the cap really was the limit, not the fixture
        self.assertNotIn(DECISIONS_H, t)
        self.assertTrue(self.health()["truncated"])
        gone = [h for h in DROP37 if h not in t]
        self.assertEqual(gone, DROP37[:len(gone)])  # F37.2 / F38.5 prefix order
        sec = f35.section(t, SUMMARY_H)
        if sec is not None:
            self.assertLessEqual(len(sec.rstrip("\n")), 4000)
        self.assertIn(EIGHT[0], t)

    def test_ac103_decisions_via_questions_never_appears_even_with_answers(self):
        t = self.go_text()
        self.assertNotIn(DECISIONS_H, t)
        self.assertNotIn("- [DB] Which database engine? -> sqlite", t)

    def test_ac103_summary_cap_is_4000(self):
        self.fresh_agent()
        self.set_shim("summary", out="X" * 9000)
        t = self.go_text()
        body = f35.section(t, SUMMARY_H).rstrip("\n")
        self.assertEqual(body, "X" * 3997 + "...")


# ---------------------------------------------------------------- AC 104
class SummaryInput(F39):
    def test_ac104_standing_decisions_none(self):
        self.set_shim("merge", rc=1)
        self.go()
        s = self.summary_stdin()
        self.assertTrue(s.startswith(STANDING), s[:100])
        self.assertTrue(s.startswith(STANDING + "; if the conversation conflicts, say so under Decisions):\n(none)\n\nCONVERSATION:\n"), s[:260])

    def test_ac104_standing_decisions_lists_active_lines_only(self):
        seed = Layout.SEED
        self.seed(seed)
        self.set_shim("merge", out="\n".join(seed) + "\n")
        self.go()
        s = self.summary_stdin()
        head, conv = s.split("\nCONVERSATION:\n", 1)
        self.assertTrue(head.startswith(STANDING))
        for l in (seed[0], seed[2], seed[3]):
            self.assertIn(l, head)
        self.assertNotIn("SUPERSEDED", head)
        self.assertNotIn("(none)", head)
        self.assertIn("USER: DECISION-A", conv)

    def test_ac104_tool_outcomes(self):
        e = [user("go", timestamp=ts(0)),
             f35.tu("b1", "Bash", {"command": "make build"}, ts=ts(1)),
             f35.tres("b1", "boom: build failed\nsecond line of output", is_error=True, ts=ts(2)),
             f35.tu("b2", "Bash", {"command": "echo fine"}, ts=ts(3)),
             f35.tres("b2", "fine-output-text", ts=ts(4)),
             f35.tu("b3", "Bash", {"command": "sleep 99"}, ts=ts(5)),
             user("done?", timestamp=ts(6))]
        self.write_transcript(e)
        self.go()
        s = self.summary_stdin()
        lines = s.split("\n")
        # a tool-only assistant message may carry the `ASSISTANT: ` prefix (same latitude as the F38 AC 85 tests)
        got = [re.sub(r"^ASSISTANT: ", "", l) for l in lines]
        self.assertIn("[tool Bash: make build] -> error: boom: build failed", got)
        self.assertIn("[tool Bash: echo fine] -> ok", got)
        self.assertIn("[tool Bash: sleep 99] -> no result", got)
        self.assertNotIn("second line of output", s)
        self.assertNotIn("fine-output-text", s)

    def test_ac104_error_first_line_cut_to_200(self):
        e = [user("go", timestamp=ts(0)), f35.tu("b1", "Bash", {"command": "x"}, ts=ts(1)),
             f35.tres("b1", "e" * 300 + "\nmore", is_error=True, ts=ts(2)), user("next", timestamp=ts(3))]
        self.write_transcript(e)
        self.go()
        m = re.search(r"\[tool Bash: x\] -> error: (e+)(?:\.\.\.)?$", self.summary_stdin(), re.M)
        self.assertIsNotNone(m)
        self.assertTrue(197 <= len(m.group(1)) <= 200, len(m.group(1)))

    def test_ac104_prompt_text(self):
        self.go()
        last = self.shim_argv()[-1]
        for bit in SUMMARY_PROMPT_BITS:
            self.assertIn(bit, last)
        self.assertIn("Under Done list only work confirmed by a tool result", last)
        self.assertNotIn("under 5000 chars", last)
        self.assertLess(last.index('prefixed "unverified:"'), last.index("under 3500 chars"))

    def test_ac104_whole_stdin_bounded_by_120000(self):
        e = [user(("%03d" % i) + "x" * 3990, timestamp=ts(i)) if i % 2 == 0 else asst_ts(("%03d" % i) + "y" * 3990, ts(i))
             for i in range(60)]
        self.write_transcript(e)
        self.go()
        s = self.summary_stdin()
        self.assertLessEqual(len(s), 120000)
        self.assertGreater(len(s), 110000)
        self.assertTrue(s.startswith(STANDING))


# ---------------------------------------------------------------- AC 105
class Backups(F39):
    def test_each_success_writes_one_backup_with_the_previous_ledger(self):
        d, text = self.seed(SEED3)
        d4 = "- D4 [2026-10-25] Ship Friday | why: deadline"
        self.set_shim("merge", out="\n".join(SEED3 + [d4]) + "\n", nth=1)
        self.go()
        b1 = self.backups()
        self.assertEqual(len(b1), 1)
        self.assertEqual(open(os.path.join(d, b1[0])).read(), text)
        time.sleep(1.2)  # backup names carry a one-second timestamp
        text2 = self.ledger_text()
        self.write_transcript(self.convo() + self.convo(start=30, tag="-2", qid="q2"))
        self.set_shim("merge", out="\n".join(SEED3 + [d4, "- D5 [2026-10-25] More | why: x"]) + "\n", nth=2)
        self.go()
        b2 = self.backups()
        self.assertEqual(len(b2), 2)
        new = [b for b in b2 if b not in b1]
        self.assertEqual(len(new), 1)
        self.assertEqual(open(os.path.join(d, new[0])).read(), text2)
        self.assertEqual(self.health()["ledger"], "ok")

    def test_at_most_20_backups_oldest_pruned(self):
        d, text = self.seed(SEED3)
        old = ["decisions.20200101T%06dZ.md" % n for n in range(20)]
        for n in old:
            open(os.path.join(d, n), "w").write("old backup " + n)
        self.set_shim("merge", out="\n".join(SEED3 + ["- D4 [2026-10-25] Ship Friday | why: deadline"]) + "\n")
        self.go()
        b = self.backups()
        self.assertEqual(len(b), 20, b)
        self.assertNotIn(old[0], b)
        self.assertTrue(all(o in b for o in old[1:]))
        new = [x for x in b if x not in old]
        self.assertEqual(len(new), 1)
        self.assertEqual(open(os.path.join(d, new[0])).read(), text)

    def test_failed_update_writes_no_backup(self):
        d, text = self.seed(SEED3)
        self.set_shim("merge", out=LEDGER2, rc=1)
        self.go()
        self.assertEqual(self.backups(), [])


# ---------------------------------------------------------------- AC 106
class InjectLedger(F39):
    HEAD_RE = re.compile(r"^Project decisions from earlier sessions in this repo \(newest first; full ledger: (/.+decisions\.md)\)\. "
                         r"Treat them as standing unless the user says otherwise:$")

    def inject(self, cwd=None, payload=None, extra=None):
        r = self.run_post(payload or {"cwd": cwd or self.cwd, "session_id": "N", "hook_event_name": "SessionStart",
                                      "source": "startup"}, extra=extra, args=("--ledger",))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        out = r.stdout
        if out.strip().startswith("{"):  # tolerate the JSON additionalContext form (see SPEC-GAPS.md F39)
            out = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        return out

    def test_ac106_prints_active_lines_newest_first(self):
        seed = Layout.SEED
        d, _ = self.seed(seed)
        out = self.inject()
        lines = out.rstrip("\n").split("\n")
        m = self.HEAD_RE.match(lines[0])
        self.assertIsNotNone(m, lines[0])
        self.assertEqual(os.path.realpath(m.group(1)), os.path.realpath(os.path.join(d, "decisions.md")))
        self.assertEqual(lines[1:], [seed[3], seed[2], seed[0]])
        self.assertNotIn("SUPERSEDED", out)
        self.assertFalse(self.shim_invoked())
        self.assertEqual(self.merge_calls(), 0)

    def test_ac106_works_from_the_repo_root_and_from_a_subdir(self):
        self.seed(Layout.SEED)
        self.assertEqual(self.inject(cwd=self.repo_root), self.inject(cwd=self.cwd))
        self.assertNotEqual(self.inject(cwd=self.cwd).strip(), "")

    def test_ac106_non_git_project(self):
        d = os.path.join(self.rt, "plain")
        os.makedirs(d)
        self.seed(SEED3, root=d)
        out = self.inject(cwd=d)
        self.assertEqual(out.rstrip("\n").split("\n")[1:], list(reversed(SEED3)))

    def test_ac106_nothing_to_print(self):
        self.assertEqual(self.inject().strip(), "")  # no ledger
        self.seed(["- D1 [2026-10-20] SUPERSEDED by D2 [2026-10-22]: Use tabs | because: changed"])
        self.assertEqual(self.inject().strip(), "")  # no active entries
        for bad in ({}, {"cwd": ""}, {"session_id": "x"}):
            self.assertEqual(self.inject(payload=bad).strip(), "", bad)
        r = self.run_post(None, raw="not json at all", args=("--ledger",))
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
        r = self.run_post(None, raw="", args=("--ledger",))
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_ac106_same_4000_char_cut_as_the_handoff(self):
        seed = [ledger_line(n, 200) for n in range(1, 61)]
        self.seed(seed)
        out = self.inject()
        body = out.rstrip("\n").split("\n")[1:]
        entries, trailer = body[:-1], body[-1]
        self.assertTrue(TRAILER_RE.match(trailer), trailer)
        self.assertEqual(entries, list(reversed(seed))[:len(entries)])
        self.assertLessEqual(sum(len(l) for l in entries), 4000)
        self.assertEqual(int(TRAILER_RE.match(trailer).group(1)), 60 - len(entries))

    def test_ac106_reads_never_writes(self):
        d, _ = self.seed(Layout.SEED)
        snap = {n: (os.path.getmtime(os.path.join(d, n)), open(os.path.join(d, n), "rb").read()) for n in os.listdir(d)}
        self.inject()
        after = {n: (os.path.getmtime(os.path.join(d, n)), open(os.path.join(d, n), "rb").read()) for n in os.listdir(d)}
        self.assertEqual(after, snap)
        self.assertEqual(sorted(os.listdir(os.path.join(self.hd, "projects"))), [key_for(self.repo_root)])

    def test_ac106_without_a_ledger_nothing_is_created(self):
        self.inject()
        self.assertFalse(os.path.exists(os.path.join(self.hd, "projects")))


# ---------------------------------------------------------------- AC 107
class Registration(F39):
    def groups(self):
        tpl = os.path.join(os.path.dirname(HOOKS_DIR), "settings.template.json")
        with open(tpl) as fh:
            d = json.load(fh)
        out = []
        for ent in d["hooks"]["SessionStart"]:
            out.append((ent.get("matcher", ""), [h.get("command", "") for h in ent.get("hooks", [])]))
        return out

    def test_ac107_ledger_under_startup_and_resume(self):
        groups = self.groups()
        for m in ("startup", "resume"):
            cmds = [c for matcher, cs in groups if m in matcher.split("|") for c in cs]
            self.assertTrue(any(re.search(r"postcompact-inject\.py\s+--ledger(\s|$)", c) for c in cmds), (m, groups))

    def test_ac107_compact_group_keeps_the_three_parts(self):
        cmds = [c for matcher, cs in self.groups() if "compact" in matcher.split("|") for c in cs]
        for k in (1, 2, 3):
            self.assertTrue(any(re.search(r"postcompact-inject\.py\s+--part[ =]%d(\s|$)" % k, c) for c in cmds), (k, cmds))

    def test_ac107_ledger_only_in_startup_and_resume_groups(self):
        for matcher, cs in self.groups():
            if any("--ledger" in c and "--part" not in c for c in cs):
                self.assertTrue(set(matcher.split("|")) <= {"startup", "resume"}, matcher)


# ---------------------------------------------------------------- AC 108
class Health(F39):
    def test_ac108_field_order_and_types(self):
        self.go()
        keys = list(self.health().keys())
        i = keys.index("summary_model")
        self.assertEqual(keys[i + 1:i + 6], LEDGER_KEYS, keys)
        h = self.health()
        self.assertIsInstance(h["ledger"], str)
        for k in ("ledger_active", "ledger_superseded", "ledger_restored"):
            self.assertIs(type(h[k]), int, k)
        self.assertEqual((h["ledger"], h["ledger_active"], h["ledger_superseded"], h["ledger_restored"]), ("ok", 2, 0, 0))
        # F39.10.3: ledger_chars = total chars of the active entries (newline counting not pinned)
        self.assertIs(type(h["ledger_chars"]), int)
        base = len(L1) + len(L2)
        self.assertTrue(base <= h["ledger_chars"] <= base + 2, h["ledger_chars"])

    def test_ac108_superseding_merge_counts(self):
        self.seed(["- D1 [2026-10-20] Use tabs | why: style"])
        self.set_shim("merge", out="- D1 [2026-10-20] SUPERSEDED by D2 [2026-10-25]: Use tabs | because: user switched\n"
                                   "- D2 [2026-10-25] Use spaces | why: user said so\n")
        self.go()
        h = self.health()
        self.assertEqual((h["ledger"], h["ledger_active"], h["ledger_superseded"]), ("ok", 1, 1))

    def test_ac108_disabled_and_failed_and_unchanged_keep_the_fields(self):
        for extra, rc, want in (({"HANDOFF_LEDGER": "0"}, None, "disabled"),):
            self.go(extra=extra)
            h = self.health()
            self.assertEqual(h["ledger"], want)
            keys = list(h.keys())
            i = keys.index("summary_model")
            self.assertEqual(keys[i + 1:i + 6], LEDGER_KEYS)
        self.seed(SEED3)
        self.set_shim("merge", rc=1)
        self.go()
        h = self.health()
        self.assertEqual(h["ledger"], "failed")
        self.assertEqual((h["ledger_active"], h["ledger_superseded"]), (3, 0))  # counts describe the ledger kept

    def test_ac108_status_unaffected_by_ledger_outcome(self):
        self.fresh_agent()
        self.go()
        self.assertEqual(self.health()["status"], "ok")
        self.set_shim("merge", rc=1)
        self.go()
        self.assertEqual(self.health()["status"], "ok")


# ---------------------------------------------------------------- AC 109 and 110
class NoCwdAndChild(F39):
    def test_ac109_no_cwd_no_ledger(self):
        p = {"session_id": "S", "trigger": "auto", "transcript_path": self.tpath}
        self.fresh_agent()
        self.go(payload=p)
        self.assertFalse(os.path.exists(os.path.join(self.hd, "projects")))
        self.assertEqual(self.merge_calls(), 0)
        h = self.health()
        self.assertEqual(h["ledger"], "none")
        t = self.latest()
        self.assertNotIn("## Project decisions", t)
        self.assertIn(AGENT_H, t)
        self.assertIn(SUMMARY_H, t)  # the summary and the rest of the handoff work as in F38
        self.assertIn(FACTS_H, t)
        self.assertEqual(h["status"], "ok")

    def test_ac110_child_run_touches_no_ledger_and_logs_nothing(self):
        d, text = self.seed(SEED3)
        snap = {n: os.path.getmtime(os.path.join(d, n)) for n in os.listdir(d)}
        r = self.run_pre(self.payload(cwd=self.cwd), fallback=None, extra={"HANDOFF_HOOK_CHILD": "1"})
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertEqual({n: os.path.getmtime(os.path.join(d, n)) for n in os.listdir(d)}, snap)
        self.assertEqual(open(os.path.join(d, "decisions.md")).read(), text)
        self.assertEqual(self.merge_calls(), 0)
        self.assertFalse(self.shim_invoked())
        self.assertFalse(os.path.exists(self.health_path()))
        self.assertFalse(os.path.exists(os.path.join(self.hd, "S-latest.md")))

    def test_ac110_child_run_without_ledger_creates_nothing(self):
        r = self.run_pre(self.payload(cwd=self.cwd), fallback=None, extra={"HANDOFF_HOOK_CHILD": "1"})
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertFalse(os.path.exists(self.hd))


# ---------------------------------------------------------------- AC 111, 113, 114 (F39.10)
TRAILER2_RE = re.compile(r"^- \((\d+) older active decisions in the full ledger; read it before acting on anything older\)$")


class CompactParts(InjectLedger):
    HEAD_K = r"^Project decisions for this repo \(part %d of the ledger; newest first; full ledger: (/.+decisions\.md)\)\. Standing unless the user says otherwise:$"

    def part(self, k, cwd=None):
        r = self.run_post({"cwd": cwd or self.cwd, "session_id": "N", "hook_event_name": "SessionStart", "source": "compact"},
                          args=("--ledger", "--part", str(k)))
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        out = r.stdout
        if out.strip().startswith("{"):
            out = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        return out

    def test_ac111_120_entries_two_parts_no_gaps_or_repeats(self):
        seed = [ledger_line(n, 180) for n in range(1, 121)]
        d, _ = self.seed(seed)
        outs = [self.part(1), self.part(2)]
        shown = []
        for k, o in enumerate(outs, 1):
            self.assertLess(len(o), 10000, k)
            lines = o.rstrip("\n").split("\n")
            m = re.match(self.HEAD_K % k, lines[0])
            self.assertIsNotNone(m, lines[0])
            self.assertEqual(os.path.realpath(m.group(1)), os.path.realpath(os.path.join(d, "decisions.md")))
            shown += [l for l in lines[1:] if l.startswith("- D")]
        self.assertEqual(shown, list(reversed(seed))[:len(shown)])  # newest first, contiguous, no repeats
        self.assertGreater(len(shown), 90)
        last = outs[1].rstrip("\n").split("\n")[-1]
        m = TRAILER2_RE.match(last)
        self.assertIsNotNone(m, last)
        self.assertEqual(int(m.group(1)), 120 - len(shown))
        self.assertGreater(int(m.group(1)), 0)
        self.assertFalse([l for l in outs[0].split("\n") if TRAILER2_RE.match(l)])  # trailer only after part 2
        self.assertFalse(self.shim_invoked())
        self.assertEqual(self.merge_calls(), 0)

    def test_ac111_ten_entries_all_in_part_1_nothing_in_part_2(self):
        seed = [ledger_line(n, 180) for n in range(1, 11)]
        self.seed(seed)
        p1 = self.part(1)
        self.assertEqual([l for l in p1.split("\n") if l.startswith("- D")], list(reversed(seed)))
        self.assertFalse([l for l in p1.split("\n") if "older active decisions" in l])
        self.assertEqual(self.part(2).strip(), "")

    def test_ac111_no_ledger_or_no_active_entries_prints_nothing(self):
        self.assertEqual((self.part(1).strip(), self.part(2).strip()), ("", ""))
        self.seed(["- D1 [2026-10-20] SUPERSEDED by D2 [2026-10-22]: Use tabs | because: changed"])
        self.assertEqual((self.part(1).strip(), self.part(2).strip()), ("", ""))

    def test_ac111_without_part_keeps_the_4000_form(self):
        seed = [ledger_line(n, 200) for n in range(1, 61)]
        self.seed(seed)
        out = self.inject()
        self.assertTrue(TRAILER_RE.match(out.rstrip("\n").split("\n")[-1]))
        self.assertLess(len(out), 4500)

    def test_ac111_reads_the_ledger_written_by_the_precompact_run(self):
        self.go()
        out = self.part(1)
        self.assertEqual([l for l in out.split("\n") if l.startswith("- D")], [L2, L1])


class LeanPromptAndTemplate(F39):
    def test_ac116_merge_prompt_ends_with_keep_values_sentence(self):
        self.go()
        self.assertTrue(self.merge_argv()[-1].endswith(KEEP))
        self.assertLess(self.merge_argv()[-1].index(LEAN), self.merge_argv()[-1].index(KEEP))

    def test_ac113_merge_prompt_ends_with_lean_sentences(self):
        self.go()
        last = self.merge_argv()[-1]
        self.assertEqual(last, MERGE_PROMPT)
        self.assertIn(LEAN, last)  # F39.10 sentences; F39.11 appends one more after them (AC 116)
        self.assertTrue(last.endswith(LEAN + " " + KEEP))
        self.assertTrue(last.endswith(KEEP))
        self.assertIn("Format of superseded lines", last)

    def test_ac114_template_compact_and_start_groups(self):
        groups = Registration.groups(self)
        compact = [c for m, cs in groups if "compact" in m.split("|") for c in cs]
        for k in (1, 2, 3):
            self.assertTrue(any(re.search(r"postcompact-inject\.py\s+--part[ =]%d(\s|$)" % k, c) and "--ledger" not in c
                                for c in compact), (k, compact))
        for k in (1, 2):
            self.assertTrue(any(re.search(r"postcompact-inject\.py\s+--ledger\s+--part[ =]%d(\s|$)" % k, c)
                                or re.search(r"postcompact-inject\.py\s+--part[ =]%d\s+--ledger(\s|$)" % k, c)
                                for c in compact), (k, compact))
        for m in ("startup", "resume"):
            cmds = [c for matcher, cs in groups if m in matcher.split("|") for c in cs]
            self.assertTrue(any(re.search(r"postcompact-inject\.py\s+--ledger(\s|$)", c) and "--part" not in c
                                for c in cmds), (m, groups))


if __name__ == "__main__":
    unittest.main()
