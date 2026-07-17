import { useEffect, useState } from 'react'
import { MODEL_PRESETS } from '../constants'

// 模态层（模型切换 / 设置 / 系统提示词）
export default function Modal({ kind, config, onClose, onSaveModel, onSaveSetting }) {
  // kind: 'model' | 'setting' | 'prompt'
  if (!kind) return null

  return (
    <div
      className="ov fixed inset-0 bg-black/20 backdrop-blur-[2px] flex items-center justify-center z-[1000]"
      style={{ display: 'flex' }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="anim-mdIn md bg-card border border-bdr rounded-[14px] w-[min(520px,90vw)] max-h-[85vh] overflow-auto p-6 shadow-[0_20px_60px_rgba(0,0,0,.1)]">
        {kind === 'model' && <ModelForm config={config} onClose={onClose} onSave={onSaveModel} />}
        {kind === 'setting' && <SettingForm onClose={onClose} onSave={onSaveSetting} />}
        {kind === 'prompt' && <PromptView onClose={onClose} />}
      </div>
    </div>
  )
}

function ModelForm({ config, onClose, onSave }) {
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState(config.model || '')
  const [baseUrl, setBaseUrl] = useState(config.base_url || '')

  useEffect(() => {
    setModel(config.model || '')
    setBaseUrl(config.base_url || '')
  }, [config])

  const pickPreset = (p) => {
    setBaseUrl(p.b)
    setModel(p.m)
  }

  const save = () => {
    if (!model) {
      alert('请输入模型名称')
      return
    }
    const body = {}
    if (apiKey) body.api_key = apiKey
    if (baseUrl) body.base_url = baseUrl
    if (model) body.model = model
    onSave(body)
  }

  return (
    <>
      <h3 className="text-base font-semibold mb-1">切换模型</h3>
      <p className="text-[13px] text-fg3 mb-[18px] leading-6">选择预设或自定义，保存后自动重连。</p>
      <div className="ml flex flex-col gap-1 mb-[18px]">
        {MODEL_PRESETS.map((p) => {
          const active = model === p.m
          return (
            <div
              key={p.n}
              className={`mo flex items-center gap-2.5 px-3 py-2.5 rounded-rs border-[1.5px] border-bdr bg-card cursor-pointer text-[13px] text-fg2 transition-all hover:border-fg4 hover:bg-bg2 hover:scale-[1.01] ${
                active ? 'on border-ac bg-ac-bg' : ''
              }`}
              onClick={() => pickPreset(p)}
            >
              <span className="mo-c w-2 h-2 rounded-full flex-shrink-0" style={{ background: p.c }} />
              <span className="mo-n font-semibold text-fg flex-1">{p.n}</span>
              <span className="mo-d text-fg4 text-xs">{p.d}</span>
            </div>
          )
        })}
      </div>
      <div className="g2 grid grid-cols-2 gap-3">
        <div className="fg mb-3.5">
          <label className="fl block text-[11px] font-semibold text-fg3 mb-1.5 tracking-[.02em] uppercase">API Key</label>
          <input
            className="fs w-full px-3 py-[9px] border border-bdr rounded-rs bg-card text-fg text-[13px] focus:border-ac focus:outline-none focus:shadow-[0_0_0_3px_var(--ac-bg)] placeholder:text-fg4"
            type="password"
            placeholder="留空保持当前"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>
        <div className="fg mb-3.5">
          <label className="fl block text-[11px] font-semibold text-fg3 mb-1.5 tracking-[.02em] uppercase">模型</label>
          <input
            className="fs w-full px-3 py-[9px] border border-bdr rounded-rs bg-card text-fg text-[13px] focus:border-ac focus:outline-none focus:shadow-[0_0_0_3px_var(--ac-bg)] placeholder:text-fg4"
            placeholder="deepseek-chat"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
        </div>
      </div>
      <div className="fg mb-3.5">
        <label className="fl block text-[11px] font-semibold text-fg3 mb-1.5 tracking-[.02em] uppercase">Base URL</label>
        <input
          className="fs w-full px-3 py-[9px] border border-bdr rounded-rs bg-card text-fg text-[13px] focus:border-ac focus:outline-none focus:shadow-[0_0_0_3px_var(--ac-bg)] placeholder:text-fg4"
          placeholder="https://api.deepseek.com/v1"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
        />
      </div>
      <div className="mf flex justify-end gap-2 mt-5">
        <button className="btn btn-g" onClick={onClose}>
          取消
        </button>
        <button className="btn btn-a" onClick={save}>
          保存
        </button>
      </div>
    </>
  )
}

function SettingForm({ onClose, onSave }) {
  const [api, setApi] = useState(localStorage.getItem('api') ? JSON.parse(localStorage.getItem('api')) : 'http://localhost:8000')
  return (
    <>
      <h3 className="text-base font-semibold mb-1">设置</h3>
      <p className="text-[13px] text-fg3 mb-[18px] leading-6">后端连接地址。</p>
      <div className="fg mb-3.5">
        <label className="fl block text-[11px] font-semibold text-fg3 mb-1.5 tracking-[.02em] uppercase">API 地址</label>
        <input
          className="fs w-full px-3 py-[9px] border border-bdr rounded-rs bg-card text-fg text-[13px] focus:border-ac focus:outline-none focus:shadow-[0_0_0_3px_var(--ac-bg)] placeholder:text-fg4"
          placeholder="http://localhost:8000"
          value={api}
          onChange={(e) => setApi(e.target.value)}
        />
      </div>
      <div className="mf flex justify-end gap-2 mt-5">
        <button className="btn btn-g" onClick={onClose}>
          关闭
        </button>
        <button className="btn btn-a" onClick={() => onSave(api.replace(/\/$/, ''))}>
          保存
        </button>
      </div>
    </>
  )
}

function PromptView({ onClose }) {
  return (
    <>
      <h3 className="text-base font-semibold mb-1">系统提示词</h3>
      <p className="text-[13px] text-fg3 mb-[18px] leading-6">Agent 行为由后端控制。</p>
      <textarea
        className="ft w-full px-3 py-[9px] border border-bdr rounded-rs bg-card text-fg text-[13px] min-h-[120px] resize-vertical leading-6"
        readOnly
        defaultValue={'你是一个强大的 AI 智能助手，拥有多种技能工具。'}
      />
      <div className="mf flex justify-end gap-2 mt-5">
        <button className="btn btn-g" onClick={onClose}>
          关闭
        </button>
      </div>
    </>
  )
}
