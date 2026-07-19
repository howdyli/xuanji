/**
 * AuthorCard —— 作者信息卡片
 * 首字母头像 + 名称 + 发布技能数
 */

interface AuthorCardProps {
  name: string
  skillCount?: number
}

const COLORS = ['#6366f1', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#3b82f6']

function hashColor(s: string): string {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return COLORS[h % COLORS.length]
}

export default function AuthorCard({ name, skillCount }: AuthorCardProps) {
  const initial = (name || '?').charAt(0).toUpperCase()
  const color = hashColor(name)

  return (
    <div
      className="rounded-xl p-4 flex items-center gap-3"
      style={{ backgroundColor: 'var(--bg-secondary, #F8FAFC)' }}
    >
      <div
        className="w-10 h-10 rounded-full flex items-center justify-center text-white text-sm font-semibold shrink-0"
        style={{ backgroundColor: color }}
      >
        {initial}
      </div>
      <div className="min-w-0">
        <div className="text-[13px] font-medium truncate" style={{ color: 'var(--text-primary, #1E293B)' }}>
          {name || '匿名'}
        </div>
        {skillCount != null && (
          <div className="text-[11.5px]" style={{ color: 'var(--text-tertiary, #94A3B8)' }}>
            已发布 {skillCount} 个技能
          </div>
        )}
      </div>
    </div>
  )
}
