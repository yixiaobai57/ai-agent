"""技能系统基类：定义技能（Skill）的通用数据结构与统一接口。

Agent 的每一项能力都实现为一个 Skill：
- 继承 BaseSkill 并实现 execute 方法
- 声明 name / description / parameters（参数 schema）
- 系统启动时由 skills/registry.py 自动发现并注册
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List
from pydantic import BaseModel


class SkillParam(BaseModel):
    """技能参数声明模型：描述一个入参的名称、类型、说明、是否必填及可选枚举值。

    该声明会自动转换为 OpenAI function calling 的 JSON Schema，供大模型理解如何传参。
    """
    name: str
    type: str = 'string'            # 参数类型：string / integer / object 等
    description: str = ''           # 参数说明，会展示给大模型，帮助它正确传参
    required: bool = True           # 是否必填
    enum: Optional[list] = None     # 可选取值枚举，用于约束参数的取值范围


class SkillResult(BaseModel):
    """技能执行结果的统一返回模型。

    无论成功失败都以该结构返回，方便 Agent 主循环（agent/core.py）统一处理。
    """
    success: bool                   # 是否执行成功
    data: Any = None                # 成功时的返回数据
    error: Optional[str] = None     # 失败时的错误信息
    metadata: Dict[str, Any] = {}   # 附加元信息（如工作流执行的步数）


class BaseSkill(ABC):
    """技能抽象基类：所有技能必须继承并实现 execute 方法。

    Agent 通过 name 定位技能，通过 description + parameters 告知大模型"何时调用、怎么传参"。
    """
    name: str = ''                      # 技能唯一标识，同时作为 tool calling 中的函数名
    description: str = ''               # 技能用途说明，决定大模型是否会触发调用
    parameters: List[SkillParam] = []   # 参数声明列表
    enabled: bool = True                # 是否启用（false 时不参与工具调用）

    def to_openai_tool(self) -> dict:
        """把技能声明转换为 OpenAI function calling 所需的 tools 格式。

        逐个将 SkillParam 映射为 JSON Schema 的 properties，供大模型解析调用参数。
        """
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
        """技能的核心业务逻辑，由具体技能实现。"""
        pass

    async def __call__(self, **kwargs) -> SkillResult:
        """技能的统一调用入口：捕获执行中的异常并包装为 SkillResult。

        Agent 主循环统一通过 __call__ 调用技能，避免底层异常直接抛出中断整个对话流程。
        """
        try:
            return await self.execute(**kwargs)
        except Exception as e:
            return SkillResult(success=False, error=str(e))
