// --- Chat view: message list, bubbles, banners (content only, no input area) ---
import { useState, useEffect, useRef } from 'react'
import type { Message } from '../types'
import { MarkdownRenderer } from './MarkdownRenderer'
import AgentTimeline from './AgentTimeline'
import { LoadingStates, ErrorDisplay } from './UXComponents'
import { downloadFile } from '../api/client'

// --- Session Context Bar (shown above messages in chat mode) ---
function SessionContextBar({
  title,
  running,
  onOpenDrawer,
}: {
  title: string
  running: boolean
  onOpenDrawer: () => void
}) {
  return (
    <div className="shrink-0 border-b border-[rgba(0,0,0,0.08)] px-5 py-2 flex items-center gap-3 animate-fade-in" style={{ minHeight: 44, background: 'var(--bg-tertiary)' }}>
      <span className="text-[12px] font-medium text-[#1a1917] flex items-center gap-1.5">
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2 3h8v7H2z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/><path d="M4 1v2M8 1v2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/></svg>
        {title || '新任务'}
      </span>
      {running ? (
        <span className="text-[10px] text-[#2d9e6b] flex items-center gap-1">
          <span className="w-[5px] h-[5px] bg-[#2d9e6b] rounded-full" />进行中
        </span>
      ) : (
        <span className="text-[10px] text-[#8a8884] flex items-center gap-1">
          <span className="w-[5px] h-[5px] bg-[#8a8884] rounded-full" />已完成
        </span>
      )}
      <button
        onClick={onOpenDrawer}
        className="ml-auto text-[10px] flex items-center gap-1 px-2 py-0.5 rounded-full hover:opacity-80 transition-colors"
        style={{ color: '#4F6EF7', background: 'rgba(79,110,247,0.1)' }}
      >
        灵享妙语 Pro
      </button>
    </div>
  )
}

// ── file path link rendering ────────────────────────────────────────────────
// Matches /workspace/ paths ending with file extensions (.pptx, .docx, .js, .md, etc.)
// Uses lazy quantifier + extension check to stop before trailing text like `（约13KB）
const FILE_PATH_RE = /(\/workspace\/[^\s<>"'`]+?\.[a-zA-Z0-9]{2,5})/g;

// --- Summary Banner (shown when messages > 10) ---
function SummaryBanner({ messages }: { messages: Message[] }) {
  const [expanded, setExpanded] = useState(false)
  const assistantMsgs = messages.filter(m => m.role === 'assistant')
  const fileCount = assistantMsgs.filter(m => FILE_PATH_RE.test(m.content)).length
  const taskCount = Math.max(1, Math.floor(assistantMsgs.length / 3))

  if (messages.length <= 10) return null

  return (
    <div className="mx-auto w-full px-4 sm:px-6 lg:px-8 xl:px-12 pt-3">
      <div className="border rounded-[10px] p-3 animate-fade-in" style={{ background: 'rgba(79, 110, 247, 0.1)', borderColor: 'rgba(79, 110, 247, 0.15)' }}>
        <p className="text-[12px]" style={{ color: '#4F6EF7' }}>
          📝 本次会话已完成约 <strong>{taskCount}</strong> 项任务{fileCount > 0 && <>，生成 <strong>{fileCount}</strong> 份文档</>}
        </p>
        <button onClick={() => setExpanded(!expanded)} className="text-[11px] mt-1 hover:underline" style={{ color: '#4F6EF7' }}>
          {expanded ? '收起摘要 ↑' : '查看详细摘要 →'}
        </button>
        {expanded && (
          <div className="mt-2 pt-2 border-t space-y-1" style={{ borderColor: 'rgba(79, 110, 247, 0.15)' }}>
            {assistantMsgs.slice(0, 5).map((m, i) => (
              <div key={m.id} className="text-[11px] text-[#6b6963] truncate">{i + 1}. {m.content.slice(0, 60)}…</div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function renderContent(content: string): React.ReactNode {
  const parts = content.split(FILE_PATH_RE);
  if (parts.length === 1) {
    return content; // No file paths — plain text
  }
  return parts.map((part, i) => {
    if (part.startsWith('/workspace/')) {
      const filename = part.split('/').pop() || part;
      // 裸 <a href> 不携带 Authorization 头会被 401 拒绝，改用 downloadFile 下载
      return (
        <a
          key={i}
          href="#"
          className="text-blue-600 underline hover:text-blue-800"
          onClick={e => {
            e.preventDefault();
            downloadFile(part, filename).catch(err => console.error('chat file download failed:', err));
          }}
        >
          {filename}
        </a>
      );
    }
    return part;
  });
}

// ── Collapsible content wrapper ──────────────────────────────────────────────
const COLLAPSE_THRESHOLD = 480 // px — roughly 20 lines of content

function CollapsibleBubble({ children, isUser }: { children: React.ReactNode; isUser: boolean }) {
  const contentRef = useRef<HTMLDivElement>(null)
  const [collapsed, setCollapsed] = useState(!isUser)
  const [overflows, setOverflows] = useState(false)

  useEffect(() => {
    if (!isUser && contentRef.current) {
      const h = contentRef.current.scrollHeight
      setOverflows(h > COLLAPSE_THRESHOLD)
      if (h <= COLLAPSE_THRESHOLD) setCollapsed(false)
    }
  }, [isUser])

  return (
    <div className="relative">
      <div
        ref={contentRef}
        className={overflows && collapsed ? 'max-h-[480px] overflow-hidden' : ''}
      >
        {children}
      </div>
      {overflows && collapsed && (
        <div className="absolute bottom-0 left-0 right-0 h-16 bg-gradient-to-t from-[var(--bg-bubble-assistant)] to-transparent pointer-events-none" />
      )}
      {overflows && (
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="mt-1.5 text-[12px] text-[#4F6EF7] font-medium hover:underline"
        >
          {collapsed ? '展开完整内容 ↓' : '收起内容 ↑'}
        </button>
      )}
    </div>
  )
}

// ── Message bubble ───────────────────────────────────────────────────────────
function MessageBubble({ msg, sessionId, authToken, onRetry }: { msg: Message; sessionId: string | null; authToken: string; onRetry?: () => void }) {
  const isUser = msg.role === 'user'

  // ✅ P1 集成：解析错误显示标记
  const errorMatch = !isUser && /^\[ERROR_DISPLAY:([\w_]+):(.+)\]$/.exec(msg.content)
  if (errorMatch) {
    const [, errorType, errorMessage] = errorMatch
    return (
      <div className="flex gap-3">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-[10px] font-bold shrink-0 bg-gradient-to-br from-blue-400 to-blue-600">
          玄
        </div>
        <div className="max-w-[80%] items-start flex flex-col">
          <ErrorDisplay
            errorType={errorType as any}
            customMessage="请求失败"
            onRetry={onRetry}
            showDetails={true}
            details={errorMessage}
          />
        </div>
      </div>
    )
  }

  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      {!isUser && (
        <div style={{
          width: 24,
          height: 24,
          borderRadius: 6,
          background: 'linear-gradient(135deg, #4F6EF7, #7C5CFC)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          marginRight: 8,
        }}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
            <line x1="5" y1="7" x2="19" y2="7" stroke="white" strokeWidth="2.5" strokeLinecap="round"/>
            <line x1="5" y1="12" x2="19" y2="12" stroke="white" strokeWidth="2.5" strokeLinecap="round"/>
            <line x1="5" y1="17" x2="19" y2="17" stroke="white" strokeWidth="2.5" strokeLinecap="round"/>
            <line x1="12" y1="4" x2="12" y2="20" stroke="white" strokeWidth="2.5" strokeLinecap="round"/>
          </svg>
        </div>
      )}
      {isUser && (
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-[10px] font-bold shrink-0"
          style={{ background: 'linear-gradient(135deg, #4F6EF7, #6366F1)' }}
        >
          我
        </div>
      )}
      <div className={`max-w-[80%] ${isUser ? 'items-end' : 'items-start'} flex flex-col`}>
        <div
          className={`rounded-2xl px-4 py-2.5 text-[13.5px] ${
            isUser
              ? 'msg-bubble-user text-white rounded-tr-sm leading-relaxed whitespace-pre-wrap'
              : 'bg-[var(--bg-bubble-assistant)] text-[var(--text-bubble-assistant)] border t-border-primary rounded-tl-sm shadow-sm msg-bubble-ai'
          }`}
        >
          {isUser ? (
            renderContent(msg.content)
          ) : (
            <CollapsibleBubble isUser={false}>
              <MarkdownRenderer content={msg.content} />
            </CollapsibleBubble>
          )}
        </div>
        <span className="text-[10px] t-text-tertiary mt-1">
          {new Date(msg.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
        </span>
        {/* AgentTimeline 历史模式：assistant 消息嵌入折叠时间线 */}
        {!isUser && msg.id && sessionId && (
          <div className="mt-2 w-full">
            <AgentTimeline
              sessionId={sessionId}
              turnId={msg.id}
              isPolling={false}
              authToken={authToken}
            />
          </div>
        )}
      </div>
    </div>
  )
}

// --- Chat Messages (content only, no input area) ---
export function ChatMessages({
  messages,
  loading,
  sessionTitle,
  onOpenDrawer,
  sessionId,
  authToken,
}: {
  messages: Message[]
  loading: boolean
  sessionTitle: string
  onOpenDrawer: () => void
  sessionId: string | null
  authToken: string
}) {
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  return (
    <>
      <SessionContextBar title={sessionTitle} running={loading} onOpenDrawer={onOpenDrawer} />
      <SummaryBanner messages={messages} />

      {/* AgentTimeline 实时模式：loading 期间显示多 Agent 协作过程 */}
      {loading && (
        <div className="mx-auto w-full px-4 sm:px-6 lg:px-8 xl:px-12 pt-2">
          <AgentTimeline sessionId={sessionId} isPolling={loading} authToken={authToken} />
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-4 sm:px-6 lg:px-8 xl:px-12 py-4 sm:py-6">
        <div className="w-full mx-auto space-y-4 sm:space-y-5">
          {messages.map((msg) => (
            <div key={msg.id} className={msg.role === 'assistant' ? 'msg-slide-in' : ''}>
            <MessageBubble msg={msg} sessionId={sessionId} authToken={authToken} onRetry={() => {}} />
            </div>
          ))}
          {loading && (
            <div className="flex gap-3 animate-fade-in">
              <div className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-[10px] font-bold shrink-0" style={{ background: 'linear-gradient(135deg, #4F6EF7, #7C5CFC)' }}>
                玄
              </div>
              {/* ✅ P1 集成：使用 LoadingStates dots 变体替换简单文本 */}
              <div className="bg-white border border-[rgba(0,0,0,0.08)] rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm msg-bubble-ai min-w-[200px]">
                <LoadingStates variant="dots" size="sm" text="思考中..." />
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>
    </>
  )
}
