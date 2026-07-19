/**
 * ViewToggle —— 网格/列表视图切换按钮组
 */

interface ViewToggleProps {
  mode: 'grid' | 'list'
  onChange: (mode: 'grid' | 'list') => void
}

const GridIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" />
    <rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" />
  </svg>
)

const ListIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" />
    <line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" />
  </svg>
)

export default function ViewToggle({ mode, onChange }: ViewToggleProps) {
  const btn = (m: 'grid' | 'list', Icon: React.FC) => (
    <button
      key={m}
      onClick={() => onChange(m)}
      className={`p-1.5 rounded-md transition-colors ${
        mode === m
          ? 'bg-gray-100 text-gray-900'
          : 'text-gray-400 hover:text-gray-600 hover:bg-gray-50'
      }`}
      title={m === 'grid' ? '网格视图' : '列表视图'}
    >
      <Icon />
    </button>
  )

  return (
    <div className="inline-flex items-center gap-0.5 border rounded-lg p-0.5" style={{ borderColor: 'var(--border-light, #E2E8F0)' }}>
      {btn('grid', GridIcon)}
      {btn('list', ListIcon)}
    </div>
  )
}
