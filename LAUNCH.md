# PRISM Launch Checklist + Post Copy

---

## Before You Push to GitHub

- [ ] Replace YOUR_USERNAME with `jakeefr` in pyproject.toml
- [ ] Add MIT LICENSE file
- [ ] Record demo GIF with vhs (demo.tape) and add to README
- [ ] Set GitHub repo description: "Session intelligence for Claude Code — find why your sessions fail and fix them"
- [ ] Add GitHub topics: `claude-code`, `claude`, `developer-tools`, `cli`, `tui`, `python`, `textual`
- [ ] Publish to PyPI: `uv build && uv publish` (needs PyPI account + token)
- [ ] Verify `pip install prism-cc` works from a clean environment
- [ ] Star your own repo (baseline social proof)

---

## GitHub Repo Settings

**Description:**
```
Session intelligence for Claude Code — find why your sessions fail and fix them
```

**Website:** (leave blank for now, or link to PyPI)

**Topics:**
```
claude-code  claude  anthropic  developer-tools  cli  tui  python  textual  terminal
```

---

## Hacker News Post

**Post at 13:00–15:00 UTC for best timing.**

**Title:**
```
PRISM – session intelligence for Claude Code (find why your sessions fail)
```

**Body:**
```
I've been using Claude Code heavily and kept hitting my token limits without understanding why. 
Turns out the session data is all there in JSONL files — Claude Code writes everything to 
~/.claude/projects/ — but nothing was reading it to surface patterns.

So I built PRISM. It reads those files and does three things:

1. Health scores across 5 dimensions (token efficiency, tool call patterns, context hygiene, 
   CLAUDE.md adherence, session continuity)
2. Diagnoses root causes — not just "you used tokens" but "your 237-line CLAUDE.md is being 
   re-read on every tool call, that's where 6738% of your session tokens went"
3. Concrete CLAUDE.md diffs — specific lines to add, remove, or move to subdirectory files

Running it against my own projects found things I never expected: migration file edits in a 
project with a rule saying never to touch them, retry loops from commands that hung waiting 
for interactive input, rules that stopped being followed after line 80 because the file 
got too long.

The CLAUDE.md adherence detection is the part I'm most interested in getting feedback on — 
it extracts imperative statements from your CLAUDE.md and checks whether session tool calls 
actually comply. It's not perfect but it caught real violations in my data.

GitHub: https://github.com/jakeefr/prism
Install: pip install prism-cc

Would love feedback on the adherence detection — it's the hardest part to get right and 
I'd like to know if it works on other people's setups.
```

---

## Reddit Post — r/ClaudeAI

**Title:**
```
I built a tool that reads your Claude Code session files and tells you exactly 
why you're burning through tokens — found some wild stuff in my own data
```

**Body:**
```
Been frustrated with hitting Claude Code limits and not knowing where the tokens went. 
The session data is all there in JSONL files on your machine but nothing was surfacing it usefully.

Built PRISM — runs locally, reads ~/.claude/projects/, no API key needed.

What it found on my machine:

- One session where CLAUDE.md re-reads consumed **6738%** of session tokens. 
  A 237-line file being re-read on every single tool call.
- A project where Claude was editing migration files despite a rule saying never to — 
  rule existed in CLAUDE.md, was being ignored
- 5 consecutive tool failures in one session that I never noticed until PRISM flagged it

The main things it does:
- Health scores per project (A–F across 5 dimensions)
- CLAUDE.md adherence check — are your rules actually being followed?
- Concrete recommendations: which lines to remove, which to move to subdirectory files

Install: `pip install prism-cc` then just run `prism analyze`

Repo: https://github.com/jakeefr/prism

Curious if anyone else runs it and finds surprising stuff in their own data. 
The 6738% number genuinely shocked me.
```

---

## Reddit Post — r/programming

**Title:**
```
I built a TUI that analyzes Claude Code's session JSONL files and surfaces 
why your context window is filling up
```

**Body:**
```
Claude Code writes detailed session logs to ~/.claude/projects/ — every tool call, 
every message, every compaction boundary. Nobody was reading them to surface useful patterns.

PRISM is a Python/Textual TUI that parses those files and computes:

- CLAUDE.md re-read cost (every tool call re-reads your CLAUDE.md from context top — 
  a 200-line file × 50 tool calls = 10k tokens just on instructions)
- Retry loop detection (3+ consecutive identical tool calls)
- Edit-revert cycles (write to file → write to same file within 3 turns)
- CLAUDE.md adherence — extracts imperative rules and checks whether session 
  tool calls comply
- Compaction loss events and what context disappeared

Real finding: one session showed 6738% CLAUDE.md re-read cost ratio. 
The file had grown to 237 lines including personality instructions that 
Claude Code's system prompt already handles.

Stack: Python, Textual (TUI framework), Rich, Typer, watchdog for live mode.
Tests: 70 passing.

pip install prism-cc / https://github.com/jakeefr/prism

Happy to answer questions about the JSONL format or the adherence detection logic.
```

---

## Timing

Best window: **Tuesday–Thursday, 13:00–15:00 UTC**

Post HN first. If it gets traction in the first 2 hours (10+ upvotes, a few comments), 
post Reddit the same day. If HN is slow, post Reddit next day independently.

Be online for 4 hours after posting HN. Answer every technical question in depth. 
Never deflect. If someone criticizes the adherence detection — agree with the limitation 
first, then explain what it does catch.
```
