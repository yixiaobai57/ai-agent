import { dateLabel } from '../utils'
import { SKILL_ICONS } from '../constants'

// 会话列表 + 技能 + 工具按钮
export default function Sidebar({ sessions, sessionId, onSelect, onNew, skills, onExport, onOpenPrompt }) {
  const groups = { 今天: [], 昨天: [], 更早: [] }
  sessions.forEach((s) => {
    const k = dateLabel(s.ts)
    ;(groups[k] || groups['更早']).push(s)
  })

  return (
    <aside className={`sb bg-sb border-r border-bdr flex flex-col h-screen overflow-hidden`}>
      <div className="sb-hd px-3.5 pt-4 pb-2.5 flex items-center justify-between flex-shrink-0">
        <span className="text-[11px] font-semibold text-fg4 tracking-[.04em] uppercase">会话</span>
        <button className="btn btn-a btn-s btn-f" onClick={onNew}>
          + 新建
        </button>
      </div>

      <div className="sb-sc flex-1 overflow-y-auto px-2.5 pb-2.5">
        {sessions.length === 0 ? (
          <div className="empty py-6 px-2 text-center text-xs text-fg4 leading-6">💬 还没有会话<br />点击「+ 新建」开始</div>
        ) : (
          ['今天', '昨天', '更早'].map(
            (k) =>
              groups[k].length > 0 && (
                <div key={k} className="sb-sec mb-[18px]">
                  <div className="sb-lbl text-[10px] font-semibold text-fg4 tracking-[.06em] uppercase px-1 pb-2">{k}</div>
                  <div>
                    {groups[k].map((s) => (
                      <button
                        key={s.id}
                        className={`ci ${s.id === sessionId ? 'on' : ''}`}
                        onClick={() => onSelect(s.id)}
                      >
                        {s.t || '新对话'}
                      </button>
                    ))}
                  </div>
                </div>
              ),
          )
        )}
      </div>

      <div className="sb-ft p-2.5 border-t border-bdr flex-shrink-0 flex flex-col gap-1.5">
        <div className="sb-sec mb-2">
          <div className="sb-lbl text-[10px] font-semibold text-fg4 tracking-[.06em] uppercase px-1 pb-2">技能</div>
          <div className="flex flex-wrap gap-1 px-0.5">
            {skills.length === 0 ? (
              <span className="text-[11px] text-fg4">连接后加载…</span>
            ) : (
              skills.map((s) => (
                <span key={s.name} className="chip">
                  {SKILL_ICONS[s.name] || '·'} {s.name}
                </span>
              ))
            )}
          </div>
        </div>
        <button className="btn btn-g btn-s w-full" onClick={onOpenPrompt}>
          系统提示词
        </button>
        <div className="flex gap-1.5">
          <button className="btn btn-g btn-s flex-1" onClick={() => onExport('txt')}>
            TXT
          </button>
          <button className="btn btn-g btn-s flex-1" onClick={() => onExport('md')}>
            Markdown
          </button>
        </div>
      </div>
    </aside>
  )
}
