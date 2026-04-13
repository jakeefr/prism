# demo.tape — PRISM session intelligence for Claude Code
# Record with: vhs demo.tape (requires vhs + ffmpeg + ttyd)
# Output: demo.gif

Output demo.gif

Set Shell "bash"
Set FontSize 14
Set Width 140
Set Height 40
Set Theme "Dracula"
Set Padding 20
Set TypingSpeed 50ms

# ── 1. prism analyze ─────────────────────────────────────────────────────────
Sleep 500ms

Type "prism analyze"
Enter
Sleep 5s

# Let the health table sit so viewers can read grades
Sleep 3s

# ── 2. prism advise on worst project ─────────────────────────────────────────
Type "prism advise --project ~/.claude/projects/D--myapp"
Enter
Sleep 4s

# Let recommendations sit
Sleep 3s

# ── 3. Flash the TUI ─────────────────────────────────────────────────────────
Type "prism"
Enter
Sleep 4s

# Press q to exit
Ctrl+C
Sleep 1s
