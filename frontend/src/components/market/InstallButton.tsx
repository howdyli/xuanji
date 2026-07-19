/**
 * InstallButton —— 带状态的安装按钮
 * idle → loading → installed，hover 时可卸载
 */
import { useState } from 'react'

interface InstallButtonProps {
  installed: boolean
  loading: boolean
  onInstall: () => void
  onUninstall?: () => void
}

export default function InstallButton({ installed, loading, onInstall, onUninstall }: InstallButtonProps) {
  const [hovered, setHovered] = useState(false)

  if (loading) {
    return (
      <button
        disabled
        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] rounded-lg bg-gray-100 text-gray-500 cursor-not-allowed"
      >
        <span className="inline-flex gap-0.5">
          {[0, 1, 2].map(i => (
            <span
              key={i}
              className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce"
              style={{ animationDelay: `${i * 0.15}s` }}
            />
          ))}
        </span>
        安装中...
      </button>
    )
  }

  if (installed) {
    const showUninstall = hovered && onUninstall
    return (
      <button
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onClick={showUninstall ? onUninstall : undefined}
        className={`inline-flex items-center gap-1 px-3 py-1.5 text-[12px] rounded-lg font-medium transition-colors ${
          showUninstall
            ? 'bg-rose-50 text-rose-600 hover:bg-rose-100'
            : ''
        }`}
        style={!showUninstall ? { backgroundColor: '#F2F0FF', color: '#7C6AF4' } : undefined}
      >
        {showUninstall ? (
          <>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
            卸载
          </>
        ) : (
          <>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="20 6 9 17 4 12" />
            </svg>
            已安装
          </>
        )}
      </button>
    )
  }

  return (
    <button
      onClick={onInstall}
      className="inline-flex items-center gap-1 px-3 py-1.5 text-[12px] rounded-lg font-medium text-white transition-colors"
      style={{ backgroundColor: '#7C6AF4' }}
      onMouseEnter={e => (e.currentTarget.style.backgroundColor = '#6B59E3')}
      onMouseLeave={e => (e.currentTarget.style.backgroundColor = '#7C6AF4')}
    >
      安装
    </button>
  )
}
