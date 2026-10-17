#!/usr/bin/env python3
"""
Jev-based model router.

Sizes up each incoming message with Jev (TypeSafe) and hands it to the
smallest Claude model that can do the job well. Fails open: if the
switch is off, or Jev is slow/unreachable/wrong, the message is handled
normally (self-handled) with zero added delay to the caller.

Usage:
  python3 router.py on
  python3 router.py off
  python3 router.py status
  python3 router.py route "<message>" [--context "<prior turn(s), optional>"]
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "router_state.json")
ENV_PATH = os.path.join(BASE_DIR, ".env")

JEV_URL = "https://api.typesafe.ai/v1/systemone"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

JEV_TIMEOUT_SECONDS = 4  # sizing must never block the caller
CONFIDENCE_FLOOR = 0.60  # below this, self-handle
CONTEXT_ONLY_FLOOR = 0.50  # noul probability above this -> treat as context-only reply

# Smallest -> biggest. Jev picks one of these three buckets directly.
# Edit the model IDs to match what your Anthropic account can call.
HELPERS = {
    "small": {
        "model": "claude-haiku-4-5-20251001",
        "label": "Haiku 4.5",
        "desc": "Lookups, renames, one-line answers, a normal email/post/short document.",
    },
    "large": {
        "model": "claude-sonnet-5",
        "label": "Sonnet 5",
        "desc": "Multi-step builds, research, a full report.",
    },
    "hardest": {
        "model": "claude-opus-5",
        "label": "Opus 5",
        "desc": "Strategy, or anything where a wrong call is expensive.",
    },
}


def load_env():
    env = dict(os.environ)
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    return env


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {
        "enabled": False,
        "counts": {"small": 0, "large": 0, "hardest": 0, "self_handled": 0, "jev_failed": 0},
        "jev_tokens": {"input": 0, "output": 0},
        "jev_calls": 0,
    }


def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def set_switch(on: bool):
    state = load_state()
    state["enabled"] = on
    save_state(state)
    print(f"Router is now {'ON' if on else 'OFF'}.")


def print_status():
    state = load_state()
    c = state["counts"]
    total = sum(c.values())
    print(f"Router: {'ON' if state['enabled'] else 'OFF'}")
    print(f"Jev calls made: {state['jev_calls']}  (failed/timed out: {c['jev_failed']})")
    print()
    print(f"{'Destination':<14}{'Messages':<10}")
    print(f"{'-'*24}")
    print(f"{'small (Haiku)':<14}{c['small']:<10}")
    print(f"{'large (Sonnet)':<14}{c['large']:<10}")
    print(f"{'hardest (Opus)':<14}{c['hardest']:<10}")
    print(f"{'self-handled':<14}{c['self_handled']:<10}")
    print(f"{'-'*24}")
    print(f"{'total':<14}{total:<10}")
    print()
    tok = state["jev_tokens"]
    print(f"Jev token usage so far: {tok['input']} in / {tok['output']} out")
    print("(Jev sizing calls are tiny classification calls, not generation — cost is a")
    print(" small fraction of a cent per message. Check console.typesafe.ai for exact $.)")


def call_jev(env, message, context):
    api_key = env.get("TYPESAFE_API_KEY")
    if not api_key:
        raise RuntimeError("TYPESAFE_API_KEY not set")

    state_payload = {"message": message}
    if context:
        state_payload["prior_conversation"] = context

    body = {
        "state": state_payload,
        "model": "jev-latest",
        "questions": {
            "size": {
                "type": "choice",
                "instructions": (
                    "How big a job is `message` to do well? Judge the work itself, "
                    "not its topic."
                ),
                "criteria": {
                    "small": (
                        "A lookup, a rename, a one-line answer, a normal email, "
                        "post, or short document — routine, low-stakes work."
                    ),
                    "large": "A multi-step build, research task, or a full report.",
                    "hardest": (
                        "Strategy, or anything where a wrong call is expensive "
                        "and hard to undo."
                    ),
                },
            },
            "context_only_reply": {
                "type": "noul",
                "instructions": (
                    "Is `message` a short reply that only makes sense inside the "
                    "ongoing conversation in `prior_conversation` (e.g. 'yes do that "
                    "but make it shorter', 'ok go ahead', 'no, the other one') — "
                    "i.e. it cannot be sized or answered without that context?"
                ),
            },
        },
    }

    req = urllib.request.Request(
        JEV_URL,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=JEV_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode())


def call_helper(env, bucket, message, context):
    api_key = env.get("ANTHROPIC_API_KEY")
    helper = HELPERS[bucket]
    if not api_key:
        return f"[no ANTHROPIC_API_KEY set — cannot actually run {helper['label']}]"

    user_content = message if not context else f"Prior conversation:\n{context}\n\nMessage:\n{message}"
    body = {
        "model": helper["model"],
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": user_content}],
    }
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(body).encode(),
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        text = "".join(b.get("text", "") for b in data.get("content", []))
        return f"{text}\n\n— done by {helper['label']}"
    except Exception as e:
        return f"[helper call failed: {e}]"


def route(message, context=None):
    """Returns dict: {routed: bool, bucket, confidence, context_only_prob, reason, output}"""
    env = load_env()
    state = load_state()

    if not state.get("enabled"):
        state["counts"]["self_handled"] += 1
        save_state(state)
        return {"routed": False, "reason": "router is OFF"}

    t0 = time.time()
    try:
        jev_resp = call_jev(env, message, context)
    except Exception as e:
        state["counts"]["self_handled"] += 1
        state["counts"]["jev_failed"] += 1
        save_state(state)
        return {"routed": False, "reason": f"Jev unavailable ({e}) — fail-open", "latency_s": time.time() - t0}

    elapsed = time.time() - t0
    answers = jev_resp.get("answers", {})
    size_ans = answers.get("size", {})
    ctx_ans = answers.get("context_only_reply", {})
    bucket = size_ans.get("choice")
    confidence = size_ans.get("confidence", 0)
    context_only_prob = ctx_ans.get("noul", 0)

    usage = jev_resp.get("usage", {})
    state["jev_calls"] += 1
    state["jev_tokens"]["input"] += usage.get("input_tokens", 0)
    state["jev_tokens"]["output"] += usage.get("output_tokens", 0)

    if context_only_prob is not None and context_only_prob >= CONTEXT_ONLY_FLOOR:
        state["counts"]["self_handled"] += 1
        save_state(state)
        return {
            "routed": False,
            "reason": f"looks like a context-only reply (p={context_only_prob:.2f})",
            "bucket": bucket,
            "confidence": confidence,
            "context_only_prob": context_only_prob,
            "latency_s": elapsed,
        }

    if bucket not in HELPERS or confidence < CONFIDENCE_FLOOR:
        state["counts"]["self_handled"] += 1
        save_state(state)
        return {
            "routed": False,
            "reason": f"low confidence ({confidence:.2f} < {CONFIDENCE_FLOOR})",
            "bucket": bucket,
            "confidence": confidence,
            "context_only_prob": context_only_prob,
            "latency_s": elapsed,
        }

    state["counts"][bucket] += 1
    save_state(state)
    output = call_helper(env, bucket, message, context)
    return {
        "routed": True,
        "bucket": bucket,
        "confidence": confidence,
        "context_only_prob": context_only_prob,
        "latency_s": elapsed,
        "output": output,
    }


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    if cmd == "on":
        set_switch(True)
    elif cmd == "off":
        set_switch(False)
    elif cmd == "status":
        print_status()
    elif cmd == "route":
        message = args[1] if len(args) > 1 else ""
        context = None
        if "--context" in args:
            context = args[args.index("--context") + 1]
        result = route(message, context)
        print(json.dumps(result, indent=2))
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
