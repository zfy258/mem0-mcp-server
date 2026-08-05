#!/usr/bin/env python3
"""Local Mem0 MCP server (stdio).

Exposes the locally installed OSS Mem0 (the ``Memory`` class from your
virtual environment) to any MCP client (Codex, Claude, Cursor, ...) as MCP
tools over stdio. No cloud API, no API key, no extra Python dependencies.

Protocol: Model Context Protocol (stdio transport, newline-delimited
JSON-RPC 2.0). This is a minimal implementation on purpose: it keeps the
bridge dependency-free and easy to read.

Register with any MCP client, e.g. Codex:
    codex mcp add mem0-local -- \
        <VENV_PYTHON> \
        <REPO_DIR>/mcp_server.py

Self-test without an MCP client:
    MEM0_DIR=/tmp/mem0_home \
        <VENV_PYTHON> \
        <REPO_DIR>/mcp_server.py --self-test
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import sys
import traceback

# Mem0's telemetry tries to phone home; keep it off for a local tool.
os.environ.setdefault("MEM0_TELEMETRY", "false")

# The user's shell often exports a socks:// proxy that httpx cannot parse.
# This bridge talks to localhost only, so strip proxies before mem0 imports
# any HTTP client. Remove this block if you later need a network proxy.
for _proxy_var in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(_proxy_var, None)

SERVER_NAME = "mem0-local"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"
DEFAULT_USER = "default_user"
OLLAMA_HOST = os.environ.get("MEM0_LOCAL_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("MEM0_LOCAL_OLLAMA_MODEL", "nomic-embed-text")
FASTEMBED_MODEL = os.environ.get("MEM0_LOCAL_FASTEMBED_MODEL", "BAAI/bge-small-zh-v1.5")


TOOLS = [
    {
        "name": "add_memory",
        "description": (
            "Store a memory in the local OSS Mem0 store. By default the text is "
            "stored verbatim with no LLM call (offline, free). Set infer=true to "
            "run Mem0's LLM fact extraction (requires a configured LLM)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text content to remember."},
                "user_id": {"type": "string", "description": "Scope the memory to a user. Defaults to 'default_user'."},
                "agent_id": {"type": "string", "description": "Optionally scope the memory to an agent."},
                "metadata": {"type": "object", "description": "Optional metadata attached to the memory."},
                "infer": {
                    "type": "boolean",
                    "description": "If true, use the LLM to extract facts. Default false (raw storage).",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "search_memories",
        "description": "Search memories by semantic similarity. Uses local embeddings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "user_id": {"type": "string", "description": "Filter by user. Defaults to 'default_user'."},
                "agent_id": {"type": "string", "description": "Filter by agent."},
                "top_k": {"type": "integer", "description": "Max results. Default 10."},
                "threshold": {"type": "number", "description": "Minimum score. Default 0.1."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_memories",
        "description": "List stored memories, newest first, with optional user/agent filters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "Filter by user. Defaults to 'default_user'."},
                "agent_id": {"type": "string", "description": "Filter by agent."},
                "top_k": {"type": "integer", "description": "Max results. Default 20."},
            },
            "required": [],
        },
    },
    {
        "name": "get_memory",
        "description": "Retrieve a single memory by its ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "Memory ID returned by add/search/list."},
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "update_memory",
        "description": "Overwrite the text (and optionally metadata) of a memory by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "Memory ID to update."},
                "text": {"type": "string", "description": "New memory text."},
                "metadata": {"type": "object", "description": "New metadata (replaces old metadata)."},
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "delete_memory",
        "description": "Delete a single memory by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "Memory ID to delete."},
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "delete_all_memories",
        "description": "Delete all memories for a user and/or agent. At least one scope is required.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "Delete memories scoped to this user."},
                "agent_id": {"type": "string", "description": "Delete memories scoped to this agent."},
            },
            "required": [],
        },
    },
]


def _mem0_dir() -> str:
    return os.environ.get("MEM0_DIR") or os.path.join(os.path.expanduser("~"), ".mem0")


def _ollama_available() -> bool:
    """True when the Ollama server is reachable and the `ollama` client is installed."""
    if importlib.util.find_spec("ollama") is None:
        return False
    try:
        host = OLLAMA_HOST.replace("http://", "").replace("https://", "").split(":")[0]
        port = int(OLLAMA_HOST.split(":")[-1].split("/")[0]) if ":" in OLLAMA_HOST else 11434
        sock = socket.create_connection((host, port), timeout=0.5)
        sock.close()
        return True
    except OSError:
        return False


def _fastembed_available() -> bool:
    return importlib.util.find_spec("fastembed") is not None


def build_memory():
    """Create the local OSS Memory instance.

    If OPENAI_API_KEY is present we use real OpenAI embeddings (and the LLM for
    infer=true). Otherwise we fall back to MockEmbeddings so the bridge works
    fully offline; semantic ranking is then degraded (all scores 1.0), which is
    fine for plumbing but not for real retrieval quality.
    """
    from mem0 import Memory
    from mem0.embeddings.mock import MockEmbeddings

    mem0_dir = _mem0_dir()
    api_key = os.environ.get("OPENAI_API_KEY")

    if api_key:
        config = {
            "llm": {"provider": "openai", "config": {"model": "gpt-5-mini"}},
            "embedder": {"provider": "openai", "config": {}},
            "vector_store": {
                "provider": "qdrant",
                "config": {"path": os.path.join(mem0_dir, "qdrant"), "embedding_model_dims": 1536},
            },
            "history_db_path": os.path.join(mem0_dir, "history.db"),
        }
        memory = Memory.from_config(config)
    elif _fastembed_available():
        try:
            print(
                f"mem0-local: using local FastEmbed ({FASTEMBED_MODEL}).",
                file=sys.stderr,
            )
            config = {
                "llm": {
                    "provider": "openai",
                    "config": {"model": "gpt-5-mini", "api_key": "dummy"},  # never called with infer=False
                },
                "embedder": {
                    "provider": "fastembed",
                    "config": {"model": FASTEMBED_MODEL},
                },
                "vector_store": {
                    "provider": "qdrant",
                    "config": {"path": os.path.join(mem0_dir, "qdrant"), "embedding_model_dims": 512},
                },
                "history_db_path": os.path.join(mem0_dir, "history.db"),
            }
            memory = Memory.from_config(config)
            # Force model download/load now so a slow first start happens here,
            # and so failures fall back instead of breaking the first tool call.
            memory.embedding_model.dense_model
            return memory
        except Exception as exc:  # noqa: BLE001 - model download or init can fail offline
            print(f"mem0-local: FastEmbed init failed ({exc}); falling back.", file=sys.stderr)
    elif _ollama_available():
        print(
            f"mem0-local: using local Ollama embedding ({OLLAMA_MODEL} @ {OLLAMA_HOST}).",
            file=sys.stderr,
        )
        config = {
            "llm": {
                "provider": "openai",
                "config": {"model": "gpt-5-mini", "api_key": "dummy"},  # never called with infer=False
            },
            "embedder": {
                "provider": "ollama",
                "config": {
                    "model": OLLAMA_MODEL,
                    "ollama_base_url": OLLAMA_HOST,
                    "embedding_dims": 512,
                },
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {"path": os.path.join(mem0_dir, "qdrant"), "embedding_model_dims": 512},
            },
            "history_db_path": os.path.join(mem0_dir, "history.db"),
        }
        memory = Memory.from_config(config)
    else:
        print(
            "mem0-local: OPENAI_API_KEY not set; using MockEmbeddings (offline, raw storage). "
            "Set OPENAI_API_KEY or configure Ollama for real semantic search.",
            file=sys.stderr,
        )
        config = {
            "llm": {
                "provider": "openai",
                "config": {"model": "gpt-5-mini", "api_key": "dummy"},  # never called with infer=False
            },
            "embedder": {
                "provider": "openai",
                "config": {"api_key": "dummy"},  # replaced by MockEmbeddings below
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {"path": os.path.join(mem0_dir, "qdrant"), "embedding_model_dims": 10},
            },
            "history_db_path": os.path.join(mem0_dir, "history.db"),
        }
        memory = Memory.from_config(config)
        memory.embedding_model = MockEmbeddings()

    return memory


_memory = None


def get_memory():
    global _memory
    if _memory is None:
        _memory = build_memory()
    return _memory


def _filters(user_id=None, agent_id=None):
    filters = {}
    if user_id:
        filters["user_id"] = user_id
    if agent_id:
        filters["agent_id"] = agent_id
    if not filters:
        filters["user_id"] = DEFAULT_USER
    return filters


def call_tool(name, args):
    memory = get_memory()
    args = args or {}

    if name == "add_memory":
        text = args.get("text")
        if not text:
            raise ValueError("add_memory requires 'text'")
        return memory.add(
            [{"role": "user", "content": text}],
            user_id=args.get("user_id") or DEFAULT_USER,
            agent_id=args.get("agent_id"),
            metadata=args.get("metadata"),
            infer=bool(args.get("infer", False)),
        )

    if name == "search_memories":
        query = args.get("query")
        if not query:
            raise ValueError("search_memories requires 'query'")
        return memory.search(
            query,
            filters=_filters(args.get("user_id"), args.get("agent_id")),
            top_k=int(args.get("top_k", 10)),
            threshold=float(args.get("threshold", 0.1)),
        )

    if name == "get_memories":
        return memory.get_all(
            filters=_filters(args.get("user_id"), args.get("agent_id")),
            top_k=int(args.get("top_k", 20)),
        )

    if name == "get_memory":
        return memory.get(args.get("memory_id"))

    if name == "update_memory":
        return memory.update(
            args.get("memory_id"),
            text=args.get("text"),
            metadata=args.get("metadata"),
        )

    if name == "delete_memory":
        return memory.delete(args.get("memory_id"))

    if name == "delete_all_memories":
        user_id = args.get("user_id")
        agent_id = args.get("agent_id")
        if not user_id and not agent_id:
            raise ValueError("delete_all_memories requires 'user_id' or 'agent_id'")
        return memory.delete_all(user_id=user_id, agent_id=agent_id)

    raise ValueError(f"Unknown tool: {name}")


# --- Minimal MCP stdio transport ------------------------------------------


def read_request():
    """Read one newline-delimited JSON-RPC message from stdin."""
    buffer = ""
    while True:
        line = sys.stdin.readline()
        if not line:
            return None
        buffer += line
        try:
            return json.loads(buffer)
        except json.JSONDecodeError:
            # Message spans multiple lines; keep buffering.
            continue


def send(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(msg):
    method = msg.get("method")
    msg_id = msg.get("id")

    if method == "initialize":
        send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            }
        )
        return

    if method == "notifications/initialized" or method == "notifications/cancelled":
        return  # notifications have no id and no response

    if method == "ping":
        send({"jsonrpc": "2.0", "id": msg_id, "result": {}})
        return

    if method == "tools/list":
        send({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}})
        return

    if method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name")
        try:
            result = call_tool(name, params.get("arguments") or {})
            send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001 - report any failure back to the client
            traceback.print_exc(file=sys.stderr)
            send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {exc}"}],
                        "isError": True,
                    },
                }
            )
        return

    if msg_id is not None:
        send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        )


def serve():
    while True:
        msg = read_request()
        if msg is None:
            break
        handle(msg)


def self_test():
    memory = get_memory()
    print(json.dumps({"memory_dir": _mem0_dir(), "offline": os.environ.get("OPENAI_API_KEY") is None}, indent=2))

    added = memory.add(
        [{"role": "user", "content": "我喜欢喝美式咖啡"}],
        user_id="alice",
        infer=False,
    )
    print(json.dumps({"add": added}, ensure_ascii=False, indent=2))

    results = memory.search("咖啡", filters={"user_id": "alice"}, top_k=5)
    print(json.dumps({"search": results}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Local Mem0 MCP server (stdio)")
    parser.add_argument("--self-test", action="store_true", help="Run a local add/search check and exit.")
    args = parser.parse_args()

    if args.self_test:
        self_test()
    else:
        serve()


if __name__ == "__main__":
    main()
