import { useState } from 'react'
import { formatTime } from '../utils'

// 单条消息气泡（支持流式游标与 trace 摘要）
export default function MessageBubble({ msg }) {
  const [copied, setCopied] = useState(false)
  const isUser = msg.role === 'user'
  const trace = msg.trace

  const copy = () => {
    navigator.clipboard.writeText(msg.content || '').then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <div className="anim-mIn flex flex-col gap-0.5 py-4 border-t border-bdr2 first:border-t-0">
      <div className="mr text-[11px] font-semibold text-fg4 mb-1.5 tracking-[.02em]">
        {isUser ? '你' : 'Agent'}
      </div>
      <div className="mb" dangerouslySetInnerHTML={{ __html: msg.html || msg.content || '' }} />
      {msg.streaming && <span className="anim-dp inline-block w-[2px] h-[13px] align-middle bg-fg3" />}
      {!isUser && (
        <div className="ma flex gap-1 mt-1.5 opacity-0 translate-y-0.5 transition-all hover:opacity-100 group-hover:opacity-100">
          <button className="ma-b px-2 py-[3px] rounded-rx border border-transparent bg-transparent text-fg4 text-[11px] cursor-pointer transition-all hover:bg-bg3 hover:text-fg2 hover:border-bdr" onClick={copy}>
            {copied ? '已复制' : '复制'}
          </button>
        </div>
      )}
      <div className="mm text-[10px] text-fg4 mt-2 flex gap-3 opacity-60 transition-opacity hover:opacity-100">
        <span>{formatTime(msg.time)}</span>
        {trace && (
          <span title="本轮推理耗时 / 工具调用次数 / token 用量">
            {trace.total_ms}ms · {trace.tool_calls} 次工具
            {trace.retries ? ` · 重试 ${trace.retries}` : ''}
          </span>
        )}
      </div>
    </div>
  )
}
