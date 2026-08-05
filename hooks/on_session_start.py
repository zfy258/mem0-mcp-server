#!/usr/bin/env python3
"""Codex SessionStart hook: print recent local Mem0 memories as context.

Plain text printed to stdout is added as extra developer context by Codex.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp_server import DEFAULT_USER, build_memory  # noqa: E402


def main():
    try:
        json.load(sys.stdin)
    except Exception:
        pass

    try:
        memory = build_memory()
        results = memory.get_all(filters={"user_id": DEFAULT_USER}, top_k=8)
        items = results.get("results", [])
        if not items:
            return
        print("## 本地 Mem0 记忆")
        for item in items:
            text = (item.get("memory") or "").replace("\n", " ")
            print(f"- {text[:200]}")
    except Exception as exc:  # hooks must never break the session
        print(f"<!-- mem0 session-start hook failed: {exc} -->", file=sys.stderr)


if __name__ == "__main__":
    main()
