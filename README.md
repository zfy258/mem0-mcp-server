# mem0-mcp-server

A local MCP server that exposes [Mem0](https://github.com/mem0ai/mem0) as
persistent memory tools to any MCP client: Codex, Claude Desktop, Cursor, and
anything else that speaks MCP over stdio.

Everything runs on your own machine. Data lives under `~/.mem0/`, there is no
cloud API and no API key required.

---

## Why this exists

MCP clients like Codex already support memory tools over MCP, but most "memory
server" setups push you toward a hosted service. This project is the opposite:
Mem0 runs locally (Qdrant in embedded mode, SQLite for history), and the
server is a thin MCP bridge in front of it.

The server is intentionally small. It implements just enough of the MCP
protocol to expose a set of memory tools. No framework, no extra runtime,
one Python file.

## How it works

```
MCP client ── stdio ──▶ mcp_server.py ──▶ mem0.Memory (your Python env)
                                              │
                                              ├─ Qdrant (local vector store)
                                              └─ SQLite (history)
```

The client starts `mcp_server.py` as a subprocess and talks to it over
newline-delimited JSON-RPC on stdin/stdout.

## Tools

| Tool | What it does |
| --- | --- |
| `add_memory` | Store a memory (raw text by default, no LLM call) |
| `search_memories` | Semantic search |
| `get_memories` | List memories, newest first |
| `get_memory` | Fetch one memory by ID |
| `update_memory` | Replace the text/metadata of a memory |
| `delete_memory` | Delete one memory |
| `delete_all_memories` | Clear memories for a user and/or agent |

## Requirements

- Python 3.10 or newer
- An MCP client (Codex, Claude Desktop, Cursor, ...)
- Optional but recommended: `fastembed` for local semantic search

## Install

The project is pip-installable:

```bash
python -m venv .venv
source .venv/bin/activate
pip install .
```

If you prefer an editable install while developing:

```bash
pip install -e .
```

Optional extras:

```bash
pip install ".[fastembed]"   # local embeddings, recommended
pip install ".[ollama]"      # use a local Ollama instance for embeddings
```

Already have a Python environment with Mem0 installed? Then you don't need
to install anything. Just point your MCP client at
`<REPO_DIR>/mcp_server.py` and use that environment's Python.

## Quick test

Run this before wiring up a client, so you know the server itself works:

```bash
mem0-mcp-server --self-test
```

Or, without installing:

```bash
MEM0_DIR=/tmp/mem0_home \
  <VENV_PYTHON> <REPO_DIR>/mcp_server.py --self-test
```

The self-test writes one memory ("我喜欢喝美式咖啡"), searches for it, and
prints both results.

## Register with an MCP client

In the commands below, `<VENV_PYTHON>` is the absolute path to your Python
interpreter and `<REPO_DIR>` is the absolute path to this repository.

### Codex CLI

```bash
codex mcp add mem0-local -- \
  <VENV_PYTHON> \
  <REPO_DIR>/mcp_server.py
```

Restart Codex, then try: "list my mem0 memories" or "remember that I like
dark mode".

### Claude Desktop

```bash
claude mcp add mem0-local -- \
  <VENV_PYTHON> \
  <REPO_DIR>/mcp_server.py
```

### Cursor

Open the MCP settings in Cursor, add a new stdio server, and set the command
to:

```bash
<VENV_PYTHON> <REPO_DIR>/mcp_server.py
```

If you installed the package, you can also register the console script
`mem0-mcp-server` directly instead of pointing at `mcp_server.py`.

## Embedding options

The server picks an embedding backend in this order:

1. `OPENAI_API_KEY` is set → OpenAI embeddings (1536 dims)
2. `fastembed` is installed → FastEmbed with `BAAI/bge-small-zh-v1.5`
   (512 dims, works well for Chinese, first run downloads the model)
3. Ollama is running and the `ollama` package is installed → Ollama embeddings
4. Nothing available → `MockEmbeddings`, fully offline but all scores are 1.0

Environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `MEM0_LOCAL_FASTEMBED_MODEL` | `BAAI/bge-small-zh-v1.5` | FastEmbed model name |
| `MEM0_LOCAL_OLLAMA_URL` | `http://localhost:11434` | Ollama base URL |
| `MEM0_LOCAL_OLLAMA_MODEL` | `nomic-embed-text` | Ollama model name |
| `MEM0_DIR` | `~/.mem0` | Where memory data is stored |

## Automatic memory hooks (Codex only)

The `hooks/` directory contains two scripts that give Codex automatic memory:

- `on_session_start.py` — prints recent memories at session start; Codex reads
  them as developer context.
- `on_stop.py` — saves the last user request + assistant reply after every
  turn. Each turn is captured once, deduplicated via
  `~/.mem0/captured_turns/`.

Install them:

```bash
cp <REPO_DIR>/hooks/hooks.json ~/.codex/hooks.json
```

Then edit `~/.codex/hooks.json` and replace the `<VENV_PYTHON>` and
`<REPO_DIR>` placeholders with real paths. The first time Codex runs the
hooks, it will ask you to review and trust them under `/hooks`.

These hooks are Codex-specific. Other MCP clients don't have this hook
mechanism, so they get the memory tools but not automatic context loading or
automatic turn saving.

## Data and privacy

- All data stays on your machine under `~/.mem0/` (or `$MEM0_DIR`).
- Telemetry is disabled: the server sets `MEM0_TELEMETRY=false` at startup.
- Proxy environment variables are stripped at startup because the server only
  talks to local services, and a `socks://` proxy can crash httpx during
  initialization.
- With no `OPENAI_API_KEY`, no network request is made at all.

## Known limitations

- Default is `infer=False`: memories are stored as raw text, without Mem0's
  LLM-based fact extraction, deduplication, or entity linking.
- This is a minimal MCP implementation. It covers the tools listed above and
  nothing more.
- The server has been tested mainly with Codex. It speaks standard MCP, so
  other clients should work, but if something misbehaves, open an issue.

## Project layout

```
mem0-mcp-server/
├── LICENSE
├── README.md
├── pyproject.toml
├── mcp_server.py
└── hooks/
    ├── hooks.json
    ├── on_session_start.py
    └── on_stop.py
```

## License

MIT. See `LICENSE`.

---

# mem0-mcp-server（中文）

一个本地 MCP 服务器，把 [Mem0](https://github.com/mem0ai/mem0) 的记忆能力以
MCP 工具的形式暴露给任意客户端：Codex、Claude Desktop、Cursor，以及其他支持
stdio MCP 的 agent。

全部在本机运行，数据默认存在 `~/.mem0/`，不依赖云端 API，也不需要 API key。

## 为什么做这个

Codex 这类 MCP 客户端本身支持通过 MCP 调用记忆工具，但常见的“记忆服务器”方案
往往把你往托管服务上引。这个项目反过来：Mem0 完全本地运行（Qdrant 嵌入式模式 +
SQLite 历史记录），服务器只是它前面的一层很薄的 MCP 桥。

实现刻意保持精简：只实现了一组记忆工具需要的 MCP 协议部分，没有框架、没有额外
运行时，核心就是一个 Python 文件。

## 工作原理

```
MCP 客户端 ── stdio ──▶ mcp_server.py ──▶ mem0.Memory（你的 Python 环境）
                                              │
                                              ├─ Qdrant（本地向量库）
                                              └─ SQLite（历史记录）
```

客户端把 `mcp_server.py` 作为子进程启动，通过 stdin/stdout 上的换行分隔
JSON-RPC 通信。

## 可用工具

| 工具 | 作用 |
| --- | --- |
| `add_memory` | 存一条记忆（默认原文存储，不调 LLM） |
| `search_memories` | 语义检索 |
| `get_memories` | 列出记忆，新的在前 |
| `get_memory` | 按 ID 取单条记忆 |
| `update_memory` | 按 ID 修改记忆文本/元数据 |
| `delete_memory` | 按 ID 删除一条记忆 |
| `delete_all_memories` | 按 user/agent 清空记忆 |

## 环境要求

- Python 3.10 及以上
- 一个 MCP 客户端（Codex、Claude Desktop、Cursor 等）
- 可选但推荐：`fastembed`，用于本地语义检索

## 安装

项目支持 pip 安装：

```bash
python -m venv .venv
source .venv/bin/activate
pip install .
```

开发时可以用可编辑安装：

```bash
pip install -e .
```

可选依赖：

```bash
pip install ".[fastembed]"   # 本地 embedding，推荐
pip install ".[ollama]"      # 用本地 Ollama 做 embedding
```

如果你已经有一个装好 Mem0 的 Python 环境，那什么都不用装，直接用那个环境的
Python 指向 `<REPO_DIR>/mcp_server.py` 注册即可。

## 快速自测

接客户端之前先跑一下，确认服务器本身没问题：

```bash
mem0-mcp-server --self-test
```

不想安装也可以：

```bash
MEM0_DIR=/tmp/mem0_home \
  <VENV_PYTHON> <REPO_DIR>/mcp_server.py --self-test
```

自测会写入一条记忆（“我喜欢喝美式咖啡”）、检索它，然后打印结果。

## 注册到 MCP 客户端

下面命令里的 `<VENV_PYTHON>` 是你的 Python 解释器绝对路径，`<REPO_DIR>` 是
本仓库的绝对路径。

### Codex CLI

```bash
codex mcp add mem0-local -- \
  <VENV_PYTHON> \
  <REPO_DIR>/mcp_server.py
```

重启 Codex 后试试：“列出我的 mem0 记忆”，或者“记住我喜欢深色模式”。

### Claude Desktop

```bash
claude mcp add mem0-local -- \
  <VENV_PYTHON> \
  <REPO_DIR>/mcp_server.py
```

### Cursor

打开 Cursor 的 MCP 设置，新增一个 stdio 服务器，命令填：

```bash
<VENV_PYTHON> <REPO_DIR>/mcp_server.py
```

如果用 pip 安装过，也可以直接把控制台命令 `mem0-mcp-server` 注册进去，不用
指向 `mcp_server.py`。

## Embedding 说明

服务器按下面的优先级选择 embedding：

1. 设置了 `OPENAI_API_KEY` → OpenAI embedding（1536 维）
2. 装了 `fastembed` → FastEmbed + `BAAI/bge-small-zh-v1.5`（512 维，中文效果
   好，首次运行会自动下载模型）
3. 本地 Ollama 在运行且装了 `ollama` 包 → Ollama embedding
4. 都没有 → `MockEmbeddings`，完全离线，但所有分数都是 1.0

环境变量：

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `MEM0_LOCAL_FASTEMBED_MODEL` | `BAAI/bge-small-zh-v1.5` | FastEmbed 模型名 |
| `MEM0_LOCAL_OLLAMA_URL` | `http://localhost:11434` | Ollama 地址 |
| `MEM0_LOCAL_OLLAMA_MODEL` | `nomic-embed-text` | Ollama 模型名 |
| `MEM0_DIR` | `~/.mem0` | 记忆数据存放位置 |

## 自动记忆钩子（仅 Codex）

`hooks/` 里有两个脚本，给 Codex 提供自动记忆：

- `on_session_start.py`：会话开始时打印最近的记忆，Codex 会把它当作 developer
  context 读入。
- `on_stop.py`：每轮回复结束后，把“用户请求 + Codex 回复”存进本地 Mem0，
  每个 turn 只存一次，通过 `~/.mem0/captured_turns/` 去重。

安装：

```bash
cp <REPO_DIR>/hooks/hooks.json ~/.codex/hooks.json
```

然后把 `~/.codex/hooks.json` 里的 `<VENV_PYTHON>` 和 `<REPO_DIR>` 占位符换成
真实路径。Codex 第一次运行钩子时，会要求你在 `/hooks` 里审查并信任它们。

这套钩子是 Codex 专用的。其他 MCP 客户端没有这种钩子机制，所以它们能用记忆
工具，但没有自动加载上下文和自动保存每一轮对话的功能。

## 数据与隐私

- 所有数据都在本机 `~/.mem0/`（或 `$MEM0_DIR`）下。
- 遥测已关闭：服务器启动时会设置 `MEM0_TELEMETRY=false`。
- 启动时会清掉代理环境变量，因为本服务只访问本地服务，而 `socks://` 代理会让
  httpx 初始化崩溃。
- 不设置 `OPENAI_API_KEY` 时，完全不会发起网络请求。

## 已知边界

- 默认 `infer=False`：记忆按原文存储，不做 Mem0 的 LLM 事实抽取、去重和实体
  链接。
- 这是最小实现，MCP 协议只覆盖上面列出的工具。
- 目前主要用 Codex 测过。它实现的是标准 MCP，其他客户端理论上能用，但如果出
  问题，欢迎提 issue。

## 目录结构

```
mem0-mcp-server/
├── LICENSE
├── README.md
├── pyproject.toml
├── mcp_server.py
└── hooks/
    ├── hooks.json
    ├── on_session_start.py
    └── on_stop.py
```

## 许可证

MIT，见 `LICENSE`。
