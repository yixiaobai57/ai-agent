"""YAML 工作流引擎：把多个技能按步骤串起来。

v2 的问题：
- 模板只认"整个值恰好是 ``{{xxx}}``"，``"标题：{{last_result}}"`` 这种拼接写不了；
- 变量缺失时静默把 ``{{x}}`` 原样当参数传下去，模型/用户看到的是坏数据；
- 技能不存在只抛一句 RuntimeError，没有可用步骤列表，出错后无法自愈。

现在支持三类占位符（可嵌在字符串里）：
- ``{{last_result}}``：上一步的输出
- ``{{params.foo}}``：本次运行传入的参数
- ``{{steps.1.data}}`` / ``{{steps.1.ok}}``：指定步骤的输出/状态
变量缺失 → 抛 ``WorkflowError(code="missing_variable")``，不再静默传脏值。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from skills.registry import registry

logger = logging.getLogger(__name__)

DEFS_DIR = Path(__file__).parent
_TEMPLATE = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")


class WorkflowError(RuntimeError):
    def __init__(self, message: str, *, code: str = "workflow_error", detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.detail = detail or {}


class WorkflowEngine:
    def __init__(self, defs_dir: Path | None = None, skill_registry=None) -> None:
        self._dir = Path(defs_dir) if defs_dir else DEFS_DIR
        # 注意：不能写 ``skill_registry or registry``——空的 SkillRegistry 因 __len__ 为 0 会被当成假值
        self._skills = skill_registry if skill_registry is not None else registry
        self._wfs: dict[str, dict[str, Any]] = {}
        self.load()

    # ---------------- 加载 ----------------
    def load(self) -> dict[str, dict[str, Any]]:
        self._wfs.clear()
        if not self._dir.exists():
            return self._wfs
        for path in sorted(self._dir.glob("*.yaml")):
            try:
                with path.open(encoding="utf-8") as fp:
                    raw = yaml.safe_load(fp)
                wf = self._validate(raw, path.name)
            except Exception as exc:  # noqa: BLE001 - 单个坏文件不该拖垮服务
                logger.warning("工作流 %s 加载失败：%s", path.name, exc)
                continue
            self._wfs[wf["name"]] = wf
        return self._wfs

    @staticmethod
    def _validate(raw: Any, filename: str) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("工作流必须是 YAML 映射")
        name = str(raw.get("name") or "").strip()
        if not name:
            raise ValueError("缺少 name")
        steps = raw.get("steps") or []
        if not isinstance(steps, list) or not steps:
            raise ValueError("steps 必须是非空列表")
        for i, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                raise ValueError(f"第 {i} 步必须是映射")
            if not (step.get("tool") or step.get("skill")):
                raise ValueError(f"第 {i} 步缺少 tool")
            if not isinstance(step.get("params") or {}, dict):
                raise ValueError(f"第 {i} 步 params 必须是映射")
        return {
            "name": name,
            "description": str(raw.get("description") or ""),
            "steps": steps,
            "source": filename,
        }

    # ---------------- 查询 ----------------
    def list_workflows(self) -> list[str]:
        return list(self._wfs.keys())

    def get_workflow(self, name: str) -> dict[str, Any] | None:
        return self._wfs.get(name)

    def describe(self) -> list[dict[str, Any]]:
        return [
            {"name": n, "description": wf.get("description", ""), "steps": len(wf.get("steps", []))}
            for n, wf in self._wfs.items()
        ]

    # ---------------- 模板 ----------------
    def _resolve(self, value: Any, ctx: dict[str, Any]) -> Any:
        if isinstance(value, dict):
            return {k: self._resolve(v, ctx) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve(v, ctx) for v in value]
        if not isinstance(value, str):
            return value

        whole = _TEMPLATE.fullmatch(value)
        if whole:
            return self._lookup(whole.group(1), ctx)

        def repl(match: re.Match[str]) -> str:
            return str(self._lookup(match.group(1), ctx))

        return _TEMPLATE.sub(repl, value)

    @staticmethod
    def _lookup(path: str, ctx: dict[str, Any]) -> Any:
        if path in ctx:
            return ctx[path]
        parts = path.split(".")
        if parts[0] == "params" and len(parts) > 1:
            params = ctx.get("params") or {}
            if parts[1] in params:
                return params[parts[1]]
            raise WorkflowError(f"缺少参数：{path}", code="missing_variable", detail={"path": path})
        if parts[0] == "steps" and len(parts) >= 3:
            try:
                idx = int(parts[1]) - 1
                result = ctx["steps"][idx]
            except (ValueError, IndexError, KeyError):
                raise WorkflowError(
                    f"步骤不存在：{path}", code="missing_variable", detail={"path": path}
                ) from None
            key = parts[2]
            if key in result:
                return result[key]
            raise WorkflowError(f"步骤字段不存在：{path}", code="missing_variable", detail={"path": path})
        if path == "last_result":
            return ctx.get("last_result", "")
        raise WorkflowError(f"未知占位符：{{{path}}}", code="missing_variable", detail={"path": path})

    # ---------------- 执行 ----------------
    async def run(self, name: str, params: dict[str, Any] | None = None, *, dry_run: bool = False) -> dict[str, Any]:
        wf = self._wfs.get(name)
        if not wf:
            raise WorkflowError(
                f"工作流不存在：{name}",
                code="workflow_not_found",
                detail={"available": self.list_workflows()},
            )

        ctx: dict[str, Any] = {"params": params or {}, "last_result": "", "steps": []}
        results: list[dict[str, Any]] = []

        for i, step in enumerate(wf["steps"], start=1):
            skill_name = step.get("tool") or step.get("skill")
            try:
                resolved = self._resolve(step.get("params") or {}, ctx)
            except WorkflowError as exc:
                raise WorkflowError(f"第 {i} 步参数解析失败：{exc}", code=exc.code, detail=exc.detail) from exc

            skill = self._skills.get(str(skill_name))
            if not skill:
                raise WorkflowError(
                    f"第 {i} 步技能不存在：{skill_name}",
                    code="skill_not_found",
                    detail={"step": i, "available": self._skills.names()},
                )

            if dry_run:
                results.append({"step": i, "skill": skill_name, "status": "skipped", "params": resolved})
                ctx["steps"].append({"ok": True, "status": "skipped", "data": ""})
                continue

            result = await skill(**resolved)  # type: ignore[misc]
            record = {
                "step": i,
                "skill": skill_name,
                "status": "ok" if result.success else "error",
                "ok": result.success,
                "data": result.data,
                "error": result.error,
                "duration_ms": result.metadata.get("duration_ms", 0),
            }
            results.append(record)
            ctx["steps"].append(record)

            if not result.success:
                return {
                    "ok": False,
                    "workflow": name,
                    "output": f"第 {i} 步（{skill_name}）失败：{result.error}",
                    "error_code": result.metadata.get("error_code") or "step_failed",
                    "steps_completed": len(results),
                    "step_results": results,
                    "trace": ctx["steps"],
                }
            ctx["last_result"] = result.data

        return {
            "ok": True,
            "workflow": name,
            "output": ctx["last_result"],
            "steps_completed": len(results),
            "step_results": results,
        }


workflow_engine = WorkflowEngine()

__all__ = ["WorkflowEngine", "WorkflowError", "workflow_engine", "DEFS_DIR"]
