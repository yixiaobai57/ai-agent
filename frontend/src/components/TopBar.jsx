// 顶部栏：状态、模型、设置、主题
export default function TopBar({ status, model, onToggleSidebar, onOpenModel, onOpenSetting, onToggleTheme, theme }) {
  const statusLabel = { ok: '已连接', wait: '连接中…', off: '离线' }[status] || status
  const statusText = { ok: '●', wait: '●', off: '●' }

  return (
    <header className="top flex items-center justify-between px-5 py-2.5 border-b border-bdr bg-bg flex-shrink-0 gap-3">
      <div className="top-l flex items-center gap-2.5 min-w-0">
        <button className="ib btn-g mob hidden max-[1024px]:flex" onClick={onToggleSidebar} aria-label="菜单">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
        <div>
          <div className="t1 text-sm font-semibold whitespace-nowrap tracking-[-.01em]">AI Agent</div>
          <div className="t2 text-[11px] text-fg4 whitespace-nowrap max-[1024px]:hidden">
            {model || 'DeepSeek'} · 技能调用
          </div>
        </div>
      </div>
      <div className="top-r flex items-center gap-1.5 flex-shrink-0">
        <span className={`st st-${status} flex items-center gap-1.5 text-[11px] text-fg4 transition-colors`} role="status" aria-live="polite">
          <span
            className={`st-d w-1.5 h-1.5 rounded-full transition-all ${
              status === 'ok' ? 'bg-ok' : status === 'wait' ? 'bg-warn anim-pulse' : 'bg-err scale-90'
            }`}
          />
          {statusLabel}
        </span>
        <button className="ib" onClick={onOpenModel} aria-label="切换模型">
          🤖
        </button>
        <button className="ib" onClick={onOpenSetting} aria-label="设置">
          ⚙
        </button>
        <button className="ib" onClick={onToggleTheme} aria-label="主题">
          {theme === 'dark' ? '☾' : '☀'}
        </button>
      </div>
    </header>
  )
}
