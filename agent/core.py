import json, asyncio
from typing import Callable, Awaitable, Optional, Dict, Any
from openai import AsyncOpenAI
from config import config
from agent.memory import ConversationMemory
from skills.registry import registry

StreamCallback = Callable[[str, Dict[str, Any]], Awaitable[None]]

SYS = ('You are a powerful AI assistant with tools.\n\n'
    'Rules:\n1. Think if you need a tool.\n'
    '2. If yes, call the best tool.\n'
    '3. Use tool results for a clear answer.\n'
    '4. Multi-step: go step by step.\n'
    '5. Reply in user language. Use Markdown.')

class Agent:
    def __init__(self, system_prompt: str = ''):
        self.client = AsyncOpenAI(
            api_key=config.OPENAI_API_KEY,
            base_url=config.API_BASE_URL,
            timeout=config.REQUEST_TIMEOUT,
        )
        self.memory = ConversationMemory(system_prompt=system_prompt or SYS)
        self._on_stream: Optional[StreamCallback] = None

    def on_stream(self, callback: StreamCallback):
        self._on_stream = callback

    async def _emit(self, event: str, data: dict):
        if self._on_stream:
            await self._on_stream(event, data)

    def _rebuild_client(self):
        self.client = AsyncOpenAI(
            api_key=config.OPENAI_API_KEY,
            base_url=config.API_BASE_URL,
            timeout=config.REQUEST_TIMEOUT,
        )

    async def run(self, user_message: str) -> str:
        self._rebuild_client()
        self.memory.add_user(user_message)
        await self._emit('thinking', {'status': 'Thinking...'})
        tools = registry.get_openai_tools()
        iteration = 0
        while iteration < config.MAX_ITERATIONS:
            iteration += 1
            messages = self.memory.get_messages()
            params = {
                'model': config.AGENT_MODEL,
                'messages': messages,
                'temperature': config.AGENT_TEMPERATURE,
                'max_tokens': config.MAX_TOKENS,
            }
            if tools:
                try:
                    params['tools'] = tools
                    params['tool_choice'] = 'auto'
                except Exception:
                    pass
            response = None
            for attempt in range(3):
                try:
                    response = await self.client.chat.completions.create(**params)
                    break
                except Exception as e:
                    err_msg = str(e)
                    if 'tool' in err_msg.lower() or 'function' in err_msg.lower():
                        params.pop('tools', None)
                        params.pop('tool_choice', None)
                        try:
                            response = await self.client.chat.completions.create(**params)
                            break
                        except Exception as e2:
                            if attempt == 2:
                                err = f'LLM error: {e2}'
                                await self._emit('error', {'message': err})
                                return err
                    elif 'timeout' in err_msg.lower() or 'timed out' in err_msg.lower():
                        if attempt < 2:
                            await self._emit('thinking', {'status': f'Retrying... (attempt {attempt+2}/3)'})
                            await asyncio.sleep(2)
                            continue
                        else:
                            err = 'LLM error: Request timed out after 3 attempts.'
                            await self._emit('error', {'message': err})
                            return err
                    else:
                        if attempt == 2:
                            err = f'LLM error: {e}'
                            await self._emit('error', {'message': err})
                            return err
            if response is None:
                err = 'LLM error: No response after retries'
                await self._emit('error', {'message': err})
                return err
            msg = response.choices[0].message
            if msg.tool_calls:
                self.memory.add_tool_call(msg.model_dump())
                for tc in msg.tool_calls:
                    fn = tc.function.name
                    try:
                        fa = json.loads(tc.function.arguments)
                    except Exception:
                        fa = {}
                    await self._emit('tool_call', {'name': fn, 'args': fa, 'status': 'running'})
                    skill = registry.get(fn)
                    if skill:
                        result = await skill(**fa)
                        content = result.data if result.success else f'Error: {result.error}'
                    else:
                        content = f'Error: skill {fn} not found'
                    await self._emit('tool_result', {'name': fn, 'data': str(content)[:500]})
                    self.memory.add_tool_result(tc.id, str(content))
            else:
                final = msg.content or ''
                self.memory.add_assistant(final)
                await self._emit('answer', {'content': final})
                await self.memory.maybe_summarize(self.client)
                return final
        fb = 'Too many steps.'
        self.memory.add_assistant(fb)
        await self._emit('answer', {'content': fb})
        return fb

    def clear_memory(self):
        self.memory.clear()
