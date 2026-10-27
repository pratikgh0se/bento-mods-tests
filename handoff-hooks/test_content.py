import json, os, re, subprocess, time, unittest
from helpers import *


def git(cwd, *a):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


NOGIT = [h for h in SECTIONS if h != '## Git']  # these cwds are not git repos


class Content(HookCase):
    def test_ac18_header_and_footer(self):
        self.write_transcript([user("x")])
        t = self.run_and_read(cwd=self.tmp)
        lines = t.rstrip("\n").split("\n")
        self.assertEqual(lines[0], "# Handoff (pre-compaction)")
        idx = []
        for pre in ("- session: S", "- cwd: " + self.tmp, "- trigger: auto", "- time: ", "- transcript: " + self.tpath):
            idx.append(next(i for i, l in enumerate(lines) if l.startswith(pre)))
        self.assertEqual(idx, sorted(idx))
        self.assertRegex(t, r"- time: \d{4}-\d\d-\d\d \d\d:\d\d:\d\dZ")
        self.assertEqual(lines[-1], FOOTER_FMT.format(p=self.tpath))
        # F39.5: the authority line directly after the header lines, before the blank line
        self.assertEqual(lines.count(AUTHORITY), 1)
        ai = lines.index(AUTHORITY)
        self.assertGreater(ai, max(idx))
        self.assertEqual(lines[ai + 1], "")
        self.assertTrue(all(l.startswith("- ") for l in lines[1:ai]), lines[:ai + 1])

    def test_ac19_all_sections_order_and_limits(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        git(repo, "init", "-q")
        open(os.path.join(repo, "dirty.txt"), "w").write("x")
        e = []
        for i in range(12):
            e.append(user("umsg%02d" % i))
        for i in range(35):
            e.append(tool("Edit", file_path="/f/file%02d.py" % i))
        e.append(tool("Write", file_path="/f/file00.py"))  # re-touch
        for i in range(7):
            e.append(tool("Bash", command="echo cmd%d" % i))
        e.append(tool("TaskCreate", subject="t1"))
        e.append(asst("final words"))
        self.write_transcript(e)
        t = self.run_and_read(cwd=repo)
        pos = [t.index(h) for h in SECTIONS]
        self.assertEqual(pos, sorted(pos))
        self.assertNotIn("umsg03", t)
        self.assertIn("umsg04", t)
        self.assertIn("umsg11", t)
        files = re.findall(r"^- (/f/file\d\d\.py)$", t, re.M)
        self.assertEqual(len(files), 30)
        self.assertEqual(files.count("/f/file00.py"), 1)
        self.assertEqual(files[-1], "/f/file00.py")
        self.assertNotIn("/f/file01.py", t)  # 35 distinct, last 30 incl. re-touched 00
        cmds = re.findall(r"^- `(echo cmd\d)`$", t, re.M)
        self.assertEqual(cmds, ["echo cmd%d" % i for i in range(2, 7)])
        self.assertIn("dirty.txt", t)
        self.assertRegex(t, r"- branch: \S*")

    def test_ac20_tasks(self):
        self.write_transcript([tool("TaskCreate", subject="s1"), tool("TaskCreate", subject="s2"),
                               tool("TaskUpdate", taskId="2", status="completed")])
        t = self.run_and_read()
        self.assertIn("## Task state", t)
        self.assertLess(t.index("- [pending] s1"), t.index("- [completed] s2"))

    def test_ac21_noise_filtered(self):
        noise = ["<task-notification x", "[SYSTEM NOTIFICATION y", "<system-reminder z", "<command-name q",
                 "<local-command r", "<command-message s", "Caveat: c", "This session is being continued x",
                 "<artifact-content-authored-by-others/> x", "<bash-input>ls", "<bash-stdout>o", "<bash-stderr>e",
                 "<local-command-stdout>l"]  # F40.3 adds the last five
        e = [user(n + " NOISE%d" % i) for i, n in enumerate(noise)]
        e.append(user("meta text", isMeta=True))
        e.append({"type": "user", "message": {"content": [{"type": "tool_result", "content": "TOOLRES"}]}})
        e.append(user("genuine one"))
        e.append(asst("first answer"))
        e.append(asst("   "))
        self.write_transcript(e)
        t = self.run_and_read()
        for bad in ("NOISE", "meta text", "TOOLRES"):
            self.assertNotIn(bad, t)
        self.assertIn("- genuine one", t)
        self.assertIn("first answer", t.split("## Last assistant message")[1])

    def test_ac22_no_git_section(self):
        self.write_transcript([user("x")])
        self.assertNotIn("## Git", self.run_and_read(cwd=self.tmp))
        self.assertNotIn("## Git", self.run_and_read(cwd=os.path.join(self.tmp, "nope")))

    def test_ac23_malformed_lines(self):
        self.write_transcript([user("before")], extra_lines=["{bad json", "[1,2]", json.dumps({"type": "user"}), '"str"'])
        with open(self.tpath, "a") as f:
            f.write(json.dumps(user("after")) + "\n")
        t = self.run_and_read()
        self.assertIn("- before", t)
        self.assertIn("- after", t)

    # F37: cap is 20,000 and the drop order is DROP37 (Files touched first, Last user messages last).
    # Heavy fixture: Task state alone (n tasks x ~160 chars) pushes the file past the cap.
    def _big(self, path_len=100, assistant="A" * 2000, ntasks=130):
        e = [user(("U%02d" % i) + "u" * 700) for i in range(8)]
        for i in range(30):
            e.append(tool("Edit", file_path="/" + ("p%02d" % i) + "d" * path_len))
        e += [tool("TaskCreate", subject=("s%03d" % i) + "s" * 150) for i in range(ntasks)]
        for i in range(5):
            e.append(tool("Bash", command=("c%d" % i) + "x" * 300))
        e.append(asst(assistant))
        self.write_transcript(e)

    def _dropped(self, t):
        exp = set(NOGIT)  # these cwds are not git repos; Open tasks present too but not in SECTIONS (not asserted here)
        return [h for h in DROP37 if h in exp and h not in t]

    def test_ac24_cap_and_drop_order(self):
        self._big()
        t = self.run_and_read()
        self.assertLessEqual(len(t), CAP)
        d = self._dropped(t)
        self.assertGreaterEqual(len(d), 1, "pressure expected")
        self.assertEqual(d, [h for h in DROP37 if h in NOGIT][:len(d)])
        self.assertIn(SECTIONS[0], t)  # F37: the user's words are not dropped here
        self.assertNotIn("## Files touched (last 30)", t)
        self.assertTrue(t.rstrip().endswith(FOOTER_FMT.format(p=self.tpath)))

    def test_ac24_heavier_drops_more_in_order(self):
        self._big(ntasks=130)
        d1 = self._dropped(self.run_and_read())
        self._big(ntasks=400, path_len=250)
        t = self.run_and_read()
        self.assertLessEqual(len(t), CAP)
        d2 = self._dropped(t)
        self.assertEqual(d2, [h for h in DROP37 if h in NOGIT][:len(d2)])
        self.assertGreaterEqual(len(d2), len(d1))
        if SECTIONS[-1] in t:
            self.assertIn("A" * 1497 + "...", t)  # whole, not cut mid-section

    def test_ac24_agent_lead_preserved(self):
        self._big()
        self.agent_file("L" * 6000, meta={"agentWrittenAt": 100, "lastNudgeAt": 100})
        t = self.run_and_read()
        self.assertIn(AGENT_H, t)
        self.assertIn("L" * 4997 + "...", t)
        self.assertTrue(t.rstrip().endswith(FOOTER_FMT.format(p=self.tpath)))
        self.assertLessEqual(len(t), CAP)
        d = self._dropped(t)
        self.assertEqual(d, [h for h in DROP37 if h in NOGIT][:len(d)])

    def test_ac25_under_cap_nothing_dropped(self):
        e = [user("small user")] + [tool("Edit", file_path="/a.py"), tool("Bash", command="ls"),
                                    tool("TaskCreate", subject="t"), asst("fin")]
        self.write_transcript(e)
        repo = os.path.join(self.tmp, "r2")
        os.makedirs(repo)
        git(repo, "init", "-q")
        open(os.path.join(repo, "f"), "w").write("1")
        t = self.run_and_read(cwd=repo)
        self.assertEqual(heads(t), SECTIONS)


class Cleanup(HookCase):
    def test_ac26_cleanup(self):
        os.makedirs(self.hd)
        self.write_transcript([user("x")])
        now = time.time()
        def mk(name, days, d=False):
            p = os.path.join(self.hd, name)
            if d:
                os.makedirs(p)
            else:
                open(p, "w").write("x")
            os.utime(p, (now - days * 86400, now - days * 86400))
        mk("old-latest.md", 15); mk("x-agent.md", 15); mk("new.md", 13)
        mk("x-agent.meta.json", 15); mk("notes.txt", 15); mk("d.md", 15, d=True)
        self.run_pre(self.payload("S"))
        ex = lambda n: os.path.exists(os.path.join(self.hd, n))
        self.assertFalse(ex("old-latest.md"))
        self.assertFalse(ex("x-agent.md"))
        self.assertTrue(ex("new.md"))
        self.assertTrue(ex("x-agent.meta.json"))
        self.assertTrue(ex("notes.txt"))
        self.assertTrue(ex("d.md"))
        self.assertTrue(ex("S-latest.md"))


class Inject(HookCase):
    def put(self, sid, content):
        os.makedirs(self.hd, exist_ok=True)
        open(os.path.join(self.hd, sid + "-latest.md"), "w").write(content)

    def test_ac27_inject(self):
        self.put("S", "\n  hello handoff\nline2  \n\n")
        self.put_sidecar("S")  # F36 AC71: a non-degraded sidecar is needed for the plain form
        r = self.run_post({"session_id": "S"})
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(len(r.stdout.strip().splitlines()), 1)
        self.assertEqual(json.loads(r.stdout), {"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "Pre-compaction handoff (auto-saved):\nhello handoff\nline2"}})

    def test_ac28_silent_cases(self):
        self.put("E", "")
        self.put("W", "  \n\t\n")
        self.put("S", "content")
        # F36 AC71: a valid sid with a missing/empty latest file now yields the degraded warning (see test_f36);
        # silence applies only when session_id is missing/empty/invalid.
        cases = [{"foo": 1}, {"session_id": ""}, {"session_id": 5}, {"session_id": None}]
        for c in cases:
            r = self.run_post(c)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""), c)
        for raw in ("not json", "", "[]", "5"):
            r = self.run_post(raw=raw)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""), raw)

    def test_ac29_sanitising_parity(self):
        # EXPECTED TO FAIL on current code (inject skips ids containing "/").
        self.write_transcript([user("slash session")])
        self.run_pre(self.payload("a/b"))
        content = open(os.path.join(self.hd, "a_b-latest.md")).read()
        r = self.run_post({"session_id": "a/b"})
        self.assertEqual(r.returncode, 0)
        self.assertNotEqual(r.stdout, "")
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        # F36: this run is degraded (no agent file, fallback disabled): warning prefix allowed, section 6 string at the end
        self.assertTrue(ctx.endswith("Pre-compaction handoff (auto-saved):\n" + content.strip()))

    def test_ac30_end_to_end_under_10k(self):
        e = [user(("U%02d" % i) + "u" * 700) for i in range(8)]
        e += [tool("Edit", file_path="/" + "d" * 200 + str(i)) for i in range(30)]
        e.append(asst("A" * 2000))
        self.write_transcript(e)
        self.agent_file("L" * 6000, meta={"agentWrittenAt": 1, "lastNudgeAt": 1})
        self.run_pre(self.payload("S"))
        r = self.run_post({"session_id": "S"})
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertLess(len(ctx), 10000)
        self.assertIn("Handoff (pre-compaction)", ctx)


if __name__ == "__main__":
    unittest.main()
