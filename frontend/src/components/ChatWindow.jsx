import { useEffect, useRef } from 'react'
import { marked } from 'marked'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'
import MessageBubble from './MessageBubble'
import ToolCall from './ToolCall'
import { SUGGESTIONS } from '../constants'
import { formatDate } from '../utils'

marked.setOptions({ breaks: true, gfm: true })

// 流式事件渲染（thinking / tool_call / tool_result / answer / error）
export default function ChatWindow({ messages, live, onSuggestion, onSend }) {
  const scrollRef = useRef(null)

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [messages, live])

  // 代码高亮 + 复制按钮
  useEffect(() => {
    const root = scrollRef.current
    if (!root) return
    root.querySelectorAll('pre code').forEach((el) => {
      try {
        hljs.highlightElement(el)
      } catch {}
    })
    root.querySelectorAll('pre:not([data-cc])').forEach((pre) => {
      pre.setAttribute('data-cc', '1')
      const btn = document.createElement('button')
      btn.className =
        'absolute top-2 right-2 px-2 py-[3px] rounded-rx border border-code-b bg-card text-fg4 text-[10px] font-semibold cursor-pointer opacity-0 -translate-y-0.5 transition-all hover:text-fg2 z-[2]'
      btn.textContent = '复制'
      btn.onclick = () => {
        const code = pre.querySelector('code')
        navigator.clipboard.writeText(code ? code.textContent : '').then(() => {
          btn.textContent = '已复制'
          btn.classList.add('text-ac')
          setTimeout(() => {
            btn.textContent = '复制'
            btn.classList.remove('text-ac')
          }, 2000)
        })
      }
      pre.appendChild(btn)
      pre.addEventListener('mouseenter', () => {
        btn.style.opacity = '1'
        btn.style.transform = 'translateY(0)'
      })
      pre.addEventListener('mouseleave', () => {
        btn.style.opacity = '0'
      })
    })
  }, [messages, live])

  const isEmpty = messages.length === 0 && !live

  return (
    <section className="chat overflow-y-auto overflow-x-hidden" aria-live="polite" ref={scrollRef}>
      <div className="max-w-msg mx-auto px-6 py-8 pb-4 flex flex-col">
        {isEmpty ? (
          <div className="wel anim-wIn flex flex-col gap-7 items-center py-12 pb-6">
            <div className="wel-l w-11 h-11 rounded-xl border-[1.5px] border-bdr flex items-center justify-center text-lg bg-bg2 text-fg3 transition-transform hover:scale-110 hover:-rotate-3">
              A
            </div>
            <h1 className="text-[22px] font-semibold tracking-[-.02em] text-center">有什么可以帮你？</h1>
            <p className="text-[13px] text-fg3 text-center max-w-[380px] leading-7">
              支持搜索、代码执行、文件操作和多模型切换的智能体助手。
            </p>
            <div className="sugs flex flex-col gap-1.5 w-full max-w-[480px] mt-1">
              {SUGGESTIONS.map((t, i) => (
                <button
                  key={i}
                  className="si anim-sIn flex items-center gap-2.5 px-3.5 py-2.5 rounded-rs border border-bdr bg-card cursor-pointer text-[13px] text-fg2 leading-[1.5] transition-all hover:border-fg4 hover:bg-bg2 hover:translate-x-1"
                  style={{ animationDelay: `${0.1 + i * 0.07}s` }}
                  onClick={() => onSend(t)}
                >
                  <span className="w-1 h-1 rounded-full bg-fg4 flex-shrink-0" />
                  {t}
                </button>
              ))}
            </div>
          </div>
        ) : (
          renderMessages(messages, live)
        )}
      </div>
    </section>
  )
}

function renderMessages(messages, live) {
  let lastDate = ''
  const nodes = []
  messages.forEach((m) => {
    const d = formatDate(m.time)
    if (d !== lastDate) {
      lastDate = d
      nodes.push(
        <div key={`d-${m.id}`} className="ds flex items-center gap-3 py-5 px-0 text-[11px] font-medium text-fg4">
          <span className="flex-1 h-px bg-bdr" />
          {d}
          <span className="flex-1 h-px bg-bdr" />
        </div>,
      )
    }
    nodes.push(<MessageBubble key={m.id} msg={{ ...m, html: marked.parse(m.content || '') }} />)
  })
  if (live) nodes.push(live)
  return nodes
}
