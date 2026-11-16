"""A2/A3：技能注册、schema 生成、参数校验。"""

from __future__ import annotations

from typing import Any

import pytest

from skills.base import BaseSkill, SkillParam, SkillResult
from skills.registry import SkillRegistry, registry


class _Demo(BaseSkill):
    name = "demo"
    description = "demo skill"
    parameters = [
        SkillParam(name="text", type="string", required=True, description="文本"),
        SkillParam(name="n", type="integer", required=False, default=3, minimum=1, maximum=10),
        SkillParam(name="mode", type="string", required=False, enum=["x", "y"]),
    ]

    async def execute(self, text: str, n: int = 3, mode: str = "x", **kw: Any) -> SkillResult:  # type: ignore[override]
        return SkillResult(success=True, data=f"{text}-{n}-{mode}")


def test_schema_generation() -> None:
    tool = _Demo().to_openai_tool()
    fn = tool["function"]
    assert fn["name"] == "demo"
    assert fn["parameters"]["required"] == ["text"]
    props = fn["parameters"]["properties"]
    assert props["n"]["type"] == "integer" and props["n"]["maximum"] == 10
    assert props["mode"]["enum"] == ["x", "y"]


def test_validate_args_coerces_and_ignores_unknown() -> None:
    skill = _Demo()
    cleaned, errors = skill.validate_args({"text": "hi", "n": "5", "bogus": 1})
    assert errors == []
    assert cleaned["n"] == 5
    assert "bogus" not in cleaned


def test_validate_args_reports_missing_and_enum_and_range() -> None:
    skill = _Demo()
    _, errors = skill.validate_args({})
    assert any("text" in e for e in errors)
    _, errors = skill.validate_args({"text": "hi", "mode": "z"})
    assert any("enum" in e or "x" in e for e in errors)
    _, errors = skill.validate_args({"text": "hi", "n": 99})
    assert any("不能大于" in e for e in errors)


def test_validate_args_rejects_non_dict() -> None:
    cleaned, errors = _Demo().validate_args("not a dict")  # type: ignore[arg-type]
    assert cleaned == {} and errors


async def test_call_wraps_validation_errors() -> None:
    result = await _Demo()(text="hi", n=99, mode="z")
    assert not result.success
    assert result.metadata["error_code"] == "invalid_arguments"
    assert "duration_ms" in result.metadata


async def test_call_returns_skill_result_and_catches_exception() -> None:
    class Boom(BaseSkill):
        name = "boom_demo"

        async def execute(self, **kw: Any) -> SkillResult:  # type: ignore[override]
            raise ValueError("nope")

    result = await Boom()()
    assert not result.success
    assert "ValueError" in str(result.error)
    assert result.metadata["error_code"] == "tool_exception"


def test_registry_rejects_duplicate_names() -> None:
    reg = SkillRegistry()
    reg.register(_Demo)
    with pytest.raises(ValueError):
        reg.register(_Demo)
    assert reg.names() == ["demo"]
    assert "demo" in reg


def test_registry_discover_is_idempotent() -> None:
    before = len(registry)
    registry.discover()
    registry.discover()
    assert len(registry) == before >= 4


def test_discovered_skills_are_exposed() -> None:
    names = set(registry.names())
    assert {"search_web", "execute_code", "file_ops", "run_workflow", "list_workflows"} <= names


def test_describe_includes_metadata() -> None:
    info = registry.get("execute_code")
    assert info is not None
    described = info.describe()
    assert described["dangerous"] is True
    assert described["name"] == "execute_code"
    assert isinstance(described["parameters"], list)
