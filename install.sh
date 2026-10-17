#!/usr/bin/env bash
# Installs the /jev skill for Claude Code and creates .env from the template.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/jev"
mkdir -p "$DEST"
sed "s#__JEV_ROUTER_DIR__#$DIR#g" "$DIR/skill/SKILL.md" > "$DEST/SKILL.md"
echo "Installed skill to $DEST"
if [ ! -f "$DIR/.env" ]; then
  cp "$DIR/.env.example" "$DIR/.env"; chmod 600 "$DIR/.env"
  echo "Created $DIR/.env - add your TYPESAFE_API_KEY and ANTHROPIC_API_KEY."
fi
echo "Next: restart Claude Code, then run /jev status"
