"""技能注册中心：维护全部已注册技能，并支持启动时自动发现。

- register：把技能类实例化并登记到内存字典
- discover：扫描 skills 包下所有模块，导入后自动触发 @registry.register 完成注册
- get_openai_tools：汇总所有启用技能，转换为 OpenAI function calling 格式供 Agent 使用
"""
import importlib, pkgutil
from typing import Dict, Optional
from .base import BaseSkill


class SkillRegistry:
    def __init__(self):
        # 技能名 -> 技能实例 的映射表
        self._skills: Dict[str, BaseSkill] = {}

    def register(self, cls):
        """注册一个技能类：实例化并按技能名登记。"""
        inst = cls()
        self._skills[inst.name] = inst
        print(f'  + Skill: {inst.name}')
        return cls

    def get(self, name: str) -> Optional[BaseSkill]:
        """按技能名获取技能实例。"""
        return self._skills.get(name)

    def get_all(self):
        """返回所有处于启用状态的技能。"""
        return {k: v for k, v in self._skills.items() if v.enabled}

    def get_openai_tools(self):
        """汇总所有启用技能，转换为 OpenAI function calling 的 tools 列表。"""
        return [s.to_openai_tool() for s in self._skills.values() if s.enabled]

    def list_skills(self):
        """返回技能摘要列表，供 API /api/skills 展示。"""
        return [{'name': s.name, 'description': s.description, 'enabled': s.enabled} for s in self._skills.values()]

    def discover(self):
        """启动时自动发现技能：扫描 skills 包内的所有模块并导入。

        模块顶层的 @registry.register 装饰器会在导入时执行，从而完成注册。
        """
        import skills as pkg
        print('Discovering skills...')
        for _, mod, _ in pkgutil.iter_modules(pkg.__path__):
            if mod in ('__init__', 'base', 'registry'):
                continue  # 跳过基础设施模块，只扫描具体技能
            try:
                importlib.import_module(f'skills.{mod}')
            except Exception as e:
                print(f'  ! {mod}: {e}')
        print(f'Total: {len(self._skills)}\n')


# 全局单例注册中心，main.py 启动时调用 registry.discover()
registry = SkillRegistry()
