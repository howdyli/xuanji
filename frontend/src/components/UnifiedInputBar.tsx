// --- Unified Input Bar (shared between home and chat) ---
import { useState, useRef } from 'react'
import { SendIcon, PaperclipIcon, SkillIcon } from './icons'
import { SessionSkillsPicker } from './SessionSkillsPicker'

// --- Quick command definitions ---
const QUICK_COMMANDS = [
  { label: '日报生成', hint: '/report', prompt: '帮我生成今日日报' },
  { label: '代码审查', hint: '/review', prompt: '帮我审查最近的代码变更' },
  { label: '全文翻译', hint: '/translate', prompt: '帮我翻译以下内容' },
  { label: '会议纪要', hint: '/minutes', prompt: '帮我整理会议纪要' },
  { label: '数据分析', hint: '/analyze', prompt: '帮我分析以下数据' },
  { label: '周报汇总', hint: '/weekly', prompt: '帮我汇总本周工作' },
]

export function UnifiedInputBar({
  isHome,
  loading,
  onSend,
  sessionId,
  inputRef,
  embedded,
}: {
  isHome: boolean
  loading: boolean
  onSend: (text: string) => void
  sessionId: string | null
  inputRef: React.RefObject<HTMLTextAreaElement | null>
  embedded?: boolean
}) {
  const [text, setText] = useState('')
  const [showCommands, setShowCommands] = useState(false)
  const [sendPressed, setSendPressed] = useState(false)

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed || loading) return
    onSend(trimmed)
    setText('')
    setShowCommands(false)
    setSendPressed(true)
    setTimeout(() => setSendPressed(false), 200)
  }

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value
    setText(val)
    const el = e.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
    if (!isHome && val.startsWith('/') && val.length < 20) {
      setShowCommands(true)
    } else {
      setShowCommands(false)
    }
  }

  const handleCommandSelect = (prompt: string) => {
    setText('')
    setShowCommands(false)
    onSend(prompt)
  }

  const filteredCommands = text.startsWith('/')
    ? QUICK_COMMANDS.filter(c => c.hint.startsWith(text.toLowerCase()) || c.label.includes(text.slice(1)))
    : QUICK_COMMANDS

  return (
    <div className={`shrink-0 ${embedded ? '' : `px-4 sm:px-6 lg:px-8 xl:px-12 ${isHome ? 'mb-5' : 'pb-3 sm:pb-5 pt-2'}`}`}>
      <div className="w-full mx-auto">
        <div className={`relative bg-white border border-[rgba(0,0,0,0.08)] ${isHome ? 'rounded-[16px]' : 'rounded-[16px]'} p-3.5 transition-all duration-200 focus-within:border-[#4F6EF7] focus-within:shadow-[0_0_0_3px_rgba(79,110,247,0.12)]`} style={{ borderRadius: 16, boxShadow: 'var(--shadow-lg)', background: 'var(--bg-secondary)', border: '1px solid var(--border-light)' }}>
          {/* Slash command popup */}
          {showCommands && filteredCommands.length > 0 && (
            <div className="absolute bottom-full left-3 right-3 mb-1 bg-white border border-[rgba(0,0,0,0.08)] rounded-[10px] shadow-md overflow-hidden z-10 animate-fade-in">
              {filteredCommands.map((cmd) => (
                <button
                  key={cmd.hint}
                  onClick={() => handleCommandSelect(cmd.prompt)}
                  className="w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-[#f0efe9] transition-colors"
                >
                  <span className="text-[11px] font-mono text-[#185FA5] w-[60px] shrink-0">{cmd.hint}</span>
                  <span className="text-[12px] text-[#1a1917]">{cmd.label}</span>
                </button>
              ))}
            </div>
          )}

          {/* Model selector (home) or mode tabs (chat) */}
          {isHome ? (
            <div className="flex items-center gap-2 mb-2.5">
              <button className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#E8F5E0] border border-[#D0E8C0] text-[11px] font-medium text-[#3D7A12] hover:bg-[#dcefcf] transition-colors">
                <span className="w-2 h-2 rounded-full bg-[#3D7A12]" />
                灵享妙语 Pro
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                  <path d="M2 3.5L5 6.5L8 3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-0.5 bg-[#f0efe9] rounded-[6px] p-[3px] w-fit mb-2.5">
              {['实景沙箱', 'Chat+', 'Auto', '技能'].map((tab, i) => (
                <button
                  key={tab}
                  className={`px-3 py-1 text-[11px] font-medium rounded-[4px] transition-all duration-150 whitespace-nowrap ${
                    i === 0 ? 'bg-white text-[#1a1917] shadow-sm' : 'text-[#9b9892] hover:text-[#6b6963]'
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>
          )}

          <textarea
            ref={inputRef}
            value={text}
            onChange={handleInput}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
              if (e.key === 'Escape') setShowCommands(false)
            }}
            placeholder={isHome ? '描述你的任务或问题…' : '继续对话，或输入 / 调用指令…'}
            rows={2}
            disabled={loading}
            className="w-full min-h-[40px] resize-none border-none outline-none text-[13px] text-[#1a1917] leading-relaxed bg-transparent placeholder:text-[#9b9892] disabled:opacity-50"
          />

          <div className="flex items-center justify-between mt-2.5 pt-2.5 border-t border-[rgba(0,0,0,0.08)]">
            <div className="flex items-center gap-1.5">
              {/* Attachment */}
              <button className="w-[30px] h-[30px] rounded-[8px] flex items-center justify-center text-[#9b9892] hover:bg-[#f0efe9] hover:text-[#6b6963] transition-colors" title="附件">
                <PaperclipIcon />
              </button>
              {/* Voice */}
              <button className="w-[30px] h-[30px] rounded-[8px] flex items-center justify-center text-[#9b9892] hover:bg-[#f0efe9] hover:text-[#6b6963] transition-colors" title="语音">
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M8 1a2 2 0 0 0-2 2v4a2 2 0 0 0 4 0V3a2 2 0 0 0-2-2z"/>
                  <path d="M12 7a4 4 0 0 1-8 0"/>
                  <path d="M8 11v3"/>
                </svg>
              </button>
              {/* Skill button in chat mode */}
              {!isHome && <SkillButton sessionId={sessionId} />}
            </div>
            <button
              onClick={handleSend}
              disabled={loading || !text.trim()}
              className={`w-[34px] h-[34px] rounded-full flex items-center justify-center text-white transition-all duration-150 hover:scale-105 disabled:opacity-50 disabled:cursor-not-allowed shrink-0 btn-press ${sendPressed ? 'scale-95' : ''}`}
              style={{ background: 'linear-gradient(135deg, #4F6EF7, #7C5CFC)' }}
            >
              <SendIcon />
            </button>
          </div>
        </div>

        {/* Keyboard shortcut hint */}
        <div className="text-center mt-2 text-[11px] text-[#9b9892]">
          按 Enter 发送，Shift+Enter 换行 · ⌘K 全局命令
        </div>
      </div>
    </div>
  )
}

// 底部工具栏的“技能”按钮 + 浮层选择器
function SkillButton({ sessionId }: { sessionId: string | null }) {
  const [open, setOpen] = useState(false)
  const btnRef = useRef<HTMLButtonElement>(null)
  return (
    <div className="relative">
      <button
        ref={btnRef}
        onClick={() => setOpen((v) => !v)}
        className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-[12px] border transition-colors ${
          open
            ? 'bg-gray-900 text-white border-gray-900'
            : 'text-gray-600 border-transparent hover:bg-white hover:border-gray-200'
        }`}
      >
        <SkillIcon />
        <span>技能</span>
      </button>
      <SessionSkillsPicker
        sessionId={sessionId}
        open={open}
        anchorEl={btnRef.current}
        onClose={() => setOpen(false)}
      />
    </div>
  )
}
