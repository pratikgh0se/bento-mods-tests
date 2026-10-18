"""lib/scrub_settings.py contract tests."""
import json, os, unittest
from msharness import Base

GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0"


class TestScrub(Base):
    def scrub(self, obj, home=None, raw=None):
        s = self.s
        home = home or s.home
        inp = os.path.join(s.sb, "in.json")
        out = os.path.join(s.sb, "out.json")
        sec = os.path.join(s.sb, "sec.txt")
        with open(inp, "w") as f:
            f.write(raw if raw is not None else json.dumps(obj))
        r = s.sh("python3", os.path.join(s.repo, "setup/lib/scrub_settings.py"), inp, out, home, sec)
        return open(out).read(), open(sec).read(), r

    def test_ac18_env_token(self):  # AC 18
        out, sec, _ = self.scrub({"env": {"MY_API_TOKEN": "abc123", "PLAIN": "v"}})
        d = json.loads(out)
        self.assertEqual(d["env"]["MY_API_TOKEN"], "__SECRET:ENV_MY_API_TOKEN__")
        self.assertEqual(d["env"]["PLAIN"], "v")
        self.assertEqual(sec, "ENV_MY_API_TOKEN\n")

    def test_ac19_shapes(self):  # AC 19
        out, sec, _ = self.scrub({"env": {"FOO": GH, "KEEP": "__SECRET:X__"},
                                  "top": GH,
                                  "headers": {"Authorization": "Bearer abcdefghij"}})
        d = json.loads(out)
        self.assertEqual(d["env"]["FOO"], "__SECRET:ENV_FOO__")
        self.assertEqual(d["env"]["KEEP"], "__SECRET:X__")
        self.assertRegex(d["top"], r"^__SECRET:.+__$")
        self.assertNotIn(GH, out)
        self.assertEqual(d["headers"]["Authorization"], "__SECRET:HEADERS_AUTHORIZATION__")

    def test_ac19_other_shapes_anywhere(self):  # AC 19, §5
        shapes = ["sk-" + "a" * 30, "gho_" + "b" * 25, "github_pat_" + "c" * 30,
                  "xoxb-1234567890-abcdefghij", "AKIA" + "ABCDEFGHIJKLMNOP", "Bearer abcdefgh12345"]
        for sh in shapes:
            with self.subTest(sh):
                out, _, _ = self.scrub({"note": sh})
                self.assertNotIn(sh, out)
                self.assertIn("__SECRET:", out)

    def test_sec5_names_lists_and_sanitising(self):  # §5 naming
        out, sec, _ = self.scrub({"mcp": {"servers": [{"env": {"A_KEY": "v"}}]},
                                  "environment": {"my-api-key": "v"}})
        d = json.loads(out)
        self.assertEqual(d["mcp"]["servers"][0]["env"]["A_KEY"], "__SECRET:MCP_SERVERS_ENV_A_KEY__")
        self.assertEqual(d["environment"]["my-api-key"], "__SECRET:ENVIRONMENT_MY_API_KEY__")

    def test_ac20_home_format_idempotent(self):  # AC 20
        h = self.s.home
        obj = {"cmd": "$HOME/x", "p": h + "/bin", "u": "café", "n": [1, {"a": h}], "z": 1, "a": 2}
        out, sec, _ = self.scrub(obj)
        # NOTE: spec says "$HOME" string is replaced by __HOME__ ; here HOME value is the arg
        self.assertTrue(out.endswith("\n"))
        d = json.loads(out)
        self.assertTrue(d["p"].startswith("__HOME__"), d["p"])
        self.assertEqual(d["p"], "__HOME__/bin")
        self.assertEqual(d["n"][1]["a"], "__HOME__")
        self.assertEqual(list(d), list(obj))
        self.assertIn("é", out)
        self.assertEqual(out, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        out2, sec2, _ = self.scrub(None, raw=out)
        self.assertEqual(out, out2)
        self.assertEqual(sec2, "")

    def test_ac20_literal_dollar_home_string(self):  # AC 20 (literal "$HOME" in value)
        out, _, _ = self.scrub({"cmd": "$HOME/x"}, home="$HOME")
        self.assertEqual(json.loads(out)["cmd"], "__HOME__/x")

    def test_ac21_secrets_list_sorted_unique_empty(self):  # AC 21
        out, sec, _ = self.scrub({"x": {"env": {"A_TOKEN": "1"}},
                                  "env": {"B_TOKEN": "1", "a-key": "1", "a_key": "1", "Z_KEY": "1"}})
        lines = sec.splitlines()
        self.assertEqual(lines, sorted(set(lines)))
        self.assertEqual(lines.count("ENV_A_KEY"), 1)
        self.assertIn("X_ENV_A_TOKEN", lines)
        out, sec, _ = self.scrub({"a": "b"})
        self.assertEqual(sec, "")


if __name__ == "__main__":
    unittest.main()
