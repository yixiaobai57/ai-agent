import asyncio, sys, io, traceback
from config import config
from skills import registry, BaseSkill, SkillResult, SkillParam

@registry.register
class CodeExecutorSkill(BaseSkill):
    name = 'execute_code'
    description = 'Execute Python code in a sandbox.'
    parameters = [SkillParam(name='code', type='string', description='Python code', required=True)]
    async def execute(self, code: str, **kw):
        old_out, old_err = sys.stdout, sys.stderr
        cap_out, cap_err = io.StringIO(), io.StringIO()
        for b in ['os.system', 'subprocess', 'shutil.rmtree']:
            if b in code:
                return SkillResult(success=False, error=f'Blocked: {b}')
        try:
            sys.stdout, sys.stderr = cap_out, cap_err
            loop = asyncio.get_event_loop()
            await asyncio.wait_for(loop.run_in_executor(None, exec, code, {'__builtins__': __builtins__}, {}), timeout=config.CODE_EXEC_TIMEOUT)
            output = cap_out.getvalue()
            errors = cap_err.getvalue()
            if errors:
                return SkillResult(success=False, data=output or None, error=errors)
            return SkillResult(success=True, data=output or '(no output)')
        except asyncio.TimeoutError:
            return SkillResult(success=False, error=f'Timeout ({config.CODE_EXEC_TIMEOUT}s)')
        except Exception:
            return SkillResult(success=False, error=traceback.format_exc())
        finally:
            sys.stdout, sys.stderr = old_out, old_err
