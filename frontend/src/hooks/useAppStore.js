import { useEffect, useRef, useState, useCallback } from 'react'
import { storage, uid } from '../utils'

// 默认后端地址：由后端单端口托管时走同源，只有 vite dev(5173) 或本地文件打开才回落到 8000
const DEFAULT_API =
  location.protocol === 'file:' || location.port === '5173' ? 'http://localhost:8000' : location.origin

// 会话 + 设置 + 主题 全局状态
export function useAppStore() {
  const [theme, setTheme] = useState(() => storage.get('th', 'dark'))
  const [apiBase, setApiBase] = useState(() => storage.get('api', DEFAULT_API))
  const [sessions, setSessions] = useState(() => storage.get('ss', []))
  const [sessionId, setSessionId] = useState(() => storage.get('sid', null))

  // 镜像当前的 sessionId：React state 更新是异步的，发消息时需要在同一次写入里拿到最新值
  const sidRef = useRef(sessionId)
  useEffect(() => {
    sidRef.current = sessionId
  }, [sessionId])

  // 持久化
  useEffect(() => storage.set('th', theme), [theme])
  useEffect(() => storage.set('api', apiBase), [apiBase])
  useEffect(() => storage.set('ss', sessions), [sessions])
  useEffect(() => storage.set('sid', sessionId), [sessionId])

  // 应用主题
  useEffect(() => {
    const isDark = theme === 'dark'
    document.body.classList.toggle('light', !isDark)
  }, [theme])

  const toggleTheme = useCallback(() => setTheme((t) => (t === 'dark' ? 'light' : 'dark')), [])

  const current = sessions.find((s) => s.id === sessionId) || null

  // 确保有一个可写入的会话 id（同步返回，避免 setState 竞态导致第一条消息丢失）
  const ensureSession = useCallback(() => {
    let sid = sidRef.current
    if (!sid) {
      sid = uid()
      sidRef.current = sid
      setSessionId(sid)
    }
    setSessions((prev) => (prev.some((s) => s.id === sid) ? prev : [{ id: sid, t: '新对话', ts: Date.now(), m: [] }, ...prev]))
    return sid
  }, [])

  const newSession = useCallback(() => {
    const s = { id: uid(), t: '新对话', ts: Date.now(), m: [] }
    sidRef.current = s.id
    setSessionId(s.id)
    setSessions((prev) => [s, ...prev])
    return s
  }, [])

  const selectSession = useCallback((id) => {
    sidRef.current = id
    setSessionId(id)
  }, [])

  // 向当前会话追加一条消息（会话不存在时自动创建）
  const appendMessage = useCallback((msg) => {
    let sid = sidRef.current
    if (!sid) {
      sid = uid()
      sidRef.current = sid
      setSessionId(sid)
    }
    setSessions((prev) => {
      const exists = prev.some((s) => s.id === sid)
      const list = exists ? prev : [{ id: sid, t: '新对话', ts: Date.now(), m: [] }, ...prev]
      return list.map((s) => {
        if (s.id !== sid) return s
        const m = [...s.m, { ...msg, id: uid(), time: msg.time || Date.now() }]
        const t = s.m.length === 0 && msg.role === 'user' ? (msg.content || '').slice(0, 24) || '新对话' : s.t
        return { ...s, m, t, ts: Date.now() }
      })
    })
    return sid
  }, [])

  // 保存模型后清空本地会话（后端配置变了，旧的推理上下文不再成立）
  const clearSessions = useCallback(() => {
    sidRef.current = null
    setSessions([])
    setSessionId(null)
  }, [])

  return {
    theme,
    toggleTheme,
    apiBase,
    setApiBase,
    sessions,
    sessionId,
    current,
    ensureSession,
    newSession,
    selectSession,
    appendMessage,
    clearSessions,
  }
}
