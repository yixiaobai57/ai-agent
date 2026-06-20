from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List
from pydantic import BaseModel

class SkillParam(BaseModel):
    name: str
    type: str = 'string'
    description: str = ''
    required: bool = True
    enum: Optional[list] = None

class SkillResult(BaseModel):
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = {}

class BaseSkill(ABC):
    name: str = ''
    description: str = ''
    parameters: List[SkillParam] = []
    enabled: bool = True

    def to_openai_tool(self) -> dict:
        props = {}
        required = []
        for p in self.parameters:
            prop = {'type': p.type, 'description': p.description}
            if p.enum:
                prop['enum'] = p.enum
            props[p.name] = prop
            if p.required:
                required.append(p.name)
        return {'type': 'function', 'function': {'name': self.name, 'description': self.description, 'parameters': {'type': 'object', 'properties': props, 'required': required}}}

    @abstractmethod
    async def execute(self, **kwargs) -> SkillResult:
        pass

    async def __call__(self, **kwargs) -> SkillResult:
        try:
            return await self.execute(**kwargs)
        except Exception as e:
            return SkillResult(success=False, error=str(e))
