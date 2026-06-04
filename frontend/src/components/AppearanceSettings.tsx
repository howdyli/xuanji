import { useTheme, SPECIAL_THEMES, MD_FONT_SIZES, type ThemeMode, type MdFontSize } from './ThemeContext'

// ── Icons ──────────────────────────────────────────────────────────

const CloseIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
)

const CheckIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20 6 9 17 4 12" />
  </svg>
)

// ── Theme mode tabs ────────────────────────────────────────────────

const MODE_OPTIONS: { id: ThemeMode; label: string; preview: string }[] = [
  { id: 'light', label: '浅色', preview: 'linear-gradient(135deg, #ffffff 50%, #f3f4f6 50%)' },
  { id: 'dark', label: '深色', preview: 'linear-gradient(135deg, #1f2937 50%, #111827 50%)' },
  { id: 'system', label: '跟随系统', preview: 'linear-gradient(135deg, #ffffff 50%, #1f2937 50%)' },
  { id: 'special', label: '特殊风格', preview: 'linear-gradient(135deg, #b8dff5 0%, #7ec8e3 50%, #4a9cc7 100%)' },
]

// ── Font size options ──────────────────────────────────────────────

const FONT_SIZE_OPTIONS: { id: MdFontSize; label: string }[] = [
  { id: 'small', label: '小' },
  { id: 'medium', label: '中' },
  { id: 'large', label: '大' },
]

// ── Component ──────────────────────────────────────────────────────

export function AppearanceSettings({ onClose }: { onClose: () => void }) {
  const { mode, setMode, specialThemeId, setSpecialTheme, mdFontSize, setMdFontSize } = useTheme()

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-[640px] max-h-[85vh] bg-white rounded-2xl shadow-2xl border border-gray-200/80 overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 shrink-0">
          <h2 className="text-[16px] font-semibold text-gray-800">外观设置</h2>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
          >
            <CloseIcon />
          </button>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-7">

          {/* ── Theme mode ──────────────────────────────────────── */}
          <section>
            <div className="mb-1 text-[14px] font-medium text-gray-800">主题模式</div>
            <div className="text-[12px] text-gray-400 mb-3">自定义应用的视觉风格</div>
            <div className="flex items-center gap-1 bg-gray-100 rounded-xl p-1">
              {MODE_OPTIONS.map((opt) => (
                <button
                  key={opt.id}
                  onClick={() => setMode(opt.id)}
                  className={`flex-1 flex items-center gap-2 px-3 py-2 rounded-lg text-[13px] font-medium transition-all ${
                    mode === opt.id
                      ? 'bg-white text-gray-900 shadow-sm'
                      : 'text-gray-500 hover:text-gray-700'
                  }`}
                >
                  <span className="w-4 h-4 rounded-full border border-gray-200 shrink-0" style={{ background: opt.preview }} />
                  {opt.label}
                </button>
              ))}
            </div>
          </section>

          {/* ── Special themes ──────────────────────────────────── */}
          {mode === 'special' && (
            <section>
              <div className="mb-1 text-[14px] font-medium text-gray-800">特殊风格</div>
              <div className="text-[12px] text-gray-400 mb-3">选择你喜欢的视觉主题</div>
              <div className="grid grid-cols-3 gap-3">
                {SPECIAL_THEMES.map((theme) => {
                  const isActive = specialThemeId === theme.id
                  const isDark = ['sky-twilight', 'forest-night', 'morandi-night'].includes(theme.id)
                  return (
                    <button
                      key={theme.id}
                      onClick={() => setSpecialTheme(theme.id)}
                      className={`group relative rounded-xl overflow-hidden border-2 transition-all ${
                        isActive ? 'border-blue-500 shadow-md' : 'border-transparent hover:border-gray-300'
                      }`}
                    >
                      {/* Preview */}
                      <div
                        className="h-[100px] w-full"
                        style={{ background: theme.preview }}
                      >
                        {/* Decorative elements */}
                        <ThemePreviewDecor id={theme.id} />
                      </div>
                      {/* Label */}
                      <div className={`px-3 py-2 text-center text-[12px] font-medium ${
                        isDark ? 'bg-gray-900 text-gray-300' : 'bg-gray-50 text-gray-700'
                      }`}>
                        {theme.name}
                      </div>
                      {/* Active checkmark */}
                      {isActive && (
                        <div className="absolute top-2 right-2 w-5 h-5 rounded-full bg-blue-500 flex items-center justify-center shadow">
                          <CheckIcon />
                        </div>
                      )}
                    </button>
                  )
                })}
              </div>
            </section>
          )}

          {/* ── Markdown font size ──────────────────────────────── */}
          <section>
            <div className="mb-1 text-[14px] font-medium text-gray-800">Markdown 字号</div>
            <div className="text-[12px] text-gray-400 mb-3">调整 AI 回复与 Markdown 编辑器的正文字号</div>
            <div className="flex items-center gap-2">
              {FONT_SIZE_OPTIONS.map((opt) => (
                <button
                  key={opt.id}
                  onClick={() => setMdFontSize(opt.id)}
                  className={`px-5 py-2 rounded-lg text-[13px] font-medium transition-all border ${
                    mdFontSize === opt.id
                      ? 'bg-gray-900 text-white border-gray-900'
                      : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            {/* Live preview */}
            <div className="mt-3 px-4 py-3 rounded-lg bg-gray-50 border border-gray-200">
              <span className="text-gray-700" style={{ fontSize: MD_FONT_SIZES[mdFontSize] }}>
                玄机是您的 AI 工作助手，可以帮您完成文档处理、数据分析、代码开发等任务。
              </span>
            </div>
          </section>

          {/* ── Keyboard zoom hint ──────────────────────────────── */}
          <section>
            <div className="mb-1 text-[14px] font-medium text-gray-800">界面缩放</div>
            <div className="text-[12px] text-gray-400">
              使用 <kbd className="px-1.5 py-0.5 bg-gray-100 rounded text-[11px] font-mono border border-gray-200">⌘+</kbd> 放大、
              <kbd className="px-1.5 py-0.5 bg-gray-100 rounded text-[11px] font-mono border border-gray-200 ml-1">⌘-</kbd> 缩小、
              <kbd className="px-1.5 py-0.5 bg-gray-100 rounded text-[11px] font-mono border border-gray-200 ml-1">⌘0</kbd> 恢复默认大小
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

// ── Decorative SVG elements for theme preview cards ────────────────

function ThemePreviewDecor({ id }: { id: string }) {
  switch (id) {
    case 'cloud-dancer':
      return (
        <svg viewBox="0 0 200 100" className="w-full h-full opacity-30" fill="currentColor">
          {/* Cloud shapes */}
          <ellipse cx="50" cy="50" rx="30" ry="15" fill="white" />
          <ellipse cx="70" cy="45" rx="20" ry="12" fill="white" />
          <ellipse cx="140" cy="60" rx="25" ry="13" fill="white" />
          <ellipse cx="160" cy="55" rx="18" ry="10" fill="white" />
          {/* Crescent moon */}
          <circle cx="170" cy="25" r="12" fill="white" opacity="0.5" />
          <circle cx="175" cy="20" r="10" fill="transparent" />
        </svg>
      )
    case 'clear-sky':
      return (
        <svg viewBox="0 0 200 100" className="w-full h-full opacity-20" fill="none" stroke="white" strokeWidth="1">
          {/* Wave patterns */}
          <path d="M0 70 Q25 55 50 70 T100 70 T150 70 T200 70" />
          <path d="M0 80 Q25 65 50 80 T100 80 T150 80 T200 80" />
          <path d="M0 60 Q25 45 50 60 T100 60 T150 60 T200 60" />
          {/* Cloud puffs */}
          <ellipse cx="40" cy="25" rx="20" ry="10" fill="white" opacity="0.3" />
          <ellipse cx="150" cy="20" rx="15" ry="8" fill="white" opacity="0.3" />
        </svg>
      )
    case 'forest-morning':
      return (
        <svg viewBox="0 0 200 100" className="w-full h-full opacity-25" fill="none" stroke="white" strokeWidth="1.5">
          {/* Tree trunks */}
          <line x1="30" y1="10" x2="30" y2="100" />
          <line x1="70" y1="5" x2="70" y2="100" />
          <line x1="110" y1="15" x2="110" y2="100" />
          <line x1="150" y1="8" x2="150" y2="100" />
          <line x1="180" y1="12" x2="180" y2="100" />
          {/* Small cabin */}
          <rect x="85" y="70" width="15" height="12" fill="white" opacity="0.3" />
          <path d="M83 70 L92.5 62 L102 70" />
        </svg>
      )
    case 'sky-twilight':
      return (
        <svg viewBox="0 0 200 100" className="w-full h-full opacity-20" fill="none" stroke="white" strokeWidth="1">
          {/* Mountains */}
          <path d="M0 100 L40 40 L80 100" />
          <path d="M60 100 L120 30 L180 100" />
          {/* House silhouettes */}
          <rect x="100" y="75" width="12" height="15" fill="white" opacity="0.2" />
          <path d="M98 75 L106 68 L114 75" fill="white" opacity="0.2" />
          {/* Stars */}
          <circle cx="30" cy="20" r="1.5" fill="white" opacity="0.6" />
          <circle cx="160" cy="15" r="1" fill="white" opacity="0.5" />
          <circle cx="90" cy="10" r="1.5" fill="white" opacity="0.4" />
          {/* Crescent moon */}
          <circle cx="170" cy="22" r="8" fill="white" opacity="0.15" />
        </svg>
      )
    case 'forest-night':
      return (
        <svg viewBox="0 0 200 100" className="w-full h-full opacity-15" fill="none" stroke="#8fbc8f" strokeWidth="1.2">
          {/* Dense trees */}
          <path d="M20 100 L20 30 M15 50 L20 30 L25 50" />
          <path d="M50 100 L50 25 M42 55 L50 25 L58 55" />
          <path d="M80 100 L80 35 M74 58 L80 35 L86 58" />
          <path d="M120 100 L120 28 M113 52 L120 28 L127 52" />
          <path d="M160 100 L160 32 M154 56 L160 32 L166 56" />
          {/* Building silhouette */}
          <rect x="135" y="72" width="18" height="28" fill="#8fbc8f" opacity="0.1" />
        </svg>
      )
    case 'morandi-night':
      return (
        <svg viewBox="0 0 200 100" className="w-full h-full opacity-20" fill="none" stroke="#b0a8a0" strokeWidth="1.2">
          {/* Still life — vase */}
          <path d="M60 85 Q55 60 65 45 Q70 40 75 45 Q85 60 80 85 Z" fill="#b0a8a0" opacity="0.15" />
          {/* Bottle */}
          <rect x="110" y="50" width="10" height="35" rx="3" fill="#b0a8a0" opacity="0.15" />
          <rect x="112" y="42" width="6" height="10" rx="2" />
          {/* Cup */}
          <path d="M150 70 L145 85 L165 85 L160 70 Z" fill="#b0a8a0" opacity="0.12" />
          {/* Crescent */}
          <circle cx="40" cy="25" r="10" fill="#b0a8a0" opacity="0.15" />
          <circle cx="45" cy="20" r="8" fill="transparent" />
        </svg>
      )
    default:
      return null
  }
}
