# demo.tape
# Record with: vhs demo.tape
# Install vhs: brew install charmbracelet/tap/vhs
# Output: demo.gif (put this in the README above the install line)

Output demo.gif

Set Shell "bash"
Set FontSize 14
Set Width 1200
Set Height 650
Set Theme "Catppuccin Mocha"
Set Padding 20
Set TypingSpeed 40ms

# Open with a clean terminal
Sleep 1s

# Show the install command briefly
Type "pip install prism-cc"
Sleep 500ms
Enter
Sleep 2s

# Clear and go straight to the money shot
Type "clear"
Enter
Sleep 300ms

# Run analyze — this is the hero moment
Type "prism analyze"
Enter
Sleep 4s

# Let the table sit so people can read the F grades and real numbers
Sleep 3s

# Scroll effect — show it found real problems
Sleep 1s

# Now show advise on the worst project
Type "prism advise --project ~/myapp"
Enter
Sleep 3s

# Let the recommendations sit
Sleep 3s

# Quick flash of the live TUI
Type "prism"
Enter
Sleep 3s

# End on the dashboard
Sleep 2s
