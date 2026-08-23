# Run from the repo root: vhs assets/demos/demo-hot-cycle.tape
# Requires: vhs, python3. Uses a throwaway vault under /tmp/demo-fma.
Output assets/readme/demo.gif

Set Theme "Catppuccin Mocha"
Set FontSize 18
Set Width 1080
Set Height 560
Set Padding 24
Set TypingSpeed 35ms
Set PlaybackSpeed 1.25

Hide
Type `export PS1='❯ ' PATH="$PWD/scripts:$PATH"`
Enter
Type `rm -rf /tmp/demo-fma && mkdir -p /tmp/demo-fma/vault/00_index/hot-inbox && cd /tmp/demo-fma && clear`
Enter
Sleep 500ms
Show

Type `# ── 1. one agent records a decision as an immutable event ──`
Sleep 500ms
Enter
Type `hot-inbox-post --kind decision --owner agent-a \`
Enter
Type `  --title "npm publish flow frozen for all repos" \`
Enter
Type `  --summary "Trusted publisher + provenance is the standard release path." \`
Enter
Type `  --canonical-path family-vault/30_decisions/npm-publish-flow.md \`
Enter
Type `  --inbox-dir vault/00_index/hot-inbox/`
Sleep 500ms
Enter
Sleep 2s

Type `clear`
Enter

Type `# ── 2. the generator folds the inbox into one short shared page ──`
Sleep 500ms
Enter
Type `family-hot-generate --vault-root vault`
Sleep 400ms
Enter
Sleep 2s

Type `# ── 3. every agent reads that page at session start — checksum-verified ──`
Sleep 500ms
Enter
Type `family-hot-read --path vault/00_index/family-hot.md --check`
Sleep 400ms
Enter
Sleep 7s
