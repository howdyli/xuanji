/**
 * FilterSidebar —— 搜索筛选侧栏
 * 排序方式 / 分类 / 来源 / 最低评分 / 重置
 * Desktop (≥lg): 固定 240px 侧栏
 * Mobile (<lg): 折叠下拉面板
 *
 * 样式约定（见 docs/frontend-style-convention.md）：
 * 全部走 Tailwind 工具类；设计令牌用任意值 `[color:var(--token,fallback)]` 引用；
 * 条件/动态样式用条件 className，不使用内联 style。
 */
import { useState } from 'react'
import type { FilterState, Category } from '../MarketplaceView'
import RatingStars from './RatingStars'

interface FilterSidebarProps {
  filters: FilterState
  onChange: (filters: FilterState) => void
  categories: Category[]
  onClear: () => void
}

const SORT_OPTIONS: { value: FilterState['sortBy']; label: string }[] = [
  { value: 'popular', label: '热门' },
  { value: 'newest', label: '最新' },
  { value: 'rating', label: '评分最高' },
  { value: 'name', label: '名称 A-Z' },
]

const SOURCE_OPTIONS = [
  { value: 'community', label: '社区' },
  { value: 'vercel', label: 'Vercel' },
  { value: 'clawhub', label: 'ClawHub' },
]

const ROW_BASE =
  'flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer text-[13px] transition-colors hover:bg-gray-50'

function SectionDivider() {
  return <div className="border-t border-[color:var(--border-light,#E2E8F0)]" />
}

function SidebarContent({ filters, onChange, categories, onClear }: FilterSidebarProps) {
  const sorted = [...categories].sort((a, b) => a.sort_order - b.sort_order)

  const toggleSource = (src: string) => {
    const next = filters.source.includes(src)
      ? filters.source.filter(s => s !== src)
      : [...filters.source, src]
    onChange({ ...filters, source: next })
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Sort */}
      <div>
        <h4 className="text-[11px] font-semibold uppercase tracking-wide mb-2 text-[color:var(--text-tertiary,#94A3B8)]">
          排序方式
        </h4>
        <div className="flex flex-col gap-1">
          {SORT_OPTIONS.map(opt => (
            <label
              key={opt.value}
              className={`${ROW_BASE} ${filters.sortBy === opt.value ? 'text-[color:var(--primary-600,#2563EB)]' : 'text-[color:var(--text-secondary,#475569)]'}`}
            >
              <input
                type="radio"
                name="sortBy"
                checked={filters.sortBy === opt.value}
                onChange={() => onChange({ ...filters, sortBy: opt.value })}
                className="accent-blue-500 w-3.5 h-3.5"
              />
              <span className="font-medium">{opt.label}</span>
            </label>
          ))}
        </div>
      </div>

      <SectionDivider />

      {/* Category */}
      <div>
        <h4 className="text-[11px] font-semibold uppercase tracking-wide mb-2 text-[color:var(--text-tertiary,#94A3B8)]">
          分类
        </h4>
        <div className="flex flex-col gap-1 max-h-48 overflow-y-auto">
          <label
            className={`${ROW_BASE} ${filters.category === null ? 'text-[color:var(--primary-600,#2563EB)]' : 'text-[color:var(--text-secondary,#475569)]'}`}
          >
            <input
              type="radio"
              name="category"
              checked={filters.category === null}
              onChange={() => onChange({ ...filters, category: null })}
              className="accent-blue-500 w-3.5 h-3.5"
            />
            <span className="font-medium">全部分类</span>
          </label>
          {sorted.map(cat => (
            <label
              key={cat.id}
              className={`${ROW_BASE} ${filters.category === cat.id ? 'text-[color:var(--primary-600,#2563EB)]' : 'text-[color:var(--text-secondary,#475569)]'}`}
            >
              <input
                type="radio"
                name="category"
                checked={filters.category === cat.id}
                onChange={() => onChange({ ...filters, category: cat.id })}
                className="accent-blue-500 w-3.5 h-3.5"
              />
              {cat.icon && <span className="text-sm">{cat.icon}</span>}
              <span className="font-medium truncate">{cat.name}</span>
            </label>
          ))}
        </div>
      </div>

      <SectionDivider />

      {/* Source */}
      <div>
        <h4 className="text-[11px] font-semibold uppercase tracking-wide mb-2 text-[color:var(--text-tertiary,#94A3B8)]">
          来源
        </h4>
        <div className="flex flex-col gap-1">
          {SOURCE_OPTIONS.map(src => (
            <label
              key={src.value}
              className={`${ROW_BASE} text-[color:var(--text-secondary,#475569)]`}
            >
              <input
                type="checkbox"
                checked={filters.source.includes(src.value)}
                onChange={() => toggleSource(src.value)}
                className="accent-blue-500 w-3.5 h-3.5 rounded"
              />
              <span className="font-medium">{src.label}</span>
            </label>
          ))}
        </div>
      </div>

      <SectionDivider />

      {/* Min rating */}
      <div>
        <h4 className="text-[11px] font-semibold uppercase tracking-wide mb-2 text-[color:var(--text-tertiary,#94A3B8)]">
          最低评分
        </h4>
        <div className="px-2">
          <RatingStars
            value={filters.minRating}
            readonly={false}
            onChange={(r: number) => onChange({ ...filters, minRating: r === filters.minRating ? 0 : r })}
            size="md"
          />
          {filters.minRating > 0 && (
            <span className="ml-2 text-[11px] text-[color:var(--text-tertiary,#94A3B8)]">
              {filters.minRating}+ 星
            </span>
          )}
        </div>
      </div>

      <SectionDivider />

      {/* Reset */}
      <button
        onClick={onClear}
        className="text-[13px] font-medium py-1.5 px-2 rounded-md transition-colors hover:bg-gray-50 text-left text-[color:var(--error-500,#EF4444)]"
      >
        重置筛选
      </button>
    </div>
  )
}

export default function FilterSidebar(props: FilterSidebarProps) {
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <>
      {/* Mobile: toggle button + collapsible panel */}
      <div className="lg:hidden">
        <button
          onClick={() => setMobileOpen(v => !v)}
          className="flex items-center gap-2 px-3 py-2 rounded-lg border text-[13px] font-medium transition-colors border-[color:var(--border-light,#E2E8F0)] bg-[var(--bg-secondary,#fff)] text-[color:var(--text-secondary,#475569)]"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="4" y1="6" x2="20" y2="6" />
            <line x1="4" y1="12" x2="16" y2="12" />
            <line x1="4" y1="18" x2="12" y2="18" />
          </svg>
          筛选
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            className={`transition-transform duration-150 ${mobileOpen ? 'rotate-180' : 'rotate-0'}`}
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>

        {mobileOpen && (
          <div className="mt-2 p-4 rounded-xl border bg-[var(--bg-secondary,#fff)] border-[color:var(--border-light,#E2E8F0)]">
            <SidebarContent {...props} />
          </div>
        )}
      </div>

      {/* Desktop: fixed 240px sidebar */}
      <aside className="hidden lg:block w-[240px] shrink-0 p-4 rounded-xl border border-[color:var(--border-light,#E2E8F0)] bg-[var(--bg-secondary,#fff)]">
        <SidebarContent {...props} />
      </aside>
    </>
  )
}
