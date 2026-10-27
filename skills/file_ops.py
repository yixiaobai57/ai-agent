"""文件读写技能：在受控工作目录内执行文件/目录操作。

安全边界：通过路径规范化后校验，拒绝任何逃逸出 BASE 工作目录的路径（防目录穿越）。
"""
from pathlib import Path
from skills import registry, BaseSkill, SkillResult, SkillParam


@registry.register
class FileOpsSkill(BaseSkill):
    name = 'file_ops'
    description = 'Read, write files, or list directory.'
    parameters = [
        SkillParam(name='action', type='string', description='read / write / list', required=True, enum=['read', 'write', 'list']),
        SkillParam(name='path', type='string', description='File path', required=True),
        SkillParam(name='content', type='string', description='Content for write', required=False),
    ]
    # 工作目录根：所有文件操作被限制在此目录内
    BASE = Path('./workspace').resolve()

    async def execute(self, action: str, path: str, content: str = '', **kw):
        # 规范化目标路径，并与 BASE 比对，防止目录穿越
        target = (self.BASE / path).resolve()
        if not str(target).startswith(str(self.BASE)):
            return SkillResult(success=False, error='Access denied')
        try:
            if action == 'read':
                if not target.exists():
                    return SkillResult(success=False, error=f'Not found: {path}')
                t = target.read_text(encoding='utf-8')
                # 限制返回长度，避免大文件撑爆上下文
                return SkillResult(success=True, data=t[:5000] if len(t) > 5000 else t)
            elif action == 'write':
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding='utf-8')
                return SkillResult(success=True, data=f'Written {len(content)} chars to {path}')
            elif action == 'list':
                if not target.exists():
                    return SkillResult(success=False, error=f'Not found: {path}')
                items = [f"{'[DIR]' if i.is_dir() else '[FILE]'} {i.name}" for i in sorted(target.iterdir())]
                return SkillResult(success=True, data='\n'.join(items) or '(empty)')
            return SkillResult(success=False, error=f'Unknown: {action}')
        except Exception as e:
            return SkillResult(success=False, error=str(e))
