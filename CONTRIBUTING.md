# 贡献指南

## 本地环境

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
```

前端：

```bash
cd frontend && npm ci
```

## 提交前必须跑完这四条

```bash
python -m ruff check .     # 静态检查
python -m mypy             # 类型检查
python -m pytest           # 全量测试（含 asyncio）
cd frontend && npm run lint && npm run build
```

CI（`.github/workflows/ci.yml`）会跑同样的命令，另外在 Python 3.11 / 3.12 双版本、Docker 镜像上各跑一遍。

## 代码约定

- **统一用 `python -m <tool>` 调用工具**，避免 PATH 里混进另一个解释器。
- 类型注解一律 PEP 585/604（`list[str]`、`str | None`），文件顶部加 `from __future__ import annotations`。
- 新增技能：继承 `BaseSkill`，在类上 `@registry.register`，`execute()` 只返回 `SkillResult`，不抛异常。
- 错误必须带机读码：`SkillResult(success=False, error="...", metadata={"error_code": "..."})`。
  错误码登记在 [docs/TOOL_PROTOCOL.md](docs/TOOL_PROTOCOL.md) 的表里，新增要同步更新。
- 涉及外部副作用的能力（写文件、执行代码、发网络请求）要把 `dangerous = True` 并在文档里说明边界。
- 改公共契约（HTTP 路径、事件名、事件字段）必须同时改 `docs/TOOL_PROTOCOL.md` 与对应测试。

## 测试约定

- 不要为「能跑通」写假测试：断言要检查**行为**（事件序列、落盘内容、错误码），而不是只断言「返回了 200」。
- LLM 一律用 `tests/helpers.py` 的 `ScriptedLLM` 脚本化，禁止在测试里打真实网络。
- 测试要做到确定性：不依赖随机数、时间与并发调度顺序。

## 分支与提交

- 分支命名：`feat/xxx`、`fix/xxx`、`docs/xxx`。
- 提交信息用祈使句，一条提交只做一件事；涉及安全边界的改动在正文说明「为什么」。

## 安全问题

发现漏洞请不要开公开 Issue，按 [SECURITY.md](SECURITY.md) 的方式联系维护者。
