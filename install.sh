#!/usr/bin/env bash
# Link the cam skills into your Claude Code skills directory.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
BACKUPS="${CLAUDE_SKILL_BACKUPS:-$HOME/.claude/skill-backups}"

mkdir -p "$DEST"

for skill in cam camqr; do
  target="$DEST/$skill"
  if [ -e "$target" ] || [ -L "$target" ]; then
    # Back up OUTSIDE the skills dir - anything left inside it is picked up
    # by Claude Code as a duplicate skill.
    mkdir -p "$BACKUPS"
    backup="$BACKUPS/$skill.backup-$(date +%Y%m%d-%H%M%S)"
    mv "$target" "$backup"
    echo "  existing $skill backed up to $backup"
  fi
  ln -s "$SRC/skills/$skill" "$target"
  echo "  linked $target -> $SRC/skills/$skill"
done

echo
echo "Installed. In Claude Code try:  /cam"
command -v qrencode >/dev/null || echo "  note: 'brew install qrencode' enables QR codes for /cam upload"
command -v ffmpeg   >/dev/null || echo "  note: 'brew install ffmpeg' is required for /cam now"
