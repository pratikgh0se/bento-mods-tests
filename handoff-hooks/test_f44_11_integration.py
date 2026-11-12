"""F44.11 (hooks 1.7.0) ACs 160-162 of specs/handoff-hooks-spec.md (code-blind: written from the spec only).
160: RESOLVE keeps the whole original after `was:`. 161: `precompact-handoff.py --ledger-repair <dir>`.
162: an active-looking line without `| why:` is still injected and traced in hooks-error.jsonl.
Black-box on the F42 fixtures (temp HOME, `claude` shim for the merge model)."""
import json, os, re, subprocess, sys
import test_f42_lossless_rules as _f42
from helpers import PRE

BACKUP_TS = "20261101T000000Z"


def full_original(n, width):
    """Active task line of exactly `width` chars with a long decision text and a `| why:` tail."""
    head = "- D%d [2026-10-22] [task] " % n
    tail = " | why: WHYTAIL-%d end" % n
    body = ("ORIG%d " % n).ljust(width - len(head) - len(tail) - 1, "q") + "Z"
    line = head + body + tail
    assert len(line) == width, (len(line), width)
    return line


def was_text(line):
    """The `was:` payload form of an active line: the text without the `- D<n> [date] ` prefix."""
    return re.match(r"^- D\d+ \[\d{4}-\d\d-\d\d\] (.*)$", line).group(1)


class Resolve800(_f42.F42):
    def test_ac160_resolve_keeps_all_of_an_800_char_entry(self):
        orig = full_original(3, 800)
        self.seed(["- D1 [2026-10-20] [rule] Use spaces | why: style",
                   "- D2 [2026-10-21] [decision] Use SQLite | why: simple", orig])
        self.set_shim("merge", out="RESOLVE D3: shipped\n")
        self.go()
        lines = self.ledger_lines()
        self.assertEqual(self.ids(lines), [1, 2, 3])
        m = re.match(_f42.RESOLVED_RE % (3, "shipped"), lines[2])
        self.assertIsNotNone(m, lines[2][:200])
        self.assertEqual(m.group(1), "2026-10-22")
        want = was_text(orig)
        self.assertIn(m.group(3), (want, re.sub(r"^\[task\] ", "", want)))  # tag kept or dropped (as AC 126), text whole
        self.assertTrue(m.group(3).endswith("| why: WHYTAIL-3 end"), m.group(3)[-60:])
        self.assertIn("ORIG3 ", m.group(3))
        self.assertFalse(m.group(3).endswith("..."))
        self.assertGreater(len(lines[2]), 800)  # not cut to the 700-char line cap
        h = self.health()
        self.assertEqual((h["ledger"], h["ledger_active"], h["ledger_resolved"]), ("ok", 2, 1))

    def test_ac160_resolve_of_a_short_entry_unchanged(self):
        self.seed(["- D1 [2026-10-20] [rule] Use spaces | why: style",
                   "- D2 [2026-10-22] [task] Approve release 1.2 | why: user ok"])
        self.set_shim("merge", out="RESOLVE D2: shipped\n")
        self.go()
        m = re.match(_f42.RESOLVED_RE % (2, "shipped"), self.ledger_lines()[1])
        self.assertIsNotNone(m)
        self.assertIn("Approve release 1.2 | why: user ok", m.group(3))


class Repair(_f42.F42):
    ORIG = {2: full_original(2, 800), 4: full_original(4, 750)}

    def cut(self, n, reason):
        """A RESOLVED line whose `was:` text was cut by the old 700-char cap (ends in `...`, no `| why:`)."""
        head = "- D%d [2026-10-22] RESOLVED [2026-10-26]: %s | was: " % (n, reason)
        return head + was_text(self.ORIG[n])[:560] + "..."

    def full_resolved(self, n, reason):
        return "- D%d [2026-10-22] RESOLVED [2026-10-26]: %s | was: %s" % (n, reason, was_text(self.ORIG[n]))

    def build(self, backup_lines=None, cut_ids=(2, 4)):
        keep = ["- D1 [2026-10-20] [rule] Use spaces | why: style",
                "- D3 [2026-10-23] [decision] Use SQLite | why: simple",
                "- D5 [2026-10-20] RESOLVED [2026-10-21]: done | was: [task] Short thing | why: y"]
        cur = [keep[0]] + [self.cut(n, "shipped %d" % n) if n in cut_ids else self.ORIG[n] for n in (2,)] \
            + [keep[1]] + [self.cut(4, "gone") if 4 in cut_ids else self.ORIG[4]] + [keep[2]]
        d, text = self.seed(cur)
        bl = backup_lines if backup_lines is not None else \
            [keep[0], self.ORIG[2], keep[1], self.ORIG[4], keep[2].replace("RESOLVED [2026-10-21]: done | was: ", "")]
        btext = "# Project decisions: %s\n%s\n" % (self.repo_root, "\n".join(bl))
        bname = "decisions.%s.md" % BACKUP_TS
        with open(os.path.join(d, bname), "w") as f:
            f.write(btext)
        return d, text, bname

    def repair(self, arg=None):
        return subprocess.run([sys.executable, PRE, "--ledger-repair", arg or self.cwd], input="", capture_output=True,
                              text=True, env=self.env(None), timeout=60, cwd=self.tmp)

    def test_ac161_restores_two_cut_lines_byte_exactly(self):
        d, before, bname = self.build()
        self.assertTrue(all(l.endswith("...") for l in self.ledger_lines() if "RESOLVED [2026-10-26]" in l))
        r = self.repair()
        self.assertEqual((r.returncode, r.stdout.strip(), r.stderr), (0, "repaired 2 of 2 cut lines", ""))
        lines = self.ledger_lines()
        self.assertEqual(self.ids(lines), [1, 2, 3, 4, 5])
        m2 = re.match(_f42.RESOLVED_RE % (2, "shipped 2"), lines[1])
        m4 = re.match(_f42.RESOLVED_RE % (4, "gone"), lines[3])
        self.assertIsNotNone(m2, lines[1][:150])
        self.assertIsNotNone(m4, lines[3][:150])
        self.assertEqual(m2.group(3), was_text(self.ORIG[2]))  # byte-exact original
        self.assertEqual(m4.group(3), was_text(self.ORIG[4]))
        self.assertTrue(m2.group(3).endswith("| why: WHYTAIL-2 end"))
        # untouched lines stay as they were
        old = [l for l in before.split("\n") if l.startswith("- D")]
        self.assertEqual((lines[0], lines[2], lines[4]), (old[0], old[2], old[4]))
        # a backup of the pre-repair ledger was written
        new = [b for b in self.backups() if b != bname]
        self.assertEqual(len(new), 1, self.backups())
        self.assertEqual(open(os.path.join(d, new[0])).read(), before)

    def test_ac161_second_run_finds_nothing_to_repair(self):
        self.build()
        self.assertEqual(self.repair().stdout.strip(), "repaired 2 of 2 cut lines")
        r = self.repair()
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "repaired 0 of 0 cut lines"))

    def test_ac161_cut_line_without_a_backup_entry_is_left_alone(self):
        d, before, bname = self.build(backup_lines=["- D1 [2026-10-20] [rule] Use spaces | why: style", self.ORIG[2]])
        r = self.repair()
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "repaired 1 of 2 cut lines"))
        lines = self.ledger_lines()
        self.assertEqual(re.match(_f42.RESOLVED_RE % (2, "shipped 2"), lines[1]).group(3), was_text(self.ORIG[2]))
        self.assertEqual(lines[3], [l for l in before.split("\n") if l.startswith("- D")][3])

    def test_ac161_missing_dir_exit_2_nothing_created(self):
        path = os.path.join(self.rt, "no", "such")
        r = self.repair(path)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.projects(), [])
        self.assertFalse(self.shim_invoked())


class NoWhy(_f42.F42):
    def err_lines(self):
        p = os.path.join(self.hd, "hooks-error.jsonl")
        return [l for l in open(p).read().split("\n") if l] if os.path.exists(p) else []

    def test_ac162_line_without_why_is_injected_and_traced(self):
        bad = "- D6 [2026-10-25] [rule] Always run five builders NOWHY-MARK"
        self.seed(["- D1 [2026-10-20] [decision] Use SQLite | why: simple", bad,
                   "- D7 [2026-10-26] [task] Ship it | why: ok"])
        before = len(self.err_lines())
        out = self.post(1)
        self.assertIn("NOWHY-MARK", out)
        self.assertIn("D1 ", out)
        self.assertIn("D7 ", out)
        new = self.err_lines()[before:]
        self.assertGreaterEqual(len(new), 1)
        self.assertTrue(any(re.search(r"\bD6\b", l) for l in new), new)
        for l in new:
            json.loads(l)  # each trace line is JSON

    def test_ac162_untagged_line_without_why_counts_as_decision(self):
        self.seed(["- D1 [2026-10-20] [rule] Use spaces | why: style", "- D2 [2026-10-25] Untagged NOWHY-MARK2"])
        out = self.post(1)
        self.assertIn("NOWHY-MARK2", out)
        self.assertTrue(any(re.search(r"\bD2\b", l) for l in self.err_lines()))

    def test_ac162_well_formed_ledger_writes_no_trace(self):
        self.seed(["- D1 [2026-10-20] [rule] Use spaces | why: style"])
        self.post(1)
        self.assertEqual(self.err_lines(), [])
