"""技能注册中心：登记、发现、按名查找、导出 OpenAI tools。

v2 只往里塞不检查，重名技能会静默覆盖；重复 import 会重复打印。
现在：
- 重名直接抛错（避免"后加载的技能干掉前面的"）
- ``discover()`` 幂等，可重复调用
- ``reset()`` 供测试清空全局状态
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

from .base import BaseSkill

logger = logging.getLogger(__name__)

_BOOTSTRAP_MODULES = {"__init__", "base", "registry"}


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, BaseSkill] = {}
        self._classes: dict[str, type[BaseSkill]] = {}
        self._discovered = False

    # ---------------- 注册 ----------------
    def register(self, cls: type[BaseSkill]) -> type[BaseSkill]:
        """类装饰器：实例化并按 name 登记。"""
        inst = cls()
        if not inst.name:
            raise ValueError(f"技能 {cls.__name__} 缺少 name 声明")
        if inst.name in self._skills:
            raise ValueError(f"技能名重复：{inst.name}（已被 {type(self._skills[inst.name]).__name__} 占用）")
        self._skills[inst.name] = inst
        self._classes[inst.name] = cls
        logger.debug("registered skill %s", inst.name)
        return cls

    # ---------------- 查询 ----------------
    def get(self, name: str) -> BaseSkill | None:
        return self._skills.get(name)

    def get_all(self) -> dict[str, BaseSkill]:
        return {k: v for k, v in self._skills.items() if v.enabled}

    def get_openai_tools(self) -> list[dict[str, Any]]:
        return [s.to_openai_tool() for s in self._skills.values() if s.enabled]

    def list_skills(self) -> list[dict[str, Any]]:
        return [s.describe() for s in self._skills.values()]

    def names(self) -> list[str]:
        return [name for name, s in self._skills.items() if s.enabled]

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: object) -> bool:
        return name in self._skills

    # ---------------- 发现 ----------------
    def discover(self) -> dict[str, BaseSkill]:
        """扫描 ``skills`` 包内的模块并导入，触发模块级 ``@registry.register``。"""
        if self._discovered:
            return self._skills
        import skills as pkg

        for _, mod, _ in pkgutil.iter_modules(pkg.__path__):
            if mod in _BOOTSTRAP_MODULES:
                continue
            try:
                importlib.import_module(f"skills.{mod}")
            except Exception as exc:  # noqa: BLE001 - 单个技能坏掉不该拖垮整个服务
                logger.warning("加载技能模块 %s 失败：%s", mod, exc)
        self._discovered = True
        return self._skills

    def reset(self) -> None:
        """仅测试用：清空注册表，允许重新注册。"""
        self._skills.clear()
        self._classes.clear()
        self._discovered = False


registry = SkillRegistry()

__all__ = ["SkillRegistry", "registry"]
