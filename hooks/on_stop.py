#!/usr/bin/env python3
"""Codex Stop hook: capture the current turn into local Mem0.

Reads the hook input JSON from stdin, extracts the last user prompt and last
assistant reply from the session transcript, and stores them as one local
memory with infer=False (no LLM, no cloud). Each turn is captured once.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp_server import DEFAULT_USER, _mem0_dir, build_memory  # noqa: E402


def parse_transcript(path):
    users, assistants = [], []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = obj.get("payload") or {}
                if obj.get("type") != "response_item" or payload.get("type") != "message":
                    continue
                role = payload.get("role")
                if role not in ("user", "assistant"):
                    continue
                text = "".join(
                    c.get("text", "")
                    for c in (payload.get("content") or [])
                    if isinstance(c, dict) and c.get("type") in ("input_text", "output_text")
                ).strip()
                if not text:
                    continue
                if role == "user":
                    users.append(text)
                else:
                    assistants.append(text)
    except OSError:
        pass
    return users, assistants


def main():
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        return

    turn_id = hook_input.get("turn_id") or ""
    transcript = hook_input.get("transcript_path") or ""
    if not turn_id or not transcript:
        return

    # Deduplicate: store each turn only once.
    marker_dir = os.path.join(_mem0_dir(), "captured_turns")
    try:
        os.makedirs(marker_dir, exist_ok=True)
        marker_file = os.path.join(marker_dir, turn_id)
        if os.path.exists(marker_file):
            return
        open(marker_file, "w").close()
    except OSError:
        return

    users, assistants = parse_transcript(transcript)
    if not users and not assistants:
        return

    last_user = (users[-1] if users else "").strip()[:400]
    last_assistant = (assistants[-1] if assistants else "").strip()[:800]
    summary = f"用户请求: {last_user}"
    if last_assistant:
        summary += f"\nCodex 回复: {last_assistant}"

    try:
        memory = build_memory()
        memory.add(
            [{"role": "user", "content": summary}],
            user_id=DEFAULT_USER,
            agent_id="codex",
            metadata={
                "session_id": hook_input.get("session_id") or "",
                "turn_id": turn_id,
                "cwd": hook_input.get("cwd") or "",
            },
            infer=False,
        )
    except Exception as exc:  # hooks must never break the session
        print(f"<!-- mem0 stop hook failed: {exc} -->", file=sys.stderr)


if __name__ == "__main__":
    main()
