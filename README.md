# AI Agent

一个多模型 AI Agent，支持工具调用和 WebSocket 实时流式输出。前后端分离，后端 FastAPI，前端纯 HTML 单页。

最初只是想把 DeepSeek 的 API 包一层自己用，后来陆续加了模型切换、工具调用、实时流式输出，还有插件系统。现在可以切 DeepSeek / Moonshot / GPT-4o / Qwen / GLM-4 五个模型，各有各的 tool calling 风格。

## 能做什么

- 五个模型随便切，每个模型可以独立配置 API key
- 工具调用：内置搜索、代码执行、文件操作、工作流四种 tool
- WebSocket 流式输出，打字机效果
- 深色模式，做了移动端适配
- 插件系统：写好 Python 文件扔进 plugins 目录就能扩展新能力

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env   # 填上你要用的模型的 API key
python main.py
```

然后浏览器打开 `frontend/index.html`。

`.env.example` 里每个模型都留了配置位，用哪个填哪个，不用的留空就行。

## 目录

```
ai-agent/
├── main.py              # FastAPI 入口
├── frontend/
│   └── index.html       # 前端单页
├── tools/               # 内置工具实现
├── plugins/             # 插件目录
├── requirements.txt
└── .env.example
```

## 已知不足

- 前端是原生 HTML，没上框架，维护起来有点脏
- 工具调用的错误处理不够细致，模型返回异常格式时会直接报错
- 插件热加载还没做，加了新插件得重启服务

## License

MIT
