"""代码执行技能：在一个受限的沙箱中执行 Python 代码。

安全边界：
- 拦截 os.system / subprocess / shutil.rmtree 等危险调用
- 限制执行超时（config.CODE_EXEC_TIMEOUT）
- 重定向 stdout/stderr，捕获输出与错误并返回给大模型
"""
import asyncio, sys, io, traceback
from config import config
from skills import registry, BaseSkill, SkillResult, SkillParam


@registry.register
class CodeExecutorSkill(BaseSkill):
    name = 'execute_code'
    description = 'Execute Python code in a sandbox.'
    parameters = [SkillParam(name='code', type='string', description='Python code', required=True)]

    async def execute(self, code: str, **kw):
        # 备份原始 stdout/stderr，后续恢复
        old_out, old_err = sys.stdout, sys.stderr
        # 用 StringIO 捕获代码运行时的标准输出/错误
        cap_out, cap_err = io.StringIO(), io.StringIO()
        # 危险调用黑名单：包含即拒绝执行
        for b in ['os.system', 'subprocess', 'shutil.rmtree']:
            if b in code:
                return SkillResult(success=False, error=f'Blocked: {b}')
        try:
            sys.stdout, sys.stderr = cap_out, cap_err
            loop = asyncio.get_event_loop()
            # 在线程池中执行用户代码，避免阻塞事件循环，并设置超时
            await asyncio.wait_for(
                loop.run_in_executor(None, exec, code, {'__builtins__': __builtins__}, {}),
                timeout=config.CODE_EXEC_TIMEOUT,
            )
            output = cap_out.getvalue()
            errors = cap_err.getvalue()
            if errors:
                # 有错误输出则视为失败，同时保留部分 stdout
                return SkillResult(success=False, data=output or None, error=errors)
            return SkillResult(success=True, data=output or '(no output)')
        except asyncio.TimeoutError:
            return SkillResult(success=False, error=f'Timeout ({config.CODE_EXEC_TIMEOUT}s)')
        except Exception:
            # 返回完整 traceback，便于大模型分析并修正代码
            return SkillResult(success=False, error=traceback.format_exc())
        finally:
            # 恢复原始 stdout/stderr，防止污染宿主进程
            sys.stdout, sys.stderr = old_out, old_err
