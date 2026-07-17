// 本地存储工具
export const storage = {
  get(k, f) {
    try {
      const v = localStorage.getItem(k)
      return v ? JSON.parse(v) : f
    } catch {
      return f
    }
  },
  set(k, v) {
    try {
      localStorage.setItem(k, JSON.stringify(v))
    } catch {}
  },
}

// 生成唯一 ID
export const uid = () => Math.random().toString(36).slice(2, 9) + Date.now().toString(36)

// 粗略估算 token 数
export const estimateTokens = (t) => {
  if (!t) return 0
  const c = (t.match(/[\u4e00-\u9fff]/g) || []).length
  return Math.round(c * 1.8 + Math.max(0, t.length - c) / 4)
}

// 会话日期分组
export const dateLabel = (ts) => {
  const d = new Date(ts).toDateString()
  const n = new Date().toDateString()
  const y = new Date()
  y.setDate(y.getDate() - 1)
  return d === n ? '今天' : d === y.toDateString() ? '昨天' : '更早'
}

// 时间格式化
export const formatTime = (ts) =>
  new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

// 日期格式化（用于消息分隔符）
export const formatDate = (ts) =>
  new Date(ts).toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'short' })
