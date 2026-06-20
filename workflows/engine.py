import yaml
from pathlib import Path
from typing import Dict, Optional
from skills.registry import registry

DEFS_DIR = Path(__file__).parent / 'defs'

class WorkflowEngine:
    def __init__(self):
        self._wfs: Dict[str, dict] = {}
        self._load()

    def _load(self):
        if not DEFS_DIR.exists():
            DEFS_DIR.mkdir(parents=True, exist_ok=True)
            return
        for f in DEFS_DIR.glob('*.yaml'):
            try:
                with open(f, encoding='utf-8') as fp:
                    wf = yaml.safe_load(fp)
                    if wf and 'name' in wf:
                        self._wfs[wf['name']] = wf
                        print(f"  > Workflow: {wf['name']}")
            except Exception as e:
                print(f'  ! {f.name}: {e}')

    def list_workflows(self):
        return list(self._wfs.keys())

    def get_workflow(self, name):
        return self._wfs.get(name)

    async def run(self, name, params=None):
        wf = self._wfs.get(name)
        if not wf:
            raise FileNotFoundError(f"Workflow '{name}' not found")
        ctx = params or {}
        results = []
        output = ''
        for i, step in enumerate(wf.get('steps', [])):
            sn = step.get('tool') or step.get('skill')
            sp = step.get('params', {})
            resolved = {}
            for k, v in sp.items():
                if isinstance(v, str) and v.startswith('{{') and v.endswith('}}'):
                    resolved[k] = ctx.get(v[2:-2].strip(), v)
                else:
                    resolved[k] = v
            skill = registry.get(sn)
            if not skill:
                raise RuntimeError(f"Step {i+1}: skill '{sn}' not found")
            r = await skill(**resolved)
            results.append({'step': i+1, 'skill': sn, 'ok': r.success})
            if not r.success:
                output = f'Step {i+1} ({sn}) failed: {r.error}'
                break
            ctx['last_result'] = r.data
            output = str(r.data)
        return {'output': output, 'steps_completed': len(results), 'step_results': results}

workflow_engine = WorkflowEngine()
