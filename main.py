import json
from typing import Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from config import config
from agent.core import Agent
from skills.registry import registry
from workflows.engine import workflow_engine

app = FastAPI(title='AI Agent Backend', version='2.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
registry.discover()
sessions: Dict[str, Agent] = {}

def get_agent(sid='default'):
    if sid not in sessions:
        sessions[sid] = Agent()
    return sessions[sid]

class ChatReq(BaseModel):
    message: str
    session_id: str = 'default'

class ConfigReq(BaseModel):
    api_key: str = None
    base_url: str = None
    model: str = None

@app.get('/health')
async def health():
    return {'status': 'ok', 'model': config.AGENT_MODEL, 'base_url': config.API_BASE_URL, 'skills': len(registry.get_all()), 'workflows': len(workflow_engine.list_workflows())}

@app.get('/api/skills')
async def list_skills():
    return {'skills': registry.list_skills()}

@app.get('/api/workflows')
async def list_wfs():
    wfs = []
    for n in workflow_engine.list_workflows():
        wf = workflow_engine.get_workflow(n)
        wfs.append({'name': n, 'description': wf.get('description', ''), 'steps': len(wf.get('steps', []))})
    return {'workflows': wfs}

@app.get('/api/config')
async def get_config():
    return {
        'model': config.AGENT_MODEL,
        'base_url': config.API_BASE_URL,
        'has_api_key': bool(config.OPENAI_API_KEY),
        'timeout': config.REQUEST_TIMEOUT,
    }

@app.post('/api/config')
async def update_config(req: ConfigReq):
    config.update(api_key=req.api_key, base_url=req.base_url, model=req.model)
    sessions.clear()
    return {'status': 'ok', 'model': config.AGENT_MODEL, 'base_url': config.API_BASE_URL}

@app.post('/api/session/new')
async def new_session():
    import uuid
    sid = str(uuid.uuid4())[:8]
    sessions[sid] = Agent()
    return {'session_id': sid}

@app.delete('/api/session')
async def clear_session(req: ChatReq):
    get_agent(req.session_id).clear_memory()
    return {'status': 'cleared'}

@app.post('/api/chat')
async def chat(req: ChatReq):
    agent = get_agent(req.session_id)
    resp = await agent.run(req.message)
    return {'response': resp}

@app.websocket('/ws/chat')
async def ws_chat(ws: WebSocket):
    await ws.accept()
    sid = 'default'
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                msg = {'message': raw}
            text = msg.get('message', '').strip()
            sid = msg.get('session_id', sid)
            if not text:
                continue
            agent = get_agent(sid)
            async def cb(event, data):
                try:
                    await ws.send_text(json.dumps({'event': event, 'data': data}, ensure_ascii=False))
                except Exception:
                    pass
            agent.on_stream(cb)
            await agent.run(text)
    except WebSocketDisconnect:
        print(f'WS disconnected: {sid}')
    except Exception as e:
        print(f'WS error: {e}')

if __name__ == '__main__':
    import uvicorn
    print('=' * 50)
    print('AI Agent Backend v2.0')
    print(f'  Model:     {config.AGENT_MODEL}')
    print(f'  API:       {config.API_BASE_URL}')
    print(f'  Skills:    {len(registry.get_all())}')
    print(f'  Workflows: {len(workflow_engine.list_workflows())}')
    print(f'  Docs:      http://localhost:{config.PORT}/docs')
    print('=' * 50)
    uvicorn.run('main:app', host=config.HOST, port=config.PORT, reload=True)
