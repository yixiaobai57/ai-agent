# 部署指南（公开 demo）

这个仓库的镜像是自包含的：前端在 `node:22-alpine` 里编译成静态文件，后端用
`python:3.12-slim` 单端口托管，**不填任何模型 Key 也能跑**（自动进入 Mock 模式）。
所以任何支持 Docker 的平台都能直接托起来。

## 一、给公开 demo 用的环境变量

公开实例和本地跑最大的区别是「谁都能来点」，所以超时要压死、会话别落盘：

| 变量 | 公开 demo 值 | 为什么 |
|---|---|---|
| `MOCK_LLM` | `true` | 不接真模型，零成本、结果确定，面试官点开就能试 |
| `MOCK_LATENCY` | `0.03` | 每个 chunk 停 30ms，前端能看到打字机效果（设 0 会一次性刷完） |
| `SESSION_BACKEND` | `memory` | 平台文件系统是临时的，SQLite 每次重启即失效；内存 + LRU 上限更稳 |
| `MAX_SESSIONS` | `200` | 陌生人也能开会话，给个上限防内存涨 |
| `SESSION_TTL` | `1800` | 半小时没人用就回收 |
| `ENABLE_CODE_EXEC` | `true` | 这是 demo 的亮点（能真跑代码），但见下一条 |
| `CODE_EXEC_TIMEOUT` | `5` | 陌生人提交的代码最多跑 5 秒就被 kill |
| `TOOL_TIMEOUT` | `15` | 单工具整体超时 |
| `ALLOW_RUNTIME_CONFIG` | `false` | 运行期改配置默认就该关；公开实例尤其不能开 |
| `LOG_LEVEL` | `WARNING` | 免得访问日志把平台日志刷满 |

`PORT` 由平台注入（Render 默认 `10000`），镜像里的健康检查已经跟着 `PORT` 走，无需改 Dockerfile。

## 二、Render（推荐，有免费档）

仓库根目录的 `render.yaml` 是 Blueprint，控制台选 **New → Blueprint** 指到本仓库即可，
上面这张表里的值都已经写在里面。

手动建服务等价于：**New → Web Service → 选本仓库 → Runtime 选 Docker → Health Check Path 填 `/health`**，
然后把上表的变量逐个加上。

**免费档的坑（必须知道）**：实例在 15 分钟无请求后休眠，下次访问要冷启动约 1 分钟。
「点开三秒就有判断」和这个天然冲突，两种解法：

1. 面试前 5 分钟先自己点一次，把实例唤醒；
2. 挂一个定时 ping（GitHub Actions `schedule` 每 10 分钟 curl 一次 `/health`），
   代价是每月约 4300 次请求，免费额度够用。仓库里 `.github/workflows/keepalive.yml` 就是干这个的。

## 三、Hugging Face Spaces

新建 **Docker** 类型 Space，`.dockerignore` 保持原样，端口按 Spaces 约定读 `PORT`（默认 `7860`），
在 Space 的 Settings → Variables 里加上表里的变量即可。免费、不会因流量超额停机，冷启动比 Render 免费档好一些。

## 四、自己的服务器 / 本地

```bash
docker compose up -d --build
# 等价于 MOCK_LLM=true docker run -p 8000:8000 ai-agent
```

不用 Docker 的话：

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cd frontend && npm ci && npm run build && cd ..
MOCK_LLM=true PORT=8000 python main.py
```

## 五、部署完怎么验收（别只看「部署成功」）

平台说成功只代表容器起来了，不代表这个 demo 能用。按顺序跑这四条：

```bash
# 1) 首页真的是编译后的前端，不是 404
curl -sI https://<域名>/ | head -1

# 2) 健康检查里 mock 必须为 true、技能数 5
curl -s https://<域名>/health

# 3) 配置接口不能回显任何 Key
curl -s https://<域名>/api/config

# 4) 真走一次对话：应该返回 trace 且 tools >= 1
curl -s -X POST https://<域名>/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"用 Python 写一个冒泡排序，然后执行它","session_id":"smoke"}'
```

第 4 条返回里没有 `trace.tools >= 1`，说明工具链路在容器里没跑起来（多半是工作目录不可写）。

## 六、公开实例的安全边界（写在明面上）

- Mock 模式下**没有任何模型调用**，不会产生费用，也不存在 Key 泄露面（`/api/config` 只回 `has_api_key: false`）。
- 代码执行仍然开着，但 `ENABLE_CODE_EXEC` 可随时关；AST 白名单 + 独立子进程 + 5 秒超时能挡住常见越权和卡死，
  **挡不住刻意的 CPU/内存耗尽**（见 SECURITY.md）。公开 demo 建议就按上表配置，别把超时放大。
- 文件读写被收敛在容器的 `/app/workspace` 里，容器重启即清空。
- 会话不落盘（`SESSION_BACKEND=memory`），不会留存任何访问者输入。
