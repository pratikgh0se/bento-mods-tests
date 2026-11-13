"""F44 Recall: ACs 137-158 of specs/handoff-hooks-spec.md "F44" (code-blind: written from the spec only).
recall.py is located via HANDOFF_HOOKS_DIR (helpers.HOOKS_DIR). Fake HOME with Claude Code style transcripts,
real temp dirs for the roots, a stdlib fake embedding server for F44.9. Keyword-only runs point RECALL_EMBED_URL at a
closed port so they are deterministic. Secrets: placeholders only."""
import hashlib, json, os, re, shutil, socket, sqlite3, subprocess, sys, tempfile, threading, time, unittest, zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import test_f42_lossless_rules as _f42
from helpers import HOOKS_DIR, PRE, POST, HookCase, AUTHORITY
from test_content import git

RECALL = os.path.join(HOOKS_DIR, "recall.py")
RECALL_LINE = ('- recall: earlier chats in this project are searchable word for word: python3 ~/.claude/hooks/recall.py '
               'search "<words or regex>" (then: recall.py open <id>; recall.py user --last 20). Use it before acting on '
               'anything vague here (exact commands, numbers, paths, names, the user\'s wording) and whenever the user '
               'refers to something said earlier; quote what you find instead of guessing. '
               'If recall and the decisions list disagree, the decisions list and the user\'s latest words win: recall shows '
               'history, not current rules.')
ALLOW_RULE = "Bash(python3 ~/.claude/hooks/recall.py:*)"
S1, S2, SUB, PRIV, SA = ("a1a1a1a1-0000-4000-8000-000000000001", "b2b2b2b2-0000-4000-8000-000000000002",
                         "c3c3c3c3-0000-4000-8000-000000000003", "d4d4d4d4-0000-4000-8000-000000000004",
                         "e5e5e5e5-0000-4000-8000-000000000005")
SECRET_KEY = "sk-EXAMPLE-NOT-A-KEY"
HIT_RE = re.compile(r"^(?P<sid>[0-9A-Za-z_-]{2,}):(?P<line>\d+) (?P<date>\d{4}-\d\d-\d\d) (?P<time>\d\d:\d\d) "
                    r"(?P<role>user|assistant|tool)(?: \[(?P<tag>word|meaning|both)\])?: (?P<snip>.*)$")
COUNT_RE = re.compile(r"^(\d+) hits shown of (\d+) \((\d+) sessions searched\)$")
CUT = "[output cut at 12,000 chars; narrow the search]"
LONG = "LONGSTART" + "x" * 9984 + "LONGEND"
assert len(LONG) == 10000
PLANTED = "Postpone the quarterly offsite until autumn PLANTED77"
PARAPHRASE = "delay yearly retreat to fall"
SYN = {"postpone": "delay", "quarterly": "period", "yearly": "period", "offsite": "event", "retreat": "event",
       "autumn": "season", "fall": "season", "until": "until", "to": "until"}
STOP = {"the", "a", "an", "and", "of", "in", "is", "it", "we", "i"}
DIM = 512


def key_for(root):
    return re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(root))[:40] + "-" + hashlib.sha1(root.encode()).hexdigest()[:8]


def slug(path):
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def embed_text(text):
    v = [0.0] * DIM
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        if tok in STOP:
            continue
        tok = SYN.get(tok, tok)
        v[zlib.crc32(tok.encode()) % DIM] += 1.0
    return v


class FakeEmbed:
    """Deterministic embedding server. .requests: list of {path, auth, texts, model}. .delay: seconds per request."""
    def __init__(self, delay=0.0):
        self.requests, self.delay = [], delay
        self.lock = threading.Lock()
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                texts = body.get("input", [])
                if isinstance(texts, str):
                    texts = [texts]
                with outer.lock:
                    outer.requests.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                           "texts": texts, "model": body.get("model"), "body": body})
                if outer.delay:
                    time.sleep(outer.delay)
                vecs = [embed_text(t) for t in texts]
                if self.path == "/v1/embeddings":
                    out = {"data": [{"embedding": v, "index": i} for i, v in enumerate(vecs)]}
                else:
                    out = {"embeddings": vecs}
                data = json.dumps(out).encode()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def all_texts(self):
        with self.lock:
            return [t for r in self.requests for t in r["texts"]]

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()


def closed_port_url():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return "http://127.0.0.1:%d" % p


class RecallBase(HookCase):
    def setUp(self):
        super().setUp()
        self.rt = os.path.realpath(self.tmp)
        base = os.path.join(self.rt, "r")
        self.proj = os.path.join(base, "proj")
        self.sub = os.path.join(self.proj, "sub")
        self.priv = os.path.join(base, "proj-private")
        for d in (self.sub, self.priv):
            os.makedirs(d)
        git(self.proj, "init", "-q")
        self.home = os.path.join(self.rt, "home")  # realpath'd home
        os.makedirs(self.home, exist_ok=True)
        self.hd = os.path.join(self.home, ".local", "state", "claude-handoffs")
        self.down = closed_port_url()
        rg = shutil.which("rg")
        self.bin_rg = os.path.join(self.tmp, "bin_rg")
        os.makedirs(self.bin_rg)
        for n in os.listdir(self.bin):
            os.symlink(os.path.join(self.bin, n), os.path.join(self.bin_rg, n))
        self.have_rg = bool(rg)
        if rg:
            os.symlink(rg, os.path.join(self.bin_rg, "rg"))
        self.build_fixture()

    # ---------------- fixture
    def tdir(self, cwd):
        d = os.path.join(self.home, ".claude", "projects", slug(cwd))
        os.makedirs(d, exist_ok=True)
        return d

    @staticmethod
    def rec(kind, content, sid, cwd, day, minute, **flags):
        d = {"type": kind, "sessionId": sid, "timestamp": "2026-03-%02dT12:%02d:00.000Z" % (day, minute),
             "message": {"role": kind, "content": content}}
        if cwd is not None:
            d["cwd"] = cwd
        d.update(flags)
        return d

    def write_session(self, path, lines):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            for l in lines:
                f.write((l if isinstance(l, str) else json.dumps(l)) + "\n")

    def build_fixture(self):
        R, p = self.rec, self.proj
        self.s1_path = os.path.join(self.tdir(p), S1 + ".jsonl")
        c = lambda i: dict(sid=S1, cwd=p, day=1, minute=i)
        s1 = [
            R("user", "Let's use a Pomodoro timer for the planner TYPED1", **c(1)),
            R("assistant", [{"type": "thinking", "thinking": "THINKONLY Pomodoro"},
                            {"type": "text", "text": "Pomodoro it is, 25 minutes ASST2"}], **c(2)),
            R("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "TOOLRES Pomodoro output line"}], **c(3)),
            R("assistant", [{"type": "tool_use", "id": "t1", "name": "Bash",
                             "input": {"command": "echo Pomodoro TOOLIN"}}], **c(4)),
            R("user", "Typed TYPED5 words <system-reminder>Pomodoro REMINDERONLY</system-reminder> done", **c(5)),
            R("user", "Pomodoro META6 caveat text here", isMeta=True, **c(6)),
            R("user", "This session is being continued Pomodoro SUMMARY7 earlier", isCompactSummary=True, **c(7)),
            R("user", "<local-command-caveat>Caveat: Pomodoro CAVEAT8 text</local-command-caveat>", **c(8)),
            R("user", [{"type": "text", "text": "BLOCKTYPED9 Pomodoro via blocks typed"}], **c(9)),
            R("user", "my key %s and password=hunter2x end SECRET10" % SECRET_KEY, **c(10)),
            R("user", "A" * 300 + "NEEDLE42" + "B" * 300, **c(11)),
            R("user", "line one\nline two NEEDLE7 tail", **c(12)),
            R("user", "FIXEDTEST a.b present here", **c(13)),
            R("user", "FIXEDTEST axb present here", **c(14)),
            R("user", PLANTED, **c(15)),
        ]
        self.write_session(self.s1_path, s1)
        self.s1_indexable = 10  # lines 1,2,5,9,10,11,12,13,14,15
        self.s2_path = os.path.join(self.tdir(p), S2 + ".jsonl")
        s2 = [R("user", "Pomodoro second chat typed SECOND1", sid=S2, cwd=None, day=2, minute=1),
              '{"type": "user", "message": Pomodoro broken json',
              R("assistant", [{"type": "text", "text": LONG}], sid=S2, cwd=p, day=2, minute=3),
              R("user", "Pomodoro follow up FOLLOWUP <system-reminder>SECRETREMINDER</system-reminder>",
                sid=S2, cwd=p, day=2, minute=4)]
        self.write_session(self.s2_path, s2)
        self.s2_indexable = 3
        self.sub_path = os.path.join(self.tdir(self.sub), SUB + ".jsonl")
        self.write_session(self.sub_path, [R("user", "Pomodoro in sub dir session SUBONE", sid=SUB, cwd=self.sub,
                                             day=3, minute=1)])
        self.write_session(os.path.join(self.tdir(self.priv), PRIV + ".jsonl"),
                           [R("user", "Pomodoro in private PRIVONE secret-ish words", sid=PRIV, cwd=self.priv, day=4, minute=1)])
        self.write_session(os.path.join(self.tdir(p), S1, "subagents", "agent-ab.jsonl"),
                           [R("assistant", [{"type": "text", "text": "Pomodoro subagent finding SUBAGENTONE"}],
                              sid=S1, cwd=p, day=5, minute=1, isSidechain=True, agentId="ab")])
        self.n_indexable = self.s1_indexable + self.s2_indexable + 1

    # ---------------- running
    def renv(self, norg=False, extra=None, embed=None):
        e = {"HOME": self.home, "PATH": self.bin if (norg or not self.have_rg) else self.bin_rg, "LANG": "C.UTF-8",
             "TZ": "UTC", "RECALL_EMBED_URL": embed if embed is not None else self.down}
        e.update(extra or {})
        return e

    def rc(self, *args, cwd=None, norg=False, extra=None, embed=None, proc_cwd=None, timeout=90):
        a = list(args)
        if cwd is not False:
            a += ["--cwd", cwd or self.proj]
        return subprocess.run([sys.executable, RECALL, *a], capture_output=True, text=True,
                              env=self.renv(norg, extra, embed), timeout=timeout, cwd=proc_cwd or self.tmp)

    def ok(self, *args, **kw):
        r = self.rc(*args, **kw)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return r.stdout

    @staticmethod
    def hits(out):
        return [m for m in (HIT_RE.match(l) for l in out.split("\n")) if m]

    @staticmethod
    def count_line(out):
        lines = [l for l in out.rstrip("\n").split("\n") if l]
        return COUNT_RE.match(lines[-1])

    def snips(self, out):
        return [m.group("snip") for m in self.hits(out)]

    def has(self, out, marker):
        return any(marker in s for s in self.snips(out))


# ============================================================ F44.1-F44.4, ACs 137-147 (keyword, embedding off)
class Recall(RecallBase):
    def test_ac137_scope_three_sessions_not_private_not_subagent(self):
        out = self.ok("search", "Pomodoro")
        sids = {m.group("sid") for m in self.hits(out)}
        self.assertEqual(sids, {S1[:8], S2[:8], SUB[:8]})
        self.assertFalse(self.has(out, "PRIVONE"))
        self.assertFalse(self.has(out, "SUBAGENTONE"))
        self.assertTrue(self.has(out, "SUBONE"))
        self.assertTrue(self.has(out, "SECOND1"))
        self.assertTrue(self.has(out, "TYPED1"))

    def test_ac137_subagents_flag_adds_the_subagent_hit(self):
        out = self.ok("search", "Pomodoro", "--subagents")
        self.assertTrue(self.has(out, "SUBAGENTONE"))
        self.assertFalse(self.has(out, "PRIVONE"))
        self.assertTrue(self.has(out, "SUBONE"))

    def test_scope_from_subdir_cwd_resolves_git_toplevel(self):
        out = self.ok("search", "Pomodoro", cwd=self.sub)
        self.assertEqual({m.group("sid") for m in self.hits(out)}, {S1[:8], S2[:8], SUB[:8]})

    def test_scope_default_cwd_is_process_cwd(self):
        r = subprocess.run([sys.executable, RECALL, "search", "Pomodoro"], capture_output=True, text=True,
                           env=self.renv(), cwd=self.proj, timeout=60)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertTrue(self.has(r.stdout, "TYPED1"))
        self.assertFalse(self.has(r.stdout, "PRIVONE"))

    def test_scope_private_root_sees_only_private(self):
        out = self.ok("search", "Pomodoro", cwd=self.priv)
        self.assertEqual({m.group("snip").split("PRIVONE")[0] != "" for m in self.hits(out)}, {True})
        self.assertTrue(self.has(out, "PRIVONE"))
        self.assertFalse(self.has(out, "TYPED1"))

    def test_scope_non_git_root_is_cwd_itself(self):
        plain = os.path.join(self.rt, "r", "plain")
        other = os.path.join(self.rt, "r", "plain-other")
        for d in (plain, other):
            os.makedirs(d)
        R = self.rec
        self.write_session(os.path.join(self.tdir(plain), "f1f1f1f1-0000.jsonl"),
                           [R("user", "Pomodoro in plain dir PLAINONE", sid="f1f1f1f1-0000", cwd=plain, day=6, minute=1)])
        self.write_session(os.path.join(self.tdir(other), "f2f2f2f2-0000.jsonl"),
                           [R("user", "Pomodoro in plain other OTHERONE", sid="f2f2f2f2-0000", cwd=other, day=6, minute=2)])
        out = self.ok("search", "Pomodoro", cwd=plain)
        self.assertTrue(self.has(out, "PLAINONE"))
        self.assertFalse(self.has(out, "OTHERONE"))

    def test_scope_symlinked_cwd_uses_realpath(self):
        link = os.path.join(self.rt, "r", "link-proj")
        os.symlink(self.proj, link)
        self.write_session(os.path.join(self.tdir(link), "f3f3f3f3-0000.jsonl"),
                           [self.rec("user", "Pomodoro via symlink path LINKONE", sid="f3f3f3f3-0000",
                                     cwd=os.path.join(link, "sub"), day=6, minute=3)])
        out = self.ok("search", "Pomodoro")
        self.assertTrue(self.has(out, "LINKONE"))

    def test_scope_cache_written_and_read_only_otherwise(self):
        def snap():
            s = {}
            for root, _, fs in os.walk(self.home):
                for f in fs:
                    p = os.path.join(root, f)
                    s[p] = open(p, "rb").read()
            return s
        before = snap()
        self.ok("search", "Pomodoro")
        after = snap()
        changed = {p for p in after if p not in before or before[p] != after[p]}
        self.assertEqual({p for p in before if p not in after}, set())
        cache = os.path.join(self.hd, "recall-index.json")
        self.assertTrue(os.path.isfile(cache))
        self.assertTrue(all(p.startswith(self.hd + os.sep) for p in changed), changed)
        d = json.load(open(cache))
        found = []

        def walk(x):
            if isinstance(x, dict):
                if {"mtime", "size", "cwd"} <= set(x):
                    found.append(x)
                for v in x.values():
                    walk(v)
        walk(d)
        self.assertGreaterEqual(len(found), 3)
        self.assertIn(self.proj, {f["cwd"] for f in found})

    # ---- AC 138
    def test_ac138_hit_format_order_and_count_line(self):
        out = self.ok("search", "Pomodoro")
        lines = [l for l in out.rstrip("\n").split("\n") if not l.startswith("mode:")]
        self.assertTrue(lines)
        hs = [HIT_RE.match(l) for l in lines[:-1]]
        self.assertTrue(all(hs), lines)
        m = COUNT_RE.match(lines[-1])
        self.assertTrue(m, lines[-1])
        self.assertEqual(int(m.group(1)), len(hs))
        self.assertGreaterEqual(int(m.group(2)), int(m.group(1)))
        self.assertEqual(int(m.group(3)), 3)
        stamps = [(h.group("date"), h.group("time")) for h in hs]
        self.assertEqual(stamps, sorted(stamps, reverse=True))
        self.assertEqual(hs[0].group("date"), "2026-03-03")
        self.assertEqual((hs[0].group("sid"), hs[0].group("time")), (SUB[:8], "12:01"))
        self.assertIn("SUBONE", hs[0].group("snip"))

    def test_ac138_line_number_points_at_the_record(self):
        out = self.ok("search", "TYPED1")
        h = self.hits(out)
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0].group("sid"), S1[:8])
        n = int(h[0].group("line"))
        self.assertIn("TYPED1", open(self.s1_path).read().split("\n")[n - 1])

    def test_snippet_context_120_chars_each_side(self):
        out = self.ok("search", "needle42")  # case-insensitive
        h = self.hits(out)
        self.assertEqual(len(h), 1)
        s = h[0].group("snip")
        self.assertIn("A" * 120 + "NEEDLE42" + "B" * 120, s)
        self.assertNotIn("A" * 121, s)
        self.assertNotIn("B" * 121, s)

    def test_snippet_newlines_shown_as_slash(self):
        s = self.snips(self.ok("search", "NEEDLE7"))
        self.assertEqual(len(s), 1)
        self.assertIn("line one / line two NEEDLE7", s[0])
        self.assertNotIn("\n", s[0])

    def test_fixed_vs_regex(self):
        rx = self.snips(self.ok("search", "FIXEDTEST a.b"))
        fx = self.snips(self.ok("search", "FIXEDTEST a.b", "--fixed"))
        self.assertEqual(len(rx), 2)
        self.assertEqual(len(fx), 1)
        self.assertIn("a.b", fx[0])

    def test_limit_and_count_line(self):
        out = self.ok("search", "Pomodoro", "--limit", "2")
        self.assertEqual(len(self.hits(out)), 2)
        m = self.count_line(out)
        self.assertEqual(m.group(1), "2")
        self.assertGreater(int(m.group(2)), 2)

    def test_session_filter(self):
        out = self.ok("search", "Pomodoro", "--session", S2[:8])
        self.assertEqual({m.group("sid") for m in self.hits(out)}, {S2[:8]})

    def test_role_tool_matches_tool_text(self):
        out = self.ok("search", "Pomodoro", "--role", "tool")
        self.assertTrue(self.has(out, "TOOLRES"))
        self.assertTrue(self.has(out, "TOOLIN"))
        self.assertEqual({m.group("role") for m in self.hits(out)}, {"tool"})

    def test_role_assistant(self):
        out = self.ok("search", "Pomodoro", "--role", "assistant")
        self.assertTrue(self.has(out, "ASST2"))
        self.assertFalse(self.has(out, "THINKONLY"))
        self.assertFalse(self.has(out, "TOOLRES"))
        self.assertEqual({m.group("role") for m in self.hits(out)}, {"assistant"})

    # ---- AC 139
    def test_ac139_role_user_exclusions(self):
        out = self.ok("search", "Pomodoro", "--role", "user")
        self.assertTrue(self.has(self.ok("search", "TYPED5", "--role", "user"), "TYPED5"))
        for bad in ("ASST2", "TOOLRES", "TOOLIN", "META6", "SUMMARY7", "CAVEAT8", "REMINDERONLY", "THINKONLY", "SECRETREMINDER"):
            self.assertFalse(self.has(out, bad), bad)
        for good in ("TYPED1", "BLOCKTYPED9", "SECOND1", "FOLLOWUP", "SUBONE"):
            self.assertTrue(self.has(out, good), good)
        self.assertEqual({m.group("role") for m in self.hits(out)}, {"user"})

    def test_ac139_reminder_text_never_matches_user_role(self):
        out = self.ok("search", "REMINDERONLY", "--role", "user")
        self.assertEqual(self.hits(out), [])
        self.assertTrue(self.count_line(out).group(1) == "0")

    # ---- AC 140
    def open_id(self, sid, line, *args):
        return self.ok("open", "%s:%d" % (sid[:8], line), *args)

    def test_ac140_open_around_one_prints_three_messages(self):
        out = self.open_id(S2, 3, "--around", "1")
        heads = [l for l in out.split("\n") if l.startswith("--- ")]
        self.assertEqual(len(heads), 3, heads)
        self.assertTrue(all(re.match(r"^--- %s:\d+ \S+.* (user|assistant)$" % S2[:8], h) for h in heads), heads)
        self.assertTrue(heads[1].startswith("--- %s:3 " % S2[:8]), heads)
        self.assertIn("SECOND1", out)   # the malformed line 2 is skipped; before-neighbour is line 1
        self.assertIn("FOLLOWUP", out)

    def test_ac140_long_message_cut_at_4000(self):
        out = self.open_id(S2, 3, "--around", "1")
        self.assertIn("LONGSTART", out)
        self.assertNotIn("LONGEND", out)
        self.assertLessEqual(out.count("x"), 4000)
        self.assertGreaterEqual(out.count("x"), 3980)
        m = re.search(r"\[cut: (\d+) more chars(?:; continue with: recall\.py open \S+ --full --from \d+)?\]", out)
        self.assertTrue(m, out[-300:])
        self.assertEqual(int(m.group(1)), 6000)

    def test_ac140_full_prints_whole_message(self):
        out = self.open_id(S2, 3, "--around", "1", "--full")
        self.assertIn(LONG, out)
        self.assertNotIn("[cut:", out)

    def test_open_default_around_is_two(self):
        out = self.open_id(S1, 9)
        heads = [l for l in out.split("\n") if l.startswith("--- ")]
        self.assertEqual(len(heads), 5, heads)

    # ---- AC 141
    def test_ac141_user_last_two_verbatim_reminders_stripped(self):
        out = self.ok("user", "--last", "2")
        heads = [l for l in out.split("\n") if l.startswith("--- ")]
        self.assertEqual(len(heads), 2, out)
        self.assertTrue(heads[0].startswith("--- %s:1 " % SUB[:8]), heads)
        self.assertTrue(heads[1].startswith("--- %s:4 " % S2[:8]), heads)
        self.assertIn("Pomodoro in sub dir session SUBONE", out)
        self.assertIn("Pomodoro follow up FOLLOWUP", out)
        self.assertNotIn("SECRETREMINDER", out)
        self.assertNotIn("system-reminder", out)
        self.assertNotIn("PRIVONE", out)

    def test_user_session_filter_and_excludes_meta(self):
        out = self.ok("user", "--last", "50", "--session", S1[:8])
        for bad in ("META6", "SUMMARY7", "CAVEAT8", "REMINDERONLY", "TOOLRES", "ASST2"):
            self.assertNotIn(bad, out)
        self.assertIn("TYPED5", out)
        self.assertIn("BLOCKTYPED9", out)

    # ---- AC 142
    def test_ac142_handoffs_lists_only_project_files(self):
        os.makedirs(self.hd)
        files = {
            "S1-latest.md": (self.proj, 1000), "S1-agent.md": (self.sub, 3000),
            "S1-20261110T120000Z.md": (self.proj, 2000),
            "P-latest.md": (self.priv, 4000), "N-latest.md": (None, 5000),
        }
        now = time.time()
        for name, (cwd, age) in files.items():
            body = "# Handoff (pre-compaction)\n- session: X\n" + ("- cwd: %s\n" % cwd if cwd else "") + "- trigger: auto\n\nbody\n"
            p = os.path.join(self.hd, name)
            open(p, "w").write(body)
            os.utime(p, (now - age, now - age))
        out = self.ok("handoffs")
        lines = [l for l in out.split("\n") if l.strip()]

        def find(name):
            return [i for i, l in enumerate(lines) if re.search(re.escape(name) + r" \d+$", l)]
        for name in ("S1-latest.md", "S1-agent.md", "S1-20261110T120000Z.md"):
            self.assertEqual(len(find(name)), 1, (name, lines))
            size = os.path.getsize(os.path.join(self.hd, name))
            self.assertTrue(lines[find(name)[0]].endswith(" %d" % size))
        for name in ("P-latest.md", "N-latest.md"):
            self.assertEqual(find(name), [], (name, lines))
        order = [find(n)[0] for n in ("S1-latest.md", "S1-20261110T120000Z.md", "S1-agent.md")]
        self.assertEqual(order, sorted(order), "newest first")

    # ---- AC 143
    def test_ac143_redaction(self):
        out = self.ok("search", "sk-EXAMPLE")
        self.assertIn("[redacted]", out)
        self.assertNotIn(SECRET_KEY, out)
        out = self.ok("search", "hunter2x")
        self.assertEqual(len(self.hits(out)), 1)
        self.assertEqual(self.count_line(out).group(1), "1")
        self.assertIn("[redacted]", out)
        self.assertNotIn("hunter2x", out)
        self.assertIn("password=[redacted]", out)

    def test_ac143_redaction_in_open_and_user(self):
        for out in (self.open_id(S1, 10), self.ok("user", "--last", "50")):
            self.assertIn("[redacted]", out)
            self.assertNotIn(SECRET_KEY, out)
            self.assertNotIn("hunter2x", out)

    # ---- AC 144
    def test_ac144_output_cut_at_12000(self):
        R = self.rec
        self.write_session(os.path.join(self.tdir(self.proj), "f4f4f4f4-0000.jsonl"),
                           [R("user", ("BIGMSG %d " % i) + "w" * 1000, sid="f4f4f4f4-0000", cwd=self.proj, day=7, minute=i)
                            for i in range(30)])
        r = self.rc("user", "--last", "30")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertIn(CUT, r.stdout)
        self.assertLessEqual(len(r.stdout.split(CUT)[0].rstrip("\n")), 12000)
        self.assertTrue(r.stdout.rstrip("\n").endswith(CUT))
        self.assertLessEqual(len(r.stdout), 12000 + len(CUT) + 2)

    def test_ac144_small_output_has_no_marker(self):
        self.assertNotIn(CUT, self.ok("search", "TYPED1"))

    # ---- AC 145
    def test_ac145_zero_hits(self):
        r = self.rc("search", "NOSUCHTHING999")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        lines = [l for l in r.stdout.rstrip("\n").split("\n") if l and not l.startswith("mode:")]
        self.assertEqual(lines, ["0 hits shown of 0 (3 sessions searched)"])

    def test_ac145_unknown_id_exit_2(self):
        r = self.rc("open", "deadbeef:1")
        self.assertEqual(r.returncode, 2)

    def test_ac145_bad_arguments_exit_2(self):
        self.assertEqual(self.rc("search").returncode, 2)
        self.assertEqual(self.rc("nosuchcommand").returncode, 2)
        self.assertEqual(self.rc("open", "notanid").returncode, 2)

    # ---- AC 146
    def test_ac146_same_results_without_rg(self):
        for args in (("search", "Pomodoro"), ("search", "needle42"), ("search", "FIXEDTEST a.b", "--fixed"),
                     ("search", "Pomodoro", "--role", "tool"), ("user", "--last", "3")):
            no = self.rc(*args, norg=True)
            self.assertEqual((no.returncode, no.stderr), (0, ""), args)
            if self.have_rg:
                withrg = self.rc(*args)
                self.assertEqual(withrg.stdout, no.stdout, args)
            else:
                self.assertTrue(no.stdout.strip())

    def test_ac146_no_rg_finds_the_expected_hits(self):
        out = self.ok("search", "Pomodoro", norg=True)
        self.assertEqual({m.group("sid") for m in self.hits(out)}, {S1[:8], S2[:8], SUB[:8]})

    # ---- AC 147
    def test_ac147_malformed_line_skipped(self):
        r = self.rc("search", "Pomodoro")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertTrue(self.has(r.stdout, "SECOND1"))
        self.assertTrue(self.has(r.stdout, "FOLLOWUP"))
        self.assertFalse(self.has(r.stdout, "broken json"))
        self.assertTrue(self.has(r.stdout, "TYPED1"))


# ============================================================ F44.9 meaning search, ACs 151-157
class Meaning(RecallBase):
    def setUp(self):
        super().setUp()
        self.fe = FakeEmbed()
        self.addCleanup(self.fe.stop)

    def index(self, *extra, embed=None, env=None):
        return self.rc("index", *extra, embed=embed or self.fe.url, extra=env)

    def sqlite_path(self):
        return os.path.join(self.hd, "recall", key_for(self.proj) + ".sqlite")

    def rows(self):
        con = sqlite3.connect(self.sqlite_path())
        try:
            for (name,) in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'").fetchall():
                cols = [r[1].lower() for r in con.execute("pragma table_info('%s')" % name)]
                if "sid" in cols and "line" in cols:
                    return con.execute("select sid, line from %s" % name).fetchall()
        finally:
            con.close()
        self.fail("no table with sid and line columns")

    def search(self, *args, **kw):
        return self.rc("search", *args, embed=self.fe.url, **kw)

    # ---- AC 151
    def test_ac151_index_rows_scope_and_incremental(self):
        r = self.index()
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        self.assertRegex(r.stdout, r"indexed \d+ chunks, \d+ remaining")
        self.assertTrue(os.path.isfile(self.sqlite_path()))
        rows = self.rows()
        pairs = {(str(s)[:8], int(l)) for s, l in rows}
        self.assertEqual(len(pairs), self.n_indexable, sorted(pairs))
        self.assertEqual({p[0] for p in pairs}, {S1[:8], S2[:8], SUB[:8]})
        self.assertGreaterEqual(len(rows), self.n_indexable + 6)  # the 10,000-char message is several chunks
        texts = " ".join(self.fe.all_texts())
        for bad in ("TOOLRES", "TOOLIN", "PRIVONE", "SUBAGENTONE", "META6", "SUMMARY7", "CAVEAT8", "REMINDERONLY",
                    "THINKONLY", "broken json"):
            self.assertNotIn(bad, texts, bad)
        n = len(rows)
        self.assertEqual(self.index().returncode, 0)
        self.assertEqual(len(self.rows()), n, "second run adds 0 rows")
        with open(self.s1_path, "a") as f:
            f.write(json.dumps(self.rec("user", "One brand new message appended later", sid=S1, cwd=self.proj,
                                        day=8, minute=1)) + "\n")
        self.assertEqual(self.index().returncode, 0)
        rows2 = self.rows()
        self.assertEqual(len(rows2), n + 1)
        self.assertEqual(len({(str(s)[:8], int(l)) for s, l in rows2}), self.n_indexable + 1)

    # ---- AC 152
    def test_ac152_secrets_never_embedded(self):
        self.assertEqual(self.index().returncode, 0)
        texts = self.fe.all_texts()
        self.assertTrue(texts)
        joined = "\n".join(texts)
        self.assertNotIn("hunter2x", joined)
        self.assertNotIn(SECRET_KEY, joined)
        self.assertIn("[redacted]", joined)

    # ---- AC 153
    def test_ac153_meaning_finds_paraphrase_without_shared_words(self):
        self.assertEqual(self.index().returncode, 0)
        self.assertFalse(set(re.findall(r"[a-z]+", PARAPHRASE)) & set(re.findall(r"[a-z]+", PLANTED.lower())))
        r = self.search(PARAPHRASE, "--meaning")
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        planted = [m for m in self.hits(r.stdout) if "PLANTED77" in m.group("snip")]
        self.assertEqual(len(planted), 1, r.stdout)
        self.assertEqual(planted[0].group("tag"), "meaning")
        kw = self.ok("search", PARAPHRASE, "--keyword", embed=self.fe.url)
        self.assertFalse(self.has(kw, "PLANTED77"))

    # ---- AC 154
    def test_ac154_hybrid_both_once_and_mode_line(self):
        self.assertEqual(self.index().returncode, 0)
        r = self.search("Pomodoro")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        first = r.stdout.split("\n")[0]
        m = re.match(r"^mode: hybrid \(meaning index covers (\d+) of (\d+) messages\)$", first)
        self.assertTrue(m, first)
        self.assertTrue(0 < int(m.group(1)) <= int(m.group(2)))
        sub = [h for h in self.hits(r.stdout) if "SUBONE" in h.group("snip")]
        self.assertEqual(len(sub), 1)
        self.assertEqual(sub[0].group("tag"), "both")
        for marker in ("TYPED1", "SECOND1"):
            self.assertEqual(len([h for h in self.hits(r.stdout) if marker in h.group("snip")]), 1)

    def test_ac154_keyword_mode_only_tagged_word_when_present(self):
        self.assertEqual(self.index().returncode, 0)
        out = self.ok("search", "NEEDLE42", "--keyword", embed=self.fe.url)
        for h in self.hits(out):
            self.assertIn(h.group("tag"), (None, "word"))

    # ---- AC 155
    def test_ac155_server_down_search_falls_back_to_keyword(self):
        r = self.rc("search", "Pomodoro", embed=self.down)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertRegex(r.stdout.split("\n")[0], r"^mode: keyword only \(meaning search off: .+\)$")
        self.assertTrue(self.has(r.stdout, "TYPED1"))
        self.assertTrue(self.count_line(r.stdout))
        self.assertTrue(all(h.group("tag") in (None, "word") for h in self.hits(r.stdout)))

    def test_ac155_server_down_index_skips(self):
        r = self.rc("index", embed=self.down)
        self.assertEqual(r.returncode, 0)
        self.assertIn("meaning index skipped:", r.stdout)

    # ---- AC 156
    def test_ac156_concurrent_index_busy(self):
        self.fe.delay = 4.0
        p1 = subprocess.Popen([sys.executable, RECALL, "index", "--cwd", self.proj], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, env=self.renv(embed=self.fe.url), cwd=self.tmp)
        try:
            deadline = time.time() + 20
            while time.time() < deadline and not self.fe.requests:
                time.sleep(0.1)
            self.assertTrue(self.fe.requests, "first indexer never reached the server")
            r2 = self.rc("index", embed=self.fe.url)
            self.assertEqual(r2.returncode, 0)
            self.assertIn("index busy", r2.stdout)
        finally:
            p1.kill()
            p1.wait()

    # ---- AC 157
    def test_ac157_openai_backend_path_and_bearer(self):
        env = {"RECALL_EMBED_BACKEND": "openai", "RECALL_EMBED_KEY": "KEYVAL-TEST"}
        r = self.index(env=env)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        self.assertTrue(self.fe.requests)
        self.assertEqual({q["path"] for q in self.fe.requests}, {"/v1/embeddings"})
        self.assertEqual({q["auth"] for q in self.fe.requests}, {"Bearer KEYVAL-TEST"})
        r = self.rc("search", PARAPHRASE, "--meaning", embed=self.fe.url, extra=env)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(any("PLANTED77" in m.group("snip") and m.group("tag") == "meaning" for m in self.hits(r.stdout)), r.stdout)
        self.assertEqual({q["path"] for q in self.fe.requests}, {"/v1/embeddings"})

    def test_ac157_openai_without_key_sends_no_bearer(self):
        self.assertEqual(self.index(env={"RECALL_EMBED_BACKEND": "openai"}).returncode, 0)
        self.assertEqual({q["path"] for q in self.fe.requests}, {"/v1/embeddings"})
        self.assertTrue(all(not (q["auth"] or "").startswith("Bearer ") for q in self.fe.requests))

    def test_default_backend_uses_api_embed_with_model(self):
        self.assertEqual(self.index().returncode, 0)
        self.assertEqual({q["path"] for q in self.fe.requests}, {"/api/embed"})
        self.assertEqual({q["model"] for q in self.fe.requests}, {"bge-m3"})
        self.assertEqual(self.index("--max-seconds", "1", env={"RECALL_EMBED_MODEL": "other-model"}).returncode, 0)


# ============================================================ hook integration: ACs 148-150, 158
class Hook(_f42.F42):
    def install_hooks(self, with_recall, real=False):
        dest = os.path.join(self.home, ".claude", "hooks")
        shutil.copytree(HOOKS_DIR, dest, ignore=shutil.ignore_patterns("recall.py", "__pycache__"))
        if with_recall:
            if real and os.path.isfile(RECALL):
                shutil.copy(RECALL, os.path.join(dest, "recall.py"))
            else:
                open(os.path.join(dest, "recall.py"), "w").write("#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n")
        self.hooks = dest
        return dest

    def pre_from(self, extra=None, sid="S"):
        env = self.env("0", extra)
        env.setdefault("RECALL_EMBED_URL", closed_port_url())
        t0 = time.time()
        r = subprocess.run([sys.executable, os.path.join(self.hooks, "precompact-handoff.py")],
                           input=json.dumps(self.payload(sid, cwd=self.cwd)), capture_output=True, text=True, env=env,
                           timeout=120)
        self.elapsed = time.time() - t0
        return r

    def post_from(self, k):
        r = subprocess.run([sys.executable, os.path.join(self.hooks, "postcompact-inject.py"), "--ledger", "--part", str(k)],
                           input=json.dumps({"cwd": self.cwd, "session_id": "N", "hook_event_name": "SessionStart",
                                             "source": "compact"}),
                           capture_output=True, text=True, env=self.env(None), timeout=60)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        out = r.stdout
        if out.strip().startswith("{"):
            out = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        return out

    # ---- AC 148
    def test_ac148_precompact_line_after_authority_when_recall_exists(self):
        self.install_hooks(True)
        r = self.pre_from()
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        lines = self.latest("S").split("\n")
        self.assertIn(AUTHORITY, lines)
        i = lines.index(AUTHORITY)
        self.assertEqual(lines[i + 1], RECALL_LINE)
        self.assertEqual(sum(1 for l in lines if l.startswith("- recall:")), 1)

    def test_ac148_omitted_when_recall_missing(self):
        self.install_hooks(False)
        r = self.pre_from()
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        t = self.latest("S")
        self.assertNotIn("- recall:", t)
        self.assertNotIn("recall.py", t)
        self.assertIn(AUTHORITY, t.split("\n"))

    # ---- AC 149
    def test_ac149_ledger_part1_has_line_after_head(self):
        self.install_hooks(True)
        lines, kmap = _f42.mixed({"rule": 20, "decision": 100, "task": 60})
        self.seed(lines)
        outs = [self.post_from(k) for k in (1, 2, 3)]
        p1 = outs[0].split("\n")
        self.assertRegex(p1[0], _f42.HEAD_RE % 1)
        self.assertEqual(p1.count(RECALL_LINE), 1)
        ri = p1.index(RECALL_LINE)
        self.assertGreater(ri, 0)
        first_entry = next(i for i, l in enumerate(p1) if re.match(r"^- D\d+ ", l))
        self.assertLess(ri, first_entry)
        for o in outs[1:]:
            self.assertNotIn("- recall:", o)
        self.check_injection(lines, kmap, outs)  # parts < 10,000, rules first, every id present (AC 128 still holds)
        self.assertLess(len(outs[0]), 10000)

    def test_ac149_line_omitted_without_recall(self):
        self.install_hooks(False)
        lines, kmap = _f42.mixed({"rule": 3, "decision": 4, "task": 3})
        self.seed(lines)
        self.assertNotIn("- recall:", self.post_from(1))

    # ---- AC 150
    def test_ac150_template_allow_rule(self):
        tpl = os.path.join(os.path.dirname(HOOKS_DIR), "settings.template.json")
        d = json.load(open(tpl))
        self.assertIn(ALLOW_RULE, d["permissions"]["allow"])

    def test_ac150_hook_version_1_7_1(self):
        self.go()
        self.assertEqual(self.health()["hook_version"], "1.7.1")
        self.assertEqual(self.sidecar("S")["hook_version"], "1.7.1")

    # ---- AC 158
    def seed_transcript_for_index(self):
        d = os.path.join(self.home, ".claude", "projects", slug(self.cwd))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "g1g1g1g1-0000.jsonl"), "w") as f:
            f.write(json.dumps({"type": "user", "sessionId": "g1g1g1g1-0000", "cwd": self.cwd,
                                "timestamp": "2026-03-01T12:00:00.000Z",
                                "message": {"role": "user", "content": "A message worth indexing for recall"}}) + "\n")

    def test_ac158_precompact_spawns_detached_indexer(self):
        self.install_hooks(True, real=True)
        self.seed_transcript_for_index()
        fe = FakeEmbed()
        self.addCleanup(fe.stop)
        r = self.pre_from(extra={"RECALL_EMBED_URL": fe.url})
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        deadline = time.time() + 20
        log = os.path.join(self.hd, "recall", "index.log")
        while time.time() < deadline and not fe.requests and not os.path.exists(log):
            time.sleep(0.2)
        self.assertTrue(fe.requests or os.path.exists(log), "no detached indexer observed")

    def test_ac158_hook_unaffected_when_server_hangs(self):
        self.install_hooks(True, real=True)
        self.seed_transcript_for_index()
        fe = FakeEmbed(delay=25.0)
        self.addCleanup(fe.stop)
        base = self.pre_from(extra={"RECALL_EMBED_URL": closed_port_url()})
        self.assertEqual(base.returncode, 0)
        r = self.pre_from(extra={"RECALL_EMBED_URL": fe.url})
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        self.assertLess(self.elapsed, 15, "hook was delayed by the hanging embedding server")
        self.assertTrue(os.path.isfile(os.path.join(self.hd, "S-latest.md")))


if __name__ == "__main__":
    unittest.main()
