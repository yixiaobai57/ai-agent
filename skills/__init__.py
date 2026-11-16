"""技能包：对外统一导出基类、结果模型与注册中心。

各技能模块写作 ``from skills import BaseSkill, SkillParam, SkillResult, registry``，
因此这里的 re-export 属于对外契约的一部分。
"""

from .base import BaseSkill as BaseSkill
from .base import SkillParam as SkillParam
from .base import SkillResult as SkillResult
from .registry import registry as registry

__all__ = ["BaseSkill", "SkillParam", "SkillResult", "registry"]
