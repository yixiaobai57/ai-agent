# 工具与事件协议

> 想加一个技能、或想用别的客户端（CLI、MCP、飞书机器人）接进来，只需要读这一页。

## 1. 事件信封

WebSocket `/ws/chat` 与 SSE `POST /api/chat/stream` 使用同一个 JSON 信封：

```json
{ "event": "token", "data": { "delta": "你" } }
```

| event | data | 何时发 |
|---|---|---|
| `thinking` | `{ "status": "..." }` | 开始一轮推理 / 工具返回后继续推理 |
| `token` | `{ "delta": "增量文本" }` | 模型每吐出一段文本 |
| `tool_call` | `{ "name": "file_ops", "args": {...}, "status": "running" }` | 决定调用工具时 |
| `tool_result` | `{ "name": "...", "data": "回喂给模型的内容", "status": "ok\|error\|timeout", "duration_ms": 12 }` | 工具执行结束 |
| `answer` | `{ "content": "最终回答", "trace": {...} }` | 本轮结束（只发一次） |
| `error` | `{ "message": "...", "code": "llm_error" }` | 不可恢复错误，之后本轮不再有事件 |
| `pong` | `{}` | 回应客户端 `{"event":"ping"}` |

`answer` 的 `trace`：

```json
{
  "steps": [
    {"index": 1, "kind": "llm", "name": "deepseek-chat", "status": "ok", "duration_ms": 820,
     "detail": {"step": 1, "has_tool_calls": true, "finish_reason": "tool_calls", "chars": 0, "tokens": 0}},
    {"index": 2, "kind": "tool", "name": "file_ops", "status": "ok", "duration_ms": 3,
     "detail": {"args": {...}}}
  ],
  "total_ms": 1420,
  "llm_calls": 2,
  "tool_calls": 1,
  "failed_tools": 0,
  "retries": 0,
  "prompt_tokens": 1234,
  "completion_tokens": 56
}
```

## 2. 技能协议

### 声明

```python
from skills import BaseSkill, SkillParam, SkillResult

class WeatherSkill(BaseSkill):
    name = "weather"
    description = "查询城市天气。"
    dangerous = False             # 是否属于「有副作用」的工具
    requires = "WEATHER_API_KEY"  # 可选：缺这个环境变量时标记为不可用

    parameters = [
        SkillParam("city", "string", "城市名，如 广州", required=True),
        SkillParam("days", "integer", "预报天数", required=False, default=1, minimum=1, maximum=7),
    ]

    async def execute(self, city: str, days: int = 1) -> SkillResult:
        if not city.strip():
            # 失败也要带 error_code，模型才知道怎么改
            return SkillResult(success=False, error="城市不能为空",
                               metadata={"error_code": "invalid_arguments"})
        return SkillResult(success=True, data=f"{city} 未来 {days} 天晴")
```

`parameters` 会被 `to_openai_tool()` 自动转成 OpenAI function-calling 的 JSON Schema，
所以「模型看到的工具签名」和「代码里的校验规则」永远同一份。

### 执行

`BaseSkill.__call__(**raw_args)` 统一做四件事：

1. 丢弃未声明参数（模型多传不该让整次调用失败）；
2. 必填缺失 / 类型转换失败 / enum 不在范围 / 越界 → `success=False, error_code="invalid_arguments"`；
3. `execute()` 抛异常 → `success=False, error_code="tool_exception"`（堆栈进日志，不回给模型）；
4. 记录 `duration_ms` 并打日志。

### 错误格式

失败结果会被序列化成下面这段文本交给模型：

```
ERROR[path_escape]: 路径越界：../secrets.txt
```

`error_code` 取值：

| code | 来源 | 含义 |
|---|---|---|
| `invalid_arguments` | `base.py` | 参数没通过校验（模型可改参数重试） |
| `tool_exception` | `base.py` | 技能内部异常（堆栈进日志） |
| `unknown_tool` | `core.py` | 工具名不存在 |
| `timeout` | `core.py` / `code_executor` / `search_web` | 超过 `TOOL_TIMEOUT` 或技能自身超时 |
| `path_escape` | `file_ops` | 试图访问 `WORKSPACE_DIR` 之外 |
| `not_found` / `is_directory` / `file_too_large` / `content_too_large` / `bad_action` / `io_error` | `file_ops` | 文件操作的具体失败原因 |
| `unsafe_code` / `syntax_error` / `runtime_error` / `disabled` | `code_executor` | 未通过 AST 白名单 / 语法错误 / 子进程非 0 退出 / 功能被开关关闭 |
| `http_error` / `network_error` | `search_web` | 搜索服务返回非 2xx / 网络不可达 |
| `missing_variable` | `workflows/engine.py` | 工作流模板变量不存在 |
| `workflow_not_found` / `skill_not_found` | `workflows/engine.py` | 工作流名或技能名不存在（`detail.available` 给出可用清单） |

## 3. 内置技能

| 技能 | 参数 | 说明 |
|---|---|---|
| `execute_code` | `code` | 隔离子进程运行 Python（仅标准库算法/数据处理），返回 stdout |
| `file_ops` | `action`(`read`/`write`/`append`/`list`)、`path`、`content` | 只在 `WORKSPACE_DIR` 内读写 |
| `search_web` | `query`、`num_results`(1–10) | 需要 `SERPER_API_KEY`；Mock 模式返回带 `metadata.mock` 的假数据 |
| `run_workflow` | `workflow_name`、`params` | 执行 YAML 工作流 |
| `list_workflows` | — | 列出可用工作流与步骤数 |

## 4. 工作流 YAML

```yaml
name: daily_report
description: Daily AI news report
steps:
  - tool: search_web
    params:
      query: AI news today
      num_results: 5
  - tool: execute_code
    params:
      code: |
        from datetime import datetime
        print(f'# AI Daily - {datetime.now().strftime("%Y-%m-%d")}')
  - tool: file_ops
    params:
      action: write
      path: daily_report.md
      content: '{{last_result}}'
```

模板变量（可嵌在字符串里，不要求整值匹配）：

| 占位符 | 含义 |
|---|---|
| `{{last_result}}` | 上一步的输出 |
| `{{params.foo}}` | 本次运行传入的参数 |
| `{{steps.1.data}}` | 第 1 步的输出 |
| `{{steps.1.ok}}` | 第 1 步是否成功（`True`/`False`） |

变量不存在 → `WorkflowError(code="missing_variable")`，不再把 `{{x}}` 原样当参数传下去。
支持 `dry_run=True` 只校验不执行；`describe()` 返回每个工作流的步骤数给前端展示。

## 5. HTTP 接口

| 方法与路径 | 说明 | 鉴权 |
|---|---|---|
| `GET /health`、`GET /api/health` | 探活 | — |
| `GET /api/skills` | 技能列表（含 schema） | — |
| `GET /api/workflows` | 工作流列表 | — |
| `GET /api/stats` | 会话数 / 技能数 / 是否 Mock | — |
| `GET /api/config` | 前端可见配置（**不回显 Key**） | — |
| `POST /api/config` | 运行期改 model/base_url/key | `ALLOW_RUNTIME_CONFIG=true` + `X-Admin-Token` |
| `POST /api/session/new` | 分配新会话 id | — |
| `DELETE /api/session` | 清空某会话记忆 | — |
| `POST /api/chat` | 一次性返回完整回答（含 trace） | — |
| `POST /api/chat/stream` | SSE 流式 | — |
| `WS /ws/chat` | 双向事件流 | — |

统一错误体：

```json
{ "error_code": "invalid_request", "message": "message: String should have at least 1 character" }
```

常见状态码：`400 invalid_config`、`401 unauthorized`、`403 runtime_config_disabled` /
`admin_token_missing`、`413 payload_too_large`、`422 invalid_request`、`500 internal_error`。
