# PRISM Command Reference

## `prism` (no arguments)

Opens the interactive TUI dashboard.

```bash
prism
```

The TUI shows all projects with health grades, lets you drill into sessions, and supports live watch mode. Press `q` to quit, arrow keys to navigate.

---

## `prism analyze`

Prints a Rich-formatted health report for all projects (or a specific one) and exits.

```bash
prism analyze
prism analyze --project <path>
prism analyze --json
```

**Options:**

| Flag | Description |
|------|-------------|
| `--project`, `-p` | Path to analyze (project dir, real path, or display name) |
| `--json` | Output as JSON instead of the Rich table |
| `--base-dir` | Override `~/.claude/projects/` (hidden, for testing) |

**Example output:**
```
 Project         Sessions  Token Eff.  Tool Health  Ctx Hygiene  MD Adherence  Continuity  Overall
 myapp                  8  C+          B+           B            D+            A           C+
 
myapp — top issues:
  ! CLAUDE.md re-reads consume >28% of session tokens
  ! Retry loop detected: Bash called 3+ times with same input
```

After the table, `prism analyze` also regenerates the HTML dashboard at `~/.claude/prism/dashboard.html`.

---

## `prism advise`

Prints CLAUDE.md recommendations based on session analysis.

```bash
prism advise
prism advise --project <path>
prism advise --apply
```

**Options:**

| Flag | Description |
|------|-------------|
| `--project`, `-p` | Analyze a specific project |
| `--apply` | Apply ADD recommendations to CLAUDE.md (with confirmation prompt) |
| `--base-dir` | Override `~/.claude/projects/` (hidden) |

**Example output:**
```
─────────────────────────────────────────────────────────────
  PRISM ADVISOR — recommendations for CLAUDE.md
─────────────────────────────────────────────────────────────

  ✦ ADD  (High impact — Fixes 3 retry loop(s) across 2 session(s))
    Always use non-interactive flags when available: --yes, -y,
    --non-interactive, --no-input.

  ✦ RESTRUCTURE  (Medium impact — 2 critical rules in attention dead zone)
    Move these rules to the top or bottom of your CLAUDE.md:
      Line 24: NEVER edit existing migration files
```

---

## `prism dashboard`

Generates the HTML dashboard and opens it in your browser.

```bash
prism dashboard
prism dashboard --serve
prism dashboard --no-open
```

**Options:**

| Flag | Description |
|------|-------------|
| `--serve` | Serve on `localhost:19821` and open in browser (Ctrl+C to stop) |
| `--no-open` | Generate only — don't open the browser |
| `--base-dir` | Override `~/.claude/projects/` (hidden) |

The dashboard is a self-contained HTML file at `~/.claude/prism/dashboard.html`. No server required to view it — open as a `file://` URL or use `--serve` for local serving.

---

## `prism replay <session-id>`

Opens an interactive timeline view of a single session.

```bash
prism replay abc123
prism replay ~/.claude/projects/my-project/abc123.jsonl
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `session-id` | Session ID (partial match supported) or path to `.jsonl` file |

The replay view lets you scrub through a session record by record, seeing tool calls, results, and context in order.

---

## `prism watch`

Opens a live dashboard watching the currently active session.

```bash
prism watch
```

**Options:**

| Flag | Description |
|------|-------------|
| `--base-dir` | Override `~/.claude/projects/` (hidden) |

Monitors `~/.claude/projects/` for new session activity and updates in real time. Press `q` to quit.

---

## `prism projects`

Lists all Claude Code projects with session counts and last-used dates.

```bash
prism projects
```

**Example output:**
```
 Project               Sessions  Last Active
 D//code/myapp               12  2h ago
 D//work/api-service          5  3d ago
 /home/user/scripts           2  1w ago

3 project(s) found in ~/.claude/projects/
```

---

## `prism --version`

Prints the installed version and exits.

```bash
prism --version
# prism v0.2.0
```
