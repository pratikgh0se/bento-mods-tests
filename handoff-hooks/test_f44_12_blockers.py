"""F44.12 (hooks 1.7.1) ACs 163-166 of specs/handoff-hooks-spec.md (code-blind: written from the spec only)."""
import json, os, re, time
import test_f44_recall as R
from test_f44_recall import RecallBase, Hook, FakeEmbed, RECALL_LINE, _f42

SID = "f6f6f6f6-0000-4000-8000-000000000006"
SENTENCE = (" If recall and the decisions list disagree, the decisions list and the user's latest words win: "
            "recall shows history, not current rules.")


def big_text(n):
    """Deterministic n-char text where every position is distinguishable (no accidental concatenation matches)."""
    out, i = [], 0
    while sum(len(x) for x in out) < n:
        out.append("[%06d]" % i)
        i += 1
    return "".join(out)[:n]


class LongOpen(RecallBase):
    def add_long(self, n, line_minute=9):
        text = big_text(n)
        path = os.path.join(self.tdir(self.proj), SID + ".jsonl")
        self.write_session(path, [self.rec("assistant", [{"type": "text", "text": text}], sid=SID, cwd=self.proj,
                                           day=6, minute=line_minute)])
        return text, "%s:1" % SID[:8]

    # ---- AC 163
    def test_ac163_50000_char_message_full_then_from(self):
        text, mid = self.add_long(50000)
        out1 = self.ok("open", mid, "--full")
        marker = "[cut: 10000 more chars; continue with: recall.py open %s --full --from 40000]" % mid
        self.assertIn(marker, out1)
        body1 = out1.split("\n", 1)[1].split(marker)[0].rstrip("\n")
        self.assertEqual(body1, text[:40000])
        out2 = self.ok("open", mid, "--full", "--from", "40000")
        head2 = out2.split("\n", 1)[0]
        self.assertTrue(re.match(r"^--- %s \S+.* assistant \[chars 40000-50000 of 50000\]$" % re.escape(mid), head2)
                        or re.match(r"^--- %s:1 \S+.* assistant \[chars 40000-50000 of 50000\]$" % re.escape(SID[:8]), head2),
                        head2)
        self.assertNotIn("[cut:", out2)
        body2 = out2.split("\n", 1)[1].rstrip("\n")
        self.assertEqual(len(body2), 10000)
        self.assertEqual(body1 + body2, text)

    # ---- AC 164
    def test_ac164_14300_char_message_whole(self):
        text, mid = self.add_long(14300)
        out = self.ok("open", mid, "--full")
        self.assertIn(text, out)
        self.assertNotIn("[cut:", out)


class ColdModel(RecallBase):
    # ---- AC 165
    def test_ac165_slow_embedding_server_still_hybrid_with_keep_alive(self):
        fe = FakeEmbed()
        self.addCleanup(fe.stop)
        r = self.rc("index", embed=fe.url)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        fe.delay = 8.0
        n0 = len(fe.requests)
        t0 = time.time()
        r = self.rc("search", "Pomodoro", embed=fe.url, timeout=120)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        self.assertGreaterEqual(time.time() - t0, 7.5, "the server must have been waited for")
        first = r.stdout.split("\n")[0]
        self.assertRegex(first, r"^mode: hybrid \(meaning index covers \d+ of \d+ messages\)$")
        self.assertTrue(self.hits(r.stdout), r.stdout)
        self.assertTrue(self.has(r.stdout, "SUBONE"))
        bodies = [q["body"] for q in fe.requests[n0:]]
        self.assertTrue(bodies, "no query reached the embedding server")
        self.assertTrue(all("keep_alive" in b for b in bodies), bodies)

    def test_ac165_index_requests_carry_keep_alive(self):
        fe = FakeEmbed()
        self.addCleanup(fe.stop)
        self.assertEqual(self.rc("index", embed=fe.url).returncode, 0)
        bodies = [q["body"] for q in fe.requests]
        self.assertTrue(bodies)
        self.assertTrue(all("keep_alive" in b for b in bodies), bodies[:1])


class Line(Hook):
    # ---- AC 166
    def test_ac166_line_has_sentence_at_both_injection_points(self):
        self.assertTrue(RECALL_LINE.endswith(SENTENCE.lstrip(" ")))
        self.install_hooks(True)
        r = self.pre_from()
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        lines = self.latest("S").split("\n")
        self.assertIn(RECALL_LINE, lines)
        self.assertTrue(RECALL_LINE.endswith(SENTENCE[1:]))

    def test_ac166_ledger_part1_has_sentence_and_stays_under_10000(self):
        self.install_hooks(True)
        lines, kmap = _f42.mixed({"rule": 20, "decision": 100, "task": 60})
        self.assertEqual(len(lines), 180)
        self.seed(lines)
        outs = [self.post_from(k) for k in (1, 2, 3)]
        p1 = outs[0].split("\n")
        self.assertEqual(p1.count(RECALL_LINE), 1)
        self.assertIn(SENTENCE[1:], RECALL_LINE)
        self.assertLess(len(outs[0]), 10000)
        self.check_injection(lines, kmap, outs)


if __name__ == "__main__":
    import unittest
    unittest.main()
