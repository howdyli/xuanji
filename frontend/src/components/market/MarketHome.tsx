/**
 * MarketHome —— 市场首页
 * 组合 HeroBanner、搜索框、CategoryTabs、排行榜、技能网格
 */
import { useState } from 'react'
import type { MarketSkillV2, Category } from '../MarketplaceView'
import HeroBanner from './HeroBanner'
import CategoryTabs from './CategoryTabs'
import SkillRankingList from './SkillRankingList'
import SkillCardRich from './SkillCardRich'

interface MarketHomeProps {
  featured: MarketSkillV2[]
  categories: Category[]
  rankings: { week: MarketSkillV2[]; month: MarketSkillV2[] }
  skills: MarketSkillV2[]
  activeCategory: string | null
  onCategoryChange: (id: string | null) => void
  onSkillClick: (name: string) => void
  onInstall: (name: string) => void
  onSearch: (query: string) => void
  loading?: boolean
}

function GridSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {Array.from({ length: 8 }).map((_, i) => (
        <div
          key={i}
          className="rounded-xl p-4 animate-pulse min-h-[180px]"
          style={{ backgroundColor: 'var(--bg-secondary, #fff)', border: '1px solid var(--border-light, #E2E8F0)' }}
        >
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg bg-gray-100" />
            <div className="w-12 h-4 rounded bg-gray-100" />
          </div>
          <div className="h-4 bg-gray-100 rounded mt-3 w-1/2" />
          <div className="h-3 bg-gray-100 rounded mt-3 w-full" />
          <div className="h-3 bg-gray-100 rounded mt-1.5 w-4/5" />
        </div>
      ))}
    </div>
  )
}

export default function MarketHome({
  featured, categories, rankings, skills,
  activeCategory, onCategoryChange, onSkillClick, onInstall, onSearch, loading,
}: MarketHomeProps) {
  const [searchInput, setSearchInput] = useState('')
  const [period, setPeriod] = useState<'week' | 'month'>('week')

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && searchInput.trim()) {
      onSearch(searchInput.trim())
    }
  }

  const currentRankings = rankings[period] ?? []

  return (
    <div className="space-y-6">
      {/* HeroBanner */}
      <HeroBanner featured={featured} onSkillClick={onSkillClick} />

      {/* Search bar */}
      <div className="flex items-center gap-2 max-w-xl mx-auto">
        <div
          className="flex-1 flex items-center gap-2 px-3.5 py-2 rounded-xl border"
          style={{
            backgroundColor: 'var(--bg-secondary, #fff)',
            borderColor: 'var(--border-light, #E2E8F0)',
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" style={{ color: 'var(--text-tertiary, #94A3B8)' }}>
            <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            type="text"
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="搜索技能名称、描述..."
            className="flex-1 text-[13px] bg-transparent outline-none"
            style={{ color: 'var(--text-primary, #1E293B)' }}
          />
        </div>
        <button
          onClick={() => searchInput.trim() && onSearch(searchInput.trim())}
          className="px-4 py-2 rounded-xl text-[13px] font-medium text-white transition-colors"
          style={{ backgroundColor: 'var(--primary-500, #3B82F6)' }}
        >
          搜索
        </button>
      </div>

      {/* Category tabs */}
      <CategoryTabs categories={categories} active={activeCategory} onChange={onCategoryChange} />

      {/* Main content: ranking + grid */}
      {loading ? (
        <GridSkeleton />
      ) : (
        <div className="flex flex-col lg:flex-row gap-6">
          {/* Ranking sidebar (desktop) */}
          <aside className="hidden lg:block w-[280px] shrink-0">
            <SkillRankingList
              skills={currentRankings}
              period={period}
              onPeriodChange={setPeriod}
              onSkillClick={onSkillClick}
            />
          </aside>

          {/* Mobile: ranking above grid */}
          <div className="lg:hidden">
            <SkillRankingList
              skills={currentRankings}
              period={period}
              onPeriodChange={setPeriod}
              onSkillClick={onSkillClick}
            />
          </div>

          {/* Skills grid */}
          <div className="flex-1 min-w-0">
            {skills.length === 0 ? (
              <div className="text-center py-16">
                <p className="text-[14px] font-medium" style={{ color: 'var(--text-primary, #1E293B)' }}>
                  暂无技能
                </p>
                <p className="text-[12.5px] mt-1" style={{ color: 'var(--text-secondary, #475569)' }}>
                  {activeCategory ? '该分类下暂无技能，试试其他分类' : '技能市场即将上线，敬请期待'}
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                {skills.map(s => (
                  <SkillCardRich
                    key={s.name}
                    skill={s}
                    onInstall={onInstall}
                    onClick={onSkillClick}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
