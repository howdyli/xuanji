/**
 * MySkillsView —— 个人技能管理
 *
 * 两个 Tab：
 *   - 我发布的：列表形式，含状态标签 + 下架操作
 *   - 我收藏的：网格形式，复用 SkillCardRich + 取消收藏按钮
 */
import { useState } from 'react'
import type { MarketSkillV2 } from '../MarketplaceView'
import SkillCardRich from './SkillCardRich'

// ─── Types ──────────────────────────────────────────────────────────────
export interface MySkillsViewProps {
  authToken: string
  tab: 'published' | 'favorites'
  onTabChange: (tab: 'published' | 'favorites') => void
  mySkills: MarketSkillV2[]
  favorites: MarketSkillV2[]
  onSkillClick: (name: string) => void
  onWithdraw: (name: string) => void
  onRemoveFavorite: (name: string) => void
  loading?: boolean
}

// skill status → badge config
type SkillStatus = 'pending' | 'approved' | 'rejected' | 'suspended'

const STATUS_CFG: Record<SkillStatus, { label: string; bg: string; fg: string }> = {
  pending:   { label: '审核中', bg: 'var(--warning-50, #fefce8)',  fg: 'var(--warning-700, #a16207)' },
  approved:  { label: '已上架', bg: 'var(--success-50, #f0fdf4)',  fg: 'var(--success-700, #15803d)' },
  rejected:  { label: '已拒绝', bg: 'var(--danger-50, #fef2f2)',   fg: 'var(--danger-700, #b91c1c)' },
  suspended: { label: '已下架', bg: 'var(--gray-100, #f3f4f6)',    fg: 'var(--text-secondary, #6b7280)' },
}

// extended skill type — backend returns status in my-skills endpoint
interface MySkill extends MarketSkillV2 {
  status?: SkillStatus
}

// ─── Component ──────────────────────────────────────────────────────────
export default function MySkillsView({
  tab,
  onTabChange,
  mySkills,
  favorites,
  onSkillClick,
  onWithdraw,
  onRemoveFavorite,
  loading = false,
}: MySkillsViewProps) {
  const [confirmName, setConfirmName] = useState<string | null>(null)

  // ── Published tab ──
  const renderPublished = () => {
    if (loading) return <SkeletonList count={3} />
    if (mySkills.length === 0) {
      return (
        <EmptyState
          icon="📦"
          title="你还没有发布过技能"
          ctaLabel="发布第一个技能"
          onCta={() => {/* parent handles navigation */}}
        />
      )
    }

    return (
      <div className="divide-y" style={{ borderColor: 'var(--border-light, #e5e7eb)' }}>
        {(mySkills as MySkill[]).map(skill => {
          const status = skill.status ?? 'approved'
          const cfg = STATUS_CFG[status]
          return (
            <div
              key={skill.name}
              className="flex items-center gap-4 py-3 cursor-pointer hover:bg-gray-50/60 transition-colors px-2 rounded-lg"
              onClick={() => onSkillClick(skill.name)}
            >
              {/* Icon */}
              <div
                className="w-9 h-9 rounded-lg flex items-center justify-center text-white text-sm font-semibold shrink-0"
                style={{ background: 'linear-gradient(135deg, var(--primary-400,#60a5fa), var(--primary-600,#2563eb))' }}
              >
                {skill.name.charAt(0).toUpperCase()}
              </div>

              {/* Info */}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate" style={{ color: 'var(--text-primary, #111827)' }}>
                  {skill.name}
                </p>
                <div className="flex items-center gap-3 mt-0.5 text-xs" style={{ color: 'var(--text-tertiary, #9ca3af)' }}>
                  <span>★ {skill.rating_avg.toFixed(1)} ({skill.rating_count})</span>
                  <span>↓ {skill.install_count}</span>
                </div>
              </div>

              {/* Status badge */}
              <span
                className="px-2 py-0.5 rounded-full text-xs font-medium shrink-0"
                style={{ background: cfg.bg, color: cfg.fg }}
              >
                {cfg.label}
              </span>

              {/* Actions */}
              {status === 'approved' && (
                <div className="shrink-0" onClick={e => e.stopPropagation()}>
                  {confirmName === skill.name ? (
                    <div className="flex items-center gap-1.5">
                      <button
                        className="text-xs px-2 py-1 rounded bg-rose-500 text-white hover:bg-rose-600 transition-colors"
                        onClick={() => { onWithdraw(skill.name); setConfirmName(null) }}
                      >
                        确认下架
                      </button>
                      <button
                        className="text-xs px-2 py-1 rounded border"
                        style={{ borderColor: 'var(--border-light, #e5e7eb)', color: 'var(--text-secondary, #6b7280)' }}
                        onClick={() => setConfirmName(null)}
                      >
                        取消
                      </button>
                    </div>
                  ) : (
                    <button
                      className="text-xs px-2.5 py-1 rounded border hover:bg-gray-50 transition-colors"
                      style={{ borderColor: 'var(--border-light, #e5e7eb)', color: 'var(--text-secondary, #6b7280)' }}
                      onClick={() => setConfirmName(skill.name)}
                    >
                      下架
                    </button>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    )
  }

  // ── Favorites tab ──
  const renderFavorites = () => {
    if (loading) return <SkeletonGrid count={4} />
    if (favorites.length === 0) {
      return (
        <EmptyState
          icon="⭐"
          title="还没有收藏任何技能"
          ctaLabel="去市场看看"
          onCta={() => onTabChange('published' /* parent will route to market */)}
        />
      )
    }
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {favorites.map(skill => (
          <div key={skill.name} className="relative">
            <SkillCardRich
              skill={skill}
              onInstall={() => {}}
              onClick={onSkillClick}
            />
            {/* Remove favorite button */}
            <button
              className="absolute top-2 right-2 z-10 w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold transition-colors hover:bg-rose-100 hover:text-rose-600"
              style={{
                background: 'rgba(255,255,255,0.85)',
                color: 'var(--text-tertiary, #9ca3af)',
                border: '1px solid var(--border-light, #e5e7eb)',
              }}
              title="取消收藏"
              onClick={e => { e.stopPropagation(); onRemoveFavorite(skill.name) }}
            >×</button>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Tab switch */}
      <div className="flex items-center gap-4 border-b" style={{ borderColor: 'var(--border-light, #e5e7eb)' }}>
        {(['published', 'favorites'] as const).map(t => (
          <button
            key={t}
            onClick={() => onTabChange(t)}
            className="relative pb-2.5 text-sm transition-colors"
            style={{
              color: tab === t ? 'var(--text-primary, #111827)' : 'var(--text-secondary, #6b7280)',
              fontWeight: tab === t ? 500 : 400,
            }}
          >
            {t === 'published' ? '我发布的' : '我收藏的'}
            {tab === t && (
              <span
                className="absolute bottom-0 left-0 right-0 h-0.5 rounded-full"
                style={{ background: 'var(--primary-500, #3b82f6)' }}
              />
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      {tab === 'published' ? renderPublished() : renderFavorites()}
    </div>
  )
}

// ─── Small helpers ──────────────────────────────────────────────────────

function EmptyState({
  icon,
  title,
  ctaLabel,
  onCta,
}: {
  icon: string
  title: string
  ctaLabel: string
  onCta: () => void
}) {
  return (
    <div className="flex flex-col items-center py-16 text-center">
      <span className="text-4xl mb-3">{icon}</span>
      <p className="text-sm font-medium mb-4" style={{ color: 'var(--text-primary, #111827)' }}>
        {title}
      </p>
      <button
        onClick={onCta}
        className="px-5 py-2 rounded-lg text-sm font-medium text-white transition-colors"
        style={{ background: 'var(--primary-500, #3b82f6)' }}
        onMouseEnter={e => (e.currentTarget.style.background = 'var(--primary-600, #2563eb)')}
        onMouseLeave={e => (e.currentTarget.style.background = 'var(--primary-500, #3b82f6)')}
      >
        {ctaLabel}
      </button>
    </div>
  )
}

function SkeletonList({ count }: { count: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 py-3 animate-pulse">
          <div className="w-9 h-9 rounded-lg bg-gray-100" />
          <div className="flex-1 space-y-1.5">
            <div className="w-1/3 h-4 bg-gray-100 rounded" />
            <div className="w-1/4 h-3 bg-gray-100 rounded" />
          </div>
          <div className="w-16 h-5 bg-gray-100 rounded-full" />
        </div>
      ))}
    </div>
  )
}

function SkeletonGrid({ count }: { count: number }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="bg-white border rounded-xl p-4 animate-pulse min-h-[148px]"
          style={{ borderColor: 'var(--border-light, #e5e7eb)' }}
        >
          <div className="w-9 h-9 rounded-lg bg-gray-100 mb-2" />
          <div className="w-2/3 h-4 bg-gray-100 rounded mb-2" />
          <div className="w-full h-3 bg-gray-100 rounded mb-1.5" />
          <div className="w-4/5 h-3 bg-gray-100 rounded" />
        </div>
      ))}
    </div>
  )
}
