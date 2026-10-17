# Building the `/jev-router`

A model router that asks **Jev** (TypeSafe's small judgment model) how big each message is, then hands it to the smallest Claude model that can do it well. It fails open: if anything is off, slow or unsure, the message is handled normally.

## 1. What you're building

| Piece | File | Job |
|---|---|---|
| Router + CLI | `router.py` | `on` / `off` / `status` / `route "<msg>"`; sizes, decides, calls helper model |
| MCP sizer (advice only) | `mcp_server.py` | Exposes a `size_job` tool over stdio; recommends a model but never routes |
| Skill | `skill/SKILL.md` (installed by `install.sh`) | The `/jev` slash command; shells out to `router.py` |
| State | `router_state.json` | `enabled` flag, per-bucket counts, Jev token usage |
| Secrets | `.env` | `TYPESAFE_API_KEY`, `ANTHROPIC_API_KEY` (never commit) |
| Installer | `install.sh` | Installs the skill with the right path and creates `.env` |

## 2. Flow

```
message ──► switch OFF? ───────────────► self-handle
        └─► Jev call (4s timeout)
              ├─ error / timeout ──────► self-handle (jev_failed++)
              ├─ context_only_reply ≥ 0.50 ─► self-handle
              ├─ confidence < 0.60 ────► self-handle
              └─ bucket + confidence ok ─► call helper model, return output
```

Buckets: `small` → Haiku, `large` → Sonnet, `hardest` → Opus.

## 3. Build steps

### 3.1 Scaffold
```bash
mkdir -p jev-router && cd jev-router
printf 'TYPESAFE_API_KEY=\nANTHROPIC_API_KEY=\n' > .env && chmod 600 .env
```
Keys come from console.typesafe.ai and console.anthropic.com. Standard library only (`urllib`, `json`), so there is nothing to `pip install`.

### 3.2 Constants (`router.py`)
```python
JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_TIMEOUT_SECONDS = 4      # sizing must never block the caller
CONFIDENCE_FLOOR    = 0.60   # below this, self-handle
CONTEXT_ONLY_FLOOR  = 0.50   # noul probability above this = context-only reply

HELPERS = {
  "small":   {"model": "claude-haiku-4-5-20251001", "label": "Haiku 4.5"},
  "large":   {"model": "claude-sonnet-5",           "label": "Sonnet 5"},
  "hardest": {"model": "claude-opus-5",             "label": "Opus 5"},
}
```

### 3.3 The Jev request
POST to `JEV_URL` with `Authorization: Bearer $TYPESAFE_API_KEY`, `"model": "jev-latest"`, and two questions over `state = {message, prior_conversation?}`:

- `size` (type `choice`): criteria `small` (lookup, rename, one-liner, normal email/post/short doc), `large` (multi-step build, research, full report), `hardest` (strategy, or a costly-to-undo call). Judge the work, not the topic.
- `context_only_reply` (type `noul`): is the message a short reply that only makes sense inside `prior_conversation`?

Read `answers.size.choice`, `answers.size.confidence`, `answers.context_only_reply.noul`, and `usage.input_tokens/output_tokens`.

### 3.4 Decision logic (`route()`)
Apply the flow in section 2 in order. Every exit path increments exactly one counter (`small`, `large`, `hardest`, `self_handled`; plus `jev_failed` on errors) and saves state.

### 3.5 Helper call
POST to `https://api.anthropic.com/v1/messages` with `x-api-key`, `anthropic-version: 2023-06-01`, `max_tokens: 1024`, a 60s timeout. If context exists, prefix it as `Prior conversation:\n…\n\nMessage:\n…`. Append `— done by <label>` to the output. Return an error string rather than raising.

### 3.6 CLI
`on` / `off` flip `state["enabled"]`. `status` prints the table and token totals. `route "<msg>" [--context "<prior>"]` prints the result dict as JSON.

### 3.7 MCP sizer (optional, advice-only)
`mcp_server.py` imports `router` and speaks JSON-RPC over stdio (`initialize`, `tools/list`, `tools/call`, `ping`). One tool, `size_job(message, prior_conversation?)`, returns the bucket, confidence and a recommendation, or "keep current model" when unsure. Register it in your MCP client config (for example Claude Desktop's `claude_desktop_config.json`) as:
```json
{"mcpServers": {"jev-sizer": {"command": "python3", "args": ["/path/to/jev-router/mcp_server.py"]}}}
```

### 3.8 The `/jev` skill
`skill/SKILL.md` (copied to `~/.claude/skills/jev/` by `install.sh`) with `allowed-tools: [Bash]`. Argument is `on`, `off` or `status` (default `status`). It runs `python3 <repo>/router.py <arg>` by absolute path and prints the output unchanged. On `on`, it adds a one-line privacy reminder.

## 4. Verify
```bash
python3 router.py on
python3 router.py route "rename foo to bar in utils.py"        # expect small
python3 router.py route "design our 3-year pricing strategy"   # expect hardest
python3 router.py route "yes, do that" --context "Draft the email"  # expect routed:false
python3 router.py status
```
Also test the fail-open path: blank `TYPESAFE_API_KEY` and confirm `routed:false` with `jev_failed` incremented.

## 5. Known issues to fix
- **Model IDs are stale.** `claude-sonnet-5` and `claude-opus-5` should probably be `claude-sonnet-5-5` and `claude-opus-5-5`, and Haiku could move to `claude-haiku-5-5`. Confirm with a test call before changing.
- **Stale comment** above `HELPERS` in `router.py` says "see README note printed by `status`", but `status` prints no such note.
- **Context handling:** `route` only gets context if the caller passes it. Nothing yet feeds conversation history in automatically.
- **State writes aren't atomic or locked.** Concurrent calls can clobber counters. Write to a temp file and `os.replace`.
- **Privacy:** every routed message goes to TypeSafe and then Anthropic. Keep the router off for private work.
- **Cost reporting** is token counts only; the dollar figure lives in the TypeSafe console.

## 6. Possible next steps
1. Wire `route` into a real entry point (a Claude Code hook or a small proxy) so routing happens without a manual call.
2. Log each decision (bucket, confidence, latency) to a JSONL file for tuning the two thresholds.
3. Add a `--dry-run` flag that sizes without calling the helper.
4. Add unit tests that mock the Jev response.
