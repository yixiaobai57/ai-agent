import { useEffect, useRef, useState, useCallback } from 'react'
import { storage, uid } from '../utils'

// 会话 + 设置 + 主题 全局状态
export function useAppStore() {
  const [theme, setTheme] = useState(() => storage.get('th', 'dark'))
  const [apiBase, setApiBase] = useState(() => storage.get('api', 'http://localhost:8000'))
  const [sessions, setSessions] = useState(() => storage.get('ss', []))
  const [sessionId, setSessionId] = useState(() => storage.get('sid', null))

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

  const ensureSession = useCallback(() => {
    setSessions((prev) => {
      if (prev.some((s) => s.id === sessionId)) return prev
      const s = { id: uid(), t: '新对话', ts: Date.now(), m: [] }
      setSessionId(s.id)
      return [s, ...prev]
    })
  }, [sessionId])

  const newSession = useCallback(() => {
    const s = { id: uid(), t: '新对话', ts: Date.now(), m: [] }
    setSessions((prev) => [s, ...prev])
    setSessionId(s.id)
    return s
  }, [])

  const selectSession = useCallback((id) => setSessionId(id), [])

  // 向当前会话追加一条消息
  const appendMessage = useCallback(
    (msg) => {
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== sessionId) return s
          const m = [...s.m, { ...msg, id: uid(), time: Date.now() }]
          const t = s.m.length === 0 && msg.role === 'user' ? (msg.content || '').slice(0, 24) || '新对话' : s.t
          return { ...s, m, t, ts: Date.now() }
        }),
      )
    },
    [sessionId],
  )

  // 替换当前会话（保存模型切换清空场景）
  const clearSessions = useCallback(() => {
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
