# jev-router

A small model router. It asks **Jev** (TypeSafe's judgment model) how big each message is, then hands it to the smallest Claude model that can do it well: Haiku for routine work, Sonnet for multi-step builds, Opus for high-stakes calls. It fails open: if the router is off, Jev is slow, or Jev is unsure, the message is handled normally.

> **Privacy:** while the router is on, routed messages are sent to TypeSafe (for sizing) and then to Anthropic (for the answer). Don't use it for private or sensitive content.

## Requirements
- Python 3 (standard library only, nothing to install)
- A TypeSafe API key (console.typesafe.ai) and an Anthropic API key
- Claude Code, if you want the `/jev` slash command

## Setup
```bash
git clone https://github.com/sogiron1/jev-router.git
cd jev-router
./install.sh          # installs the /jev skill, creates .env
# edit .env and add your two keys
```

## Use
```bash
python3 router.py on
python3 router.py route "rename foo to bar in utils.py"
python3 router.py route "yes, do that" --context "Draft the email"
python3 router.py status
python3 router.py off
```
In Claude Code: `/jev on`, `/jev off`, `/jev status`.

`mcp_server.py` is an optional MCP server exposing a `size_job` tool that only recommends a model (it never routes). See [BUILD.md](BUILD.md) for registration.

## How it decides
Self-handled if: the switch is off, Jev errors or times out (4s), the message looks like a context-only reply (probability >= 0.50), or confidence is under 0.60. Otherwise `small` -> Haiku, `large` -> Sonnet, `hardest` -> Opus. Thresholds and model IDs are constants at the top of `router.py`.

## Notes
- The model IDs in `router.py` may need updating to what your Anthropic account can call.
- `router_state.json` (created on first use) keeps counts and is git-ignored.
- Full build walkthrough and known issues: [BUILD.md](BUILD.md).

MIT licensed.
