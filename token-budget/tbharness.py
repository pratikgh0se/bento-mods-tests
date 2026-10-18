"""Shared harness for the token-budget contract tests.

Code-blind: written from docs/token-budget-spec.md only. Everything runs in a
temp root with HOME, state, vault, settings and claude-home redirected there.
The fake `claude`, `ccusage`, `osascript` and `launchctl` executables are also
placed first on PATH so that nothing real can ever be reached.
"""
import copy
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("TOKEN_BUDGET_REPO", os.environ.get("MACHINE_SETUP_REPO", os.path.expanduser("~/CodeBase/machine-setup")))
TOOLS = os.path.join(REPO, "tools", "token-budget")
FIXTURES = os.path.join(HERE, "fixtures")
CTX_DIR = os.path.join(FIXTURES, "context")

NOW = "2026-10-19T09:00:03Z"          # Monday, ISO week 2026-W43
ANALYZE_NOW = "2026-10-19T09:00:10Z"
WEEK = "2026-W43"

CTX_BEFORE = os.path.join(CTX_DIR, "2026-10-15-before.txt")
CTX_AFTER = os.path.join(CTX_DIR, "2026-10-15-after.txt")
CTX_AFTER2 = os.path.join(CTX_DIR, "2026-10-15-after2.txt")

CATEGORY_KEYS = [
    "system_prompt", "system_tools", "system_tools_deferred",
    "mcp_server_instructions", "mcp_tools", "mcp_tools_deferred",
    "custom_agents", "memory_files", "skills", "messages", "free_space",
    "autocompact_buffer",
]

PYTHON = sys.executable

FAKE_CLAUDE = """#!%(py)s
import json, os, sys
log = os.environ.get("FAKE_LOG")
argv = sys.argv[1:]
entry = {"tool": "claude", "argv": argv, "cwd": os.path.realpath(os.getcwd()),
         "listing": sorted(os.listdir(".")), "prog": sys.argv[0]}
if log:
    with open(log, "a") as f:
        f.write(json.dumps(entry) + "\\n")
if os.environ.get("FAKE_CLAUDE_FAIL") == "all":
    sys.stderr.write("fake claude failure\\n")
    sys.exit(1)
if "--output-format" in argv:
    mode = os.environ.get("FAKE_JSON_MODE", "ok")
    if mode == "fail":
        sys.stderr.write("network error\\n")
        sys.exit(1)
    if mode == "garbage":
        print("this is not json {{{")
        sys.exit(0)
    with open(os.environ["FAKE_JSON_FILE"]) as f:
        sys.stdout.write(f.read())
    sys.exit(0)
path = os.environ.get("FAKE_CONTEXT_FILE")
if not path:
    sys.stderr.write("FAKE_CONTEXT_FILE unset\\n")
    sys.exit(1)
with open(path) as f:
    sys.stdout.write(f.read())
""" % {"py": PYTHON}

FAKE_CCUSAGE = """#!%(py)s
import json, os, sys
log = os.environ.get("FAKE_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps({"tool": "ccusage", "argv": sys.argv[1:]}) + "\\n")
mode = os.environ.get("FAKE_CCUSAGE_MODE", "ok")
if mode == "fail":
    sys.stderr.write("ccusage exploded\\n")
    sys.exit(1)
a = sys.argv[1:]
if "weekly" in a:
    print(json.dumps({"weekly": [{"week": "2026-10-19", "totalCost": 61.8}],
                      "totals": {"totalCost": 61.8}}))
else:
    print(json.dumps({"daily": [{"date": "2026-10-19", "totalCost": 14.2}],
                      "totals": {"totalCost": 14.2}}))
""" % {"py": PYTHON}

SHIM = """#!/bin/bash
# records every call; never performs anything
printf '%s\\t%s\\n' "$(basename "$0")" "$*" >> "$SHIM_LOG"
exit 0
"""

FAKE_JSON = {
    "type": "result", "subtype": "success", "is_error": False,
    "result": "ok", "session_id": "00000000-0000-0000-0000-000000000000",
    "total_cost_usd": 0.0123,
    "usage": {
        "input_tokens": 9, "output_tokens": 5,
        "cache_creation_input_tokens": 28600,
        "cache_read_input_tokens": 0,
    },
}


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def read(path):
    with open(path, "rb") as f:
        return f.read()


def write(path, data, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)
    if mode is not None:
        os.chmod(path, mode)


def iso(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def ago(days, now=NOW, extra_seconds=0):
    t = iso(now) - dt.timedelta(days=days, seconds=extra_seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%S.123Z")


def file_tree(root):
    out = {}
    for d, _dirs, files in os.walk(root):
        for fn in files:
            p = os.path.join(d, fn)
            out[os.path.relpath(p, root)] = sha256(p)
    return out


def jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in read(path).decode().splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


class Env:
    """An isolated world. Use as: self.env = Env(self)."""

    def __init__(self, case):
        self.root = tempfile.mkdtemp(prefix="tbtest-")
        case.addCleanup(shutil.rmtree, self.root, True)
        self.home = os.path.join(self.root, "home")
        self.state = os.path.join(self.root, "state")
        self.claude_home = os.path.join(self.root, "claude-home")
        self.settings = os.path.join(self.root, "claude-home", "settings.json")
        self.vault = os.path.join(self.root, "vault")
        self.work = os.path.join(self.root, "work")
        self.bin = os.path.join(self.root, "bin")
        self.shims = os.path.join(self.root, "shims")
        self.log = os.path.join(self.root, "fake.log")
        self.shim_log = os.path.join(self.root, "shim.log")
        for d in (self.home, self.claude_home, self.vault, self.work, self.bin, self.shims):
            os.makedirs(d, exist_ok=True)
        self.fake_claude = os.path.join(self.bin, "claude")
        self.fake_ccusage = os.path.join(self.bin, "ccusage")
        write(self.fake_claude, FAKE_CLAUDE, 0o755)
        write(self.fake_ccusage, FAKE_CCUSAGE, 0o755)
        self.json_file = os.path.join(self.bin, "claude.json")
        write(self.json_file, json.dumps(FAKE_JSON))
        for name in ("osascript", "launchctl"):
            write(os.path.join(self.shims, name), SHIM, 0o755)
        # also catch accidental PATH lookups of claude / ccusage
        write(os.path.join(self.shims, "claude"), FAKE_CLAUDE, 0o755)
        write(os.path.join(self.shims, "ccusage"), FAKE_CCUSAGE, 0o755)
        self.context_file = CTX_AFTER2
        self.cwd = self.work
        write(self.settings, json.dumps({"env": {"KEEP": "1"}}, indent=2) + "\n")

    # -- environment -------------------------------------------------
    def env(self, now=NOW, notify="0", vault=True, extra=None, unset=()):
        e = {
            "PATH": self.shims + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": self.home,
            "TZ": "UTC",
            "LANG": "en_US.UTF-8",
            "TOKEN_BUDGET_STATE_DIR": self.state,
            "CLAUDE_SETTINGS_FILE": self.settings,
            "CLAUDE_HOME": self.claude_home,
            "TOKEN_BUDGET_NOTIFY": notify,
            "TOKEN_BUDGET_CLAUDE_BIN": self.fake_claude,
            "TOKEN_BUDGET_CCUSAGE_BIN": self.fake_ccusage,
            "FAKE_LOG": self.log,
            "SHIM_LOG": self.shim_log,
            "FAKE_CONTEXT_FILE": self.context_file,
            "FAKE_JSON_FILE": self.json_file,
        }
        if now:
            e["TOKEN_BUDGET_NOW"] = now
        if vault:
            e["OBSIDIAN_VAULT_PATH"] = self.vault
        if extra:
            e.update(extra)
        for k in unset:
            e.pop(k, None)
        return e

    def run(self, script, args=(), now=NOW, notify="0", vault=True, extra=None,
            unset=(), cwd=None, timeout=180):
        path = os.path.join(TOOLS, script)
        if script.endswith(".py"):
            cmd = [PYTHON, path]
        else:
            cmd = ["/bin/bash", path]
        cmd += list(args)
        return subprocess.run(
            cmd, env=self.env(now, notify, vault, extra, unset),
            cwd=cwd or self.cwd, capture_output=True, text=True, timeout=timeout)

    def probe(self, *args, **kw):
        return self.run("probe.sh", args, **kw)

    def run_sh(self, *args, **kw):
        return self.run("run.sh", args, **kw)

    def apply(self, *args, **kw):
        return self.run("apply.sh", args, **kw)

    def analyze(self, now=ANALYZE_NOW, extra_args=(), **kw):
        args = ["--state-dir", self.state, "--now", now,
                "--claude-home", self.claude_home, "--settings", self.settings]
        args += list(extra_args)
        return self.run("analyze.py", args, **kw)

    # -- paths / readers --------------------------------------------
    def p(self, *parts):
        return os.path.join(self.state, *parts)

    @property
    def ledger_path(self):
        return self.p("ledger.jsonl")

    def ledger(self):
        return jsonl(self.ledger_path)

    def applied(self):
        return jsonl(self.p("applied.jsonl"))

    def fake_calls(self, tool="claude"):
        return [c for c in jsonl(self.log) if c.get("tool") == tool]

    def shim_calls(self):
        if not os.path.exists(self.shim_log):
            return []
        return [l for l in read(self.shim_log).decode().splitlines() if l]

    def backups(self):
        d = self.p("backups")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def set_settings(self, obj, mode=None):
        write(self.settings, json.dumps(obj, indent=2) + "\n", mode)

    def set_context(self, text_or_path):
        if os.path.exists(text_or_path):
            self.context_file = text_or_path
        else:
            p = os.path.join(self.bin, "ctx-%d.txt" % len(os.listdir(self.bin)))
            write(p, text_or_path)
            self.context_file = p

    def manifest_of(self, ledger_line):
        return json.loads(read(self.p(ledger_line["manifest"])))


# ---------------------------------------------------------------------
# synthetic /context text, mirrors the real captures' layout
# ---------------------------------------------------------------------
def make_context(rows, total="16.2k", window="200k", header=True,
                 warning_lines=(), skills=(), extra_sections=""):
    out = []
    out.extend(warning_lines)
    out.append("## Context Usage")
    out.append("")
    out.append("**Model:** claude-haiku-5-5  ")
    if header:
        out.append("**Tokens:** %s / %s (8%%)" % (total, window))
    out.append("")
    out.append("### Estimated usage by category")
    out.append("")
    out.append("| Category | Tokens | Percentage |")
    out.append("|----------|--------|------------|")
    for name, tok in rows:
        out.append("| %s | %s | 1.0%% |" % (name, tok))
    out.append("")
    out.append("### MCP Tools")
    out.append("")
    out.append("| Tool | Server | Tokens |")
    out.append("|------|--------|--------|")
    out.append("| mcp__deferredsrv__tool_a | deferredsrv | 999 |")
    out.append("| mcp__deferredsrv__tool_b | deferredsrv | 888 |")
    out.append("")
    out.append("### Skills")
    out.append("")
    out.append("| Skill | Source | Tokens |")
    out.append("|-------|--------|--------|")
    for name, src, tok in skills:
        out.append("| %s | %s | %s |" % (name, src, tok))
    out.append("")
    out.append(extra_sections)
    return "\n".join(out) + "\n"


BASIC_ROWS = [
    ("System prompt", "1.2k"),
    ("System tools", "627"),
    ("MCP server instructions", "513"),
    ("MCP tools (deferred)", "67k"),
    ("System tools (deferred)", "22.5k"),
    ("Custom agents", "0"),
    ("Memory files", "12,345"),
    ("Skills", "0"),
    ("Messages", "1.5k"),
    ("Free space", "100k"),
    ("Autocompact buffer", "33k"),
]
# non-deferred sum = 1200+627+513+0+12345+0+1500 = 16185


# ---------------------------------------------------------------------
# analyze scenario builder
# ---------------------------------------------------------------------
def base_categories():
    return {
        "system_prompt": 3300, "system_tools": 11200,
        "system_tools_deferred": 22500, "mcp_server_instructions": 513,
        "mcp_tools": 0, "mcp_tools_deferred": 67000, "custom_agents": 521,
        "memory_files": 1800, "skills": 9900, "messages": 1500,
        "free_space": 138300, "autocompact_buffer": 33000, "other": {},
    }


def base_manifest(ts):
    return {
        "schema": 1, "ts": ts, "cli_version": "2.1.88",
        "skills": [], "mcp_servers": [], "denied_mcp_servers": [],
        "plugins": [],
        "claude_md": {
            "user": {"path": "~/.claude/CLAUDE.md", "bytes": 1000, "est_tokens": 250},
            "vault": {"path": "~/notes-vault/_CLAUDE.md", "bytes": 4000, "est_tokens": 1000},
        },
        "hooks": [], "skill_overrides": {},
        "env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "400000"},
    }


def skill(name, source="user", tokens=40, path=None, override=None):
    return {"name": name, "source": source,
            "path": path or "~/.claude/skills/%s" % name,
            "override": override, "tokens": tokens}


def connector(name, tokens=600, tools=3, deferred=False):
    return {"name": name, "kind": "connector", "deferred": deferred,
            "tool_count": tools, "always_loaded_tokens": tokens}


def local_mcp(name, tokens=0, tools=3, deferred=False):
    return {"name": name, "kind": "local", "deferred": deferred,
            "tool_count": tools, "always_loaded_tokens": tokens}


def ledger_line(week, ts, total, cats=None, cli="2.1.88", manifest=None):
    cats = cats or base_categories()
    return {
        "schema": 1, "ts": ts, "week": week, "cli_version": cli, "model": "haiku",
        "total_always_loaded": total, "category_sum_check": total,
        "categories": cats, "context_window": 400000,
        "trivial_turn": {"input_tokens": 9, "output_tokens": 5,
                         "cache_creation_input_tokens": 28600,
                         "cache_read_input_tokens": 0, "total_cost_usd": 0.0123},
        "spend": {"daily_usd": 14.2, "weekly_usd": 61.8},
        "manifest": manifest or "manifests/%s.json" % ts.replace(":", "-"),
        "denied_mcp_notices": 0, "warnings": [],
    }


class Scenario:
    """prev (2026-W42) + cur (2026-W43) ledger lines with manifests,
    plus a transcript tree with enough history by default."""

    PREV_TS = "2026-10-12T09:00:03Z"
    CUR_TS = "2026-10-19T09:00:03Z"

    def __init__(self, env, history=True):
        self.env = env
        self.prev_total = 30000
        self.delta = 0
        self.prev = base_manifest(self.PREV_TS)
        self.cur = base_manifest(self.CUR_TS)
        self.prev_cats = base_categories()
        self.cur_cats = base_categories()
        self.extra_lines = []        # (week, ts, total) placed before prev
        self.single = False
        self.cur_cli = "2.1.88"
        self.prev_cli = "2.1.88"
        os.makedirs(env.claude_home, exist_ok=True)
        self.proj = os.path.join(env.claude_home, "projects", "-tmp-proj")
        os.makedirs(self.proj, exist_ok=True)
        self._n = 0
        if history:
            self.transcript([{"type": "user", "timestamp": ago(60, ANALYZE_NOW),
                              "message": {"role": "user", "content": "hello"}}])

    # transcripts ----------------------------------------------------
    def transcript(self, lines, name=None):
        self._n += 1
        p = os.path.join(self.proj, name or "s%03d.jsonl" % self._n)
        with open(p, "w") as f:
            for ln in lines:
                f.write(ln if isinstance(ln, str) else json.dumps(ln))
                f.write("\n")
        return p

    @staticmethod
    def tool_use(name, inp, ts):
        return {"type": "assistant", "timestamp": ts,
                "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "toolu_x", "name": name, "input": inp}]}}

    def skill_use(self, name, days_ago):
        self.transcript([self.tool_use("Skill", {"skill": name}, ago(days_ago, ANALYZE_NOW))])

    def slash(self, name, days_ago):
        self.transcript([{"type": "user", "timestamp": ago(days_ago, ANALYZE_NOW),
                          "message": {"role": "user", "content": "/%s some args" % name}}])

    def tool(self, name, days_ago, inp=None):
        self.transcript([self.tool_use(name, inp or {}, ago(days_ago, ANALYZE_NOW))])

    # build ----------------------------------------------------------
    def build(self):
        e = self.env
        os.makedirs(e.state, exist_ok=True)
        lines = []
        for week, ts, total in self.extra_lines:
            lines.append(ledger_line(week, ts, total))
            write(e.p("manifests", ts.replace(":", "-") + ".json"),
                  json.dumps(base_manifest(ts), indent=2, sort_keys=True))
        if not self.single:
            pc = copy.deepcopy(self.prev_cats)
            lines.append(ledger_line("2026-W42", self.PREV_TS, self.prev_total, pc, self.prev_cli))
            self.prev["cli_version"] = self.prev_cli
            write(e.p("manifests", self.PREV_TS.replace(":", "-") + ".json"),
                  json.dumps(self.prev, indent=2, sort_keys=True))
        cc = copy.deepcopy(self.cur_cats)
        cc["skills"] += self.delta
        lines.append(ledger_line(WEEK, self.CUR_TS, self.prev_total + self.delta, cc, self.cur_cli))
        self.cur["cli_version"] = self.cur_cli
        write(e.p("manifests", self.CUR_TS.replace(":", "-") + ".json"),
              json.dumps(self.cur, indent=2, sort_keys=True))
        with open(e.ledger_path, "w") as f:
            for l in lines:
                f.write(json.dumps(l) + "\n")
        return self

    def run(self, **kw):
        self.build()
        p = self.env.analyze(**kw)
        data = None
        if p.returncode == 0:
            data = json.loads(p.stdout)
        return p, data


def proposal_ids(data):
    return [p["id"] for p in data["proposals"]]


def by_id(data, pid):
    for p in data["proposals"]:
        if p["id"] == pid:
            return p
    return None


def reg_kinds(data):
    return [r["kind"] for r in data["regressions"]]


# ---------------------------------------------------------------------
# apply fixtures
# ---------------------------------------------------------------------
COMPACT_PROPOSAL = {
    "id": "compact-window", "rule": "R3",
    "title": "Set CLAUDE_CODE_AUTO_COMPACT_WINDOW=400000",
    "evidence": "unset (behavioural)", "est_saving_tokens": 0, "risk": "low",
    "action": {"type": "json_patch", "file": "settings", "ops": [
        {"op": "add", "path": "/env/CLAUDE_CODE_AUTO_COMPACT_WINDOW", "value": "400000"}]},
    "command": "apply.sh compact-window",
}

DEFAULT_SETTINGS = {
    "model": "opus",
    "env": {"FOO": "bar"},
    "permissions": {"allow": ["Bash(ls:*)"]},
    "hooks": {},
    "zeta": [1, 2, 3],
}


def write_proposals(env, proposals, week=WEEK):
    doc = {"schema": 1, "week": week, "generated_at": ANALYZE_NOW, "baseline": False,
           "proposals": proposals, "regressions": [], "stats": {}}
    write(env.p("proposals", "%s.json" % week), json.dumps(doc, indent=2, sort_keys=True) + "\n")


def apply_setup(case, proposals=None, settings=None, mode=0o640):
    env = Env(case)
    env.set_settings(settings if settings is not None else copy.deepcopy(DEFAULT_SETTINGS), mode)
    os.makedirs(env.state, exist_ok=True)
    write_proposals(env, proposals if proposals is not None else [copy.deepcopy(COMPACT_PROPOSAL)])
    return env


class Base(unittest.TestCase):
    def setUp(self):
        self.env = Env(self)

    def assertExit(self, proc, code, msg=""):
        self.assertEqual(
            proc.returncode, code,
            "%s expected exit %s got %s\nSTDOUT:\n%s\nSTDERR:\n%s"
            % (msg, code, proc.returncode, proc.stdout[-2000:], proc.stderr[-2000:]))


# ---------------------------------------------------------------------
# spend-breakdown transcript helpers (4.1.4)
# ---------------------------------------------------------------------
def asst_line(ts, model, inp=0, out=0, cr=0, cc=0, mid=None, rid=None, text="assistant words"):
    d = {"type": "assistant", "timestamp": ts,
         "message": {"role": "assistant", "model": model,
                     "content": [{"type": "text", "text": text}],
                     "usage": {"input_tokens": inp, "output_tokens": out,
                               "cache_read_input_tokens": cr,
                               "cache_creation_input_tokens": cc}}}
    if mid is not None:
        d["message"]["id"] = mid
    if rid is not None:
        d["requestId"] = rid
    return d


def write_jsonl(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        for ln in lines:
            f.write(ln if isinstance(ln, str) else json.dumps(ln))
            f.write("\n")


def spend_blank_families():
    return {k: {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "est_usd": 0}
            for k in ("fable", "opus", "sonnet", "haiku", "other")}
