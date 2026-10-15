#!/usr/bin/env python3
"""A stand-in for the claude CLI, for tests. Emits canned stream-json.

Every call is appended to $FAKE_CLAUDE_LOG as one JSON line {args, prompt, cwd}.
Prompt keywords: SLOW (sleeps, for cancel tests), MAKEFILE (writes a PNG in cwd),
FAIL (exits with an error result).
"""
import json
import os
import sys
import time
import uuid


def log(entry):
    p = os.environ.get("FAKE_CLAUDE_LOG")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


def out(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    args = sys.argv[1:]
    if args[:1] == ["--version"]:
        print("9.9.9 (Fake Claude)")
        return 0
    if args[:2] == ["mcp", "add"]:
        log({"args": args, "cwd": os.getcwd()})
        print("Added HTTP MCP server kweo to user config")
        return 0
    prompt = sys.stdin.read() if "-p" in args else ""
    log({"args": args, "prompt": prompt, "cwd": os.getcwd()})
    sid = args[args.index("--resume") + 1] if "--resume" in args else str(uuid.uuid4())
    out({"type": "system", "subtype": "init", "session_id": sid, "cwd": os.getcwd(), "tools": []})
    if "FAIL" in prompt:
        out({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "Something broke.", "session_id": sid})
        return 1
    mid = "msg_1"
    out({"type": "stream_event", "session_id": sid, "event": {"type": "message_start", "message": {"id": mid}}})
    out({"type": "stream_event", "session_id": sid, "event": {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "tu_1", "name": "Bash", "input": {}}}})
    out({"type": "assistant", "session_id": sid, "message": {"id": mid, "content": [{"type": "tool_use", "id": "tu_1", "name": "Bash", "input": {"command": "python3 ~/.claude/skills/ig-reel/hookscore.py hooks.txt --json"}}]}})
    if "SLOW" in prompt:
        time.sleep(60)
    out({"type": "user", "session_id": sid, "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "[{\"score\": 87}]", "is_error": False}]}})
    made = ""
    if "MAKEFILE" in prompt:
        p = os.path.join(os.getcwd(), "fake-slide.png")
        with open(p, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\0" * 32)
        made = f" Saved {p}."
    mid2 = "msg_2"
    out({"type": "stream_event", "session_id": sid, "event": {"type": "message_start", "message": {"id": mid2}}})
    out({"type": "stream_event", "session_id": sid, "event": {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}})
    reply = ("Resumed. " if "--resume" in args else "") + "Hook A wins with 87." + made
    for i in range(0, len(reply), 7):
        out({"type": "stream_event", "session_id": sid, "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": reply[i:i + 7]}}})
    out({"type": "assistant", "session_id": sid, "message": {"id": mid2, "content": [{"type": "text", "text": reply}]}})
    out({"type": "result", "subtype": "success", "is_error": False, "result": reply, "session_id": sid, "total_cost_usd": 0.0, "num_turns": 2})
    return 0


if __name__ == "__main__":
    sys.exit(main())
