# PRISM

Python CLI tool. Session intelligence for Claude Code.

## Commands
- Run tests: `pytest`
- Install dev: `pip install -e ".[dev]"` or `uv sync --dev`
- Run locally: `python -m prism` or `prism` after install

## Structure
- `prism/parser.py` — all JSONL parsing logic, no analysis here
- `prism/analyzer.py` — all metrics calculation, no I/O here
- `prism/advisor.py` — recommendation generation, reads analyzer output
- `prism/app.py` — Textual TUI, imports widgets from prism/widgets/
- `prism/cli.py` — Typer CLI, thin layer that calls analyzer/advisor/app

## Rules
- Never mix parsing and analysis — parser returns raw records, analyzer computes metrics
- Never hardcode `~/.claude` path — use `Path.home() / ".claude"` and make it configurable
- Always handle malformed JSONL gracefully — skip bad lines, never crash
- Use `Path` objects throughout, never string concatenation for paths
- Textual widgets must not import from cli.py — no circular deps
- Run `pytest` before marking any task done
- New code must have corresponding tests before committing

## Code Review (roborev)

roborev is configured for continuous background review. Every commit triggers
an automatic review via a post-commit hook. The daemon runs locally; config
and review database live in `~/.roborev/` (outside this repo).

Workflow after every commit:
1. `~/.roborev/bin/roborev.exe status` — check that the review job was queued
2. `~/.roborev/bin/roborev.exe wait <job_id>` — wait for the review to finish
3. `~/.roborev/bin/roborev.exe show` — view findings for HEAD
4. If issues are flagged: fix them, commit, and wait for the new review to pass
5. `~/.roborev/bin/roborev.exe list --open` — confirm no open findings remain

Other useful commands:
- `~/.roborev/bin/roborev.exe tui` — interactive review queue
- `~/.roborev/bin/roborev.exe fix` — let an agent fix open findings automatically

Never move to the next task or phase of work while there are open roborev
findings. The review queue must be clear before proceeding.
