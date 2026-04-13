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
