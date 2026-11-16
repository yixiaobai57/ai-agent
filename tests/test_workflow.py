"""A9：工作流引擎的模板解析、结构化错误、dry-run。"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import config
from skills.registry import registry
from workflows.engine import WorkflowEngine, WorkflowError, workflow_engine


async def test_daily_report_end_to_end(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path / "workspace")
    result = await workflow_engine.run("daily_report")

    assert result["ok"] is True
    assert result["steps_completed"] == 3
    assert "daily_report.md" in result["output"]
    written = (tmp_path / "workspace" / "daily_report.md")
    assert written.exists(), "第三步应把内容落盘"
    assert "AI Daily" in written.read_text(encoding="utf-8")


async def test_unknown_workflow_lists_available() -> None:
    with pytest.raises(WorkflowError) as exc:
        await workflow_engine.run("nope")
    assert exc.value.code == "workflow_not_found"
    assert "daily_report" in exc.value.detail["available"]


async def test_missing_template_variable_raises(tmp_path: Path) -> None:
    defs = tmp_path / "wfs"
    defs.mkdir()
    (defs / "t.yaml").write_text(
        "name: t\nsteps:\n  - tool: search_web\n    params:\n      query: '{{params.topic}}'\n",
        encoding="utf-8",
    )
    engine = WorkflowEngine(defs_dir=defs, skill_registry=registry)
    with pytest.raises(WorkflowError) as exc:
        await engine.run("t")
    assert exc.value.code == "missing_variable"
    assert exc.value.detail["path"] == "params.topic"


async def test_template_embedded_and_step_reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    defs = tmp_path / "wfs"
    defs.mkdir()
    (defs / "t2.yaml").write_text(
        "\n".join(
            [
                "name: t2",
                "steps:",
                "  - tool: search_web",
                "    params:",
                "      query: '{{params.topic}}'",
                "  - tool: file_ops",
                "    params:",
                "      action: write",
                "      path: out.md",
                "      content: '标题：{{steps.1.data}}'",
            ]
        ),
        encoding="utf-8",
    )
    engine = WorkflowEngine(defs_dir=defs, skill_registry=registry)
    workspace = tmp_path / "ws"
    monkeypatch.setattr(config, "WORKSPACE_DIR", workspace)
    result = await engine.run("t2", {"topic": "AI agent"})
    assert result["ok"] is True
    text = (workspace / "out.md").read_text(encoding="utf-8")
    assert text.startswith("标题：")
    assert "AI agent" in text


async def test_missing_skill_is_structured() -> None:
    engine = WorkflowEngine(skill_registry=type(registry)())
    with pytest.raises(WorkflowError) as exc:
        await engine.run("daily_report")
    assert exc.value.code == "skill_not_found"
    assert exc.value.detail["step"] == 1


async def test_dry_run_does_not_execute(tmp_path: Path) -> None:
    result = await workflow_engine.run("daily_report", dry_run=True)
    assert result["ok"] is True
    assert result["steps_completed"] == 3
    assert all(s["status"] == "skipped" for s in result["step_results"])


def test_describe_contains_step_counts() -> None:
    described = {d["name"]: d for d in workflow_engine.describe()}
    assert described["daily_report"]["steps"] == 3


async def test_step_failure_is_reported(tmp_path: Path) -> None:
    defs = tmp_path / "wfs"
    defs.mkdir()
    (defs / "bad.yaml").write_text(
        "name: bad\nsteps:\n  - tool: file_ops\n    params:\n      action: read\n      path: '../escape.txt'\n",
        encoding="utf-8",
    )
    engine = WorkflowEngine(defs_dir=defs, skill_registry=registry)
    result = await engine.run("bad")
    assert result["ok"] is False
    assert result["error_code"] == "path_escape"
    assert result["steps_completed"] == 1
