# AI Agent

![version](https://img.shields.io/badge/version-2.0.0-blue)
![python](https://img.shields.io/badge/python-3.10+-green)
![license](https://img.shields.io/badge/license-MIT-lightgrey)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)
![OpenAI%20Compatible](https://img.shields.io/badge/OpenAI-Compatible-412991)

> 一个可插拔的多模型 AI Agent —— 工具调用、工作流编排、WebSocket 流式输出，开箱即用。

前后端分离架构：后端基于 FastAPI，前端为纯 HTML 单页应用。最初只是想给 DeepSeek 的 API 包一层自用，后来陆续加入了模型切换、工具调用、实时流式输出和插件式技能系统，现在已经演变成一个可以切换 DeepSeek / Moonshot / GPT-4o / Qwen / GLM-4 等多个模型、各具 tool calling 风格的通用 Agent 框架。

---

## 核心特性

| 能力 | 说明 |
| --- | --- |
| **多模型切换** | 支持 DeepSeek / Moonshot / GPT-4o / Qwen / GLM-4 等任意 OpenAI 兼容模型，每个模型可独立配置 API Key 与 Base URL |
| **工具调用** | 内置搜索、代码执行、文件操作、工作流执行四类技能，Agent 自主决策何时调用 |
| **工作流编排** | 用 YAML 定义多步骤任务，串联多个技能自动执行（如每日报告生成） |
| **流式输出** | WebSocket 实时推送，打字机效果，前端即问即答 |
| **会话记忆** | 自动维护上下文，长对话自动摘要，避免 token 溢出 |
| **插件式扩展** | 写好一个 Skill 文件丢进 `skills/` 目录即可自动注册新能力，无需改动核心代码 |
| **深色模式** | 自带暗色主题，并完成移动端响应式适配 |
| **工程化前端** | React + Vite + Tailwind CSS，组件化拆分，开发模式热更新，构建产物可由后端单端口托管 |

## 快速开始

### 后端

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
#   编辑 .env，填入你要使用的模型的 API Key

# 3. 启动后端
python main.py
```

### 前端

```bash
cd frontend
npm install
npm run dev      # 开发模式，访问 http://localhost:5173
# 或
npm run build    # 构建到 frontend/dist，后端会自动托管在 :8000
```

> 开发模式下前端运行在 5173，通过 Vite 代理转发 `/api` 和 `/ws` 到后端 8000。
> 生产构建后，直接访问 `http://localhost:8000` 即可单端口使用。
> `.env.example` 里每个模型都留了配置位，用哪个填哪个，不用的留空即可。

## 项目结构

```
ai-agent/
├── main.py                  # FastAPI 入口，HTTP + WebSocket 路由
├── config.py                # 配置管理（环境变量加载）
├── agent/
│   ├── core.py              # Agent 主循环：对话、工具调用、流式回调
│   └── memory.py            # 会话记忆与自动摘要
├── skills/                  # 技能系统（可插拔）
│   ├── base.py              # 技能基类与数据模型
│   ├── registry.py          # 技能注册中心，自动发现
│   ├── search_web.py        # 联网搜索
│   ├── code_executor.py     # 代码执行
│   ├── file_ops.py          # 文件读写
│   └── workflow_runner.py   # 工作流执行器
├── workflows/
│   ├── engine.py            # 工作流引擎
│   └── daily_report.yaml    # 工作流定义（YAML）
├── frontend/                # React + Vite + Tailwind 前端
│   ├── src/
│   │   ├── App.jsx          # 应用入口，组合各组件
│   │   ├── components/      # UI 组件
│   │   │   ├── Sidebar.jsx
│   │   │   ├── TopBar.jsx
│   │   │   ├── ChatWindow.jsx
│   │   │   ├── MessageBubble.jsx
│   │   │   ├── Composer.jsx
│   │   │   ├── ToolCall.jsx
│   │   │   └── Modal.jsx
│   │   ├── hooks/           # 自定义 hooks
│   │   │   ├── useAppStore.js   # 全局状态（会话/主题/配置）
│   │   │   └── useWebSocket.js  # WebSocket 连接与事件
│   │   ├── constants.js
│   │   ├── utils.js
│   │   └── index.css        # Tailwind + 主题变量
│   ├── index.html
│   ├── vite.config.js       # 含 dev proxy
│   └── package.json
├── requirements.txt
└── .env.example
```

## 技能系统

技能（Skill）是 Agent 的能力扩展单元。每个技能继承 `BaseSkill`，声明参数 schema 后会自动转换为 OpenAI tool calling 格式。

新增一个技能只需三步：

1. 在 `skills/` 下新建 Python 文件
2. 继承 `BaseSkill`，实现 `execute` 方法
3. 用 `@registry.register` 装饰 —— 启动时自动发现注册

```python
from skills import registry, BaseSkill, SkillResult, SkillParam

@registry.register
class MySkill(BaseSkill):
    name = 'my_skill'
    description = '做一件很酷的事'
    parameters = [
        SkillParam(name='input', description='输入内容', required=True),
    ]

    async def execute(self, input: str, **kw):
        return SkillResult(success=True, data=f'处理结果: {input}')
```

## 工作流

工作流用 YAML 描述，把多个技能按步骤串联起来，自动执行。内置示例 `daily_report.yaml` 演示了「搜索 → 执行代码 → 写文件」的完整链路：

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

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查，返回当前模型与已加载技能数 |
| `POST` | `/api/chat` | 同步对话 |
| `WS` | `/ws/chat` | 流式对话（推荐） |
| `GET` / `POST` | `/api/config` | 查询 / 更新运行时配置 |
| `GET` | `/api/skills` | 列出所有技能 |
| `GET` | `/api/workflows` | 列出所有工作流 |
| `POST` | `/api/session/new` | 新建会话 |
| `DELETE` | `/api/session` | 清空指定会话记忆 |

启动后访问 `http://localhost:8000/docs` 可查看交互式 API 文档。

## 已知不足

- 工具调用的错误处理较粗，模型返回异常格式时会直接报错
- 技能暂不支持热加载，新增技能需重启服务
- 会话状态保存在内存中，重启即丢失

## License

MIT
