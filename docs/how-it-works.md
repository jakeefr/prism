# How PRISM Works

PRISM reads Claude Code's session files and computes health metrics across five dimensions. This document explains the technical details.

## Session Files

Claude Code writes session data to `~/.claude/projects/` as JSONL (newline-delimited JSON) files. Each line is a JSON object representing one record in the conversation. PRISM reads these files directly — it never modifies them.

### Record types

| Type | Description |
|------|-------------|
| `user` | A user message (can contain tool results) |
| `assistant` | An assistant response (can contain tool calls) |
| `system` | A system-injected record (compaction boundaries, summaries) |

### Content blocks

Each `user` or `assistant` record contains a `content` array of typed blocks:

- `text` — plain text content
- `tool_use` — a tool call (`tool_name`, `tool_input`)
- `tool_result` — the result of a tool call (`tool_content`, `is_error`)
- `thinking` — extended thinking content (if enabled)

### Compaction boundaries

When Claude Code compacts the context, it inserts a `system` record with `subtype: "compact_boundary"` and a `summary` field containing the compressed history. PRISM detects these to measure context hygiene.

---

## Five Health Dimensions

### 1. Token Efficiency (20% of overall score)

Measures how efficiently tokens are being used.

**Metrics computed:**
- `claude_md_size_tokens` — estimated token cost of CLAUDE.md
- `claude_md_reread_tokens` — `claude_md_size_tokens × tool_call_count` (per session)
- `compaction_count` — total compaction boundary events
- `sidechain_count` — records marked `is_sidechain: true`

**Score penalties:**
- Compaction rate > 2/session: −30 points
- Compaction rate > 1/session: −15 points
- CLAUDE.md waste ratio > 30% of session tokens: −25 points
- High sidechain ratio (>30%): −20 points

**Token estimation:** PRISM uses `len(text) // 4` (chars-per-token heuristic). This under-counts for code but is fast and consistent.

### 2. Tool Health (25% of overall score)

Measures the quality of tool call patterns.

**Detects:**
- **Retry loops** — same tool called 3+ times with identical input
- **Interactive commands** — Bash calls without `-y`/`--yes`/`--non-interactive` flags (e.g. `npm init`, `apt install`)
- **Migration file edits** — Write/Edit calls to paths matching `*/migrations/*`
- **Edit-revert cycles** — same file edited twice within 3 turns
- **Consecutive failures** — 3+ tool results with error patterns in a row

**Score penalties:**
- Each retry loop: −15 points (capped at −40)
- Each interactive command: −8 points (capped at −20)
- Each edit-revert cycle: −8 points (capped at −15)
- Each consecutive failure run: −10 points (capped at −20)

### 3. Context Hygiene (20% of overall score)

Measures context management quality.

**Detects:**
- Compaction events (especially mid-task)
- Long sessions (>100 turns)
- Mid-task compactions (tool patterns repeat after boundary — context loss signal)

**Mid-task detection:** Checks if the first 5 tool names after a compaction boundary overlap with the 10 most common tool names before the boundary. If ≥2 overlap, it's a mid-task compaction.

### 4. CLAUDE.md Adherence (20% of overall score)

Measures whether the rules in CLAUDE.md are being followed.

**Rule extraction:** Lines matching `Never|Always|Don't|Use|Avoid|Run|Prefer|Must|Ensure` (case-insensitive) at the start of a line.

**Automated checks currently implemented:**
- Migration rules (`Never edit migration files` → check for migration file edits)
- Interactive command rules (`use non-interactive` → check for interactive Bash calls)
- TypeScript `any` rules (`never use any` → check Write/Edit for `: any` patterns)

**Line count penalty:** Files over 80 lines get a −15 point penalty. Over 120 lines: additional −10.

### 5. Session Continuity (15% of overall score)

Measures session health and resume quality.

**Detects:**
- Truncated session files (write interrupted mid-record)
- Context re-establishment phrases at session start (`"what is..."`, `"could you describe..."`)

---

## Overall Score

```
overall_score = (
    token_efficiency.score × 0.20 +
    tool_health.score × 0.25 +
    context_hygiene.score × 0.20 +
    claude_md_adherence.score × 0.20 +
    session_continuity.score × 0.15
)
```

If no CLAUDE.md is found, adherence scores as 70 (neutral).

## Letter Grades

| Score | Grade |
|-------|-------|
| ≥95   | A+    |
| ≥90   | A     |
| ≥85   | A-    |
| ≥80   | B+    |
| ≥75   | B     |
| ≥70   | B-    |
| ≥65   | C+    |
| ≥60   | C     |
| ≥55   | C-    |
| ≥50   | D+    |
| ≥45   | D     |
| ≥40   | D-    |
| <40   | F     |
