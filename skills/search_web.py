import httpx
from config import config
from skills import registry, BaseSkill, SkillResult, SkillParam

@registry.register
class SearchWebSkill(BaseSkill):
    name = 'search_web'
    description = 'Search the internet for information.'
    parameters = [
        SkillParam(name='query', type='string', description='Search query', required=True),
        SkillParam(name='num_results', type='integer', description='Number of results', required=False),
    ]
    async def execute(self, query: str, num_results: int = 5, **kw):
        api_key = config.SERPER_API_KEY
        if not api_key:
            return SkillResult(success=True, data=f"[Mock] Results for '{query}':\n1. {query} - Wiki\n2. {query} news\n3. {query} guide\n(Set SERPER_API_KEY for real results)")
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post('https://google.serper.dev/search', headers={'X-API-KEY': api_key, 'Content-Type': 'application/json'}, json={'q': query, 'num': num_results})
            resp.raise_for_status()
            data = resp.json()
        results = []
        for item in data.get('organic', [])[:num_results]:
            results.append(f"**{item.get('title', '')}**\n{item.get('snippet', '')}\n{item.get('link', '')}")
        return SkillResult(success=True, data='\n\n'.join(results) or 'No results')
