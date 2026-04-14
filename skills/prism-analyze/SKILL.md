# prism-analyze

Analyze Claude Code session health using PRISM.

## When to use
When the user asks to analyze their Claude Code sessions, check token usage,
audit their CLAUDE.md, or understand why sessions are failing.

## Usage

Run the analysis:
```bash
prism analyze
```

If prism is not installed:
```bash
pip install prism-cc
prism analyze
```

For a specific project:
```bash
prism analyze --project <path>
```

For CLAUDE.md recommendations:
```bash
prism advise
```

## What PRISM shows
- Health scores (A-F) across 5 dimensions per project
- Token efficiency: CLAUDE.md re-read costs, compaction frequency
- Tool health: retry loops, edit-revert cycles, consecutive failures
- Context hygiene: compaction loss events, mid-task boundaries
- CLAUDE.md adherence: whether your rules are actually being followed
- Session continuity: resume success rate, truncated sessions

## Output
PRISM prints a health report table and top issues per project.
Run `prism` (no args) to open the interactive TUI dashboard.
Run `prism dashboard` to open the HTML dashboard in your browser.
