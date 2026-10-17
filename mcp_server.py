#!/usr/bin/env python3
"""MCP stdio server exposing Jev job-sizing as a tool (advice only, no routing)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import router  # noqa: E402

TOOL = {
    "name": "size_job",
    "description": (
        "Ask Jev how big a job a message is and which Claude model is the smallest "
        "that can do it well. Returns small (Haiku), large (Sonnet) or hardest (Opus), "
        "with Jev's confidence. PRIVACY: the message text is sent to TypeSafe (Jev's "
        "maker); do not call this for private or sensitive content."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "The user's message to size up."},
            "prior_conversation": {
                "type": "string",
                "description": "Optional short summary of the prior turn(s), for short replies.",
            },
        },
        "required": ["message"],
    },
}


def size_job(message, context):
    env = router.load_env()
    try:
        resp = router.call_jev(env, message, context)
    except Exception as e:
        return {"recommendation": "unknown", "advice": f"Jev unavailable ({e}); carry on with the current model."}
    a = resp.get("answers", {})
    bucket = a.get("size", {}).get("choice")
    conf = a.get("size", {}).get("confidence", 0)
    ctx_only = a.get("context_only_reply", {}).get("noul", 0)
    if ctx_only >= router.CONTEXT_ONLY_FLOOR:
        return {"size": bucket, "confidence": conf, "context_only_reply": ctx_only,
                "recommendation": "keep current model",
                "advice": "Short reply that only makes sense in this conversation; stay on the current model."}
    if bucket not in router.HELPERS or conf < router.CONFIDENCE_FLOOR:
        return {"size": bucket, "confidence": conf, "context_only_reply": ctx_only,
                "recommendation": "keep current model",
                "advice": "Jev is not sure enough; stay on the current model."}
    h = router.HELPERS[bucket]
    return {"size": bucket, "confidence": conf, "context_only_reply": ctx_only,
            "recommendation": h["label"],
            "advice": f"Smallest model that can do this well: {h['label']} ({h['desc']})"}


def reply(msg_id, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": msg_id}
    if error:
        out["error"] = error
    else:
        out["result"] = result
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        method, msg_id = req.get("method"), req.get("id")
        if msg_id is None:
            continue
        if method == "initialize":
            reply(msg_id, {
                "protocolVersion": req.get("params", {}).get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "jev-sizer", "version": "1.0.0"},
            })
        elif method == "tools/list":
            reply(msg_id, {"tools": [TOOL]})
        elif method == "tools/call":
            args = req.get("params", {}).get("arguments", {})
            result = size_job(args.get("message", ""), args.get("prior_conversation"))
            reply(msg_id, {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]})
        elif method == "ping":
            reply(msg_id, {})
        else:
            reply(msg_id, error={"code": -32601, "message": f"Method not found: {method}"})


if __name__ == "__main__":
    main()
