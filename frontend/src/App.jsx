import { useCallback, useEffect, useState } from 'react'
import Sidebar from './components/Sidebar'
import ChatWindow from './components/ChatWindow'
import Composer from './components/Composer'
import TopBar from './components/TopBar'
import Modal from './components/Modal'
import { useAppStore } from './hooks/useAppStore'
import { useWebSocket } from './hooks/useWebSocket'
import { estimateTokens, formatTime } from './utils'
import ToolCall from './components/ToolCall'

export default function App() {
  const store = useAppStore()
  const [live, setLive] = useState(null) // 流式临时节点
  const [busy, setBusy] = useState(false)
  const [modal, setModal] = useState(null) // 'model' | 'setting' | 'prompt'
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [pendingTool, setPendingTool] = useState(null)

  // 处理 WebSocket 事件
  const onEvent = useCallback(
    (event, data) => {
      if (event === 'thinking') {
        setLive(
          <div className="mg py-4 anim-mIn">
            <div className="mr text-[11px] font-semibold text-fg4 mb-1.5">Agent</div>
            <div className="typ flex gap-1 py-1.5">
              <span className="anim-dp w-1 h-1 rounded-full bg-fg4" />
              <span className="anim-dp w-1 h-1 rounded-full bg-fg4" style={{ animationDelay: '.2s' }} />
              <span className="anim-dp w-1 h-1 rounded-full bg-fg4" style={{ animationDelay: '.4s' }} />
            </div>
          </div>,
        )
      } else if (event === 'tool_call') {
        setPendingTool({ name: data.name, args: data.args, status: 'running' })
        setLive(<ToolCall name={data.name} args={data.args} status="running" />)
      } else if (event === 'tool_result') {
        setPendingTool((p) => (p ? { ...p, status: 'ok', result: data.data } : null))
        setLive((prev) => {
          if (!prev) return null
          // 简单替换：重新渲染 ToolCall
          return <ToolCall name={data.name} args={pendingTool?.args} status="ok" result={data.data} />
        })
      } else if (event === 'answer') {
        setLive(null)
        setPendingTool(null)
        store.appendMessage({
          role: 'assistant',
          content: data.content,
          tokens: estimateTokens(data.content),
        })
        done()
      } else if (event === 'error') {
        setLive(
          <div className="mg py-4 anim-mIn">
            <div className="mr text-[11px] font-semibold text-err mb-1.5">错误</div>
            <div className="mb text-err">{String(data.message || 'Error')}</div>
          </div>,
        )
        done()
      }
    },
    [store, pendingTool],
  )

  const ws = useWebSocket(store.apiBase, onEvent)

  const done = useCallback(() => {
    setBusy(false)
  }, [])

  // 发送消息
  const send = useCallback(
    (text, attachments = []) => {
      store.ensureSession()
      const content = text || '(附件)'
      store.appendMessage({
        role: 'user',
        content,
        tokens: estimateTokens(text),
        att: attachments.slice(),
      })
      setBusy(true)
      setLive(null)
      ws.send({ message: text, session_id: store.sessionId })
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

  // 模型保存
  const saveModel = async (body) => {
    try {
      await ws.updateConfig(body)
      setModal(null)
      store.clearSessions()
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
