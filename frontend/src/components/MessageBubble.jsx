import { useState } from 'react'
import { formatTime } from '../utils'

// 单条消息气泡
export default function MessageBubble({ msg }) {
  const [copied, setCopied] = useState(false)
  const isUser = msg.role === 'user'

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
      {!isUser && (
        <div className="ma flex gap-1 mt-1.5 opacity-0 translate-y-0.5 transition-all hover:opacity-100 group-hover:opacity-100">
          <button className="ma-b px-2 py-[3px] rounded-rx border border-transparent bg-transparent text-fg4 text-[11px] cursor-pointer transition-all hover:bg-bg3 hover:text-fg2 hover:border-bdr" onClick={copy}>
            {copied ? '已复制' : '复制'}
          </button>
        </div>
      )}
      <div className="mm text-[10px] text-fg4 mt-2 flex gap-3 opacity-60 transition-opacity hover:opacity-100">
        <span>{formatTime(msg.time)}</span>
      </div>
    </div>
  )
}
