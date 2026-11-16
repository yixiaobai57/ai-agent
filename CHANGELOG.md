# 更新日志

遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)；版本号用 `主版本.次版本.修订号`。

## [3.0.0] - 2026-11-16

从「能演示」升级到「能交付」：修掉 5 个真实缺陷/安全漏洞，补齐测试、静态检查、CI、容器化与文档。

### 安全（Security）

- **`POST /api/config` 默认关闭**：v2 无鉴权且可改写 `base_url`，等于允许任何人把 API Key 转发到自己的服务器。
  现在必须 `ALLOW_RUNTIME_CONFIG=true` 且携带 `X-Admin-Token`（`hmac.compare_digest` 比较），否则返回
  `403 runtime_config_disabled` / `401 unauthorized`。
- **CORS 白名单化**：移除 `allow_origins=["*"]` 与 `allow_credentials=True` 的非法组合。
- **文件路径边界**：从 `startswith` 字符串比较改为 `os.path.commonpath` 目录级判断，
  修复 `workspace2/` 等同前缀兄弟目录可越权读写的问题；`BASE` 不再在 import 期按 CWD 解析。
- **代码执行隔离**：黑名单 → AST 白名单 + 危险调用拦截（`eval/exec/compile/__import__/getattr-dunder`），
  从宿主 `exec` 改为 `python -I` 子进程 + 独立临时工作目录 + 超时 kill，不再污染全局 `sys.stdout`。
- 请求体超限返回 `413 payload_too_large`；`GET /api/config` 只回 `has_api_key`，绝不回显密钥。
- **构建产物不含密钥**：`.dockerignore` 排除 `.env` / `.env.*`（此前 `COPY . .` 会把本地密钥打进镜像层）。
- **`docker compose up` 不再硬依赖 `.env`**：改为 `${VAR:-默认}` 插值透传，缺省的 Key 自动进入 Mock 模式。

### 修复（Fixed）

- **长对话 400**：记忆按条数硬切会切断 `assistant(tool_calls)` 与 `tool` 消息的配对。
  改为只在 user 轮边界切窗，并按 token 预算整组裁剪。
- **并发回调竞态**：单例 Agent 上覆盖 `on_stream` 会导致同一会话多标签页互相抢回调；
  改为 `run(message, on_event=cb)` 按调用传入。
- **空 registry 假值**：`WorkflowEngine(skill_registry or registry)` 中空注册表因 `__len__ == 0`
  被当成假值，静默改用全局注册表；改为 `is not None`。
- **工具失败不可纠错**：工具异常不再穿透到 HTTP 层，统一转成 `ERROR[<code>]: ...` 回喂模型。
- **超时后线程继续跑**：v2 的 `wait_for` 超时后目标仍在执行；v3 超时直接 kill 子进程。
- **测试跨平台化**：`test_absolute_path_is_blocked` 原先用 `SYSTEMROOT`/`C:/Windows` 构造越界路径，
  在 Linux 上退化成相对路径、断言从 `path_escape` 变成 `not_found`；改为在临时目录里新建真实兄弟目录。

### 新增（Added）

- `agent/llm.py`：Provider 抽象（流式增量、工具参数分片拼接、仅在「尚未吐字」时指数退避重试、
  工具不支持时自动降级）、`MockLLM`（零 Key 可跑完整工具调用链路）。
- `agent/trace.py`：结构化轨迹（步骤 / 耗时 / 状态 / token / 重试），随 `answer` 事件下发前端。
- `sessions/store.py`：`SessionStore` 协议 + 内存 LRU/TTL + SQLite（upsert、按 `updated_at` 淘汰、坏数据自愈）。
- `POST /api/chat/stream`（SSE，带 keep-alive 与断连取消）、`GET /api/stats`。
- 前端：token 级流式渲染（文本与工具调用混排）、工具失败态与耗时、消息尾部 trace 摘要、
  运行期改配置关闭时的显式提示。
- 工程化：`pyproject.toml`（ruff / mypy / pytest / coverage）、`requirements-dev.txt`、
  `.github/workflows/ci.yml`（后端双版本 + 前端 + Docker）、`Dockerfile`、`docker-compose.yml`、
  `Makefile`、`scripts/e2e_smoke.py`、`docs/ARCHITECTURE.md`、`docs/TOOL_PROTOCOL.md`。

### 变更（Changed）

- 配置层迁移到 `pydantic-settings`，并**保留 v2 的全部属性名**（`config.AGENT_MODEL` 等）以兼容旧脚本。
- HTTP 错误体统一为 `{error_code, message}`；WebSocket 事件统一为 `{event, data}` 信封。
- 技能基类：`SkillResult` 增加 `metadata.error_code`、`as_tool_content()`；
  参数校验覆盖必填、类型转换、enum、最小/最大值，未知参数直接丢弃。
- 工作流模板支持 `{{last_result}}` / `{{params.x}}` / `{{steps.N.data|ok}}` 且可嵌入字符串；
  变量缺失或技能不存在抛结构化 `WorkflowError`。
- 前端默认后端地址改为同源（单端口托管开箱可用），仅 vite dev(5173) 回落 8000。

### 测试

- 105 个测试通过、1 个跳过（Windows 无软链接权限）；总覆盖率 89%。
  `skills/search_web.py`（Mock 降级 / 条数收敛 / 超时·HTTP·网络三类错误）与
  `skills/workflow_runner.py`（成功 / 步骤失败 / 结构化错误 / 工作流清单）补到 100%。
- `ruff check .` 全绿；`mypy` 在 22 个源文件上无报错。
- `scripts/e2e_smoke.py`：HTTP / SSE / WS / 参数校验拒绝 全部通过（Mock 模式，零密钥）。
- GitHub Actions 四条 job（backend 3.11 & 3.12 / frontend / docker 构建 + 容器冒烟）全部通过。

## [2.0.0]

- 多模型切换、工具调用、YAML 工作流、WebSocket 输出、React 前端、深色模式。

## [1.0.0]

- 初版：FastAPI + DeepSeek 的最小可用对话服务。
