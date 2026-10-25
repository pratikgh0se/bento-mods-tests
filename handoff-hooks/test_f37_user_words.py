"""F37 "Keep the user's words": ACs 72-80 of specs/handoff-hooks-spec.md (F37 + F37.5 two-part inject).
Black-box: hooks are invoked exactly like the F35/F36 tests (temp HOME, HANDOFF_HOOKS_DIR via helpers.py).
Calibration of "exactly k sections must go" is done by bisection over a fixture knob, see find_k()."""
import json, os, re, unittest
from helpers import *
import test_f35 as f35
import test_f36 as f36
from test_content import git

CONT1 = re.compile(r"^\[Handoff continues in part 2 \(injected separately; parts may appear in any order\) and in (/.+-latest\.md): (\d+) more chars \(sections: (.+)\)\. Read it before acting\.\]$")
CONT2 = re.compile(r"^\[Handoff continues in (/.+-latest\.md): (\d+) more chars \(sections: (.+)\)\. Read it before acting\.\]$")
ALL8 = set(DROP37)  # F39.6: eight sections (no Decisions via questions)


def synth_file(total, secs=None, sec_len=1500, agent_len=5000):
    """A realistic latest.md of ~`total` chars: header, agent section, `## ` fact sections, footer."""
    names = secs or [h[3:] for h in EIGHT]
    out = "# Handoff (pre-compaction)\n- session: S\n- cwd: /x\n- trigger: auto\n\n"
    out += AGENT_H + "\n" + ("L" * (agent_len - 1)) + "\n\n"
    out += FACTS_H + "\n\n"
    i = 0
    while len(out) < total - sec_len - 120:
        n = names[i % len(names)]
        i += 1
        out += "## %s%s\n" % (n, "" if i <= len(names) else " (%d)" % i)
        out += "".join("- item %02d %s\n" % (j, "w" * 60) for j in range(max(1, (sec_len - 40) // 72)))
        out += "\n"
    pad = total - len(out) - len("Full transcript: /t.jsonl. Read it for exact details before guessing.\n") - 1
    out += "## Last assistant message\n" + "z" * max(0, pad - 28) + "\n\n"
    out += "Full transcript: /t.jsonl. Read it for exact details before guessing.\n"
    return out


def split_secs(text):
    """Split into chunks at lines starting '## ' (first chunk = header); each rstripped."""
    parts = re.split(r"(?m)^(?=## )", text.strip())
    return [p.rstrip() for p in parts if p.strip()]


class F37(f36.F36):
    def entries(self, ntasks=3, nd=3, hdr=10, plen=120, nusers=12, nfiles=30):
        e = [user(("U%02d " % i) + "u" * 450) for i in range(nusers)]
        for i in range(nd):
            e += [f35.ask("q%d" % i, [("Question %d?" % i, "H" * hdr, ["a", "b"])]),
                  f35.answer("q%d" % i, {"Question %d?" % i: "a"})]
        e += [tool("Edit", file_path="/" + ("p%02d" % i) + "d" * plen) for i in range(nfiles)]
        e += [tool("TaskCreate", subject=("s%03d" % i) + "s" * 150) for i in range(ntasks)]
        e += [tool("Bash", command=("c%d" % i) + "x" * 150) for i in range(5)]
        for i in range(2):
            e += [f35.tu("bg%d" % i, "Agent", {"description": "background job %d" % i, "prompt": "p", "subagent_type": "g",
                                              "run_in_background": True}),
                  f35.tres("bg%d" % i, "agentId: bgid%d" % i, {"agentId": "bgid%d" % i, "isAsync": True})]
        e.append(asst("A" * 1000))
        return e

    def rich_repo(self):
        repo = self.repo()
        for i in range(40):
            open(os.path.join(repo, "untracked_file_with_long_name_%02d.txt" % i), "w").write("x")
        return repo

    def run_build(self, entries):
        self.write_transcript(entries)
        return self.run_and_read(cwd=self.repo_dir)

    def find_k(self, build, k, hi, cwd=None, expected=ALL8):
        """Smallest knob value whose file drops >= k of `expected` sections; returns that file text."""
        def run(x):
            self.write_transcript(build(x))
            return self.run_and_read(cwd=cwd(x) if cwd else self.repo_dir)
        t0 = run(0)
        self.assertEqual(set(h for h in DROP37 if h in t0), set(expected),
                         "calibration fixture invalid: expected sections not all present at knob 0")
        nd = lambda t: len(dropped37(t, expected))
        self.assertEqual(nd(t0), 0, "calibration fixture invalid: already over the cap at knob 0")
        self.assertGreaterEqual(nd(run(hi)), k, "calibration fixture cannot force %d drops" % k)
        lo, h = 0, hi
        while lo < h:
            m = (lo + h) // 2
            if nd(run(m)) >= k:
                h = m
            else:
                lo = m + 1
        return run(lo)

    def setUp(self):
        super().setUp()
        self.repo_dir = self.rich_repo()
        self.put_agent("L" * 1000, age_min=1)  # F39.6: cap 14,000 (was 20,000), so a smaller agent body keeps all eight sections at knob 0

    # ---------------------------------------------------------------- AC 72
    def test_ac72_user_words_survive_heavy_transcript(self):
        t = self.run_build(self.entries(ntasks=400, nd=10, hdr=150, plen=250))
        self.assertLessEqual(len(t), CAP)
        self.assertIn(EIGHT[0], t)
        users = [l for l in f35.section(t, EIGHT[0]).split("\n") if l.startswith("- ")]
        self.assertEqual(len(users), 8)
        self.assertIn("U11 ", users[-1])
        self.assertIn("U04 ", users[0])
        self.assertIn(AGENT_H, t)
        self.assertTrue(t.rstrip().endswith(FOOTER_FMT.format(p=self.tpath)))
        self.assertNotIn(DROP37[0], t, "pressure expected: Files touched dropped first")
        for h in (EIGHT[0], EIGHT[3]):  # Last user messages, Open tasks (F39.6: no Decisions section)
            if h not in t:
                self.assertNotIn(DROP37[0], t)

    def test_ac72_old_cap_is_gone(self):
        # a file between the old 9,500 cap and the F39.6 cap (14,000) keeps every section
        t = self.run_build(self.entries(ntasks=3))
        self.assertGreater(len(t), OLD_CAP)
        self.assertEqual(heads9(t), EIGHT)

    # ---------------------------------------------------------------- AC 73
    def _check_k(self, t, k):
        self.assertEqual(dropped37(t, ALL8), DROP37[:k])
        self.assertIn(EIGHT[0], t)
        self.assertLessEqual(len(t), CAP)
        self.assertIn(AGENT_H, t)
        self.assertTrue(t.rstrip().endswith(FOOTER_FMT.format(p=self.tpath)))

    def test_ac73_drop_order_k1(self):
        self._check_k(self.find_k(lambda n: self.entries(ntasks=3 + n), 1, 400), 1)

    def test_ac73_drop_order_k3(self):
        self._check_k(self.find_k(lambda n: self.entries(ntasks=3 + n), 3, 400), 3)

    def test_ac73_drop_order_all_eight_users_last(self):
        # The non-user sections cannot be forced out by transcript content alone (each is size-capped), so the
        # header is inflated with a very long (nonexistent) cwd; that means no Git section (see SPEC-GAPS.md).
        exp = ALL8 - {"## Git"}
        t = self.find_k(lambda m: self.entries(ntasks=3, nd=10, hdr=200, plen=100), 6, 150,
                        cwd=lambda m: "/" + "d" * (100 * m + 100), expected=exp)
        self.assertEqual(dropped37(t, exp), [h for h in DROP37 if h in exp][:6])
        for h in DROP37[:-1]:
            self.assertNotIn(h, t)
        self.assertIn(EIGHT[0], t)
        self.assertLessEqual(len(t), CAP)
        self.assertEqual(len([l for l in f35.section(t, EIGHT[0]).split("\n") if l.startswith("- ")]), 8)
        self.assertTrue(t.rstrip().endswith(FOOTER_FMT.format(p=self.tpath)))

    # ---------------------------------------------------------------- AC 74
    def test_ac74_small_file_unchanged(self):
        for n in (9000, 9650):
            with self.subTest(n=n):
                body = "## Last user messages (oldest first)\n" + ("- hello world %s\n" % ("x" * 40)) * ((n - 40) // 60)
                body = body[:n].rstrip("\n") + "\n"
                self.put_latest(body)
                self.put_sidecar()
                for args in ((), ("--part", "1")):
                    ctx = self.post_ctx(args=args)
                    self.assertEqual(ctx, PLAIN + body.strip())
                    self.assertNotIn("[Handoff continues", ctx)

    # ---------------------------------------------------------------- AC 75 (continuation line as amended by F37.5)
    def test_ac75_inline_cut_15k(self):
        content = synth_file(15000)
        self.put_latest(content)
        self.put_sidecar()
        path = os.path.join(self.hd, "S-latest.md")
        for args in ((), ("--part", "1")):
            ctx = self.post_ctx(args=args)
            self.check_part1(ctx, content, path)

    def check_part1(self, ctx, content, path):
        self.assertLess(len(ctx), 10000)
        self.assertTrue(ctx.startswith(PLAIN))
        lines = ctx.split("\n")
        m = CONT1.match(lines[-1])
        self.assertIsNotNone(m, "last line must be the part-1 continuation line: %r" % lines[-1])
        self.assertEqual(m.group(1), path)
        self.assertEqual(sum(1 for l in lines if l.startswith("[Handoff continues")), 1)
        inl = "\n".join(lines[:-1])[len(PLAIN):].rstrip()
        stripped = content.strip()
        self.assertTrue(stripped.startswith(inl), "inlined text must be an exact prefix of the file content")
        rest = stripped[len(inl):].lstrip("\n")
        self.assertTrue(rest.startswith("## "), "cut must fall on a whole '## ' section boundary")
        self.assertIn(AGENT_H, inl)
        self.assertEqual(int(m.group(2)), len(stripped) - len(inl))  # chars of the file after the inlined text
        names = [h[3:] for h in sec_names(rest)]
        # names: heading text; a trailing parenthetical like "(last 30)" may be omitted (SPEC-GAPS.md)
        self.assertIn(m.group(3), (", ".join(names), ", ".join(re.sub(r" \(.*\)$", "", n) for n in names)))
        first_rest = [p for p in re.split(r"(?m)^(?=## )", rest) if p][0]
        self.assertGreater(len(PLAIN) + len(inl) + 1 + len(first_rest.rstrip()), 9700 - 400,
                           "greedy: the next whole section would still have fit")
        return inl, rest, int(m.group(2))

    # ---------------------------------------------------------------- AC 76
    def test_ac76_degraded_plus_cut(self):
        content = synth_file(15000)
        self.put_latest(content)
        self.put_sidecar(status="degraded", reasons=["agent_absent"])
        ctx = self.post_ctx()
        self.assertTrue(ctx.startswith("HANDOFF DEGRADED: "))
        self.assertLess(len(ctx), 10000)
        self.assertIn("\n" + PLAIN, ctx)
        self.assertRegex(ctx.split("\n")[-1], CONT1.pattern)
        self.assertEqual(sum(1 for l in ctx.split("\n") if l.startswith("[Handoff continues")), 1)

    # ---------------------------------------------------------------- AC 77
    def test_ac77_health_truncated_true_when_files_dropped(self):
        self.write_transcript(self.entries(ntasks=400, nd=10, hdr=150, plen=250))
        self.run_ok(cwd=self.repo_dir)
        h = self.health()
        self.assertIs(h["truncated"], True)
        self.assertNotIn(DROP37[0], self.latest())

    def test_ac77_health_inline_cut_prediction(self):
        for target, want_cut in ((12000, True), (5000, False)):
            with self.subTest(target=target):
                if want_cut:
                    build = lambda n: self.entries(ntasks=3 + n)
                else:  # small transcript and a short agent body so a ~5,000-char file is reachable
                    self.put_agent("L" * 500, age_min=1)
                    build = lambda n: self.entries(ntasks=3 + n, nd=1, nusers=3, nfiles=3)
                n, t = self.fit(build, target, cwd=self.repo_dir)
                self.assertGreaterEqual(len(heads9(t)), 6)
                self.run_ok(cwd=self.repo_dir)  # same transcript, fresh agent file, fallback off
                h = self.health()
                self.assertIs(h["truncated"], False)
                self.assertIs(h["inline_cut"], want_cut)
                self.assertEqual(h["output_chars"], len(self.latest()))

    # ---------------------------------------------------------------- AC 78 (as amended by F37.6: up to three parts)
    CONT_N = re.compile(r"^\[Handoff continues in part (\d) \(injected separately; parts may appear in any order\) and in (/.+-latest\.md): (\d+) more chars \(sections: .+\)\. Read it before acting\.\]$")

    def parts(self, content, nparts=3):
        self.put_latest(content)
        self.put_sidecar()
        out = []
        for k in range(1, nparts + 1):
            r = self.run_post({"session_id": "S"}, args=("--part", str(k)))
            self.assertEqual((r.returncode, r.stderr), (0, ""), k)
            out.append(json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else None)
        return out

    def check_parts(self, content, ctxs, path):
        """Every part < 10,000 with its own header; concatenated bodies (minus headers/continuation lines) == file."""
        heads = [PLAIN, PLAIN2, "Pre-compaction handoff (auto-saved, part 3):\n"]
        body_lines = []
        self.assertIsNotNone(ctxs[0])
        seen_none = False
        for k, c in enumerate(ctxs):
            if c is None:
                seen_none = True
                continue
            self.assertFalse(seen_none, "part %d printed after an empty part" % (k + 1))
            self.assertLess(len(c), 10000, "part %d" % (k + 1))
            self.assertTrue(c.startswith(heads[k]), "part %d begins with its own header" % (k + 1))
            lines = c.split("\n")
            last = lines[-1]
            more = last.startswith("[Handoff continues")
            if more:
                if k < 2:
                    m = self.CONT_N.match(last)
                    self.assertIsNotNone(m, last)
                    self.assertEqual(int(m.group(1)), k + 2)
                    self.assertEqual(m.group(2), path)
                else:
                    m = CONT2.match(last)
                    self.assertIsNotNone(m, "part 3 uses the path-only form: %r" % last)
                    self.assertEqual(m.group(1), path)
            else:
                self.assertTrue(k == 2 or all(x is None for x in ctxs[k + 1:]), "no continuation line but later parts exist")
            body = "\n".join(lines[:-1] if more else lines)[len(heads[k]):]
            body_lines += [l.rstrip() for l in body.split("\n") if l.strip()]
        want = [l.rstrip() for l in content.strip().split("\n") if l.strip()]
        self.assertEqual(body_lines, want, "concatenated parts must equal the file content")
        self.assertFalse(ctxs[-1] is not None and ctxs[-1].split("\n")[-1].startswith("[Handoff continues in part"))

    def test_ac78_parts_cover_file(self):
        path = os.path.join(self.hd, "S-latest.md")
        for total in (17500, 19000, 20000):
            with self.subTest(total=total):
                content = synth_file(total, sec_len=250)
                ctxs = self.parts(content)
                self.check_parts(content, ctxs, path)
                self.assertTrue(ctxs[0].split("\n")[-1].startswith("[Handoff continues in part 2 (injected separately; parts may appear in any order) and in "))

    def test_ac78_big_sections_up_to_6000(self):
        path = os.path.join(self.hd, "S-latest.md")
        names = ["Alpha", "Beta", "Gamma"]
        content = synth_file(20000, secs=names, sec_len=5500)
        ctxs = self.parts(content)
        self.check_parts(content, ctxs, path)

    def test_ac78_no_part_flag_is_part1(self):
        content = synth_file(15000)
        self.put_latest(content)
        self.put_sidecar()
        self.assertEqual(self.post_ctx(), self.post_ctx(args=("--part", "1")))

    def test_ac75_long_home_path_and_long_section_list(self):
        # amended AC 75: every part < 10,000 for any path length; an over-long section-name list is shortened ending ", ..."
        self.home = os.path.join(self.tmp, "h" * 100, "i" * 90, "home")
        os.makedirs(self.home)
        self.hd = os.path.join(self.home, ".local", "state", "claude-handoffs")
        self.assertGreaterEqual(len(self.hd), 200)
        names = ["Very long section name number %02d %s" % (i, "n" * 60) for i in range(60)]
        content = synth_file(19000, secs=names, sec_len=250)
        ctxs = self.parts(content)
        path = os.path.join(self.hd, "S-latest.md")
        self.assertLess(len(ctxs[0]), 10000)
        self.assertRegex(ctxs[0].split("\n")[-1], CONT1.pattern)
        for c in ctxs:
            if c is not None:
                self.assertLess(len(c), 10000)
        self.check_parts(content, ctxs, path)
        # file of 15,000 chars through the default (no --part) entry point as well
        self.put_latest(synth_file(15000, secs=names, sec_len=250))
        c = self.post_ctx()
        self.assertLess(len(c), 10000)
        self.assertRegex(c.split("\n")[-1], CONT1.pattern)

    # ---------------------------------------------------------------- AC 79
    def test_ac79_small_file_part2_silent(self):
        body = "## Last user messages (oldest first)\n" + ("- hello world %s\n" % ("x" * 40)) * 80
        body = body[:5000].rstrip("\n") + "\n"
        self.put_latest(body)
        self.put_sidecar()
        r = self.run_post({"session_id": "S"}, args=("--part", "2"))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertEqual(self.post_ctx(args=("--part", "1")), PLAIN + body.strip())

    # ---------------------------------------------------------------- AC 80
    def test_ac80_settings_template_registers_both_parts(self):
        tpl = os.path.join(os.path.dirname(os.path.dirname(HOOKS_DIR)), "claude", "settings.template.json") \
            if os.path.basename(HOOKS_DIR) != "hooks" or os.path.basename(os.path.dirname(HOOKS_DIR)) != "claude" \
            else os.path.join(os.path.dirname(HOOKS_DIR), "settings.template.json")
        with open(tpl) as fh:
            d = json.load(fh)
        cmds = []
        for ent in d["hooks"]["SessionStart"]:
            if ent.get("matcher") == "compact":
                cmds += [h.get("command", "") for h in ent.get("hooks", [])]
        inj = [c for c in cmds if "postcompact-inject.py" in c]
        for k in (1, 2, 3):
            self.assertTrue(any(re.search(r"postcompact-inject\.py\s+--part[ =]%d(\s|$)" % k, c) for c in inj), (k, inj))


if __name__ == "__main__":
    unittest.main()
