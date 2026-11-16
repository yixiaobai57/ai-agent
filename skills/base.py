"""技能系统基类。

一个 Skill = Agent 的一项能力：
- ``name`` 是 tool calling 里的函数名，全局唯一
- ``description`` + ``parameters`` 决定大模型何时调用、怎么传参
- 继承 ``BaseSkill`` 实现 ``execute``，用 ``@registry.register`` 注册即可被自动发现

v2 的问题：技能直接把模型传来的参数 ``**fa`` 灌进 ``execute``，模型多传一个不存在的
参数就 TypeError、少传必填参数也 TypeError，而异常被 ``__call__`` 吞成一句
"error"，模型完全不知道该怎么改。这里加了一层**参数校验 + 友好纠错**，
把校验失败的细节回喂给模型，让它下一轮自己修正。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from config import config

JSONSchema = dict[str, Any]

_TYPE_MAP: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


class SkillParam(BaseModel):
    """单个入参声明，会转换成 JSON Schema 给大模型看。"""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    enum: list[Any] | None = None
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None

    def to_schema(self) -> dict[str, Any]:
        prop: dict[str, Any] = {"type": self.type}
        if self.description:
            prop["description"] = self.description
        if self.enum:
            prop["enum"] = self.enum
        if self.default is not None:
            prop["default"] = self.default
        if self.minimum is not None:
            prop["minimum"] = self.minimum
        if self.maximum is not None:
            prop["maximum"] = self.maximum
        return prop


class SkillResult(BaseModel):
    """统一结果结构：成功/失败都走它，Agent 主循环只处理这一种返回。"""

    success: bool
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def as_tool_content(self, limit: int = 4000) -> str:
        """转成回喂给模型的一段文本（失败时明确告诉它怎么修）。"""
        if self.success:
            text = self.data if isinstance(self.data, str) else repr(self.data)
            return text[:limit] if len(text) > limit else text
        code = self.metadata.get("error_code") or "tool_error"
        return f"ERROR[{code}]: {self.error}"


class BaseSkill(ABC):
    name: str = ""
    description: str = ""
    parameters: list[SkillParam] = []
    enabled: bool = True
    # 危险能力（会写文件/执行代码）在 /api/skills 里单独标注，便于前端提示
    dangerous: bool = False
    requires: str | None = None  # 需要的环境变量，例如 SERPER_API_KEY

    # ---------------- schema ----------------
    def to_openai_tool(self) -> JSONSchema:
        props: dict[str, Any] = {}
        required: list[str] = []
        for p in self.parameters:
            props[p.name] = p.to_schema()
            if p.required:
                required.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": props, "required": required},
            },
        }

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "dangerous": self.dangerous,
            "requires": self.requires,
            "available": True if not self.requires else bool(getattr(config, self.requires, "")),
            "parameters": [p.model_dump() for p in self.parameters],
        }

    # ---------------- 参数校验 ----------------
    def validate_args(self, raw: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
        """校验并清洗模型传来的参数。

        规则：
        1. 未知参数直接丢弃（模型爱编参数，不该让它导致 TypeError）
        2. 必填缺失 → 报错
        3. 类型不符但可安全转换（如 "5" → 5）→ 转换；否则报错
        4. ``enum`` / ``minimum`` / ``maximum`` 越界 → 报错
        """
        raw = raw or {}
        if not isinstance(raw, dict):
            return {}, [f"arguments 必须是 JSON object，实际是 {type(raw).__name__}"]

        cleaned: dict[str, Any] = {}
        errors: list[str] = []
        declared = {p.name: p for p in self.parameters}

        for p in self.parameters:
            if p.name not in raw or raw[p.name] is None:
                if p.required:
                    errors.append(f"缺少必填参数 '{p.name}'（{p.type}，{p.description or '无说明'}）")
                elif p.default is not None:
                    cleaned[p.name] = p.default
                continue
            value = raw[p.name]
            ok, converted, why = _coerce(value, p.type)
            if not ok:
                errors.append(f"参数 '{p.name}' 类型不符：{why}")
                continue
            if p.enum and converted not in p.enum:
                errors.append(f"参数 '{p.name}' 必须是 {p.enum} 之一，实际 {converted!r}")
                continue
            if isinstance(converted, int | float) and not isinstance(converted, bool):
                if p.minimum is not None and converted < p.minimum:
                    errors.append(f"参数 '{p.name}' 不能小于 {p.minimum}")
                    continue
                if p.maximum is not None and converted > p.maximum:
                    errors.append(f"参数 '{p.name}' 不能大于 {p.maximum}")
                    continue
            cleaned[p.name] = converted

        unknown = [k for k in raw if k not in declared]
        if unknown:
            # 仅记录，不进 errors：模型多传参数不该让整个调用失败
            pass
        return cleaned, errors

    # ---------------- 执行 ----------------
    @abstractmethod
    async def execute(self, **kwargs: Any) -> SkillResult:
        """具体能力实现。"""

    async def __call__(self, **kwargs: Any) -> SkillResult:
        """统一入口：校验参数 → 执行 → 兜异常 → 附耗时。"""
        started = time.perf_counter()
        cleaned, errors = self.validate_args(kwargs)
        if errors:
            return SkillResult(
                success=False,
                error="参数校验不通过：" + "；".join(errors),
                metadata={"error_code": "invalid_arguments", "duration_ms": _ms(started)},
            )
        try:
            result = await self.execute(**cleaned)
        except Exception as exc:  # noqa: BLE001 - 工具异常必须转成结果交给模型
            return SkillResult(
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                metadata={"error_code": "tool_exception", "duration_ms": _ms(started)},
            )
        if not isinstance(result, SkillResult):
            result = SkillResult(success=True, data=result)
        result.metadata.setdefault("duration_ms", _ms(started))
        return result


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _coerce(value: Any, expected: str) -> tuple[bool, Any, str]:
    if expected not in _TYPE_MAP:
        return True, value, ""
    want = _TYPE_MAP[expected]
    if expected == "boolean":
        if isinstance(value, bool):
            return True, value, ""
        if isinstance(value, str) and value.lower() in ("true", "false", "1", "0"):
            return True, value.lower() in ("true", "1"), ""
        return False, None, f"期望 boolean，实际 {type(value).__name__}"
    if isinstance(value, bool) and expected in ("integer", "number"):
        return False, None, "期望数字，实际 boolean"
    if isinstance(value, want):
        return True, value, ""
    # 安全转换：字符串数字 / 数字字符串
    if expected in ("integer", "number") and isinstance(value, str):
        try:
            return True, (int(value) if expected == "integer" else float(value)), ""
        except ValueError:
            return False, None, f"无法把 {value!r} 转成 {expected}"
    if expected == "string" and isinstance(value, int | float):
        return True, str(value), ""
    return False, None, f"期望 {expected}，实际 {type(value).__name__}"


__all__ = ["BaseSkill", "SkillParam", "SkillResult"]
