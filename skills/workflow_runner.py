"""把 YAML 工作流包装成可被模型调用的技能。

Agent 通过 ``run_workflow`` 触发"搜索 → 计算 → 落盘"这类固定链路；
``list_workflows`` 让它先知道自己有哪些工作流可用，减少瞎猜工作流名。
"""

from __future__ import annotations

from typing import Any

from skills import BaseSkill, SkillParam, SkillResult, registry


@registry.register
class WorkflowRunnerSkill(BaseSkill):
    name = "run_workflow"
    description = "执行预定义的多步骤工作流（YAML 定义，可串联搜索/代码/文件等技能）。"
    parameters = [
        SkillParam(name="workflow_name", type="string", description="工作流名，见 list_workflows", required=True),
        SkillParam(name="params", type="object", description="传给工作流的参数对象", required=False),
    ]

    async def execute(self, workflow_name: str, params: dict[str, Any] | None = None, **kw: Any) -> SkillResult:  # type: ignore[override]
        from workflows.engine import WorkflowError, workflow_engine  # 延迟导入，避免循环依赖

        try:
            result = await workflow_engine.run(workflow_name, params or {})
        except WorkflowError as exc:
            return SkillResult(
                success=False,
                error=str(exc),
                metadata={"error_code": exc.code, **exc.detail},
            )

        if not result.get("ok"):
            return SkillResult(
                success=False,
                data=result.get("output"),
                error=result.get("output") or "工作流执行失败",
                metadata={
                    "error_code": result.get("error_code", "step_failed"),
                    "steps": result.get("steps_completed", 0),
                },
            )
        return SkillResult(
            success=True,
            data=result.get("output") or "Done",
            metadata={"steps": result.get("steps_completed", 0), "workflow": workflow_name},
        )


@registry.register
class ListWorkflowsSkill(BaseSkill):
    name = "list_workflows"
    description = "列出当前可用的工作流及其步骤数量。"
    parameters: list = []

    async def execute(self, **kw: Any) -> SkillResult:  # type: ignore[override]
        from workflows.engine import workflow_engine

        items = workflow_engine.describe()
        if not items:
            return SkillResult(success=True, data="当前没有可用的工作流。")
        lines = [f"- {i['name']}：{i['description']}（{i['steps']} 步）" for i in items]
        return SkillResult(success=True, data="可用工作流：\n" + "\n".join(lines), metadata={"count": len(items)})


__all__ = ["WorkflowRunnerSkill", "ListWorkflowsSkill"]
