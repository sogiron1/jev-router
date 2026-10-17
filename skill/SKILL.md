---
name: jev
description: Turn the Jev model router on/off, or show its status (how many messages went to each model size and what Jev has cost so far).
allowed-tools:
  - Bash
---

## What this does

Controls the Jev-based model router at `__JEV_ROUTER_DIR__/router.py`.
It sizes up each message with Jev (small/large/hardest) and hands well-understood
jobs to the smallest Claude model that can do them. Low-confidence calls and short
replies that only make sense in context are self-handled.

## Arguments

`status` is one of: `on`, `off`, `status` (default: `status` if empty).

## Steps

1. Run exactly one of these based on the argument, using the absolute path
   (do not `cd` first):
   - `on`     → `python3 __JEV_ROUTER_DIR__/router.py on`
   - `off`    → `python3 __JEV_ROUTER_DIR__/router.py off`
   - `status` → `python3 __JEV_ROUTER_DIR__/router.py status`
   - anything else / empty → run `status` and tell the user the valid
     arguments are `on`, `off`, `status`.
2. Print the command's output back to the user as-is.
3. If turning it **on**, remind the user in one line: while it's on, messages
   passed through the router are sent to TypeSafe (Jev's maker) and then to
   Anthropic — keep it off for private work.
4. If the command fails because of a sandbox/permission block, say so plainly
   and do not try to work around it.
