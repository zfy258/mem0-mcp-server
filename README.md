# mem0-mcp-server

本机 Mem0 的通用 MCP 服务器：通过 stdio 向任意 MCP 客户端（Codex、Claude
Desktop、Cursor 等）提供持久记忆工具。数据完全保存在本地，不需要云端 API、
不需要 API key、也不需要额外安装 Python 包（复用你已有的 mem0 环境）。

## 它做了什么

这是一个最小的 MCP（Model Context Protocol）stdio 服务器。客户端通过标准输
入输出和它对话，它把请求转成对本地 `Memory` 类的调用：

```
MCP client ── stdio MCP ──▶ mcp_server.py ──▶ mem0.Memory（你的 Python 环境）
                                                   │
                                                   ├─ Qdrant（本地向量库）
                                                   └─ SQLite（历史记录）
```

所有记忆都只存在你自己的机器上（默认 `~/.mem0/` 下，可用 `MEM0_DIR` 覆盖）。

## 可用工具

| 工具 | 作用 |
| --- | --- |
| `add_memory` | 存一条记忆（默认原文存储，不调 LLM） |
| `search_memories` | 语义检索 |
| `get_memories` | 列出记忆 |
| `get_memory` | 按 ID 取单条记忆 |
| `update_memory` | 按 ID 改记忆 |
| `delete_memory` | 按 ID 删除 |
| `delete_all_memories` | 按 user/agent 清空 |

## 环境要求

- 一个已安装 OSS Mem0 的 Python 环境（`pip install mem0ai`），例如项目自带的
  `.venv`，或复用你现有的环境。
- Qdrant 以嵌入式模式运行（`qdrant-client` 自带的本地存储），不需要单独起服务。

## 安装到 MCP 客户端

把下面命令里的 `<VENV_PYTHON>` 换成你的 Python 解释器路径，`<REPO_DIR>` 换成
本仓库路径。

### Codex CLI

```bash
codex mcp add mem0-local -- \
  <VENV_PYTHON> \
  <REPO_DIR>/mcp_server.py
```

### Claude Desktop

```bash
claude mcp add mem0-local -- \
  <VENV_PYTHON> \
  <REPO_DIR>/mcp_server.py
```

### Cursor

在 Cursor 的 MCP 设置里新增一个 stdio 服务器，命令填：

```bash
<VENV_PYTHON> <REPO_DIR>/mcp_server.py
```

重启客户端后，问它一句"列出我的 mem0 记忆"或"记住我喜欢深色模式"，工具出现
就成功了。

## 先自测（不依赖 MCP 客户端）

```bash
MEM0_DIR=/tmp/mem0_home \
  <VENV_PYTHON> \
  <REPO_DIR>/mcp_server.py --self-test
```

## 关于 embedding 的说明

服务器按以下优先级自动选择 embedding（都不需要花钱）：

1. `OPENAI_API_KEY` 存在 → OpenAI embedding（1536 维）
2. 已安装 `fastembed` → FastEmbed + `BAAI/bge-small-zh-v1.5`（512 维，中文
   效果好，模型首次运行自动下载到本机缓存，进程内运行、无后台服务）
3. 本地 Ollama 在运行且装了 `ollama` Python 包 → Ollama embedding
4. 都没有 → `MockEmbeddings`（离线兜底，所有分数 1.0，仅供验证通路）

可用环境变量覆盖：`MEM0_LOCAL_FASTEMBED_MODEL`、`MEM0_LOCAL_OLLAMA_URL`、
`MEM0_LOCAL_OLLAMA_MODEL`。

## 已知边界

- 默认 `infer=False`（原文存储），不会自动做事实抽取/去重/实体链接。
- 这是学习用的最小实现，MCP 协议只实现了本桥需要的部分。

## 生命周期钩子（Codex 自动记忆）

`hooks/` 下有两个脚本，配合 `hooks/hooks.json` 使用：

- `on_session_start.py`：新会话开始时，把最近的本地记忆作为上下文打印出来，
  Codex 会把它当作 developer context 读入。
- `on_stop.py`：每次回复结束时，把"用户请求 + Codex 回复"存入本地 Mem0
  （每个 turn 只存一次，用 `~/.mem0/captured_turns/` 标记去重）。

安装（把钩子定义复制到用户级配置目录）：

```bash
cp <REPO_DIR>/hooks/hooks.json ~/.codex/hooks.json
```

然后把 `hooks.json` 里的 `<VENV_PYTHON>` 和 `<REPO_DIR>` 替换成真实路径。
首次运行时 Codex 会要求你在 `/hooks` 里审查并信任这两个钩子。

注意：钩子脚本会直接调用你 Python 环境里的 Mem0，不经过 MCP 服务器，所以即使
MCP 没接好，钩子也能独立工作。

## 代理变量

`mcp_server.py` 启动时会清掉 `ALL_PROXY` 等代理环境变量。原因是本服务只访问
本地服务，而系统里的 `socks://` 代理会让 httpx 初始化崩溃。
