"""setup/leak-scan.sh contract tests (ACs 70-83) and the CI workflow check."""
import getpass
import json, os, re, subprocess, unittest, uuid
from msharness import Base, MS_REPO

GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3"
FIND = re.compile(r"^(?P<path>.+):(?P<line>\d+): \[(?P<rule>[^\]]+)\]$")


class LeakBase(Base):
    def tree(self, files, git=True, name="tree"):
        """Create a fixture tree; returns its dir (a git repo with everything added when git=True)."""
        root = os.path.join(self.s.sb, name)
        os.makedirs(root, exist_ok=True)
        for rel, content in files.items():
            self.s.w(root, rel, content)
        if git:
            self.s.sh("git", "init", "-q", cwd=root)
            self.s.sh("git", "add", "-A", cwd=root)
        return root

    def scan(self, root, *args, priv="none", **kw):
        return self.s.run("leak-scan.sh", "--root", root, *args, priv=priv, **kw)

    def findings(self, r):
        return [m.groupdict() for m in (FIND.match(l) for l in r.stdout.splitlines()) if m]

    def rules_for(self, r, path):
        return [f["rule"] for f in self.findings(r) if f["path"] == path]

    def one(self, content, fname="a.txt", extra=None):
        files = {fname: content}
        files.update(extra or {})
        root = self.tree(files)
        return root, self.scan(root)


class TestBasics(LeakBase):
    def test_ac70_clean_tree(self):  # AC 70
        root = self.tree({"README.md": "hello\n", "src/a.py": "print(1)\n"})
        r = self.scan(root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "leak-scan: 2 files")
        self.assertIn("leak-scan: denylist: none", lines)
        self.assertIn("leak-scan: 0 finding(s)", lines)
        self.assertEqual(lines[-1], "leak-scan: PASS")

    def test_ac70_non_git_dir_scans_all_files(self):  # 11.8 files
        root = self.tree({"README.md": "hello\n", ".git/config": "x\n"}, git=False)
        r = self.scan(root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.splitlines()[0], "leak-scan: 1 files")

    def test_ac71_home_paths(self):  # AC 71
        for text in ("/Users/zed/proj/x", "/home/zed/x", "C:\\Users\\zed\\x"):
            with self.subTest(text):
                root, r = self.one("see %s here\n" % text)
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertEqual(self.rules_for(r, "a.txt"), ["home-path"])
                self.assertEqual(self.findings(r)[0]["line"], "1")
                self.assertNotIn("zed", r.stdout)
                self.assertEqual(r.stdout.splitlines()[-1], "leak-scan: FAIL")

    def test_ac71_tokens_pass(self):  # AC 71
        for text in ("__HOME__/x", "~/x", "$HOME/x"):
            with self.subTest(text):
                root, r = self.one("p = %s\n" % text)
                self.assertEqual(r.returncode, 0, r.stdout)

    def test_ac72_emails(self):  # AC 72
        flagged = ["a@corp.org"]
        passing = ["1+n@users.noreply.github.com", "x@example.com", "x@mail.example.com",
                   "plugin@market", "pkg@1.2.3"]
        for t in flagged:
            with self.subTest(t):
                root, r = self.one("mail %s now\n" % t)
                self.assertEqual(r.returncode, 1)
                self.assertEqual(self.rules_for(r, "a.txt"), ["email"])
                self.assertNotIn("corp.org", r.stdout)
        for t in passing:
            with self.subTest(t):
                root, r = self.one("ref %s now\n" % t)
                self.assertEqual(r.returncode, 0, r.stdout)

    def test_ac73_uuid(self):  # AC 73
        u = str(uuid.uuid4())
        for v in (u, u.upper()):
            with self.subTest(v):
                root, r = self.one("id=%s\n" % v)
                self.assertEqual(r.returncode, 1)
                self.assertEqual(self.rules_for(r, "a.txt"), ["uuid"])
                self.assertNotIn(v.lower(), r.stdout.lower())
        root, r = self.one("hex=%s\n" % u.replace("-", ""))
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_ac73_uuid_embedded_in_longer_token_passes(self):  # 11.8 "not embedded"
        u = str(uuid.uuid4())
        root, r = self.one("id=a%s\n" % u)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_ac74_secrets(self):  # AC 74
        root, r = self.one("key = %s\n" % GH)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.rules_for(r, "a.txt"), ["secret:github-token"])
        for l in r.stdout.splitlines():
            self.assertNotIn("key =", l)
            self.assertNotIn(GH, l)
        root, r = self.one("anything\n", fname="foo.env")
        self.assertEqual(self.rules_for(r, "foo.env"), ["secret:forbidden-filename"])
        self.assertEqual(r.returncode, 1)

    def test_ac74_secret_scan_allow_still_honoured(self):  # AC 74
        root, r = self.one("key = %s\n" % GH, extra={".secret-scan-allow": "a.txt\tghp_\n"})
        self.assertEqual(self.rules_for(r, "a.txt"), [], r.stdout)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_ac74_secret_scan_secret_assignment_rule_name(self):  # 11.8 secret:<name>
        root, r = self.one('password = "aaaaaaaaaaaaaaaaaaaaaaaa"\n')
        self.assertEqual(self.rules_for(r, "a.txt"), ["secret:secret-assignment"])


class TestDenylist(LeakBase):
    def deny(self, text, name="deny.txt"):
        return self.s.w(self.s.sb, name, text)

    def test_ac75_simple_denylist(self):  # AC 75
        d = self.deny("Zebra\n")
        root = self.tree({"a.txt": "a zebra b\n", "b.txt": "clean\n"})
        r = self.scan(root, "--denylist", d)
        self.assertEqual(r.returncode, 1)
        self.assertIn("leak-scan: denylist: 1 entries", r.stdout)
        self.assertEqual(self.rules_for(r, "a.txt"), ["denylist#1"])
        self.assertNotIn("zebra", r.stdout.lower())

    def test_ac75_path_hit_line_zero(self):  # AC 75
        d = self.deny("Quokka\n")
        root = self.tree({"docs/quokka-notes.md": "clean\n"})
        r = self.scan(root, "--denylist", d)
        self.assertEqual(r.returncode, 1)
        self.assertIn("docs/quokka-notes.md:0: [denylist-path#1]", r.stdout.splitlines())

    def test_ac75_regex_comments_blanks_line_numbers(self):  # AC 75
        d = self.deny("# comment\n\nZebra\nre:^proj-\\d+$\n")
        root = self.tree({"a.txt": "proj-42\n", "b.txt": "x ZEBRA y\n", "c.txt": "proj-x\n"})
        r = self.scan(root, "--denylist", d)
        self.assertIn("leak-scan: denylist: 2 entries", r.stdout)
        self.assertEqual(self.rules_for(r, "a.txt"), ["denylist#4"])
        self.assertEqual(self.rules_for(r, "b.txt"), ["denylist#3"])
        self.assertEqual(self.rules_for(r, "c.txt"), [])
        self.assertNotIn("proj-", r.stdout)
        self.assertNotIn("zebra", r.stdout.lower())

    def test_ac76_discovery_from_env_overlay(self):  # AC 76
        s = self.s
        s.ow("leak-denylist.txt", "Zebra\n")
        root = self.tree({"a.txt": "zebra\n"})
        r = self.scan(root, priv=s.ov)
        self.assertEqual(r.returncode, 1)
        self.assertIn("leak-scan: denylist: 1 entries", r.stdout)
        r = self.scan(root, "--no-denylist", priv=s.ov)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("leak-scan: denylist: none", r.stdout)

    def test_ac76_discovery_from_sibling_overlay(self):  # AC 76 / 11.2
        s = self.s
        s.w(s.sibling(), "leak-denylist.txt", "Zebra\n")
        root = self.tree({"a.txt": "zebra\n"})
        r = self.scan(root, priv=None)
        self.assertEqual(r.returncode, 1)
        self.assertIn("leak-scan: denylist: 1 entries", r.stdout)

    def test_ac76_flag_beats_overlay(self):  # 11.8 order
        s = self.s
        s.ow("leak-denylist.txt", "Zebra\n")
        d = self.deny("Giraffe\n")
        root = self.tree({"a.txt": "zebra giraffe\n"})
        r = self.scan(root, "--denylist", d, priv=s.ov)
        self.assertEqual(self.rules_for(r, "a.txt"), ["denylist#1"])
        self.assertIn("denylist: 1 entries", r.stdout)

    def test_ac76_no_overlay_none_and_exit_codes(self):  # AC 76
        root = self.tree({"a.txt": "zebra\n"})
        r = self.scan(root)
        self.assertEqual(r.returncode, 0)
        self.assertIn("leak-scan: denylist: none", r.stdout)
        r = self.scan(root, "--require-denylist")
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertEqual(self.findings(r), [])
        self.assertNotIn("leak-scan: PASS", r.stdout)
        r = self.scan(root, "--denylist", os.path.join(self.s.sb, "missing.txt"))
        self.assertEqual(r.returncode, 2)
        r = self.scan(root, "--bogus")
        self.assertEqual(r.returncode, 2)
        r = self.scan(os.path.join(self.s.sb, "no-such-dir"))
        self.assertEqual(r.returncode, 2)

    def test_ac76_require_denylist_satisfied(self):  # 11.8 exit 4 only when none
        d = self.deny("Zebra\n")
        root = self.tree({"a.txt": "clean\n"})
        r = self.scan(root, "--require-denylist", "--denylist", d)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_ac77_denylist_file_names(self):  # AC 77
        for name in ("leak-denylist.txt", "sub/dir/leak-allow.txt"):
            with self.subTest(name):
                root, r = self.one("x\n", fname=name)
                self.assertEqual(r.returncode, 1)
                self.assertIn("denylist-file", self.rules_for(r, name))


class TestAllowlist(LeakBase):
    ALLOW = "docs/*\temail\tfoo@bar\\.io\n"

    def test_ac78_path_rule_regex_allow(self):  # AC 78
        root = self.tree({".leak-scan-allow": self.ALLOW,
                          "docs/a.md": "foo@bar.io\n",
                          "src/a.md": "foo@bar.io\n",
                          "docs/b.md": "other@bar.io\n",
                          "docs/c.md": "foo@bar.io /Users/q/x\n"})
        r = self.scan(root)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.rules_for(r, "docs/a.md"), [])
        self.assertEqual(self.rules_for(r, "src/a.md"), ["email"])
        self.assertEqual(self.rules_for(r, "docs/b.md"), ["email"])
        self.assertEqual(self.rules_for(r, "docs/c.md"), ["home-path"])

    def test_ac78_star_rule(self):  # AC 78
        root = self.tree({".leak-scan-allow": "docs/*\t*\t/Users/q\n",
                          "docs/a.md": "p /Users/q/x\n", "src/a.md": "p /Users/q/x\n"})
        r = self.scan(root)
        self.assertEqual(self.rules_for(r, "docs/a.md"), [])
        self.assertEqual(self.rules_for(r, "src/a.md"), ["home-path"])

    def test_ac78_regex_must_match_offending_text_not_line(self):  # 11.8
        root = self.tree({".leak-scan-allow": "docs/*\temail\tsafe\n",
                          "docs/a.md": "safe line a@corp.org\n"})
        r = self.scan(root)
        self.assertEqual(self.rules_for(r, "docs/a.md"), ["email"])

    def test_ac78_inline_marker(self):  # AC 78
        root = self.tree({
            "a.txt": "mail a@corp.org  # leak-scan: allow=email\n",
            "b.txt": "mail a@corp.org /Users/q/x  # leak-scan: allow=email\n",
            "c.txt": "mail a@corp.org  # leak-scan: allow=home-path,uuid\n",
            "d.txt": "mail a@corp.org /Users/q/x  # leak-scan: allow=email,home-path\n"})
        r = self.scan(root)
        self.assertEqual(self.rules_for(r, "a.txt"), [])
        self.assertEqual(self.rules_for(r, "b.txt"), ["home-path"])
        self.assertEqual(self.rules_for(r, "c.txt"), ["email"])
        self.assertEqual(self.rules_for(r, "d.txt"), [])

    def test_ac78_inline_does_not_suppress_secret_or_denylist(self):  # AC 78
        d = self.s.w(self.s.sb, "deny.txt", "Zebra\n")
        root = self.tree({
            "a.txt": "k = %s  # leak-scan: allow=secret:github-token\n" % GH,
            "b.txt": "zebra  # leak-scan: allow=denylist#1\n"})
        r = self.scan(root, "--denylist", d)
        self.assertEqual(self.rules_for(r, "a.txt"), ["secret:github-token"])
        self.assertEqual(self.rules_for(r, "b.txt"), ["denylist#1"])

    def test_ac78_public_allow_cannot_allow_denylist(self):  # 11.8
        d = self.s.w(self.s.sb, "deny.txt", "Zebra\n")
        root = self.tree({".leak-scan-allow": "docs/*\tdenylist#1\t[Zz]ebra\n",
                          "docs/a.md": "a Zebra b\n"})
        r = self.scan(root, "--denylist", d)
        self.assertEqual(self.rules_for(r, "docs/a.md"), ["denylist#1"])

    def test_ac78_overlay_leak_allow_can_allow_denylist(self):  # AC 78
        s = self.s
        s.ow("leak-denylist.txt", "Zebra\n")
        s.ow("leak-allow.txt", "docs/*\tdenylist#1\t[Zz]ebra\n")
        root = self.tree({"docs/a.md": "a Zebra b\n", "src/a.md": "a Zebra b\n"})
        r = self.scan(root, priv=s.ov)
        self.assertEqual(self.rules_for(r, "docs/a.md"), [])
        self.assertEqual(self.rules_for(r, "src/a.md"), ["denylist#1"])
        s.ow("leak-allow.txt", "*\t*\t[Zz]ebra\n")
        r = self.scan(root, priv=s.ov)
        self.assertEqual(self.findings(r), [])
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_ac78_overlay_leak_allow_for_non_denylist_rule(self):  # 11.8
        s = self.s
        s.ow("leak-allow.txt", "docs/*\temail\ta@corp\\.org\n")
        root = self.tree({"docs/a.md": "a@corp.org\n"})
        r = self.scan(root, priv=s.ov)
        self.assertEqual(r.returncode, 0, r.stdout)


class TestOrderingStaged(LeakBase):
    def test_ac79_determinism_and_ordering(self):  # AC 79
        root = self.tree({
            "b.txt": "x a@corp.org y /Users/q/x\nline2 b@corp.org\n",
            "a.txt": "z@corp.org\n" + "k = %s\n" % GH,
            "dir/B.txt": "c@corp.org\n"})
        r1, r2 = self.scan(root), self.scan(root)
        self.assertEqual(r1.stdout, r2.stdout)
        keys = [(f["path"], int(f["line"]), f["rule"]) for f in self.findings(r1)]
        c_key = lambda k: (k[0].encode(), k[1], k[2].encode())
        self.assertEqual(keys, sorted(keys, key=c_key))
        self.assertEqual(len(keys), 6)

    def test_ac79_binary_and_symlink_skipped(self):  # AC 79
        root = self.tree({"README.md": "hi\n"})
        with open(os.path.join(root, "bin.dat"), "wb") as f:
            f.write(b"\x00\x01 /Users/zed/x a@corp.org\n")
        with open(os.path.join(root, "target.txt"), "w") as f:
            f.write("clean\n")
        os.symlink("/Users/zed/x", os.path.join(root, "link"))
        self.s.sh("git", "add", "-A", cwd=root)
        r = self.scan(root)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_ac80_staged(self):  # AC 80
        root = self.tree({"a.txt": "clean\n"})
        self.s.sh("git", "config", "user.email", "1+t@users.noreply.github.com", cwd=root)
        self.s.sh("git", "commit", "-q", "-m", "i", cwd=root)
        self.s.w(root, "a.txt", "p /Users/zed/x\n")                    # unstaged leak
        r = self.scan(root, "--staged")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(r.stdout.splitlines()[-1], "leak-scan: PASS")
        self.s.sh("git", "add", "a.txt", cwd=root)                      # staged leak
        r = self.scan(root, "--staged")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.rules_for(r, "a.txt"), ["home-path"])
        self.s.w(root, "a.txt", "clean again\n")                        # worktree fixed, index still leaks
        r = self.scan(root, "--staged")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.rules_for(r, "a.txt"), ["home-path"])


class TestPreCommit(LeakBase):
    def repo_with_hook(self):
        s = self.s
        s.sh("git", "init", "-q", cwd=s.repo)
        s.sh("git", "config", "core.hooksPath", "setup/githooks", cwd=s.repo)
        s.sh("git", "config", "user.email", "1+t@users.noreply.github.com", cwd=s.repo)
        s.sh("git", "config", "user.name", "T", cwd=s.repo)

    def commit(self, files):
        s = self.s
        for rel, c in files.items():
            s.w(s.repo, rel, c)
        s.sh("git", "add", *files, cwd=s.repo)
        return s.sh("git", "commit", "-q", "-m", "t", cwd=s.repo, check=False)

    def test_ac81_ac28_hook_blocks_leaks_allows_clean(self):  # AC 81, 28
        self.repo_with_hook()
        r = self.commit({"ok.txt": "clean\n"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        bad = [{"h.txt": "/Users/zed/x\n"}, {"e.txt": "a@corp.org\n"},
               {"u.txt": str(uuid.uuid4()) + "\n"}, {"s.txt": "k = %s\n" % GH},
               {"foo.env": "x\n"}, {"leak-denylist.txt": "x\n"}]
        for files in bad:
            with self.subTest(list(files)):
                r = self.commit(files)
                self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
                self.s.sh("git", "reset", "-q", cwd=self.s.repo)
                for rel in files:
                    os.remove(os.path.join(self.s.repo, rel))
        r = self.commit({"ok2.txt": "still clean\n"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class TestCI(unittest.TestCase):
    PATH = os.path.join(MS_REPO, ".github", "workflows", "leak-scan.yml")

    def load(self):
        self.assertTrue(os.path.isfile(self.PATH), "missing " + self.PATH)
        r = subprocess.run(["ruby", "-ryaml", "-rjson", "-e",
                            "puts JSON.generate(YAML.safe_load(File.read(ARGV[0])))", self.PATH],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, "invalid YAML: " + r.stderr)
        return json.loads(r.stdout)

    def test_ac82_workflow(self):  # AC 82
        d = self.load()
        on = d.get("on", d.get("true"))
        self.assertIsNotNone(on, d.keys())
        names = on if isinstance(on, list) else list(on)
        self.assertIn("push", names)
        self.assertIn("pull_request", names)
        self.assertEqual(d["permissions"], {"contents": "read"})
        steps = [st for j in d["jobs"].values() for st in j["steps"]]
        self.assertTrue([st for st in steps if "setup/leak-scan.sh" in str(st.get("run", ""))])
        uses = [st["uses"] for st in steps if "uses" in st]
        self.assertTrue(uses)
        for u in uses:
            self.assertRegex(u, r"@\S+$")
        with open(self.PATH) as f:
            self.assertNotIn("secrets.", f.read())


class TestPublicTreeSelfCheck(unittest.TestCase):
    def test_ac83_public_tree(self):  # AC 83 (read-only run on the delivered tree, no overlay)
        script = os.path.join(MS_REPO, "setup", "leak-scan.sh")
        env = {k: v for k, v in os.environ.items() if not k.startswith("MACHINE_SETUP")}
        env["MACHINE_SETUP_PRIVATE"] = "none"
        r = subprocess.run([script], cwd=MS_REPO, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr)
        for rel in ("repos.tsv", "leak-denylist.txt", "leak-allow.txt"):
            self.assertFalse(os.path.exists(os.path.join(MS_REPO, rel)), rel)
        hits = []
        # The personal launchd prefix: override with PERSONAL_LAUNCHD_PREFIX, default "com.<login name>".
        prefix = os.environ.get("PERSONAL_LAUNCHD_PREFIX") or "com." + getpass.getuser()
        for dp, dn, fn in os.walk(MS_REPO):
            if ".git" in dn:
                dn.remove(".git")
            for n in fn:
                p = os.path.join(dp, n)
                if os.path.islink(p):
                    continue
                with open(p, "rb") as f:
                    if prefix.encode() in f.read():
                        hits.append(os.path.relpath(p, MS_REPO))
        self.assertEqual(hits, [], "personal launchd prefix found")
        g = subprocess.run(["git", "-C", MS_REPO, "log", "--format=%ae%n%ce"],
                           capture_output=True, text=True)
        if g.returncode == 0:
            for e in set(l for l in g.stdout.splitlines() if l):
                self.assertTrue(e.endswith("@users.noreply.github.com"), "commit email not noreply")


if __name__ == "__main__":
    unittest.main()
