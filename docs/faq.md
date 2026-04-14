# FAQ

## General

**Why is my Token Efficiency score low?**

The most common causes:
1. **Long CLAUDE.md** — Every tool call re-reads your CLAUDE.md. A 200-line file × 50 tool calls = 10,000 tokens/session on instructions alone. Run `prism advise` to see which lines to trim.
2. **High compaction rate** — If sessions are hitting context limits and compacting repeatedly, each compaction wastes tokens on the summary. Keep sessions focused.
3. **High sidechain ratio** — Sidechains (background tasks) fragment context. More than 30% sidechain records is a warning sign.

---

**What is a compaction boundary?**

When Claude Code's context window fills up, it automatically compresses old conversation history into a summary. This is a "compaction boundary." The boundary is recorded in the session file with `subtype: "compact_boundary"`.

A single compaction per session is normal. Multiple compactions per session suggests the session is too long or the context is being filled by something avoidable (like a large CLAUDE.md being re-read constantly).

---

**What is a mid-task compaction?**

A mid-task compaction happens when Claude Code compacts the context while in the middle of a task, and then immediately needs to re-do work it already did before the compaction. PRISM detects this by checking if tool call patterns after the boundary repeat tool call patterns from before it.

This is more serious than a regular compaction because it means the compaction caused actual rework.

---

**Why is my Tool Health score low?**

Common causes:
1. **Retry loops** — The same Bash command or tool was called 3+ times with the same input. Usually means the command is failing and Claude is retrying without understanding the error.
2. **Interactive commands** — Commands like `npm init` or `apt install` without `-y` flags can hang waiting for user input. Add `Always use non-interactive flags` to your CLAUDE.md.
3. **Consecutive failures** — 3+ tool results in a row that returned errors. Usually indicates Claude is stuck on a problem.

---

**How do I fix a D grade?**

Run `prism advise` for specific recommendations. The most impactful fixes are generally:

1. **Trim your CLAUDE.md** if it's over 80 lines — this often fixes both Token Efficiency and MD Adherence scores
2. **Add non-interactive flags** to your CLAUDE.md if Tool Health is low
3. **Add migration file protection** if you're seeing migration edits in tool history
4. **Keep sessions shorter** if Context Hygiene is low — start a new session after completing a major task

---

**What does "N/A" mean for MD Adherence?**

PRISM couldn't find a CLAUDE.md for this project. It searches session files for a `cwd` field and looks for `CLAUDE.md` in that directory. If your CLAUDE.md is in a different location, the score can't be computed.

---

**Why are my sessions being detected as truncated?**

A session file is truncated when Claude Code was killed mid-write (SIGKILL, force-quit, power loss). The last JSON record in the file is incomplete. To avoid this, use Ctrl+C to stop Claude Code gracefully rather than force-quitting.

---

## CLAUDE.md

**How long should my CLAUDE.md be?**

Under 80 lines for maximum adherence. Under 50 lines is ideal. Every line costs tokens on every tool call.

The practical limit depends on your session size: if your sessions average 30 tool calls and your CLAUDE.md is 40 lines (~200 tokens), that's 6,000 tokens/session on instructions — acceptable. At 200 lines it's 30,000 tokens — significant.

---

**Why does PRISM flag rules as violated even though I can see them being followed?**

PRISM's rule checking is heuristic-based. It only checks rules it can detect automatically:
- Migration file edits (checks Write/Edit tool_input paths)
- Interactive commands (checks Bash command patterns)
- TypeScript `any` usage (checks Write/Edit content)

If your rule doesn't match one of these patterns, PRISM reports it as "unchecked" rather than violated. A WARN recommendation means PRISM found actual evidence of a violation in the session data.

---

**Should I put personality/tone instructions in CLAUDE.md?**

Generally no. Claude Code's system prompt already handles tone, formatting, and personality. Adding "be concise" or "use clear explanations" to CLAUDE.md wastes lines that cost tokens and doesn't meaningfully change behavior.

Save CLAUDE.md for project-specific constraints: never edit X, always run Y, use Z pattern.

---

## Installation

**Does PRISM work on Windows?**

Yes. PRISM works on macOS, Linux, and Windows. Session files are in `~/.claude/projects/` on all platforms (Claude Code normalizes to the user's home directory).

---

**Do I need a Claude API key?**

No. PRISM reads local files only. It never makes network calls.

---

**Can I use PRISM with Claude Code Pro/Max/Team?**

Yes. PRISM reads session files, which are written by Claude Code regardless of subscription tier.

---

## Dashboard

**Where is the HTML dashboard stored?**

`~/.claude/prism/dashboard.html` — a self-contained HTML file. Open it directly in any browser or run `prism dashboard --serve` to serve it on localhost.

**Does the dashboard update automatically?**

It regenerates every time you run `prism analyze` or `prism dashboard`. It doesn't auto-refresh in the browser — reload the page after running an analysis.
