/**
 * SkillRankingList —— 热门排行榜
 * Top 10 技能，金银铜色标记前三名
 */
import type { MarketSkillV2 } from '../MarketplaceView'
import RatingStars from './RatingStars'

interface SkillRankingListProps {
  skills: MarketSkillV2[]
  period: 'week' | 'month'
  onPeriodChange: (period: 'week' | 'month') => void
  onSkillClick: (name: string) => void
  title?: string
}

const medalColors: Record<number, { bg: string; text: string }> = {
  1: { bg: '#FEF3C7', text: '#B45309' },   // gold
  2: { bg: '#E5E7EB', text: '#4B5563' },   // silver
  3: { bg: '#FED7AA', text: '#C2410C' },   // bronze
}

function formatCount(n: number): string {
  if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k'
  return String(n)
}

export default function SkillRankingList({
  skills, period, onPeriodChange, onSkillClick, title = '热门排行',
}: SkillRankingListProps) {
  const top10 = skills.slice(0, 10)

  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{ backgroundColor: 'var(--bg-secondary, #fff)', borderColor: 'var(--border-light, #E2E8F0)' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 pt-4 pb-2">
        <h3 className="text-[14px] font-semibold" style={{ color: 'var(--text-primary, #1E293B)' }}>
          {title}
        </h3>
        <div className="flex items-center gap-0.5 text-[12px]">
          {(['week', 'month'] as const).map(p => (
            <button
              key={p}
              onClick={() => onPeriodChange(p)}
              className={`px-2.5 py-1 rounded-md font-medium transition-colors ${
                period === p
                  ? 'bg-gray-100 text-gray-900'
                  : 'text-gray-400 hover:text-gray-600'
              }`}
            >
              {p === 'week' ? '本周' : '本月'}
            </button>
          ))}
        </div>
      </div>

      {/* List */}
      <div className="px-2 pb-2">
        {top10.length === 0 && (
          <p className="text-center text-[12px] py-8" style={{ color: 'var(--text-tertiary, #94A3B8)' }}>
            暂无数据
          </p>
        )}
        {top10.map((skill, idx) => {
          const rank = idx + 1
          const medal = medalColors[rank]
          return (
            <button
              key={skill.name}
              onClick={() => onSkillClick(skill.name)}
              className="w-full flex items-center gap-3 px-2 py-2.5 rounded-lg hover:bg-gray-50 transition-colors text-left"
            >
              {/* Rank badge */}
              <span
                className="w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold shrink-0"
                style={medal ? { backgroundColor: medal.bg, color: medal.text } : { color: 'var(--text-tertiary, #94A3B8)' }}
              >
                {rank}
              </span>

              {/* Name + rating */}
              <div className="flex-1 min-w-0">
                <div className="text-[13px] font-medium truncate" style={{ color: 'var(--text-primary, #1E293B)' }}>
                  {skill.name}
                </div>
                <div className="mt-0.5">
                  <RatingStars value={skill.rating_avg} size="sm" />
                </div>
              </div>

              {/* Install count */}
              <span className="shrink-0 text-[11px] font-medium" style={{ color: 'var(--text-tertiary, #94A3B8)' }}>
                {formatCount(skill.install_count)}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
