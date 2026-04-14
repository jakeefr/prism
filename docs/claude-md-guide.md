# Optimizing Your CLAUDE.md

PRISM's advisor detects patterns in your session data and generates concrete recommendations for your CLAUDE.md. This guide explains the principles behind each recommendation type.

## The 80-line threshold

Research and real-world testing show that LLM instruction-following degrades significantly after the first 80 lines of a context file. PRISM flags files over 80 lines and recommends trimming.

**Why this happens:** Every tool call re-reads CLAUDE.md from the top of context. Longer files mean more tokens per call and lower adherence for rules buried deep in the file.

**The "Mr. Tinkleberry test"**: Put an absurd instruction at line 90+ of your CLAUDE.md ("Never call any variable 'tinkleberry'"). If Claude follows it in the first turn but ignores it by turn 20, your file has grown past the effective attention threshold.

---

## The U-shaped attention curve

LLMs pay most attention to content at the **beginning** and **end** of a prompt. The middle 55% of the file receives the least attention.

For a CLAUDE.md with N lines, PRISM identifies the "danger zone" as:
- **Start**: line `int(N × 0.20)` 
- **End**: line `int(N × 0.75)`

Critical rules (`NEVER`, `ALWAYS`, `DO NOT`, `CRITICAL`, `MUST NOT`) found in this zone get a **RESTRUCTURE** recommendation — move them to the first 20% or last 25% of the file.

**Practical rule**: Put your most important constraints at the very top. Put reinforcing examples and context at the bottom. Let the middle contain lower-priority style/preference notes.

---

## Line count and token cost

Every line in CLAUDE.md is paid for on every tool call. A 200-line file with 50 tool calls = 10,000 tokens per session spent on instructions.

**Calculate your waste ratio:**
```
waste_ratio = claude_md_size_tokens × tool_calls / session_tokens
```

If this is >15% of session tokens, PRISM flags it. If >30%, it's a high-impact issue.

---

## Subdirectory CLAUDE.md files

Rules that only apply to a specific part of your codebase don't need to live in the root CLAUDE.md. Claude Code reads CLAUDE.md files hierarchically — a `src/CLAUDE.md` is loaded when working in `src/`.

**Move to subdirectory CLAUDE.md when:**
- The rule mentions a specific directory (`src/`, `tests/`, `api/`)
- The rule is only relevant for one framework or language in a mixed project
- The rule references file patterns that only exist in one area

PRISM's RESTRUCTURE recommendations identify these candidates automatically.

---

## Rule phrasing

Effective rules are:
1. **Specific** — "Never edit files in db/migrations/" beats "be careful with migrations"
2. **Actionable** — The model should know exactly what to do or not do
3. **Verifiable** — PRISM can only check rules it can detect in tool calls

Rules that start with `NEVER`, `ALWAYS`, `DO NOT` are the most reliably followed because they're syntactically unambiguous.

**Avoid:**
- Personality instructions ("be concise", "sound professional") — Claude Code's system prompt handles tone
- Documentation copies ("here's how our auth system works...") — link to the file instead
- Redundant rules that Claude Code follows by default

---

## Recommendation types

| Action | What it means |
|--------|---------------|
| **ADD** | Add a new rule — evidence shows something is happening that your CLAUDE.md doesn't address |
| **TRIM** | Remove lines — usually personality/tone instructions past line 80 |
| **WARN** | A rule you have is being violated — strengthen the phrasing or add context |
| **RESTRUCTURE** | Move rules to better positions — subdirectory files or earlier in the file |

---

## Applying recommendations

```bash
# Review recommendations (read-only)
prism advise

# Apply ADD recommendations with confirmation
prism advise --apply
```

`--apply` only adds new rules. It doesn't remove or modify existing content. You'll see a preview and be asked to confirm before anything is written.
