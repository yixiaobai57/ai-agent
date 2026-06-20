import importlib, pkgutil
from typing import Dict, Optional
from .base import BaseSkill

class SkillRegistry:
    def __init__(self):
        self._skills: Dict[str, BaseSkill] = {}

    def register(self, cls):
        inst = cls()
        self._skills[inst.name] = inst
        print(f'  + Skill: {inst.name}')
        return cls

    def get(self, name: str) -> Optional[BaseSkill]:
        return self._skills.get(name)

    def get_all(self):
        return {k: v for k, v in self._skills.items() if v.enabled}

    def get_openai_tools(self):
        return [s.to_openai_tool() for s in self._skills.values() if s.enabled]

    def list_skills(self):
        return [{'name': s.name, 'description': s.description, 'enabled': s.enabled} for s in self._skills.values()]

    def discover(self):
        import skills as pkg
        print('Discovering skills...')
        for _, mod, _ in pkgutil.iter_modules(pkg.__path__):
            if mod in ('__init__', 'base', 'registry'):
                continue
            try:
                importlib.import_module(f'skills.{mod}')
            except Exception as e:
                print(f'  ! {mod}: {e}')
        print(f'Total: {len(self._skills)}\n')

registry = SkillRegistry()
