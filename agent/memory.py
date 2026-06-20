from typing import List, Dict, Optional
from openai import AsyncOpenAI
from config import config

class ConversationMemory:
    def __init__(self, system_prompt: str = ''):
        self.system_prompt = system_prompt
        self.messages: List[Dict] = []
        self.summary: Optional[str] = None

    def add_user(self, content: str):
        self.messages.append({'role': 'user', 'content': content})

    def add_assistant(self, content: str):
        self.messages.append({'role': 'assistant', 'content': content})

    def add_tool_call(self, assistant_msg: dict):
        self.messages.append(assistant_msg)

    def add_tool_result(self, tool_call_id: str, content: str):
        self.messages.append({'role': 'tool', 'tool_call_id': tool_call_id, 'content': content})

    def get_messages(self, max_turns: int = 20) -> List[Dict]:
        result = []
        sys = self.system_prompt
        if self.summary:
            sys += '\n\n[Summary]\n' + self.summary
        result.append({'role': 'system', 'content': sys})
        result.extend(self.messages[-max_turns * 2:])
        return result

    def get_full_history(self) -> List[Dict]:
        return self.messages.copy()

    async def maybe_summarize(self, client: AsyncOpenAI):
        if len(self.messages) <= config.MEMORY_SUMMARY_THRESHOLD * 2:
            return
        old = self.messages[: -config.MEMORY_SUMMARY_THRESHOLD * 2]
        parts = []
        for m in old:
            if m['role'] in ('user', 'assistant') and m.get('content'):
                label = 'User' if m['role'] == 'user' else 'AI'
                parts.append(label + ': ' + m['content'])
        old_text = '\n'.join(parts)
        if not old_text:
            return
        resp = await client.chat.completions.create(
            model=config.AGENT_MODEL,
            messages=[{'role': 'system', 'content': 'Summarize in under 100 words.'}, {'role': 'user', 'content': old_text}],
            max_tokens=200,
        )
        ns = resp.choices[0].message.content
        self.summary = (self.summary + '\n' + ns) if self.summary else ns
        self.messages = self.messages[-config.MEMORY_SUMMARY_THRESHOLD * 2:]

    def clear(self):
        self.messages.clear()
        self.summary = None
