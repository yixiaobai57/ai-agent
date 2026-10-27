"""工作流执行技能：把预定义的 YAML 多步骤工作流封装成一个可调用技能。

Agent 可通过该技能触发类似"搜索→执行代码→写文件"的自动化链路。
"""
from skills import registry, BaseSkill, SkillResult, SkillParam


@registry.register
class WorkflowRunnerSkill(BaseSkill):
    name = 'run_workflow'
    description = 'Execute a predefined multi-step workflow.'
    parameters = [
        SkillParam(name='workflow_name', type='string', description='Workflow name', required=True),
        SkillParam(name='params', type='object', description='Parameters', required=False),
    ]

    async def execute(self, workflow_name: str, params: dict = None, **kw):
        from workflows.engine import workflow_engine  # 延迟导入，避免循环依赖
        try:
            r = await workflow_engine.run(workflow_name, params or {})
            # 返回输出与已执行步数，步数写入 metadata 便于观测
            return SkillResult(success=True, data=r.get('output', 'Done'), metadata={'steps': r.get('steps_completed', 0)})
        except FileNotFoundError:
            # 工作流不存在时，列出可用工作流，帮助大模型纠正
            return SkillResult(success=False, error=f"Not found: {workflow_name}. Available: {', '.join(workflow_engine.list_workflows())}")
        except Exception as e:
            return SkillResult(success=False, error=str(e))
