"""A7 补充：run_workflow / list_workflows 的三种返回形态与错误码透传。"""

from __future__ import annotations

from typing import Any

import pytest

from skills.workflow_runner import ListWorkflowsSkill, WorkflowRunnerSkill
from workflows.engine import WorkflowError


class FakeEngine:
    def __init__(self, *, result: dict[str, Any] | None = None, error: Exception | None = None,
                 items: list[dict[str, Any]] | None = None) -> None:
        self._result = result or {}
        self._error = error
        self._items = items or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def run(self, name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((name, params or {}))
        if self._error:
            raise self._error
        return self._result

    def describe(self) -> list[dict[str, Any]]:
        return self._items


def _patch_engine(monkeypatch: pytest.MonkeyPatch, engine: FakeEngine) -> FakeEngine:
    import workflows.engine as engine_module

    monkeypatch.setattr(engine_module, "workflow_engine", engine)
    return engine


async def test_run_workflow_success(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _patch_engine(
        monkeypatch,
        FakeEngine(result={"ok": True, "output": "报告已生成", "steps_completed": 3}),
    )

    result = await WorkflowRunnerSkill().execute(workflow_name="daily_report", params={"topics": "ai"})

    assert result.success
    assert result.data == "报告已生成"
    assert result.metadata == {"steps": 3, "workflow": "daily_report"}
    assert engine.calls == [("daily_report", {"topics": "ai"})]


async def test_run_workflow_defaults_params_to_empty_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _patch_engine(monkeypatch, FakeEngine(result={"ok": True, "output": "Done"}))

    await WorkflowRunnerSkill().execute(workflow_name="w")

    assert engine.calls == [("w", {})]


async def test_run_workflow_failure_keeps_result_error_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_engine(
        monkeypatch,
        FakeEngine(result={"ok": False, "output": "第 2 步失败", "error_code": "step_failed", "steps_completed": 1}),
    )

    result = await WorkflowRunnerSkill().execute(workflow_name="w")

    assert not result.success
    assert result.data == "第 2 步失败"
    assert result.error == "第 2 步失败"
    assert result.metadata["error_code"] == "step_failed"
    assert result.metadata["steps"] == 1


async def test_run_workflow_error_is_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_engine(
        monkeypatch,
        FakeEngine(error=WorkflowError("没有这个工作流", code="workflow_not_found", detail={"name": "nope"})),
    )

    result = await WorkflowRunnerSkill().execute(workflow_name="nope")

    assert not result.success
    assert result.metadata["error_code"] == "workflow_not_found"
    assert result.metadata["name"] == "nope"
    assert "没有这个工作流" in str(result.error)


async def test_list_workflows_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_engine(monkeypatch, FakeEngine(items=[]))

    result = await ListWorkflowsSkill().execute()

    assert result.success
    assert "当前没有可用的工作流" in str(result.data)


async def test_list_workflows_describes_each_item(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_engine(
        monkeypatch,
        FakeEngine(
            items=[
                {"name": "daily_report", "description": "每日报告", "steps": 3},
                {"name": "weekly", "description": "周报", "steps": 2},
            ]
        ),
    )

    result = await ListWorkflowsSkill().execute()

    assert result.success
    assert result.metadata["count"] == 2
    data = str(result.data)
    assert "- daily_report：每日报告（3 步）" in data
    assert "- weekly：周报（2 步）" in data
