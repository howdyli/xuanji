/**
 * CategoryTabs —— 横向可滚动分类标签条
 * 左侧固定"全部"标签，分类标签可横向滚动
 */
import { useRef } from 'react'
import type { Category } from '../MarketplaceView'

interface CategoryTabsProps {
  categories: Category[]
  active: string | null
  onChange: (categoryId: string | null) => void
}

export default function CategoryTabs({ categories, active, onChange }: CategoryTabsProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  const sorted = [...categories].sort((a, b) => a.sort_order - b.sort_order)

  const isActive = (id: string | null) => active === id

  const tabCls = (id: string | null) =>
    `shrink-0 inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-[13px] font-medium whitespace-nowrap transition-colors scroll-snap-align-start ${
      isActive(id)
        ? 'text-white'
        : 'hover:bg-gray-100'
    }`

  const tabStyle = (id: string | null): React.CSSProperties =>
    isActive(id)
      ? { backgroundColor: 'var(--primary-500, #3B82F6)', color: 'var(--text-inverse, #fff)' }
      : { backgroundColor: 'transparent', color: 'var(--text-secondary, #475569)' }

  return (
    <div
      ref={scrollRef}
      className="flex items-center gap-2 overflow-x-auto pb-1"
      style={{ scrollSnapType: 'x mandatory', scrollbarWidth: 'none' }}
    >
      {/* 全部 */}
      <button
        onClick={() => onChange(null)}
        className={tabCls(null)}
        style={tabStyle(null)}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" />
          <rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" />
        </svg>
        全部
      </button>

      {sorted.map(cat => (
        <button
          key={cat.id}
          onClick={() => onChange(cat.id)}
          className={tabCls(cat.id)}
          style={tabStyle(cat.id)}
        >
          {cat.icon && <span className="text-sm">{cat.icon}</span>}
          {cat.name}
        </button>
      ))}
    </div>
  )
}
