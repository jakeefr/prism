---
description: Get CLAUDE.md recommendations from PRISM. Use when asked to audit, fix, improve, or check what is wrong with a CLAUDE.md file.
---

# prism-advise

Get concrete CLAUDE.md recommendations based on real session data.

## When to use
When the user asks to audit their CLAUDE.md, fix their CLAUDE.md,
improve their CLAUDE.md, or understand what is wrong with it.

## Before running

First check if PRISM is installed:
```bash
prism --version
```

If the command is not found, install it first:
```bash
pip install prism-cc
```

Then verify it installed correctly:
```bash
prism --version
```

Once confirmed installed, proceed with the advise command.

## Usage

Run the advisor for the current project:
```bash
prism advise --project .
```

For a different project:
```bash
prism advise --project <path>
```

From an agentsview database (real API token counts, richer data):
```bash
prism advise --source agentsview
prism advise --source agentsview --agentsview-db /path/to/sessions.db
```

DB path resolution: `AGENTSVIEW_DATA_DIR` → `AGENT_VIEWER_DATA_DIR` → `~/.agentsview/sessions.db`.
Note: `--project` cannot be used with `--source agentsview`.

## Interpreting the output

PRISM prints recommendations with four action types:

- **ADD** means a new rule should be added to CLAUDE.md. Session data shows
  a problem that no existing rule addresses. Example: retry loops caused by
  missing non-interactive flags.
- **TRIM** means lines should be removed from CLAUDE.md. Usually personality
  or tone instructions past line 80 that waste tokens on every tool call.
- **WARN** means an existing rule is being violated in sessions. The rule
  exists but Claude is not following it. May need stronger phrasing or
  better placement.
- **RESTRUCTURE** means rules should be moved. Either to subdirectory
  CLAUDE.md files (if they only apply to one part of the codebase) or to
  the top/bottom of the file (if critical rules are buried in the attention
  dead zone).

Each recommendation includes an impact level (High, Medium, Low) and
evidence from actual session data.

## Applying recommendations

If the user wants to apply the ADD recommendations automatically:
```bash
prism advise --project . --apply
```

This adds new rules to the CLAUDE.md file. It will show a preview and
ask for confirmation before writing anything. Only ADD recommendations
are applied automatically. TRIM and RESTRUCTURE changes must be done
by hand.

## What PRISM checks
- Whether CLAUDE.md is too long (adherence drops past 80 lines)
- Whether critical rules are buried in the attention dead zone
- Whether rules are being violated in actual sessions
- Whether subdirectory-specific rules belong in subdirectory CLAUDE.md files
- Whether interactive commands or retry loops need new rules
- Whether migration file protections are missing
