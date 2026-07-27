// --- Unified Input Bar (shared between home and chat) ---
import { useState, useRef, useEffect } from 'react'
import { SendIcon, PaperclipIcon, SkillIcon } from './icons'
import { SessionSkillsPicker } from './SessionSkillsPicker'
import { SessionKnowledgePicker } from './SessionKnowledgePicker'
import { useExperts, ExpertPickerPopover, ExpertPickerList } from './ExpertPicker'
import { MentionPicker, useSessionSkills } from './MentionPicker'
import {
  createBase,
  getDocument,
  getSessionBases,
  setSessionBases,
  uploadDocument,
} from '../api/knowledge'

// --- 聊天上传限制（与后端 knowledge 路由一致，前端预检）---
const UPLOAD_ACCEPT = '.pdf,.docx,.md,.markdown,.txt,.text'
const ALLOWED_EXTS = ['.pdf', '.docx', '.md', '.markdown', '.txt', '.text']
const MAX_UPLOAD_BYTES = 32 * 1024 * 1024
const POLL_INTERVAL_MS = 3000
const POLL_MAX_ATTEMPTS = 60 // 最多轮询 3 分钟

interface UploadItem {
  key: string
  fileName: string
  status: 'uploading' | 'processing' | 'ready' | 'failed'
  error?: string
}

// --- Quick command definitions ---
const QUICK_COMMANDS = [
  { label: '日报生成', hint: '/report', prompt: '帮我生成今日日报' },
  { label: '代码审查', hint: '/review', prompt: '帮我审查最近的代码变更' },
  { label: '全文翻译', hint: '/translate', prompt: '帮我翻译以下内容' },
  { label: '会议纪要', hint: '/minutes', prompt: '帮我整理会议纪要' },
  { label: '数据分析', hint: '/analyze', prompt: '帮我分析以下数据' },
  { label: '周报汇总', hint: '/weekly', prompt: '帮我汇总本周工作' },
]

// --- @技能 提示提取（纯函数，供单测）---
// 与启用技能名精确匹配的 @token 才计入；保序去重，最多 3 个。
export function extractSkillHints(text: string, enabledSkills: string[]): string[] {
  const hints: string[] = []
  const re = /@(\S+)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    const name = m[1]
    if (enabledSkills.includes(name) && !hints.includes(name)) {
      hints.push(name)
      if (hints.length >= 3) break
    }
  }
  return hints
}

export function UnifiedInputBar({
  isHome,
  loading,
  onSend,
  sessionId,
  inputRef,
  embedded,
  activeExpert,
  onSelectExpert,
}: {
  isHome: boolean
  loading: boolean
  onSend: (text: string, opts?: { skillHints?: string[] }) => void
  sessionId: string | null
  inputRef: React.RefObject<HTMLTextAreaElement | null>
  embedded?: boolean
  activeExpert: string | null
  onSelectExpert: (name: string | null) => void
}) {
  const [text, setText] = useState('')
  const [showCommands, setShowCommands] = useState(false)
  const [sendPressed, setSendPressed] = useState(false)
  const [showExperts, setShowExperts] = useState(false)
  const [showMention, setShowMention] = useState(false)
  const [mentionQuery, setMentionQuery] = useState('')
  const [uploads, setUploads] = useState<UploadItem[]>([])
  const [kbRefreshKey, setKbRefreshKey] = useState(0)
  const expertBtnRef = useRef<HTMLButtonElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const aliveRef = useRef(true)
  const { experts, loading: expertsLoading } = useExperts()
  // 会话启用技能：供 @ 浮层技能栏与发送时 hints 提取共用
  const { skills: sessionSkills, loading: sessionSkillsLoading } = useSessionSkills(
    sessionId, !isHome && !!sessionId,
  )
  const activeExpertObj = activeExpert ? experts.find((e) => e.name === activeExpert) : null

  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
    }
  }, [])

  // “@” 唤起手势：匹配光标处正在输入的 @token（与 / 指令互斥）。
  const MENTION_RE = /(^|\s)@(\S*)$/

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed || loading) return
    // @技能 token 解析为 skill_hints（本条消息提示）；正文原样保留 @ 字样
    const skillHints = extractSkillHints(trimmed, sessionSkills.map((s) => s.name))
    if (skillHints.length > 0) {
      onSend(trimmed, { skillHints })
    } else {
      onSend(trimmed)
    }
    setText('')
    setShowCommands(false)
    setShowMention(false)
    setSendPressed(true)
    setTimeout(() => setSendPressed(false), 200)
  }

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value
    setText(val)
    const el = e.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
    const mention = val.match(MENTION_RE)
    if (mention) {
      setShowMention(true)
      setMentionQuery(mention[2])
      setShowCommands(false)
    } else {
      setShowMention(false)
      if (!isHome && val.startsWith('/') && val.length < 20) {
        setShowCommands(true)
      } else {
        setShowCommands(false)
      }
    }
  }

  const handleCommandSelect = (prompt: string) => {
    setText('')
    setShowCommands(false)
    onSend(prompt)
  }

  // 选中 @ 专家：删除输入框里的 @token（不留字面提及）并激活专家。
  const handleMentionSelect = (name: string) => {
    setText((prev) => prev.replace(MENTION_RE, '$1'))
    setShowMention(false)
    onSelectExpert(name)
    inputRef.current?.focus()
  }

  // 选中 @ 技能：@token 替换为 `@技能名 `，留在文本里（发送时解析为 hints）。
  const handleMentionSkillSelect = (name: string) => {
    setText((prev) => prev.replace(MENTION_RE, `$1@${name} `))
    setShowMention(false)
    inputRef.current?.focus()
  }

  const filteredCommands = text.startsWith('/')
    ? QUICK_COMMANDS.filter(c => c.hint.startsWith(text.toLowerCase()) || c.label.includes(text.slice(1)))
    : QUICK_COMMANDS

  // --- 聊天文件上传：进知识库 + 自动建库绑定（设计文档 §6.2/§6.3）---

  const patchUpload = (key: string, patch: Partial<UploadItem>) =>
    setUploads((prev) => prev.map((u) => (u.key === key ? { ...u, ...patch } : u)))

  // 目标库：已绑定→第一个绑定库；无绑定→自动建个人库并绑定
  const ensureTargetKb = async (sid: string): Promise<string> => {
    const bound = await getSessionBases(sid)
    if (bound.kb_ids.length > 0) return bound.kb_ids[0]
    const now = new Date()
    const mmdd = `${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
    const base = await createBase({ name: `会话资料 ${mmdd}`, scope: 'personal' })
    await setSessionBases(sid, [base.id])
    setKbRefreshKey((k) => k + 1)
    return base.id
  }

  // 轮询摄取状态直到 ready/failed（上限 3 分钟，瞬时错误继续轮询）
  const pollDocStatus = async (key: string, docId: string) => {
    for (let i = 0; i < POLL_MAX_ATTEMPTS; i++) {
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))
      if (!aliveRef.current) return
      try {
        const { document } = await getDocument(docId, { limit: 1 })
        if (document.status === 'ready') {
          patchUpload(key, { status: 'ready' })
          return
        }
        if (document.status === 'failed') {
          patchUpload(key, {
            status: 'failed',
            error: '解析失败，可到知识库页面查看详情',
          })
          return
        }
      } catch {
        // transient error: keep polling
      }
    }
    patchUpload(key, { status: 'failed', error: '解析超时，可到知识库页面查看详情' })
  }

  const handleFiles = async (files: FileList | null) => {
    if (!files || !sessionId) return
    const list = Array.from(files)
    if (fileInputRef.current) fileInputRef.current.value = ''
    for (const file of list) {
      const key = `${Date.now()}-${Math.random().toString(36).slice(2)}`
      const dot = file.name.lastIndexOf('.')
      const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : ''
      if (!ALLOWED_EXTS.includes(ext)) {
        setUploads((prev) => [...prev, { key, fileName: file.name, status: 'failed', error: '仅支持 pdf/docx/md/txt' }])
        continue
      }
      if (file.size > MAX_UPLOAD_BYTES) {
        setUploads((prev) => [...prev, { key, fileName: file.name, status: 'failed', error: '文件超过 32MB' }])
        continue
      }
      setUploads((prev) => [...prev, { key, fileName: file.name, status: 'uploading' }])
      try {
        const kbId = await ensureTargetKb(sessionId)
        const res = await uploadDocument(kbId, file)
        patchUpload(key, { status: 'processing' })
        void pollDocStatus(key, res.id)
      } catch (e) {
        patchUpload(key, { status: 'failed', error: e instanceof Error ? e.message : '上传失败' })
      }
    }
  }

  // 附件/知识库按钮仅在活动会话（chat 模式且有 sessionId）渲染
  const kbEnabled = !isHome && !!sessionId

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

          {/* @ 内联浮层：会话内为专家+技能两栏，首页保持专家单栏（关键词实时过滤） */}
          {showMention && (
            <div className="absolute bottom-full left-3 right-3 mb-1 bg-white border border-[rgba(0,0,0,0.08)] rounded-[12px] shadow-md overflow-hidden z-10 animate-fade-in">
              {isHome ? (
                <ExpertPickerList
                  experts={experts}
                  loading={expertsLoading}
                  query={mentionQuery}
                  activeName={activeExpert}
                  onSelect={handleMentionSelect}
                  showSearch={false}
                />
              ) : (
                <MentionPicker
                  open={showMention}
                  anchorEl={inputRef.current}
                  query={mentionQuery}
                  experts={experts}
                  expertsLoading={expertsLoading}
                  skills={sessionSkills}
                  skillsLoading={sessionSkillsLoading}
                  activeExpert={activeExpert}
                  onSelectExpert={handleMentionSelect}
                  onSelectSkill={handleMentionSkillSelect}
                  onClose={() => setShowMention(false)}
                />
              )}
            </div>
          )}

          {/* Mode tabs (unified across home and chat, per composer design) */}
          <div className="flex items-center gap-0.5 bg-[#f0efe9] rounded-[6px] p-[3px] w-fit mb-2.5">
            {['实景沙箱', 'Chat+', 'Auto', '技能'].map((tab, i) => (
              <button
                key={tab}
                className={`px-3 py-1 text-[11px] font-medium rounded-[4px] transition-all duration-150 whitespace-nowrap ${
                  i === 0 ? 'bg-white text-[#1a1917] border border-[rgba(0,0,0,0.08)] shadow-sm' : 'text-[#9b9892] hover:text-[#6b6963]'
                }`}
              >
                {tab}
              </button>
            ))}
          </div>

          {/* 当前专家芯片（可一键取消） */}
          {activeExpert && (
            <div className="flex items-center gap-1.5 mb-2 w-fit pl-2 pr-1.5 py-1 rounded-full bg-[#E9F3FB] border border-[#cfe4f5] text-[12px] text-[#185FA5]">
              <span className="leading-none">🧠</span>
              <span className="truncate max-w-[160px]">当前专家：{activeExpertObj?.display_name || activeExpert}</span>
              <button
                type="button"
                onClick={() => onSelectExpert(null)}
                className="w-4 h-4 rounded-full flex items-center justify-center text-[#4A6B82] hover:bg-white hover:text-[#185FA5] transition-colors"
                title="取消召唤"
              >
                ✕
              </button>
            </div>
          )}

          {/* 上传状态芯片（仿专家芯片，输入框上方） */}
          {uploads.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-2">
              {uploads.map((u) => (
                <div
                  key={u.key}
                  className={`flex items-center gap-1.5 w-fit pl-2 pr-1.5 py-1 rounded-full border text-[12px] ${
                    u.status === 'failed'
                      ? 'bg-red-50 border-red-200 text-red-700'
                      : u.status === 'ready'
                        ? 'bg-[#E8F5E0] border-[#D0E8C0] text-[#3D7A12]'
                        : 'bg-[#f0efe9] border-[rgba(0,0,0,0.08)] text-[#6b6963]'
                  }`}
                >
                  <span className="leading-none">📎</span>
                  <span className="truncate max-w-[140px]">{u.fileName}</span>
                  <span className="shrink-0">
                    {u.status === 'uploading' && '上传中…'}
                    {u.status === 'processing' && '解析中…'}
                    {u.status === 'ready' && '✓ 已就绪可引用'}
                    {u.status === 'failed' && (u.error || '失败')}
                  </span>
                  <button
                    type="button"
                    onClick={() => setUploads((prev) => prev.filter((x) => x.key !== u.key))}
                    className="w-4 h-4 rounded-full flex items-center justify-center hover:bg-white transition-colors"
                    title="移除（不删除已上传文档）"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}

          <textarea
            ref={inputRef}
            value={text}
            onChange={handleInput}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
              if (e.key === 'Escape') { setShowCommands(false); setShowMention(false) }
            }}
            placeholder={isHome ? '描述你的任务或问题，或输入 @ 召唤专家…' : '继续对话，或输入 / 调用指令、@ 召唤专家…'}
            rows={2}
            disabled={loading}
            className="w-full min-h-[40px] resize-none border-none outline-none text-[13px] text-[#1a1917] leading-relaxed bg-transparent placeholder:text-[#9b9892] disabled:opacity-50"
          />

          <div className="flex items-center justify-between mt-2.5 pt-2.5 border-t border-[rgba(0,0,0,0.08)]">
            <div className="flex items-center gap-1.5">
              {/* Attachment — 常驻展示；无活动会话时禁用（上传进知识库） */}
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept={UPLOAD_ACCEPT}
                className="hidden"
                onChange={(e) => handleFiles(e.target.files)}
              />
              <button
                type="button"
                disabled={!kbEnabled}
                onClick={() => fileInputRef.current?.click()}
                className="w-[30px] h-[30px] rounded-[8px] flex items-center justify-center text-[#6b6963] hover:bg-white hover:text-[#1a1917] transition-colors disabled:text-[#c4c1ba] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                title={kbEnabled ? '上传文件到知识库（pdf/docx/md/txt，≤32MB）' : '开始会话后可上传文件'}
              >
                <PaperclipIcon />
              </button>
              {/* Voice — 功能待上线，暂禁用避免误导 */}
              <button disabled className="w-[30px] h-[30px] rounded-[8px] flex items-center justify-center text-[#c4c1ba] opacity-50 cursor-not-allowed transition-colors" title="语音（即将支持）">
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M8 1a2 2 0 0 0-2 2v4a2 2 0 0 0 4 0V3a2 2 0 0 0-2-2z"/>
                  <path d="M12 7a4 4 0 0 1-8 0"/>
                  <path d="M8 11v3"/>
                </svg>
              </button>
              {/* Expert button (home + chat) */}
              <div className="relative">
                <button
                  ref={expertBtnRef}
                  type="button"
                  onClick={() => { setShowExperts((v) => !v); setShowCommands(false); setShowMention(false) }}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-[12px] border transition-colors ${
                    showExperts || activeExpert
                      ? 'bg-[#3898EC] text-white border-[#3898EC]'
                      : 'text-gray-600 border-transparent hover:bg-white hover:border-gray-200'
                  }`}
                >
                  <span className="text-[13px] leading-none">🧠</span>
                  <span>专家</span>
                </button>
                <ExpertPickerPopover
                  open={showExperts}
                  onClose={() => setShowExperts(false)}
                  activeName={activeExpert}
                  onSelect={(name) => { onSelectExpert(name); setShowExperts(false) }}
                  experts={experts}
                  loading={expertsLoading}
                  anchorEl={expertBtnRef.current}
                />
              </div>
              {/* Skill button (home + chat; picker 兼容无会话) */}
              <SkillButton sessionId={sessionId} />
              {/* Knowledge-base binding button — 无活动会话时展示禁用态 */}
              {kbEnabled && sessionId ? (
                <KnowledgeButton sessionId={sessionId} refreshKey={kbRefreshKey} />
              ) : (
                <button
                  type="button"
                  disabled
                  className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[12px] border border-transparent text-gray-400 opacity-60 cursor-not-allowed"
                  title="开始会话后可绑定知识库"
                >
                  <span className="text-[13px] leading-none">📚</span>
                  <span>知识库</span>
                </button>
              )}
            </div>
            <button
              onClick={handleSend}
              disabled={loading || !text.trim()}
              className={`w-[34px] h-[34px] rounded-full flex items-center justify-center text-white transition-all duration-150 hover:scale-105 disabled:opacity-50 disabled:cursor-not-allowed shrink-0 btn-press ${sendPressed ? 'scale-95' : ''}`}
              style={{ background: 'linear-gradient(135deg, #B3AFFA, #9D97F6)' }}
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

// 底部工具栏的“知识库”按钮 + 绑定浮层（有绑定时高亮 + 数量徽标）
function KnowledgeButton({ sessionId, refreshKey }: { sessionId: string; refreshKey: number }) {
  const [open, setOpen] = useState(false)
  const [count, setCount] = useState(0)
  const btnRef = useRef<HTMLButtonElement>(null)

  // 回显当前绑定数；上传自动建库绑定后由 refreshKey 触发刷新
  useEffect(() => {
    let cancelled = false
    getSessionBases(sessionId)
      .then((r) => {
        if (!cancelled) setCount(r.kb_ids.length)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [sessionId, refreshKey])

  return (
    <div className="relative">
      <button
        ref={btnRef}
        onClick={() => setOpen((v) => !v)}
        className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-[12px] border transition-colors ${
          open || count > 0
            ? 'bg-[#3D7A12] text-white border-[#3D7A12]'
            : 'text-gray-600 border-transparent hover:bg-white hover:border-gray-200'
        }`}
      >
        <span className="text-[13px] leading-none">📚</span>
        <span>知识库{count > 0 ? ` ·${count}` : ''}</span>
      </button>
      <SessionKnowledgePicker
        sessionId={sessionId}
        open={open}
        anchorEl={btnRef.current}
        onClose={() => setOpen(false)}
        onSaved={(ids) => setCount(ids.length)}
      />
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
