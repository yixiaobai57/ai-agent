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
        from workflows.engine import workflow_engine
        try:
            r = await workflow_engine.run(workflow_name, params or {})
            return SkillResult(success=True, data=r.get('output', 'Done'), metadata={'steps': r.get('steps_completed', 0)})
        except FileNotFoundError:
            return SkillResult(success=False, error=f"Not found: {workflow_name}. Available: {', '.join(workflow_engine.list_workflows())}")
        except Exception as e:
            return SkillResult(success=False, error=str(e))
