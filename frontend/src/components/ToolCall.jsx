import { useState } from 'react'
import { SKILL_ICONS } from '../constants'

// 工具调用行 + 结果展开
export default function ToolCall({ name, args, status, result }) {
  const [expanded, setExpanded] = useState(false)
  let argStr = ''
  try {
    argStr = typeof args === 'object' ? JSON.stringify(args) : String(args)
  } catch {
    argStr = String(args)
  }
  const argPreview = argStr.length > 120 ? argStr.slice(0, 120) + '…' : argStr

  return (
    <div className="anim-tIn flex items-center gap-2 px-3 py-2 rounded-rs bg-bg2 border border-bdr2 my-1.5 text-xs">
      <span className="text-[13px] flex-shrink-0">{SKILL_ICONS[name] || '🔧'}</span>
      <span className="font-semibold text-fg2">{name}</span>
      <span className="text-fg4 text-[11px]">{argPreview.replace(/</g, '&lt;')}</span>
      <span
        className={`ml-auto flex items-center gap-1 text-[11px] transition-colors ${status === 'ok' ? 'text-ok' : 'text-fg4'}`}
      >
        {status === 'ok' ? (
          '✓'
        ) : (
          <>
            <span className="anim-spin inline-block w-2 h-2 border-2 border-bdr border-t-ac rounded-full" />
          </>
        )}
      </span>
      {result && (
        <div className="w-full mt-1 ml-0 p-2 bg-card border border-bdr rounded-rx text-[11px] text-fg3 font-mono leading-[1.5] anim-exIn max-h-20 overflow-auto whitespace-pre-wrap break-words">
          {result.length > 200 ? result.slice(0, 200) + '…' : result}
        </div>
      )}
    </div>
  )
}
