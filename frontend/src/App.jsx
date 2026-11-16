import { useCallback, useEffect, useState } from 'react'
import { marked } from 'marked'
import Sidebar from './components/Sidebar'
import ChatWindow from './components/ChatWindow'
import Composer from './components/Composer'
import TopBar from './components/TopBar'
import Modal from './components/Modal'
import ToolCall from './components/ToolCall'
import MessageBubble from './components/MessageBubble'
import { useAppStore } from './hooks/useAppStore'
import { useWebSocket } from './hooks/useWebSocket'
import { estimateTokens, formatTime } from './utils'

marked.setOptions({ breaks: true, gfm: true })

// 流式片段：{kind:'text', text} 或 {kind:'tool', name, args, status, result, duration}
const EMPTY_PARTS = []

export default function App() {
  const store = useAppStore()
  const [parts, setParts] = useState(EMPTY_PARTS)
  const [thinking, setThinking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [modal, setModal] = useState(null) // 'model' | 'setting' | 'prompt'
  const [sidebarOpen, setSidebarOpen] = useState(false)

  // 处理 WebSocket 事件（token 级增量拼接，避免整段覆盖）
  const onEvent = useCallback(
    (event, data) => {
      if (event === 'thinking') {
        setThinking(true)
      } else if (event === 'token') {
        const delta = data?.delta || ''
        if (!delta) return
        setThinking(false)
        setParts((prev) => {
          const last = prev[prev.length - 1]
          if (last && last.kind === 'text') {
            return [...prev.slice(0, -1), { ...last, text: last.text + delta }]
          }
          return [...prev, { kind: 'text', text: delta }]
        })
      } else if (event === 'tool_call') {
        setThinking(false)
        setParts((prev) => [
          ...prev,
          { kind: 'tool', name: data.name, args: data.args, status: data.status || 'running' },
        ])
      } else if (event === 'tool_result') {
        setParts((prev) => {
          const idx = [...prev]
            .reverse()
            .findIndex((p) => p.kind === 'tool' && p.status === 'running' && p.name === data.name)
          if (idx === -1) return prev
          const pos = prev.length - 1 - idx
          const next = [...prev]
          next[pos] = { ...next[pos], status: data.status || 'ok', result: data.data, duration: data.duration_ms }
          return next
        })
        setThinking(true)
      } else if (event === 'answer') {
        setParts(EMPTY_PARTS)
        setThinking(false)
        store.appendMessage({
          role: 'assistant',
          content: data.content,
          tokens: estimateTokens(data.content),
          trace: data.trace,
        })
        setBusy(false)
      } else if (event === 'error') {
        setParts((prev) => [
          ...prev,
          { kind: 'error', text: `${data.message || 'Error'}${data.code ? `（${data.code}）` : ''}` },
        ])
        setThinking(false)
        setBusy(false)
      }
    },
    [store],
  )

  const ws = useWebSocket(store.apiBase, onEvent)

  // 发送消息
  const send = useCallback(
    (text, attachments = []) => {
      const content = text || '(附件)'
      const sid = store.appendMessage({
        role: 'user',
        content,
        tokens: estimateTokens(text),
        att: attachments.slice(),
      })
      setBusy(true)
      setParts(EMPTY_PARTS)
      setThinking(true)
      ws.send({ message: text, session_id: sid })
    },
    [store, ws],
  )

  // 导出
  const exportChat = (fmt) => {
    const s = store.current
    if (!s) return
    const ls = s.m.map((m) => `[${formatTime(m.time)}] ${m.role === 'user' ? '用户' : 'Agent'}：\n${m.content}`)
    const c = fmt === 'md' ? `# ${s.t}\n\n${ls.join('\n\n---\n\n')}` : ls.join('\n\n')
    const blob = new Blob([c], { type: fmt === 'md' ? 'text/markdown' : 'text/plain' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${s.t || 'chat'}.${fmt}`
    document.body.appendChild(a)
    a.click()
    a.remove()
  }

  // 模型保存：后端可能因安全默认拒绝（runtime_config_disabled），把原因如实展示
  const saveModel = async (body) => {
    try {
      const d = await ws.updateConfig(body)
      if (d.status === 'ok') {
        setModal(null)
        store.clearSessions()
        return
      }
      alert(d.message || d.error_code || '保存失败')
    } catch (e) {
      alert('失败: ' + e.message)
    }
  }

  // 设置保存
  const saveSetting = (api) => {
    store.setApiBase(api)
    setModal(null)
  }

  // ESC 关闭模态
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') {
        setModal(null)
        setSidebarOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const live = renderLive(parts, thinking, busy)

  return (
    <div className="app grid h-screen overflow-hidden" style={{ gridTemplateColumns: 'var(--sbw,256px) 1fr' }}>
      {/* 移动端遮罩 */}
      {sidebarOpen && <div className="bk fixed inset-0 bg-black/20 z-[998]" onClick={() => setSidebarOpen(false)} />}

      {/* 侧边栏 */}
      <div className={`${sidebarOpen ? 'open' : ''} max-[1024px]:fixed max-[1024px]:left-0 max-[1024px]:top-0 max-[1024px]:bottom-0 max-[1024px]:z-[999] max-[1024px]:-translate-x-full max-[1024px]:transition-transform max-[1024px]:shadow-2xl ${sidebarOpen ? 'max-[1024px]:translate-x-0' : ''}`}>
        <Sidebar
          sessions={store.sessions}
          sessionId={store.sessionId}
          onSelect={(id) => {
            store.selectSession(id)
            setSidebarOpen(false)
          }}
          onNew={() => {
            store.newSession()
            setSidebarOpen(false)
          }}
          skills={ws.skills}
          onExport={exportChat}
          onOpenPrompt={() => setModal('prompt')}
        />
      </div>

      {/* 主区域 */}
      <main className="main grid h-screen overflow-hidden min-w-0" style={{ gridTemplateRows: 'auto 1fr auto' }}>
        <TopBar
          status={ws.status}
          model={ws.config.model}
          onToggleSidebar={() => setSidebarOpen(true)}
          onOpenModel={() => setModal('model')}
          onOpenSetting={() => setModal('setting')}
          onToggleTheme={store.toggleTheme}
          theme={store.theme}
        />
        <ChatWindow messages={store.current?.m || []} live={live} onSend={(t) => send(t)} />
        <Composer onSend={send} busy={busy} online={ws.status === 'ok'} model={ws.config.model} />
      </main>

      <Modal
        kind={modal}
        config={ws.config}
        onClose={() => setModal(null)}
        onSaveModel={saveModel}
        onSaveSetting={saveSetting}
      />
    </div>
  )
}

// 把流式片段渲染成 DOM。文本片段交给 MessageBubble（保留 Markdown/代码高亮），
// 工具片段交给 ToolCall（保留展开与耗时展示）。
function renderLive(parts, thinking, busy) {
  if (!parts.length) {
    if (!thinking && !busy) return null
    return (
      <div className="mg py-4 anim-mIn">
        <div className="mr text-[11px] font-semibold text-fg4 mb-1.5">Agent</div>
        <div className="typ flex gap-1 py-1.5">
          <span className="anim-dp w-1 h-1 rounded-full bg-fg4" />
          <span className="anim-dp w-1 h-1 rounded-full bg-fg4" style={{ animationDelay: '.2s' }} />
          <span className="anim-dp w-1 h-1 rounded-full bg-fg4" style={{ animationDelay: '.4s' }} />
        </div>
      </div>
    )
  }

  return (
    <div className="anim-mIn">
      {parts.map((p, i) => {
        if (p.kind === 'tool') {
          return (
            <ToolCall key={`t-${i}`} name={p.name} args={p.args} status={p.status} result={p.result} duration={p.duration} />
          )
        }
        if (p.kind === 'error') {
          return (
            <div key={`e-${i}`} className="mg py-4">
              <div className="mr text-[11px] font-semibold text-err mb-1.5">错误</div>
              <div className="mb text-err">{p.text}</div>
            </div>
          )
        }
        return (
          <MessageBubble
            key={`m-${i}`}
            msg={{
              id: `live-${i}`,
              role: 'assistant',
              content: p.text,
              html: marked.parse(p.text || ''),
              time: Date.now(),
              streaming: true,
            }}
          />
        )
      })}
      {thinking && (
        <div className="typ flex gap-1 py-1.5 pl-1">
          <span className="anim-dp w-1 h-1 rounded-full bg-fg4" />
          <span className="anim-dp w-1 h-1 rounded-full bg-fg4" style={{ animationDelay: '.2s' }} />
          <span className="anim-dp w-1 h-1 rounded-full bg-fg4" style={{ animationDelay: '.4s' }} />
        </div>
      )}
    </div>
  )
}
