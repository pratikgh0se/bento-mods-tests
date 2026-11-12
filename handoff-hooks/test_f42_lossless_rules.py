"""F42 lossless standing rules: ACs 125-136 of specs/handoff-hooks-spec.md "F42".
Black-box (temp HOME, `claude` shim on PATH; merge knobs `set_shim("merge", ...)`). Ledger and summary enabled.
Reuses the F39 fixtures (seed, ledger_lines, state, health, backups ...). Entry kinds: `[rule]`, `[decision]`, `[task]`
after the date; untagged = decision. Injection parts: `postcompact-inject.py --ledger --part 1|2|3`."""
import json, os, random, re, shutil, subprocess, sys, time, unittest
from helpers import *
from test_f39_ledger import (F39, SEED3, LEAN, KEEP, MERGE_PROMPT, MERGE_BASE42, F42_ADD, L1, L2, LEDGER_KEYS, ts,
                             parse_ts, today_dates, SUMMARY_TEXT, Registration)

TODAY = time.strftime("%Y-%m-%d", time.gmtime())
KINDS = ("rule", "decision", "task")
RANK = {"rule": 0, "decision": 1, "task": 2}
FULL_RE = re.compile(r"^- D(\d+) \[\d{4}-\d\d-\d\d\] (?:\[(rule|decision|task)\] )?(.*)$")
IDX_RE = re.compile(r"^- D(\d+) \[(rule|decision|task)\] (.*)$")
COUNT_RE = re.compile(r"^- \((\d+) more active entries not listed; read the full ledger\)$")
HEAD_RE = r"^Project decisions for this repo \(part %d of the ledger;.*full ledger: (/.+decisions\.md)\)"
NOTE_PFX = "Index entries are summaries: read the full entry in "
NOTE_SFX = " before acting on one."
RESOLVED_RE = r"^- D%d \[(\d{4}-\d\d-\d\d)\] RESOLVED \[(\d{4}-\d\d-\d\d)\]: %s \| was: (.*)$"


def entry(n, kind, width=300, day=20):
    """Active ledger line of about `width` chars; kind None = untagged."""
    head = "- D%d [2026-10-%02d] " % (n, day) + ("[%s] " % kind if kind else "")
    tail = " | why: r"
    text = ("%s%d " % ((kind or "decision").upper(), n)).ljust(width - len(head) - len(tail), "x")
    return head + text + tail


def entry_text(line):
    m = FULL_RE.match(line)
    return m.group(3)[:-len(" | why: r")]


def mixed(counts, width=300, seed=7, untagged_every=4):
    """(lines, kinds{id: kind}) for ids 1..N with the given {kind: n} counts, shuffled, some decisions untagged."""
    kinds = [k for k in KINDS for _ in range(counts[k])]
    random.Random(seed).shuffle(kinds)
    lines, kmap, di = [], {}, 0
    for n, k in enumerate(kinds, 1):
        tag = k
        if k == "decision":
            di += 1
            if di % untagged_every == 0:
                tag = None
        lines.append(entry(n, tag, width))
        kmap[n] = k
    return lines, kmap


class F42(F39):
    def post(self, k, args=None, source="compact"):
        r = self.run_post({"cwd": self.cwd, "session_id": "N", "hook_event_name": "SessionStart", "source": source},
                          args=args or ("--ledger", "--part", str(k)))
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        out = r.stdout
        if out.strip().startswith("{"):
            out = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        return out

    def parts(self):
        return [self.post(k) for k in (1, 2, 3)]

    def parse(self, outs):
        """Parsed injection: full [(id, kind, line, part)], index [(id, kind, text, part)], count [(k, part, is_last)]."""
        full, idx, cnt = [], [], []
        for p, o in enumerate(outs, 1):
            lines = [l for l in o.rstrip("\n").split("\n") if l.strip()]
            for i, l in enumerate(lines):
                m = IDX_RE.match(l)
                if m:
                    idx.append((int(m.group(1)), m.group(2), m.group(3), p))
                    continue
                m = FULL_RE.match(l)
                if m:
                    full.append((int(m.group(1)), m.group(2) or "decision", l, p))
                    continue
                m = COUNT_RE.match(l)
                if m:
                    cnt.append((int(m.group(1)), p, i == len(lines) - 1))
        return full, idx, cnt

    def prio(self, kmap):
        """Ids in F42.3 priority order: rules, decisions, tasks, each newest (highest id) first."""
        return sorted(kmap, key=lambda n: (RANK[kmap[n]], -n))

    def check_injection(self, lines, kmap, outs, may_drop=False):
        """Shared structural checks of F42.3 on three part outputs; returns (full, idx, cnt)."""
        ledger = {int(re.match(r"^- D(\d+)", l).group(1)): l for l in lines}
        for k, o in enumerate(outs, 1):
            self.assertLess(len(o), 10000, "part %d" % k)
            if o.strip():
                self.assertRegex(o.split("\n")[0], HEAD_RE % k)
        used = [k for k, o in enumerate(outs, 1) if o.strip()]
        self.assertEqual(used, list(range(1, len(used) + 1)), "parts are filled in order: %s" % used)
        full, idx, cnt = self.parse(outs)
        order = self.prio(kmap)
        for n, k, line, p in full:
            self.assertEqual(line, ledger[n])  # full text is the ledger line itself
            self.assertEqual(k, kmap[n], n)
        fids = [f[0] for f in full]
        self.assertEqual(fids, order[:len(fids)], "full text is a prefix of the priority order")
        iids = [i[0] for i in idx]
        self.assertEqual(iids, [n for n in order if n in set(iids)], "index in priority order")
        self.assertFalse(set(fids) & set(iids), "an entry is either in full or in the index")
        for n, k, text, p in idx:
            self.assertEqual(k, kmap[n], n)
            body = re.sub(r"(…|\.\.\.)$", "", text)
            self.assertLessEqual(len(body), 90, (n, text))
            self.assertTrue(entry_text(ledger[n]).startswith(body), (n, text))
            self.assertGreater(len(body), 0)
        if idx:
            # the index may span the last parts (see SPEC-GAPS.md F42): it starts after all full text, in the tail parts
            ip = sorted({i[3] for i in idx})
            self.assertEqual(ip, list(range(ip[0], used[-1] + 1)), "index fills the tail parts: %s of %s" % (ip, used))
            self.assertLessEqual(max([f[3] for f in full] or [0]), ip[0], "no full text after the index starts")
            first = outs[ip[0] - 1]
            self.assertIn(NOTE_PFX, first)
            self.assertIn(NOTE_SFX, first)
            self.assertIn("decisions.md", first[first.index(NOTE_PFX):])
        else:
            self.assertNotIn(NOTE_PFX, "".join(outs))
        return full, idx, cnt


# ---------------------------------------------------------------- AC 125 (F42.1) and the parser on both hooks
class Tags(F42):
    def seed8(self):
        return self.seed(["- D%d [2026-10-%02d] Old decision %d | why: w" % (n, 10 + n, n) for n in range(1, 9)])

    def test_ac125_tagged_rule_is_applied_with_its_tag(self):
        self.seed8()
        line = "- D9 [%s] [rule] Run 5-9 builders in parallel | why: x" % TODAY
        self.set_shim("merge", out=line + "\n")
        self.go()
        lines = self.ledger_lines()
        self.assertEqual(self.ids(lines), list(range(1, 10)))
        self.assertEqual(lines[8], line)
        h = self.health()
        self.assertEqual((h["ledger"], h["ledger_active"], h["ledger_superseded"], h["ledger_resolved"]), ("ok", 9, 0, 0))

    def test_ac125_decision_and_task_tags_are_applied_too(self):
        self.seed8()
        out = ["- D9 [%s] [decision] Use SQLite | why: x" % TODAY, "- D10 [%s] [task] Approve the release | why: y" % TODAY,
               "- D11 [%s] untagged still accepted | why: z" % TODAY]
        self.set_shim("merge", out="\n".join(out) + "\n")
        self.go()
        self.assertEqual(self.ledger_lines()[8:], out)
        self.assertEqual(self.health()["ledger_active"], 11)

    def test_ac125_postcompact_parser_reads_it_as_an_active_rule_first(self):
        # rule D1 is the OLDEST entry and still comes before the newer untagged decisions
        self.seed(["- D1 [2026-10-20] [rule] Never touch the legacy dir | why: user rule",
                   "- D2 [2026-10-21] Use tabs | why: style", "- D3 [2026-10-22] Keep API v1 | why: compat"])
        out = self.post(1)
        ids = [int(m.group(1)) for l in out.split("\n") for m in [re.match(r"^- D(\d+) ", l)] if m]
        self.assertEqual(ids, [1, 3, 2])

    def test_ac125_untagged_is_a_decision_and_tasks_come_last(self):
        self.seed(["- D1 [2026-10-20] [task] Approve release | why: a", "- D2 [2026-10-21] Untagged old | why: b",
                   "- D3 [2026-10-22] [rule] Rule | why: c", "- D4 [2026-10-23] [decision] Tagged new | why: d",
                   "- D5 [2026-10-24] [task] Newest task | why: e"])
        out = self.post(1)
        ids = [int(m.group(1)) for l in out.split("\n") for m in [re.match(r"^- D(\d+) ", l)] if m]
        self.assertEqual(ids, [3, 4, 2, 5, 1])

    def test_tag_is_part_of_the_entry_text_when_superseded(self):
        self.seed(["- D1 [2026-10-20] [rule] Use tabs | why: style"])
        self.set_shim("merge", out="- D2 [%s] [rule] Use spaces | why: user said so\nSUPERSEDE D1 BY D2: switched\n" % TODAY)
        self.go()
        lines = self.ledger_lines()
        self.assertRegex(lines[0], r"^- D1 \[\d{4}-\d\d-\d\d\] SUPERSEDED by D2 \[\d{4}-\d\d-\d\d\]: \[rule\] Use tabs \| because: switched$")
        h = self.health()
        self.assertEqual((h["ledger_active"], h["ledger_superseded"]), (1, 1))

    def test_rule_leaves_by_supersede_only_postcompact_never_injects_superseded(self):
        self.seed(["- D1 [2026-10-20] SUPERSEDED by D2 [2026-10-22]: [rule] Use tabs | because: switched",
                   "- D2 [2026-10-22] [rule] Use spaces | why: x"])
        out = self.post(1)
        self.assertIn("Use spaces", out)
        self.assertNotIn("Use tabs", out)

    def test_merge_prompt_has_the_f42_sentences(self):
        self.go()
        last = self.merge_argv()[-1]
        self.assertTrue(last.startswith(MERGE_BASE42), "F40.1 prompt is kept (with the kind tag in its line formats)")
        self.assertTrue(last.endswith(F42_ADD))
        self.assertEqual(last, MERGE_PROMPT)


# ---------------------------------------------------------------- AC 126 RESOLVE
class Resolve(F42):
    SEED = ["- D1 [2026-10-20] [rule] Use spaces | why: style",
            "- D2 [2026-10-21] [rule] Never ship on Friday | why: rule",
            "- D3 [2026-10-22] [task] Approve release 1.2 | why: user ok",
            "- D4 [2026-10-23] Untagged one-off approval | why: ok",
            "- D5 [2026-10-24] [decision] Use SQLite | why: simple"]

    def resolved_re(self, n, reason):
        return re.compile(RESOLVED_RE % (n, re.escape(reason)))

    def test_ac126_resolve_task_and_untagged_rules_ignored(self):
        self.seed(self.SEED)
        self.set_shim("merge", out="RESOLVE D3: shipped\nRESOLVE D2: not a task\nRESOLVE D4: done already\n")
        self.go()
        lines = self.ledger_lines()
        self.assertEqual(self.ids(lines), [1, 2, 3, 4, 5])
        m = self.resolved_re(3, "shipped").match(lines[2])
        self.assertIsNotNone(m, lines[2])
        self.assertEqual(m.group(1), "2026-10-22")  # entry date kept in front
        self.assertIn(m.group(2), today_dates())
        self.assertIn("Approve release 1.2 | why: user ok", m.group(3))  # original text, no id/date prefix
        self.assertFalse(m.group(3).startswith("- D"))
        self.assertIn(m.group(3), ("[task] Approve release 1.2 | why: user ok", "Approve release 1.2 | why: user ok"))
        m4 = self.resolved_re(4, "done already").match(lines[3])
        self.assertIsNotNone(m4, lines[3])  # untagged entries can be resolved
        self.assertEqual((lines[0], lines[1], lines[4]), (self.SEED[0], self.SEED[1], self.SEED[4]))  # rule untouched
        h = self.health()
        self.assertEqual((h["ledger"], h["ledger_active"], h["ledger_superseded"], h["ledger_resolved"]), ("ok", 3, 0, 2))

    def test_ac126_resolve_on_a_rule_is_ignored_alone(self):
        d, text = self.seed(self.SEED)
        self.set_shim("merge", out="RESOLVE D2: whatever\nRESOLVE D1: no\n")
        self.go()
        self.assertEqual(self.ledger_lines(), self.SEED)
        h = self.health()
        self.assertEqual((h["ledger_active"], h["ledger_resolved"]), (5, 0))

    def test_resolve_of_missing_superseded_or_resolved_entry_is_ignored(self):
        seed = self.SEED + ["- D6 [2026-10-25] SUPERSEDED by D5 [2026-10-26]: [task] Old | because: x",
                            "- D7 [2026-10-25] RESOLVED [2026-10-26]: done | was: [task] Done thing | why: y"]
        self.seed(seed)
        self.set_shim("merge", out="RESOLVE D99: nope\nRESOLVE D6: nope\nRESOLVE D7: again\n")
        self.go()
        self.assertEqual(self.ledger_lines(), seed)
        self.assertEqual(self.health()["ledger_resolved"], 1)

    def test_ac126_resolved_entries_are_never_injected_nor_counted_active(self):
        self.seed(self.SEED)
        self.set_shim("merge", out="RESOLVE D3: shipped\n")
        self.go()
        outs = self.parts()
        joined = "".join(outs)
        self.assertNotIn("RESOLVED", joined)
        self.assertNotIn("Approve release 1.2", joined)
        self.assertNotRegex(joined, r"(?m)^- D3 ")
        for n in (1, 2, 4, 5):
            self.assertRegex(joined, r"(?m)^- D%d " % n)

    def test_ac126_counts_persist_on_a_run_without_changes(self):
        self.seed(self.SEED)
        self.set_shim("merge", out="RESOLVE D3: shipped\n")
        self.go()
        self.write_transcript(self.convo(start=300, tag="2"))
        self.set_shim("merge", out="NO CHANGES")
        self.go()
        h = self.health()
        self.assertEqual((h["ledger"], h["ledger_active"], h["ledger_resolved"]), ("unchanged", 4, 1))
        self.assertRegex(self.ledger_lines()[2], r"RESOLVED")

    def test_resolved_entries_not_in_summary_standing_decisions(self):
        self.seed(self.SEED)
        self.set_shim("merge", out="RESOLVE D3: shipped\n")
        self.go()
        self.write_transcript(self.convo(start=300, tag="2"))
        self.set_shim("merge", out="NO CHANGES")
        self.go()
        stdin = self.summary_stdin()
        self.assertNotIn("Approve release 1.2", stdin)


# ---------------------------------------------------------------- AC 127 KIND
class Kind(F42):
    def untagged(self, n):
        return ["- D%d [2026-10-%02d] Entry number %d | why: w" % (i, 1 + (i % 28), i) for i in range(1, n + 1)]

    @staticmethod
    def tagged(line, kind):
        return re.sub(r"^(- D\d+ \[\d{4}-\d\d-\d\d\]) ", r"\1 [%s] " % kind, line, count=1)

    def test_ac127_kind_tags_untagged_entry_text_otherwise_identical(self):
        seed = self.untagged(5)
        seed[4] = "- D5 [2026-10-05] [decision] Already tagged | why: w"
        self.seed(seed)
        self.set_shim("merge", out="KIND D4 rule\nKIND D2 task\nKIND D3 decision\nKIND D5 rule\nKIND D9 rule\nKIND D1 bogus\n")
        self.go()
        lines = self.ledger_lines()
        self.assertEqual(lines[3], self.tagged(seed[3], "rule"))
        self.assertEqual(lines[1], self.tagged(seed[1], "task"))
        self.assertEqual(lines[2], self.tagged(seed[2], "decision"))
        self.assertEqual(lines[4], seed[4])  # KIND on a tagged entry is ignored
        self.assertEqual(lines[0], seed[0])  # invalid kind ignored
        self.assertEqual(len(lines), 5)  # no entry for the unknown id
        h = self.health()
        self.assertEqual((h["ledger"], h["ledger_active"]), ("ok", 5))

    def test_ac127_only_the_first_40_kind_lines_are_applied(self):
        seed = self.untagged(45)
        self.seed(seed)
        self.set_shim("merge", out="".join("KIND D%d rule\n" % n for n in range(1, 42)))
        self.go()
        lines = self.ledger_lines()
        for n in range(1, 41):
            self.assertEqual(lines[n - 1], self.tagged(seed[n - 1], "rule"), n)
        self.assertEqual(lines[40:], seed[40:])  # D41 (the 41st line) and later are untouched
        self.assertEqual(self.health()["ledger_active"], 45)

    def test_kind_does_not_add_entries_and_state_still_advances(self):
        seed = self.untagged(3)
        self.seed(seed)
        self.set_shim("merge", out="KIND D1 rule\n")
        self.go()
        self.assertEqual(len(self.ledger_lines()), 3)
        self.assertEqual(self.health()["ledger"], "ok")
        self.assertEqual(len(self.backups()), 1)


# ---------------------------------------------------------------- AC 128-131 injection
class Injection(F42):
    def test_ac128_180_entries_lossless_three_parts(self):
        lines, kmap = mixed({"rule": 20, "decision": 100, "task": 60}, width=300)
        extra = ["- D181 [2026-10-20] SUPERSEDED by D1 [2026-10-21]: [rule] Gone | because: x",
                 "- D182 [2026-10-20] RESOLVED [2026-10-21]: done | was: [task] Done | why: y"]
        self.seed(lines + extra)
        outs = self.parts()
        self.assertTrue(all(o.strip() for o in outs), [len(o) for o in outs])
        full, idx, cnt = self.check_injection(lines, kmap, outs)
        seen = {f[0] for f in full} | {i[0] for i in idx}
        self.assertEqual(seen, set(range(1, 181)))  # every id in full text or as an index line
        self.assertEqual(cnt, [])
        # all 20 rules in full text in part 1, before any decision
        p1 = [f for f in full if f[3] == 1]
        self.assertEqual([f[0] for f in p1 if f[1] == "rule"], sorted((n for n in kmap if kmap[n] == "rule"), reverse=True))
        kinds_p1 = [f[1] for f in p1]
        self.assertEqual(kinds_p1[:20], ["rule"] * 20)
        self.assertNotIn("rule", kinds_p1[20:])
        self.assertTrue(idx, "180 x 300 chars cannot all fit in full text")
        joined = "".join(outs)
        self.assertNotIn("SUPERSEDED", joined)
        self.assertNotIn("RESOLVED", joined)
        self.assertNotRegex(joined, r"(?m)^- D18[12] ")

    def test_ac128_index_line_is_at_most_90_chars_of_text_plus_prefix(self):
        lines, kmap = mixed({"rule": 20, "decision": 100, "task": 60}, width=300)
        self.seed(lines)
        _, idx, _ = self.parse(self.parts())
        self.assertTrue(idx)
        for n, k, text, p in idx:
            self.assertLessEqual(len(re.sub(r"(…|\.\.\.)$", "", text)), 90)
        # the rendered line itself: prefix `- D<n> [kind] ` + <=90 chars + a short ellipsis
        for o in self.parts():
            for l in o.split("\n"):
                if IDX_RE.match(l):
                    self.assertLessEqual(len(l), len("- D999 [decision] ") + 90 + 3, l)

    def test_ac129_400_entries_rules_survive_count_line_present(self):
        lines, kmap = mixed({"rule": 30, "decision": 150, "task": 220}, width=300)
        self.seed(lines)
        outs = self.parts()
        full, idx, cnt = self.check_injection(lines, kmap, outs)
        seen = {f[0] for f in full} | {i[0] for i in idx}
        rules = {n for n in kmap if kmap[n] == "rule"}
        self.assertTrue(rules <= seen, sorted(rules - seen))
        self.assertEqual(len(cnt), 1, cnt)
        k, part, is_last = cnt[0]
        self.assertTrue(is_last, "the count line ends the output")
        self.assertEqual(part, max(p for p, o in enumerate(outs, 1) if o.strip()))
        self.assertEqual(k, 400 - len(seen))
        self.assertGreater(k, 0)
        # drop order: oldest tasks first, then decisions, never rules
        missing = set(kmap) - seen
        self.assertFalse(missing & rules)
        tasks = sorted(n for n in kmap if kmap[n] == "task")
        if missing & {n for n in kmap if kmap[n] == "decision"}:
            self.assertTrue(set(tasks) <= missing)
        miss_tasks = sorted(missing & set(tasks))
        kept_tasks = sorted(seen & set(tasks))
        if miss_tasks and kept_tasks:
            self.assertLess(max(miss_tasks), min(kept_tasks), "oldest tasks are dropped first")
        # after shrinking, every index line is at most 50 chars of text
        for n, kind, text, p in idx:
            self.assertLessEqual(len(re.sub(r"(…|\.\.\.)$", "", text)), 50, (n, text))

    def test_ac130_small_ledger_one_part_no_index(self):
        lines, kmap = mixed({"rule": 2, "decision": 5, "task": 3}, width=200)
        self.seed(lines)
        outs = self.parts()
        self.assertTrue(outs[0].strip())
        self.assertEqual((outs[1].strip(), outs[2].strip()), ("", ""))
        full, idx, cnt = self.check_injection(lines, kmap, outs)
        self.assertEqual((idx, cnt), ([], []))
        self.assertEqual([f[0] for f in full], self.prio(kmap))
        self.assertNotIn(NOTE_PFX, outs[0])

    def test_ac130_no_active_entries_prints_nothing(self):
        self.seed(["- D1 [2026-10-20] SUPERSEDED by D2 [2026-10-22]: [rule] Use tabs | because: changed",
                   "- D2 [2026-10-22] RESOLVED [2026-10-23]: done | was: [task] x | why: y"])
        self.assertEqual([o.strip() for o in self.parts()], ["", "", ""])

    def test_ac131_startup_part_1_is_not_the_4000_cut(self):
        lines, kmap = mixed({"rule": 10, "decision": 60, "task": 30}, width=300)  # 100 entries, 30k chars
        self.seed(lines)
        self.assertGreaterEqual(sum(len(l) for l in lines), 29000)
        p1 = self.post(1, source="startup")
        self.assertLess(len(p1), 10000)
        self.assertGreater(len(p1), 8000)
        self.assertRegex(p1.split("\n")[0], HEAD_RE % 1)
        full = self.parse([p1])[0]
        self.assertGreater(sum(len(f[2]) for f in full), 4000)
        self.assertEqual([f[0] for f in full], self.prio(kmap)[:len(full)])
        self.assertEqual([f[1] for f in full[:10]], ["rule"] * 10)
        self.assertFalse(self.shim_invoked())

    def test_ac131_plain_ledger_equals_part_1(self):
        lines, kmap = mixed({"rule": 10, "decision": 60, "task": 30}, width=300)
        self.seed(lines)
        pl = {"cwd": self.cwd, "session_id": "N", "hook_event_name": "SessionStart", "source": "startup"}
        a = self.run_post(pl, args=("--ledger",))
        b = self.run_post(pl, args=("--ledger", "--part", "1"))
        self.assertEqual((a.returncode, a.stderr, b.returncode, b.stderr), (0, "", 0, ""))
        self.assertEqual(a.stdout, b.stdout)
        self.assertNotEqual(a.stdout.strip(), "")

    def test_ac131_resume_and_startup_parts_2_and_3_exist(self):
        lines, kmap = mixed({"rule": 10, "decision": 60, "task": 30}, width=300)
        self.seed(lines)
        for src in ("startup", "resume"):
            outs = [self.post(k, source=src) for k in (1, 2, 3)]
            self.check_injection(lines, kmap, outs)
            self.assertTrue(outs[1].strip(), src)

    def test_invariant_300_short_entries_every_id_appears(self):
        lines, kmap = mixed({"rule": 25, "decision": 150, "task": 125}, width=100)
        self.seed(lines)
        outs = self.parts()
        full, idx, cnt = self.check_injection(lines, kmap, outs)
        self.assertEqual({f[0] for f in full} | {i[0] for i in idx}, set(range(1, 301)))
        self.assertEqual(cnt, [])
        self.assertTrue(idx)

    def test_injection_never_writes_and_never_calls_the_model(self):
        lines, kmap = mixed({"rule": 5, "decision": 10, "task": 5}, width=200)
        d, _ = self.seed(lines)
        snap = {n: open(os.path.join(d, n), "rb").read() for n in os.listdir(d)}
        self.parts()
        self.assertEqual({n: open(os.path.join(d, n), "rb").read() for n in os.listdir(d)}, snap)
        self.assertEqual(self.merge_calls(), 0)


# ---------------------------------------------------------------- AC 132 maintenance
class Maintain(F42):
    SEED = ["- D1 [2026-10-20] Never ship on Friday | why: rule", "- D2 [2026-10-21] Approve release 1.2 | why: ok",
            "- D3 [2026-10-22] Never ship on Fridays | why: dup"]

    def run_maintain(self, extra=None, arg=None):
        return subprocess.run([sys.executable, PRE, "--ledger-maintain", arg or self.cwd], input="", capture_output=True,
                              text=True, env=self.env(None, extra), timeout=60, cwd=self.tmp)

    def both_roles(self, out):
        # the maintenance system prompt is not pinned: answer under either shim role
        self.set_shim("merge", out=out)
        self.set_shim("summary", out=out)

    def maint_stdin(self):
        for name in ("merge.stdin", "stdin"):
            p = os.path.join(self.shimdir, name)
            if os.path.exists(p):
                return open(p).read()
        self.fail("the model was not called")

    def test_ac132_applies_kind_resolve_supersede_ignores_new_entries(self):
        d, text = self.seed(self.SEED)
        self.both_roles("KIND D1 rule\nRESOLVE D2: done\nSUPERSEDE D3 BY D1: dup\n- D99 [%s] new | why: x\n" % TODAY)
        r = self.run_maintain()
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        lines = self.ledger_lines()
        self.assertEqual(self.ids(lines), [1, 2, 3])
        self.assertEqual(lines[0], "- D1 [2026-10-20] [rule] Never ship on Friday | why: rule")
        self.assertIsNotNone(re.match(RESOLVED_RE % (2, "done"), lines[1]), lines[1])
        self.assertRegex(lines[2], r"^- D3 \[2026-10-22\] SUPERSEDED by D1 \[\d{4}-\d\d-\d\d\]: .*Never ship on Fridays.* \| because: dup$")
        self.assertNotIn("D99", self.ledger_text())
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(open(os.path.join(d, self.backups()[0])).read(), text)
        self.assertRegex(r.stdout.strip(), r"^kind=1 resolved=1 superseded=1 active_before=3 active_after=1$")
        self.assertEqual(len(r.stdout.strip().split("\n")), 1)

    def test_ac132_sends_the_full_ledger_without_a_transcript(self):
        self.seed(self.SEED)
        self.write_transcript(self.convo())
        self.both_roles("NO CHANGES")
        r = self.run_maintain()
        self.assertEqual(r.returncode, 0, r.stderr)
        stdin = self.maint_stdin()
        for l in self.SEED:
            self.assertIn(l, stdin)
        self.assertNotIn("NEW CONVERSATION", stdin)
        self.assertNotIn("DECISION-A", stdin)
        self.assertRegex(r.stdout.strip(), r"^kind=0 resolved=0 superseded=0 active_before=3 active_after=3$")
        self.assertEqual(self.ledger_lines(), self.SEED)

    def test_ac132_kind_limit_is_lifted(self):
        seed = ["- D%d [2026-10-20] Entry %d | why: w" % (n, n) for n in range(1, 61)]
        self.seed(seed)
        self.both_roles("".join("KIND D%d decision\n" % n for n in range(1, 61)))
        r = self.run_maintain()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout.strip(), r"^kind=60 resolved=0 superseded=0 active_before=60 active_after=60$")
        self.assertTrue(all("[decision] " in l for l in self.ledger_lines()))

    def test_ac132_same_validation_as_the_merge(self):
        seed = ["- D1 [2026-10-20] [rule] A rule | why: w", "- D2 [2026-10-21] [task] A task | why: w"]
        self.seed(seed)
        self.both_roles("RESOLVE D1: no\nRESOLVE D2: yes\nKIND D2 rule\nRESOLVE D77: no\n")
        r = self.run_maintain()
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = self.ledger_lines()
        self.assertEqual(lines[0], seed[0])
        self.assertIsNotNone(re.match(RESOLVED_RE % (2, "yes"), lines[1]), lines[1])
        self.assertRegex(r.stdout.strip(), r"^kind=0 resolved=1 superseded=0 active_before=2 active_after=1$")

    def test_ac132_ledger_0_is_a_no_op(self):
        d, text = self.seed(self.SEED)
        self.both_roles("KIND D1 rule\n")
        r = self.run_maintain(extra={"HANDOFF_LEDGER": "0"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.ledger_text(), text)
        self.assertEqual(self.backups(), [])
        self.assertFalse(self.shim_invoked())
        self.assertEqual(self.merge_calls(), 0)

    def test_ac132_works_from_any_path_inside_the_repo(self):
        self.seed(self.SEED)
        self.both_roles("KIND D1 rule\n")
        r = self.run_maintain(arg=self.repo_root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[rule]", self.ledger_lines()[0])


# ---------------------------------------------------------------- AC 133 subagents
class Subagent(F42):
    def snapshot(self):
        out = {}
        for dp, _, fs in os.walk(self.hd):
            for f in fs:
                p = os.path.join(dp, f)
                out[os.path.relpath(p, self.hd)] = open(p, "rb").read()
        return out

    def check_subagent(self, payload, trigger):
        d, text = self.seed(SEED3)
        state = open(os.path.join(d, "decisions.state.json"), "rb").read()
        before = self.snapshot()
        r = self.run_pre(payload, fallback=None)
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        after = self.snapshot()
        changed = {k for k in after if after[k] != before.get(k)} | (set(before) - set(after))
        self.assertEqual(changed, {"health.jsonl"}, changed)
        self.assertTrue(after["health.jsonl"].startswith(before.get("health.jsonl", b"")))
        new = after["health.jsonl"][len(before.get("health.jsonl", b"")):].decode().strip().split("\n")
        self.assertEqual(len(new), 1, new)
        h = json.loads(new[0])
        self.assertEqual((h["trigger"], h["status"], h["ledger"]), (trigger, "subagent", "skipped"))
        self.assertEqual(self.ledger_text(), text)
        self.assertEqual(open(os.path.join(d, "decisions.state.json"), "rb").read(), state)
        self.assertFalse(self.shim_invoked())
        self.assertEqual(self.merge_calls(), 0)

    def test_ac133_agent_id_set(self):
        p = self.payload("S", cwd=self.cwd, trigger="auto")
        p["agent_id"] = "agent-abc123"
        self.check_subagent(p, "auto")

    def test_ac133_agent_id_set_manual_trigger(self):
        p = self.payload("S", cwd=self.cwd, trigger="manual")
        p["agent_id"] = "a1"
        self.check_subagent(p, "manual")

    def test_ac133_transcript_under_subagents(self):
        sub = os.path.join(self.tmp, "proj", "S", "subagents")
        os.makedirs(sub)
        tp = os.path.join(sub, "agent-1.jsonl")
        shutil.copy(self.tpath, tp)
        p = self.payload("S", cwd=self.cwd)
        p["transcript_path"] = tp
        self.check_subagent(p, "auto")

    def test_ac133_empty_or_null_agent_id_is_a_normal_run(self):
        for aid in ("", None):
            shutil.rmtree(self.hd, ignore_errors=True)
            self.seed(SEED3)
            self.set_shim("merge", out="- D4 [%s] Ship Friday | why: deadline\n" % TODAY)
            p = self.payload("S", cwd=self.cwd)
            p["agent_id"] = aid
            r = self.run_pre(p, fallback=None)
            self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
            self.assertNotEqual(self.health()["status"], "subagent", aid)
            self.assertTrue(os.path.exists(os.path.join(self.hd, "S-latest.md")), aid)
            self.assertEqual(self.health()["ledger"], "ok")


# ---------------------------------------------------------------- AC 134 error trace
class ErrorTrace(F42):
    # The hook is robust to every malformed-input provocation tried (missing/unreadable transcript, wrong JSON types,
    # unwritable files), so a main-level exception is forced with the existing F36 `toplevel` fault seam.
    FAULT = {"HANDOFF_TEST_FAULT": "toplevel"}

    def err_lines(self):
        p = os.path.join(self.hd, "hooks-error.jsonl")
        if not os.path.exists(p):
            return []
        return [l for l in open(p).read().split("\n") if l]

    def test_ac134_forced_exception_is_traced_and_health_says_error(self):
        r = self.run_pre(self.payload("S", cwd=self.cwd), extra=self.FAULT, fallback=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = self.err_lines()
        self.assertEqual(len(lines), 1, lines)
        e = json.loads(lines[0])
        for k in ("ts", "hook", "version", "sid", "error", "trace"):
            self.assertIn(k, e)
        self.assertEqual(e["hook"], "precompact")
        self.assertTrue(str(e["sid"]).startswith("S"))
        self.assertTrue(e["error"])
        trace = e["trace"] if isinstance(e["trace"], list) else str(e["trace"]).rstrip("\n").split("\n")
        self.assertTrue(1 <= len(trace) <= 20, len(trace))
        h = self.health()
        self.assertEqual(h["status"], "error")
        self.assertEqual(e["version"], h["hook_version"])

    def test_ac134_error_log_rotates_above_1000000_bytes(self):
        os.makedirs(self.hd, exist_ok=True)
        p = os.path.join(self.hd, "hooks-error.jsonl")
        old = ('{"ts":"2026-01-01T00:00:00Z","hook":"precompact","version":"0","sid":"o","error":"e","trace":"t"}\n'
               .ljust(1000100, " ")[:-1] + "\n")
        open(p, "w").write(old)
        r = self.run_pre(self.payload("S", cwd=self.cwd), extra=self.FAULT, fallback=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(open(p + ".1").read(), old)
        self.assertEqual(len(self.err_lines()), 1)

    def test_ac134_unreadable_transcript_never_breaks_the_hook(self):
        # spec example: an unreadable transcript path. Either handled quietly or traced; the contract is exit 0, a health
        # line, and (if traced) the F42.6 line shape.
        open(self.tpath, "w").write("{}\n")
        os.chmod(self.tpath, 0)
        self.addCleanup(os.chmod, self.tpath, 0o600)
        r = self.run_pre(self.payload("S", cwd=self.cwd), fallback=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        h = self.health()
        self.assertIn(h["status"], ("ok", "degraded", "error"))
        for l in self.err_lines():
            e = json.loads(l)
            self.assertEqual(e["hook"], "precompact")
            self.assertEqual(h["status"], "error")

    def test_no_error_line_on_a_normal_run(self):
        r = self.run_pre(self.payload("S", cwd=self.cwd), fallback=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.err_lines(), [])


# ---------------------------------------------------------------- AC 135 and 136
class TemplateAndVersion(F42):
    def cmds(self, matcher):
        return [c for m, cs in Registration.groups(self) if matcher in m.split("|") for c in cs]

    def test_ac135_ledger_parts_1_2_3_under_compact_startup_resume(self):
        for m in ("compact", "startup", "resume"):
            cmds = self.cmds(m)
            for k in (1, 2, 3):
                self.assertTrue(any(re.search(r"postcompact-inject\.py\s+--ledger\s+--part[ =]%d(\s|$)" % k, c)
                                    or re.search(r"postcompact-inject\.py\s+--part[ =]%d\s+--ledger(\s|$)" % k, c)
                                    for c in cmds), (m, k, cmds))

    def test_ac135_startup_and_resume_have_no_plain_ledger_command(self):
        for m in ("startup", "resume"):
            for c in self.cmds(m):
                if re.search(r"postcompact-inject\.py", c) and "--ledger" in c:
                    self.assertIn("--part", c, c)

    def test_ac135_compact_keeps_the_handoff_parts(self):
        cmds = self.cmds("compact")
        for k in (1, 2, 3):
            self.assertTrue(any(re.search(r"postcompact-inject\.py\s+--part[ =]%d(\s|$)" % k, c) and "--ledger" not in c
                                for c in cmds), (k, cmds))

    def test_ac136_hook_version_1_7_0(self):
        self.go()
        self.assertEqual(self.health()["hook_version"], "1.7.0")
        self.assertEqual(self.sidecar("S")["hook_version"], "1.7.0")

    def test_ac136_health_field_order_with_resolved(self):
        self.go()
        keys = list(self.health().keys())
        i = keys.index("summary_model")
        self.assertEqual(keys[i + 1:i + 8], LEDGER_KEYS, keys)
        self.assertEqual(keys[keys.index("ledger_superseded") + 1], "ledger_resolved")
        self.assertIs(type(self.health()["ledger_resolved"]), int)

    def test_ledger_resolved_present_when_disabled_and_none(self):
        self.go(extra={"HANDOFF_LEDGER": "0"})
        self.assertEqual(self.health()["ledger_resolved"], 0)


if __name__ == "__main__":
    unittest.main()
