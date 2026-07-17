import { useEffect, useRef, useState } from 'react'

// 输入框 + 附件 + 发送
export default function Composer({ onSend, busy, online, model }) {
  const [text, setText] = useState('')
  const [attachments, setAttachments] = useState([])
  const taRef = useRef(null)
  const fileRef = useRef(null)

  const update = () => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 160) + 'px'
  }

  useEffect(() => {
    update()
  }, [text])

  const canSend = (text.trim().length > 0 || attachments.length > 0) && !busy

  const submit = () => {
    if (!canSend) return
    if (!online) {
      alert('后端未连接。请确保 python main.py 在运行。')
      return
    }
    onSend(text, attachments)
    setText('')
    setAttachments([])
    setTimeout(update, 0)
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const onFileChange = (e) => {
    setAttachments(Array.from(e.target.files || []).map((f) => ({ name: f.name })))
    e.target.value = ''
  }

  return (
    <footer className="cmp border-t border-bdr px-5 py-3 pb-4 bg-bg flex-shrink-0">
      <div className="max-w-msg mx-auto flex flex-col gap-2">
        {attachments.length > 0 && (
          <div className="ab flex flex-wrap gap-1.5">
            {attachments.map((a, i) => (
              <span key={i} className="ac inline-flex items-center gap-1.5 px-2.5 py-[3px] rounded-full border border-bdr bg-bg2 text-[11px] text-fg3 anim-mIn">
                {a.name}
                <button
                  className="ax bg-transparent border-none cursor-pointer text-fg4 text-xs pl-0.5 transition-colors hover:text-err"
                  onClick={() => setAttachments((prev) => prev.filter((_, idx) => idx !== i))}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="ir flex items-end gap-1.5 border border-bdr rounded-r bg-card px-2.5 py-1.5 transition-all focus-within:border-ac focus-within:shadow-[0_0_0_3px_var(--ac-bg)]">
          <label
            className="btn btn-i btn-g cursor-pointer flex items-center justify-center"
            style={{ width: 30, height: 30, borderRadius: 'var(--rx)' }}
            title="附件"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
            </svg>
            <input ref={fileRef} type="file" multiple accept=".pdf,.txt,.doc,.docx" className="sr absolute w-px h-px overflow-hidden" onChange={onFileChange} />
          </label>
          <textarea
            ref={taRef}
            rows="1"
            placeholder="输入消息…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            className="flex-1 border-none outline-none resize-none bg-transparent min-h-[22px] max-h-40 leading-[1.6] text-sm py-1 placeholder:text-fg4"
          />
          <button
            className={`sb2 w-[34px] h-[34px] rounded-rs border-none bg-ac text-ac-fg cursor-pointer flex items-center justify-center flex-shrink-0 transition-all hover:bg-ac-h hover:scale-110 active:scale-95 disabled:opacity-25 disabled:cursor-not-allowed ${
              busy ? 'anim-sp opacity-70' : ''
            }`}
            disabled={!canSend}
            onClick={submit}
          >
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>
        <div className="ch text-[10px] text-fg4 flex justify-between">
          <span>Enter 发送 · Shift+Enter 换行</span>
          <span>{model || '演示模式'}</span>
        </div>
      </div>
    </footer>
  )
}
