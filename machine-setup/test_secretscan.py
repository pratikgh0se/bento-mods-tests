"""setup/secret-scan.sh contract tests (ACs 22-27)."""
import os, unittest
from msharness import Base

GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3"


class SecretBase(Base):
    def setUp(self):
        super().setUp()
        self.s.pub_reset()
        for f in (".secret-scan-allow", ".leak-scan-allow"):
            p = os.path.join(self.s.repo, f)
            if os.path.exists(p):
                os.remove(p)
        shutil_rm = __import__("shutil").rmtree
        shutil_rm(os.path.join(self.s.repo, "setup"), ignore_errors=True)  # scan only fixtures
        self.scanner = None

    def scan(self, root=None):
        # the script is resolved from the pristine public tree; the sandbox copy was emptied above,
        # so run the real script against the fixture dir argument (spec 6: one directory argument)
        from msharness import MS_REPO
        root = root or self.s.repo
        return self.s.run(os.path.join(MS_REPO, "setup", "secret-scan.sh"), root, cwd=root)


class TestSecretScan(SecretBase):
    def test_ac22_planted_github_token(self):  # AC 22
        self.s.rw("f.txt", "key = %s\n" % GH)
        r = self.scan()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("f.txt:1: [github-token]", r.stdout)
        self.assertIn("regex-scan: 1 finding(s)", r.stdout)
        self.assertEqual(r.stdout.rstrip().splitlines()[-1], "secret-scan: FAIL")

    def test_ac22_untracked_in_git_work_tree(self):  # AC 22 (git ls-files -co)
        self.s.rw("f.txt", "key = %s\n" % GH)
        self.s.git_init(self.s.repo, commit=False)
        r = self.scan()
        self.assertEqual(r.returncode, 1, r.stdout)

    def test_ac23_allowlist(self):  # AC 23
        s = self.s
        s.rw("f.txt", "key = %s\n" % GH)
        s.rw(".secret-scan-allow", "f.txt\tghp_[A-Za-z0-9]+\n")
        r = self.scan()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("regex-scan: 0 finding(s)", r.stdout)
        self.assertEqual(r.stdout.rstrip().splitlines()[-1], "secret-scan: PASS")
        s.rw(".secret-scan-allow", "ghp_[A-Za-z0-9]+\n")
        self.assertEqual(self.scan().returncode, 0)
        s.rw(".secret-scan-allow", "other.txt\tghp_[A-Za-z0-9]+\n")
        self.assertEqual(self.scan().returncode, 1)

    def test_ac24_secret_assignment(self):  # AC 24
        s = self.s
        s.rw("ok.txt", 'api_key = "__SECRET:X__"\ntoken = $TOKEN\n')
        self.assertEqual(self.scan().returncode, 0)
        s.rw("bad.txt", 'password = "aaaaaaaaaaaaaaaaaaaaaaaa"\n')
        r = self.scan()
        self.assertEqual(r.returncode, 1)
        self.assertIn("bad.txt:1: [secret-assignment]", r.stdout)

    def test_ac25_forbidden_filenames(self):  # AC 25
        for name in ("foo.env", "settings.local.json", ".env", "k.pem", "id_rsa", ".credentials.json"):
            with self.subTest(name):
                self.s.cleanup(); self.setUp()
                self.s.rw(name, "anything\n")
                r = self.scan()
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn("FORBIDDEN-FILENAME " + name, r.stdout)

    def test_ac25_gitignored_not_scanned(self):  # AC 25
        s = self.s
        s.rw(".gitignore", "*.pem\n")
        s.rw("k.pem", "x\n")
        s.rw("ok.txt", "fine\n")
        s.git_init(s.repo, commit=False)
        r = self.scan()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("FORBIDDEN-FILENAME", r.stdout)

    def test_ac26_rules(self):  # AC 26
        s = self.s
        s.rw("k.txt", "-----BEGIN RSA PRIVATE KEY-----\n")
        s.rw("a.txt", "id AKIA" + "ABCDEFGHIJKLMNOP\n")
        s.rw("u.txt", "url ://user:pass1234@host/x\n")
        r = self.scan()
        self.assertEqual(r.returncode, 1)
        self.assertIn("k.txt:1: [private-key]", r.stdout)
        self.assertIn("a.txt:1: [aws-key]", r.stdout)
        self.assertIn("u.txt:1: [url-credentials]", r.stdout)

    def test_ac27_binary_symlink_skipped_and_clean_pass(self):  # AC 27
        s = self.s
        s.rw("ok.txt", "fine\n")
        with open(os.path.join(s.repo, "b.bin"), "wb") as f:
            f.write(b"\x00" + GH.encode())
        os.symlink("ok.txt", os.path.join(s.repo, "lnk"))
        r = self.scan()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(r.stdout.rstrip().splitlines()[-1], "secret-scan: PASS")
        self.assertRegex(r.stdout, r"(?m)^secret-scan: \d+ files$")


if __name__ == "__main__":
    unittest.main()
