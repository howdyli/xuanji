/**
 * SearchBar —— 增强搜索栏组件
 * 280ms 防抖、Ctrl+K 快捷键聚焦、清除按钮
 */
import { useEffect, useRef } from 'react'

interface SearchBarProps {
  value: string
  onChange: (value: string) => void
  onSearch: (query: string) => void
  placeholder?: string
  autoFocus?: boolean
}

export default function SearchBar({
  value,
  onChange,
  onSearch,
  placeholder = '搜索技能...',
  autoFocus = false,
}: SearchBarProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 280ms debounce → auto-trigger onSearch
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      if (value.trim()) onSearch(value.trim())
    }, 280)
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [value]) // eslint-disable-line react-hooks/exhaustive-deps

  // Ctrl+K / Cmd+K shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && value.trim()) {
      if (timerRef.current) clearTimeout(timerRef.current)
      onSearch(value.trim())
    }
  }

  const handleClear = () => {
    onChange('')
    inputRef.current?.focus()
  }

  return (
    <div
      className="flex items-center gap-2 px-3.5 py-2 rounded-xl border transition-all"
      style={{
        backgroundColor: 'var(--bg-secondary, #fff)',
        borderColor: 'var(--border-light, #E2E8F0)',
      }}
      onFocus={e =>
        ((e.currentTarget as HTMLDivElement).style.borderColor = 'var(--primary-500, #3B82F6)')
      }
      onBlur={e =>
        ((e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border-light, #E2E8F0)')
      }
    >
      {/* Search icon */}
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        className="shrink-0"
        style={{ color: 'var(--text-tertiary, #94A3B8)' }}
      >
        <circle cx="11" cy="11" r="8" />
        <line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>

      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        autoFocus={autoFocus}
        className="flex-1 min-w-0 text-[13px] bg-transparent outline-none"
        style={{ color: 'var(--text-primary, #1E293B)' }}
      />

      {/* Clear button */}
      {value && (
        <button
          onClick={handleClear}
          className="shrink-0 w-5 h-5 flex items-center justify-center rounded-full transition-colors hover:bg-gray-200"
          style={{ color: 'var(--text-tertiary, #94A3B8)' }}
          aria-label="清除搜索"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      )}

      {/* Ctrl+K hint */}
      {!value && (
        <kbd
          className="hidden sm:inline-flex items-center px-1.5 py-0.5 text-[10px] font-mono rounded border shrink-0"
          style={{
            color: 'var(--text-tertiary, #94A3B8)',
            borderColor: 'var(--border-light, #E2E8F0)',
            backgroundColor: 'var(--bg-tertiary, #F1F5F9)',
          }}
        >
          ⌘K
        </kbd>
      )}
    </div>
  )
}
