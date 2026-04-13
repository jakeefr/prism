# PRISM

**Session intelligence for Claude Code. Find out why your sessions are burning tokens — and fix them.**

[![PyPI version](https://img.shields.io/pypi/v/prism-cc.svg)](https://pypi.org/project/prism-cc/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/github/actions/workflow/status/jakeefr/prism/tests.yml?label=tests)](https://github.com/jakeefr/prism/actions)

<!-- demo gif goes here -->

```bash
pip install prism-cc
```

---

## The problem

Your Claude Code sessions are silently wasting tokens and you don't know why.

Running PRISM against real session data from a single machine found:

- A project with **6738% CLAUDE.md re-read cost** in one session — a 237-line file being re-read on every tool call
- A project where **CLAUDE.md re-reads consumed 480% of total session tokens** — more tokens on instructions than on actual work
- **4 migration file edits** in a project that had a rule saying never to touch them — the rule existed, Claude ignored it
- **5 consecutive tool failures** in a single session with no diagnosis

None of this was visible before PRISM. The token counter just said you hit your limit.

---

## What PRISM does

PRISM reads Claude Code's session files from `~/.claude/projects/` — the same files Claude Code writes automatically — and tells you three things:

1. **Why your tokens are disappearing** — CLAUDE.md re-read costs, retry loops, compaction losses, sidechain waste
2. **Whether your CLAUDE.md rules are actually being followed** — or silently ignored mid-session
3. **Exactly what to change** — concrete diff recommendations, not generic advice

You keep using Claude Code exactly as normal. PRISM is the tool you run after.

---

## Quick start

```bash
# Install
pip install prism-cc

# Analyze all your Claude Code projects
prism analyze

# Get specific CLAUDE.md fix recommendations
prism advise

# Open the full interactive dashboard
prism

# Watch a session live as it runs
prism watch
```

---

## What you'll see

```
 Project                   Overall   Token Eff.  Tool Health  Ctx Hygiene  MD Adherence  Continuity
 myapp            C+        D           B+           D            C             A
 ai-assistant          C         F           A            B            B+            A-
 data-pipeline        C+        C+          D            B            C+            B
 web-scraper                  C+        D+          B            B+           B             A
 D//prism                   B+        B+          A-           B+           A             A
```

Followed by the advisor:

```
╭──────────────────────────────────────────────────────────╮
│  PRISM ADVISOR — recommendations for myapp        │
╰──────────────────────────────────────────────────────────╯

  ✦ TRIM  (High impact — silent token drain every session)
    Remove lines 120–148: personality/tone instructions
    Claude Code's system prompt already handles this.
    These 29 lines cost tokens on every single tool call.

  ✦ RESTRUCTURE  (Reduce root-level re-read cost)
    Move 3 rules to subdirectory CLAUDE.md files:
    - "Use functional components only in React"
    - "Import from @/components, never relative paths"
    - "Run bun run typecheck after TypeScript changes"
    These only matter in src/ — loading them globally wastes
    tokens in every session that doesn't touch that directory.
```

---

## Features

| Dimension | What PRISM measures |
|---|---|
| **Token Efficiency** | CLAUDE.md re-read costs, cache hit patterns, compaction frequency |
| **Tool Health** | Retry loops, edit-revert cycles, consecutive failures, interactive command hangs |
| **Context Hygiene** | Compaction loss events, mid-task boundaries, sidechain fragmentation |
| **CLAUDE.md Adherence** | Whether your rules are actually being followed — or ignored mid-session |
| **Session Continuity** | Resume success rate, context loss on restart, truncated session files |

---

## How it works

```
You use Claude Code normally
         ↓
Claude Code writes session files to ~/.claude/projects/
         ↓
PRISM reads and analyzes those files
         ↓
Health scores  +  root cause diagnosis  +  CLAUDE.md diff
```

PRISM never touches Claude Code. It never modifies your sessions. It reads the JSONL files Claude Code already writes and surfaces what's inside them.

---

## The CLAUDE.md re-read problem

Every tool call Claude Code makes re-reads your CLAUDE.md from the top of the context. A 200-line CLAUDE.md × 50 tool calls = 10,000 tokens spent on instructions, per session. If your CLAUDE.md has grown to include personality instructions, full documentation copies, or rules that only apply to one subdirectory — you're paying for all of it every time.

PRISM measures this exactly and tells you which lines are costing you the most.

The "Mr. Tinkleberry test" (from HN, 748 upvotes): put an absurd instruction in your CLAUDE.md. When Claude stops following it mid-session, your file has grown too long and adherence is degrading. PRISM automates this test across all your real sessions.

---

## Commands

```bash
prism                          # Full interactive TUI dashboard
prism analyze                  # Rich-formatted health report, then exit
prism analyze --project ~/myproject   # One project only
prism analyze --json           # JSON output for scripting
prism advise                   # CLAUDE.md recommendations
prism advise --apply           # Write recommendations (with confirmation)
prism replay <session-id>      # Scrub through a session timeline
prism watch                    # Live dashboard for the running session
prism projects                 # List all projects with session counts
```

---

## Install

```bash
# pip
pip install prism-cc

# pipx (recommended — isolated install)
pipx install prism-cc

# from source
git clone https://github.com/jakeefr/prism
cd prism
pip install -e .
```

Requires Python 3.11+. No Claude API key needed — reads local files only. Works on macOS and Linux. Windows support via WSL.

---

## Contributing

Issues and PRs welcome. If you run `prism analyze` and find something interesting in your own session data, open an issue — real-world patterns help improve the detection logic.

```bash
git clone https://github.com/jakeefr/prism
cd prism
pip install -e ".[dev]"
pytest
```

---

## License

MIT — do whatever you want with it.

---

*PRISM doesn't send anything anywhere. All analysis runs locally against files already on your machine.*
