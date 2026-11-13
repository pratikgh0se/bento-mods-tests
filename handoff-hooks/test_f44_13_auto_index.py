"""F44.13 (hooks 1.8.0) ACs 167-171 of specs/handoff-hooks-spec.md (code-blind: written from the spec only).
index --all, session-end hook entry, settings template and launchd plist. Temp HOME, fake embedding server or closed port."""
import glob, json, os, re, shutil, sqlite3, subprocess, sys, time, unittest, threading
from test_f44_recall import RecallBase, FakeEmbed, RECALL, HOOKS_DIR, git, slug, closed_port_url

SID = ["a%d%d%d%d%d%d%d-0000-4000-8000-00000000000%d" % (i, i, i, i, i, i, i, i) for i in range(1, 8)]


class AutoBase(RecallBase):
    def mkrepo(self, name):
        p = os.path.join(self.rt, "multi", name)
        os.makedirs(p)
        git(p, "init", "-q")
        return p

    def add_session(self, folder_cwd, sid, rec_cwd, text, day=1):
        d = os.path.join(self.home, ".claude", "projects", slug(folder_cwd))
        os.makedirs(d, exist_ok=True)
        self.write_session(os.path.join(d, sid + ".jsonl"),
                           [self.rec("user", text, sid=sid, cwd=rec_cwd, day=day, minute=1)])

    def build_multi(self):
        """3 git projects (A under two folders), one gone cwd, one non-git cwd. Returns the 3 toplevels."""
        self.A, self.B, self.C = (self.mkrepo(n) for n in ("alpha", "beta", "gamma"))
        os.makedirs(os.path.join(self.A, "inner"))
        self.add_session(self.A, SID[0], self.A, "Alpha planning notes ALPHA1", day=1)
        self.add_session(os.path.join(self.A, "inner"), SID[1], os.path.join(self.A, "inner"), "Alpha inner ALPHA2", day=2)
        self.add_session(self.B, SID[2], self.B, "Beta budget words BETA1", day=3)
        self.add_session(self.C, SID[3], self.C, "Gamma roadmap GAMMA1", day=4)
        gone = os.path.join(self.rt, "multi", "gone")
        self.add_session(gone, SID[4], gone, "Gone project GONE1", day=5)
        nogit = os.path.join(self.rt, "multi", "nogit")
        os.makedirs(nogit)
        self.add_session(nogit, SID[5], nogit, "No git here NOGIT1", day=6)
        return [self.A, self.B, self.C]

    def all_rows(self):
        n = 0
        for f in glob.glob(os.path.join(self.hd, "recall", "*.sqlite")):
            con = sqlite3.connect(f)
            try:
                for (name,) in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'"):
                    cols = [r[1].lower() for r in con.execute("pragma table_info('%s')" % name)]
                    if "sid" in cols and "line" in cols:
                        n += con.execute("select count(*) from %s" % name).fetchone()[0]
            finally:
                con.close()
        return n

    def run_all(self, embed, *extra, timeout=60):
        t = time.time()
        r = subprocess.run([sys.executable, RECALL, "index", "--all", *extra], capture_output=True, text=True,
                           env=self.renv(embed=embed), timeout=timeout, cwd=self.tmp)
        self.elapsed_all = time.time() - t
        return r


class IndexAll(AutoBase):
    def setUp(self):
        super().setUp()
        # F44 fixture's own project must not be among the "3 projects": remove its transcripts
        shutil.rmtree(os.path.join(self.home, ".claude", "projects"))
        self.tops = self.build_multi()
        self.fe = FakeEmbed()
        self.addCleanup(self.fe.stop)

    def test_ac167_indexes_each_git_project_once(self):
        r = self.run_all(self.fe.url)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        lines = r.stdout.rstrip("\n").split("\n")
        self.assertEqual(lines[-1], "indexed 3 of 3 projects", r.stdout)
        for top in self.tops:
            self.assertEqual(len([l for l in lines if l.startswith(top + ": ")]), 1, (top, r.stdout))
        self.assertFalse(any("gone" in l or "nogit" in l for l in lines), r.stdout)
        texts = " ".join(self.fe.all_texts())
        for want in ("ALPHA1", "ALPHA2", "BETA1", "GAMMA1"):
            self.assertIn(want, texts)
        for bad in ("GONE1", "NOGIT1"):
            self.assertNotIn(bad, texts)
        self.assertEqual(len(glob.glob(os.path.join(self.hd, "recall", "*.sqlite"))), 3)
        n = self.all_rows()
        self.assertGreaterEqual(n, 4)
        r2 = self.run_all(self.fe.url)
        self.assertEqual((r2.returncode, r2.stderr), (0, ""), r2.stdout)
        self.assertEqual(self.all_rows(), n, "second run adds 0 rows")
        self.assertEqual(r2.stdout.rstrip("\n").split("\n")[-1], "indexed 3 of 3 projects")

    def test_ac168_server_down_skips_once(self):
        r = self.run_all(self.down, timeout=30)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        self.assertLess(self.elapsed_all, 10)
        self.assertEqual(r.stdout.count("meaning index skipped:"), 1, r.stdout)
        self.assertEqual(r.stdout.rstrip("\n").split("\n")[-1], "indexed 0 of 3 projects", r.stdout)

    def test_ac169_busy_project_is_skipped_others_indexed(self):
        slow = FakeEmbed(delay=8.0)
        self.addCleanup(slow.stop)
        holder = subprocess.Popen([sys.executable, RECALL, "index", "--cwd", self.B], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, env=self.renv(embed=slow.url), cwd=self.tmp)
        self.addCleanup(lambda: (holder.kill(), holder.wait()))
        deadline = time.time() + 20
        while time.time() < deadline and not slow.requests:
            time.sleep(0.1)
        self.assertTrue(slow.requests, "holder never started embedding")
        r = self.run_all(self.fe.url, timeout=60)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        lines = r.stdout.rstrip("\n").split("\n")
        busy = [l for l in lines if l.startswith(self.B + ": ")]
        self.assertEqual(len(busy), 1, r.stdout)
        self.assertIn("index busy", busy[0])
        for top in (self.A, self.C):
            self.assertTrue(any(l.startswith(top + ": ") and "index busy" not in l for l in lines), (top, r.stdout))
        texts = " ".join(self.fe.all_texts())
        self.assertIn("ALPHA1", texts)
        self.assertIn("GAMMA1", texts)
        self.assertNotIn("BETA1", texts)
        self.assertEqual(lines[-1], "indexed 2 of 3 projects", r.stdout)


class SessionEnd(AutoBase):
    def run_se(self, stdin, embed, timeout=30):
        t = time.time()
        r = subprocess.run([sys.executable, RECALL, "session-end"], input=stdin, capture_output=True, text=True,
                           env=self.renv(embed=embed), timeout=timeout, cwd=self.tmp)
        self.elapsed_se = time.time() - t
        return r

    def test_ac170_valid_cwd_fast_silent_then_indexes(self):
        fe = FakeEmbed()
        self.addCleanup(fe.stop)
        r = self.run_se(json.dumps({"session_id": "x", "cwd": self.proj, "hook_event_name": "SessionEnd"}), fe.url)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertLess(self.elapsed_se, 1.0)
        log = os.path.join(self.hd, "recall", "index.log")
        deadline = time.time() + 30
        while time.time() < deadline and not fe.requests and not os.path.exists(log):
            time.sleep(0.2)
        self.assertTrue(fe.requests or os.path.exists(log), "no detached indexer observed")

    def test_ac170_bad_inputs_exit_0_silent(self):
        gone = os.path.join(self.rt, "does", "not", "exist")
        nogit = os.path.join(self.rt, "plain")
        os.makedirs(nogit)
        cases = {"empty": "", "not json": "not json", "missing cwd": json.dumps({"session_id": "x"}),
                 "gone cwd": json.dumps({"cwd": gone}), "non-git cwd": json.dumps({"cwd": nogit})}
        for name, stdin in cases.items():
            r = self.run_se(stdin, self.down)
            self.assertEqual((r.returncode, r.stdout), (0, ""), (name, r.stderr))
            self.assertLess(self.elapsed_se, 1.0, name)


class Wiring(unittest.TestCase):
    SETTINGS_DIR = os.path.dirname(HOOKS_DIR)

    def settings_path(self):
        for n in ("settings.json", "settings.template.json"):  # SPEC-GAPS: spec says settings.json, repo has the template
            p = os.path.join(self.SETTINGS_DIR, n)
            if os.path.isfile(p):
                return p
        self.fail("no settings file in %s" % self.SETTINGS_DIR)

    def test_ac171_settings_has_one_session_end_entry(self):
        d = json.load(open(self.settings_path()))
        groups = d.get("hooks", {}).get("SessionEnd")
        self.assertTrue(groups, "no SessionEnd hooks")
        cmds = [h.get("command", "") for g in groups for h in g.get("hooks", [])]
        mine = [c for c in cmds if re.search(r"recall\.py\s+session-end(\s|$)", c)]
        self.assertEqual(len(mine), 1, cmds)
        self.assertIn("python3", mine[0])
        t = [h.get("timeout") for g in groups for h in g.get("hooks", []) if "session-end" in h.get("command", "")]
        self.assertTrue(t[0] is None or t[0] <= 30, t)

    def test_ac171_launchd_plist_valid_with_index_all(self):
        ld = os.path.join(os.path.dirname(self.SETTINGS_DIR), "launchd")
        p = os.path.join(ld, "com.pratik.recall-index.plist")
        if not os.path.isfile(p):  # SPEC-GAPS: other agents here ship as .plist.tmpl
            p = p + ".tmpl"
        self.assertTrue(os.path.isfile(p), "plist missing in %s" % ld)
        if not shutil.which("plutil"):
            self.skipTest("plutil not available")
        r = subprocess.run(["plutil", "-lint", p], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        j = subprocess.run(["plutil", "-convert", "json", "-o", "-", p], capture_output=True, text=True, timeout=20)
        self.assertEqual(j.returncode, 0, j.stderr)
        args = json.loads(j.stdout)["ProgramArguments"]
        self.assertIn("index", args)
        self.assertIn("--all", args)


if __name__ == "__main__":
    unittest.main()
