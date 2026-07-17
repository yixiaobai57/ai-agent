// 预设模型列表
export const MODEL_PRESETS = [
  { n: 'DeepSeek', d: '性价比高，中文优秀', c: '#3b82f6', b: 'https://api.deepseek.com/v1', m: 'deepseek-chat' },
  { n: 'MiMo-Coder', d: '小米代码模型', c: '#16a34a', b: 'https://api.xiaomimo.com/v1', m: 'MiMo-Coder' },
  { n: 'GPT-4o', d: 'OpenAI', c: '#8b5cf6', b: 'https://api.openai.com/v1', m: 'gpt-4o' },
  { n: 'Qwen', d: '通义千问', c: '#f97316', b: 'https://dashscope.aliyuncs.com/compatible-mode/v1', m: 'qwen-plus' },
  { n: 'GLM-4', d: '智谱', c: '#eab308', b: 'https://open.bigmodel.cn/api/paas/v4', m: 'glm-4-flash' },
  { n: 'Claude', d: 'Anthropic', c: '#78716c', b: 'https://api.anthropic.com/v1', m: 'claude-3-5-sonnet-20241022' },
]

// 技能图标映射
export const SKILL_ICONS = {
  search_web: '🔍',
  execute_code: '💻',
  file_ops: '📁',
  run_workflow: '⚡',
}

// 欢迎页建议
export const SUGGESTIONS = [
  '用 Python 写一个冒泡排序，然后执行它',
  '搜索一下最近 AI 领域有什么新闻',
  '帮我创建一个 hello.py 写入 Hello World',
  '运行 daily_report 工作流',
]
