/**
 * SkillDetailPage —— 技能详情全页视图
 *
 * Desktop: 左 2/3 内容 + 右 1/3 信息栏
 * Mobile:  单列堆叠，安装按钮固定底部
 */
import { useState } from 'react'
import type { MarketSkillV2, Review } from '../MarketplaceView'
import { MarkdownRenderer } from '../MarkdownRenderer'
import ScreenshotCarousel from './ScreenshotCarousel'
import RatingDistribution from './RatingDistribution'
import ReviewCard from './ReviewCard'
import ReviewForm from './ReviewForm'
import AuthorCard from './AuthorCard'

// ─── Types ────────────────────────────────────────────────────────────────

interface SkillDetailPageProps {
  skill: MarketSkillV2 | null
  skillName: string
  reviews: Review[]
  authToken: string
  onBack: () => void
  onInstall: (name: string) => void
  onMarkHelpful: (reviewId: string) => void
  onToggleFavorite: (name: string) => void
  isFavorite?: boolean
  loading?: boolean
}

// ─── Helpers ──────────────────────────────────────────────────────────────

function formatCount(n: number): string {
  if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k'
  return String(n)
}

function sourceBadgeType(source: string): 'official' | 'community' | 'bundle' {
  if (source === 'official') return 'official'
  if (source === 'bundle') return 'bundle'
  return 'community'
}

const BADGE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  official:  { bg: 'var(--primary-50, #EFF6FF)',   text: 'var(--primary-700, #1D4ED8)',  label: '官方' },
  community: { bg: 'var(--success-50, #ECFDF5)',   text: 'var(--success-700, #047857)',  label: '社区' },
  bundle:    { bg: 'var(--info-50, #EEF2FF)',      text: 'var(--info-700, #4338CA)',     label: '套件' },
}

function InlineStars({ value, size = 14 }: { value: number; size?: number }) {
  return (
    <span className="inline-flex items-center gap-0.5">
      {Array.from({ length: 5 }, (_, i) => (
        <svg key={i} width={size} height={size} viewBox="0 0 24 24" fill={i < Math.round(value) ? '#f59e0b' : '#CBD5E1'}>
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87L18.18 22 12 18.27 5.82 22 7 14.14l-5-4.87 6.91-1.01L12 2z" />
        </svg>
      ))}
      <span className="ml-1 text-xs font-medium" style={{ color: 'var(--text-secondary, #475569)' }}>
        {value.toFixed(1)}
      </span>
    </span>
  )
}

// ─── Skeleton ─────────────────────────────────────────────────────────────

function DetailSkeleton() {
  return (
    <div className="animate-pulse space-y-6 p-6">
      <div className="h-5 w-16 rounded bg-gray-200" />
      <div className="flex gap-6">
        <div className="flex-1 space-y-4">
          <div className="h-7 w-48 rounded bg-gray-200" />
          <div className="h-4 w-32 rounded bg-gray-100" />
          <div className="h-4 w-64 rounded bg-gray-100" />
          <div className="h-48 rounded-xl bg-gray-100" />
        </div>
        <div className="w-72 space-y-3">
          <div className="h-10 rounded-lg bg-gray-200" />
          <div className="h-32 rounded-xl bg-gray-100" />
        </div>
      </div>
    </div>
  )
}

// ─── Not Found ────────────────────────────────────────────────────────────

function NotFound({ name, onBack }: { name: string; onBack: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="text-4xl mb-4">🔍</div>
      <h2 className="text-lg font-medium" style={{ color: 'var(--text-primary, #1E293B)' }}>
        技能不存在
      </h2>
      <p className="text-sm mt-1" style={{ color: 'var(--text-secondary, #64748B)' }}>
        找不到 &quot;{name}&quot;，可能已下架或名称有误
      </p>
      <button
        onClick={onBack}
        className="mt-4 px-4 py-1.5 rounded-lg text-sm font-medium text-white"
        style={{ backgroundColor: 'var(--primary-500, #3B82F6)' }}
      >
        返回市场
      </button>
    </div>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────

export default function SkillDetailPage({
  skill, skillName, reviews, onBack, onInstall,
  onMarkHelpful, onToggleFavorite, isFavorite, loading,
}: SkillDetailPageProps) {
  const [installing, setInstalling] = useState(false)

  // Loading state
  if (!skill && loading) return <DetailSkeleton />
  // Not found
  if (!skill) return <NotFound name={skillName} onBack={onBack} />

  const badge = BADGE_STYLES[sourceBadgeType(skill.source_type)]
  const distribution = computeDistribution(reviews)

  const handleInstall = () => {
    setInstalling(true)
    onInstall(skill.name)
    setTimeout(() => setInstalling(false), 1500)
  }

  return (
    <div className="min-h-0 flex flex-col">
      {/* Back button */}
      <button
        onClick={onBack}
        className="shrink-0 inline-flex items-center gap-1 text-[13px] mb-4 transition-colors hover:text-blue-600"
        style={{ color: 'var(--text-secondary, #64748B)' }}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="15 18 9 12 15 6" />
        </svg>
        返回
      </button>

      {/* Desktop: 2-col / Mobile: stack */}
      <div className="flex flex-col lg:flex-row gap-6 min-h-0">
        {/* ── Left content (2/3) ── */}
        <div className="flex-1 min-w-0 space-y-6">
          {/* Header */}
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl font-semibold" style={{ color: 'var(--text-primary, #1E293B)' }}>
                {skill.name}
              </h1>
              <span
                className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border border-transparent"
                style={{ backgroundColor: badge.bg, color: badge.text }}
              >
                {badge.label}
              </span>
              {skill.featured && (
                <span
                  className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium"
                  style={{ backgroundColor: 'var(--warning-50, #FFFBEB)', color: 'var(--warning-700, #B45309)' }}
                >
                  精选
                </span>
              )}
            </div>
            <p className="text-[12.5px] mt-1" style={{ color: 'var(--text-secondary, #64748B)' }}>
              by {skill.author || '匿名'} · v{skill.version}
            </p>
            <div className="flex items-center gap-3 mt-2 flex-wrap">
              <InlineStars value={skill.rating_avg} />
              <span className="text-[11.5px]" style={{ color: 'var(--text-tertiary, #94A3B8)' }}>
                ({skill.rating_count} 评价)
              </span>
              <span className="text-[11.5px] flex items-center gap-0.5" style={{ color: 'var(--text-tertiary, #94A3B8)' }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 5v14M5 12l7 7 7-7" />
                </svg>
                {formatCount(skill.install_count)} 安装
              </span>
            </div>
            <div className="flex items-center gap-2 mt-3">
              <button
                onClick={() => onToggleFavorite(skill.name)}
                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[12px] border transition-colors ${
                  isFavorite ? 'bg-rose-50 border-rose-200 text-rose-600' : 'border-gray-200 hover:bg-gray-50'
                }`}
                style={!isFavorite ? { color: 'var(--text-secondary, #64748B)' } : undefined}
              >
                {isFavorite ? '❤️' : '🤍'} {isFavorite ? '已收藏' : '收藏'}
              </button>
            </div>
          </div>

          {/* Screenshots */}
          <ScreenshotCarousel screenshots={skill.screenshots} />

          {/* Description */}
          {skill.description && (
            <section>
              <SectionTitle>描述</SectionTitle>
              <p className="text-[13.5px] leading-relaxed" style={{ color: 'var(--text-secondary, #475569)' }}>
                {skill.description}
              </p>
            </section>
          )}

          {/* SKILL.md / README rendered via MarkdownRenderer */}
          {skill.readme_content && (
            <section>
              <SectionTitle>文档</SectionTitle>
              <div className="text-[13.5px]">
                <MarkdownRenderer content={skill.readme_content} />
              </div>
            </section>
          )}

          {/* Reviews */}
          {reviews.length > 0 && (
            <section>
              <SectionTitle>评价 ({reviews.length})</SectionTitle>
              <div className="mb-4">
                <RatingDistribution
                  distribution={distribution}
                  average={skill.rating_avg}
                  total={skill.rating_count}
                />
              </div>
              <div className="mb-4">
                <ReviewForm onSubmit={() => {}} loading={false} />
              </div>
              <div>
                {reviews.map((r) => (
                  <ReviewCard key={r.id} review={r} onHelpful={onMarkHelpful} />
                ))}
              </div>
            </section>
          )}
        </div>

        {/* ── Right sidebar (1/3) ── */}
        <div className="w-full lg:w-72 shrink-0 space-y-4">
          {/* Info panel */}
          <div
            className="rounded-xl p-4 space-y-3"
            style={{ backgroundColor: 'var(--bg-secondary, #F8FAFC)' }}
          >
            {/* Install button */}
            <button
              onClick={handleInstall}
              disabled={installing || skill.installed}
              className="w-full py-2 rounded-lg text-[13px] font-medium transition-colors disabled:opacity-50"
              style={{
                backgroundColor: skill.installed ? '#F2F0FF' : '#7C6AF4',
                color: skill.installed ? '#7C6AF4' : '#fff',
              }}
            >
              {installing ? '安装中...' : skill.installed ? '已安装' : '安装'}
            </button>

            <InfoRow label="版本" value={skill.version} />
            <InfoRow label="分类" value={skill.category} />
            <InfoRow label="许可" value="MIT" />
            <InfoRow label="更新" value={skill.updated_at?.slice(0, 10) || '-'} />
          </div>

          {/* Author */}
          <AuthorCard name={skill.author} />

          {/* Tags */}
          {skill.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {skill.tags.map((t) => (
                <span
                  key={t}
                  className="px-2 py-0.5 rounded-full text-[11px]"
                  style={{ backgroundColor: 'var(--bg-secondary, #F1F5F9)', color: 'var(--text-secondary, #64748B)' }}
                >
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Mobile fixed-bottom install */}
      <div className="lg:hidden fixed bottom-0 left-0 right-0 bg-white border-t px-4 py-3 flex items-center justify-between z-40"
        style={{ borderColor: 'var(--border-light, #E2E8F0)' }}
      >
        <div className="text-[13px] font-medium" style={{ color: 'var(--text-primary, #1E293B)' }}>
          {skill.name}
        </div>
        <button
          onClick={handleInstall}
          disabled={installing || skill.installed}
          className="px-5 py-2 rounded-lg text-[13px] font-medium transition-colors disabled:opacity-50"
          style={{
            backgroundColor: skill.installed ? '#F2F0FF' : '#7C6AF4',
            color: skill.installed ? '#7C6AF4' : '#fff',
          }}
        >
          {installing ? '安装中...' : skill.installed ? '已安装' : '安装'}
        </button>
      </div>
    </div>
  )
}

// ─── Small helpers ────────────────────────────────────────────────────────

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-[15px] font-medium mb-3 pb-2 border-b" style={{ color: 'var(--text-primary, #1E293B)', borderColor: 'var(--border-light, #E2E8F0)' }}>
      {children}
    </h3>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-[12.5px]">
      <span style={{ color: 'var(--text-tertiary, #94A3B8)' }}>{label}</span>
      <span style={{ color: 'var(--text-primary, #1E293B)' }}>{value}</span>
    </div>
  )
}

function computeDistribution(reviews: Review[]): number[] {
  const dist = [0, 0, 0, 0, 0] // index 0=5★ ... 4=1★
  for (const r of reviews) {
    const idx = 5 - Math.min(Math.max(r.rating, 1), 5)
    dist[idx]++
  }
  return dist
}

// Extend MarketSkillV2 with optional readme_content for detail page
declare module '../MarketplaceView' {
  interface MarketSkillV2 {
    readme_content?: string
  }
}
