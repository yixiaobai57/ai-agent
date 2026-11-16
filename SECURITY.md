# 安全说明

这个项目会**执行模型生成的 Python 代码**、**读写文件**、**发起网络请求**，所以默认姿态是「能力可关、边界可验」。

## 已实现的防护

| 面 | 措施 | 位置 |
|---|---|---|
| 代码执行 | AST 白名单（仅标准库算法/数据处理）＋禁止 `eval/exec/compile/__import__/open/getattr-dunder`＋`python -I` 子进程＋独立临时目录＋超时 kill＋输出截断 | `skills/code_executor.py` |
| 文件读写 | 目录级包含判断（`os.path.commonpath` + `normcase`），拒绝同前缀兄弟目录；读/写各有字符与字节上限 | `skills/file_ops.py` |
| 运行期改配置 | 默认关闭（403）；开启后仍需 `X-Admin-Token`，用 `hmac.compare_digest` 比较 | `api/deps.py` |
| 跨域 | CORS 白名单，不使用 `*` + credentials | `main.py` |
| 请求体 | `MAX_REQUEST_BYTES` 超限即 413，不进入业务逻辑 | `main.py` |
| 密钥泄露 | `GET /api/config` 只返回 `has_api_key`；日志不打印密钥 | `config.public_dict()` |
| 会话爆炸 | `MAX_SESSIONS` + TTL + LRU/按 `updated_at` 淘汰 | `sessions/store.py` |

## 已知边界（请勿据此上生产）

1. **代码执行不是硬隔离。** AST 白名单能挡住常见越权调用，但挡不住刻意构造的资源耗尽
   （巨量内存分配、极高 CPU 占用）。生产环境请改为容器/沙箱（gVisor、Firecracker、nsjail），
   并在外层加 CPU/内存/文件描述符配额。
2. **文件工具只保护了「路径」，没保护「内容」。** 写入内容不做敏感信息过滤。
3. **会话 SQLite 是单机方案**，多副本部署需替换为共享存储实现 `SessionStore` 协议。
4. **Mock 模式的搜索结果是假数据**，带 `metadata.mock` 标记，勿用于任何真实决策。

## 部署建议

```bash
# 最小暴露面
ENABLE_CODE_EXEC=false
ALLOW_RUNTIME_CONFIG=false
CORS_ORIGINS=https://your-domain.example

# 必须开启代码执行时
ENABLE_CODE_EXEC=true
CODE_EXEC_TIMEOUT=5
TOOL_TIMEOUT=10
```

建议在反向代理层再加：TLS、请求速率限制、鉴权（本项目的鉴权只覆盖「改配置」这一个高危接口，
对话接口默认按内网/单用户场景设计）。

## 报告漏洞

请勿公开 Issue。把复现步骤、影响范围、PoC 发到维护者邮箱（仓库 profile 可见），
48 小时内确认，修复后在 CHANGELOG 记录（不披露细节）。
