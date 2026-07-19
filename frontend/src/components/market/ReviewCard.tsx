/**
 * ReviewCard —— 单条评价卡片
 * 用户头像（首字母彩色圆形）+ 用户名 + 时间 + 星级 + 评论 + 有用按钮
 */
import type { Review } from '../MarketplaceView'

interface ReviewCardProps {
  review: Review
  onHelpful?: (id: string) => void
}

const AVATAR_COLORS = [
  '#6366f1', '#8b5cf6', '#ec4899', '#f43f5e', '#f97316', '#14b8a6', '#3b82f6',
]

function avatarColor(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return AVATAR_COLORS[h % AVATAR_COLORS.length]
}

function StarsRow({ value }: { value: number }) {
  return (
    <div className="inline-flex items-center gap-0.5">
      {Array.from({ length: 5 }, (_, i) => (
        <svg key={i} width="14" height="14" viewBox="0 0 24 24" fill={i < value ? '#f59e0b' : '#CBD5E1'}>
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87L18.18 22 12 18.27 5.82 22 7 14.14l-5-4.87 6.91-1.01L12 2z" />
        </svg>
      ))}
    </div>
  )
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const days = Math.floor(diff / 86400000)
  if (days < 1) return '今天'
  if (days < 30) return `${days} 天前`
  if (days < 365) return `${Math.floor(days / 30)} 个月前`
  return `${Math.floor(days / 365)} 年前`
}

export default function ReviewCard({ review, onHelpful }: ReviewCardProps) {
  const initial = (review.user.name || '?').charAt(0).toUpperCase()
  const color = avatarColor(review.user.name)

  return (
    <div className="py-4 border-b last:border-b-0" style={{ borderColor: 'var(--border-light, #E2E8F0)' }}>
      <div className="flex items-start gap-3">
        {/* Avatar */}
        <div
          className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-semibold shrink-0"
          style={{ backgroundColor: color }}
        >
          {initial}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[13px] font-medium" style={{ color: 'var(--text-primary, #1E293B)' }}>
              {review.user.name}
            </span>
            <StarsRow value={review.rating} />
            <span className="text-[11px]" style={{ color: 'var(--text-tertiary, #94A3B8)' }}>
              {timeAgo(review.created_at)}
            </span>
          </div>
          {review.comment && (
            <p className="mt-1.5 text-[13px] leading-relaxed" style={{ color: 'var(--text-secondary, #475569)' }}>
              {review.comment}
            </p>
          )}
          {onHelpful && (
            <button
              onClick={() => onHelpful(review.id)}
              className="mt-2 inline-flex items-center gap-1 text-[11.5px] transition-colors hover:text-blue-600"
              style={{ color: 'var(--text-tertiary, #94A3B8)' }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3H14z" />
                <path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3" />
              </svg>
              有用 ({review.helpful_count})
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
