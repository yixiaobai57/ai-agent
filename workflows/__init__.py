"""工作流包：对外暴露引擎与全局单例。"""

from .engine import WorkflowEngine as WorkflowEngine
from .engine import workflow_engine as workflow_engine

__all__ = ["WorkflowEngine", "workflow_engine"]
