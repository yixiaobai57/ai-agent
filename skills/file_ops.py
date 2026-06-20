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
    BASE = Path('./workspace').resolve()
    async def execute(self, action: str, path: str, content: str = '', **kw):
        target = (self.BASE / path).resolve()
        if not str(target).startswith(str(self.BASE)):
            return SkillResult(success=False, error='Access denied')
        try:
            if action == 'read':
                if not target.exists(): return SkillResult(success=False, error=f'Not found: {path}')
                t = target.read_text(encoding='utf-8')
                return SkillResult(success=True, data=t[:5000] if len(t) > 5000 else t)
            elif action == 'write':
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding='utf-8')
                return SkillResult(success=True, data=f'Written {len(content)} chars to {path}')
            elif action == 'list':
                if not target.exists(): return SkillResult(success=False, error=f'Not found: {path}')
                items = [f"{'[DIR]' if i.is_dir() else '[FILE]'} {i.name}" for i in sorted(target.iterdir())]
                return SkillResult(success=True, data='\n'.join(items) or '(empty)')
            return SkillResult(success=False, error=f'Unknown: {action}')
        except Exception as e:
            return SkillResult(success=False, error=str(e))
