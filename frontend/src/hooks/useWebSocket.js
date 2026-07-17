import { useEffect, useRef, useState, useCallback } from 'react'

// WebSocket 连接管理 + 事件分发
export function useWebSocket(apiBase, onEvent) {
  const [status, setStatus] = useState('off') // ok | wait | off
  const [skills, setSkills] = useState([])
  const [config, setConfig] = useState({ model: '', base_url: '' })
  const wsRef = useRef(null)
  const retryRef = useRef(0)
  const timerRef = useRef(null)
  const onEventRef = useRef(onEvent)
  useEffect(() => {
    onEventRef.current = onEvent
  }, [onEvent])

  const fetchMeta = useCallback(() => {
    fetch(`${apiBase}/api/skills`)
      .then((r) => r.json())
      .then((d) => setSkills(d.skills || []))
      .catch(() => setSkills([]))
    fetch(`${apiBase}/api/config`)
      .then((r) => r.json())
      .then((d) => setConfig(d))
      .catch(() => {})
  }, [apiBase])

  const connect = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    if (retryRef.current >= 10) {
      setStatus('off')
      return
    }
    if (wsRef.current) {
      wsRef.current.onopen = wsRef.current.onmessage = wsRef.current.onclose = wsRef.current.onerror = null
      try {
        wsRef.current.close()
      } catch {}
      wsRef.current = null
    }
    const url = apiBase.replace(/^http/, 'ws') + '/ws/chat'
    try {
      const ws = new WebSocket(url)
      wsRef.current = ws
      setStatus('wait')
      ws.onopen = () => {
        retryRef.current = 0
        setStatus('ok')
        fetchMeta()
      }
      ws.onmessage = (e) => {
        try {
          const m = JSON.parse(e.data)
          onEventRef.current?.(m.event, m.data)
        } catch {}
      }
      ws.onclose = () => {
        setStatus('off')
        retryRef.current += 1
        timerRef.current = setTimeout(connect, Math.min(2000 * Math.pow(1.5, retryRef.current), 30000))
      }
      ws.onerror = () => setStatus('off')
    } catch {
      retryRef.current += 1
      timerRef.current = setTimeout(connect, 5000)
    }
  }, [apiBase, fetchMeta])

  useEffect(() => {
    retryRef.current = 0
    connect()
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      if (wsRef.current) {
        wsRef.current.onclose = null
        try {
          wsRef.current.close()
        } catch {}
      }
    }
  }, [connect])

  const reconnect = useCallback(() => {
    retryRef.current = 0
    connect()
  }, [connect])

  const send = useCallback((payload) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload))
      return true
    }
    return false
  }, [])

  const updateConfig = useCallback(
    async (body) => {
      const r = await fetch(`${apiBase}/api/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await r.json()
      if (d.status === 'ok') {
        setConfig(d)
        reconnect()
      }
      return d
    },
    [apiBase, reconnect],
  )

  return { status, skills, config, send, reconnect, updateConfig, fetchMeta }
}
