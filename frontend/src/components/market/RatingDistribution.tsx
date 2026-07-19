/**
 * RatingDistribution —— 评分分布柱状图
 * 显示 5 星到 1 星的横向柱状图 + 平均分 + 总数
 */

interface RatingDistributionProps {
  distribution: number[]  // [5星数, 4星数, 3星数, 2星数, 1星数]
  average: number
  total: number
}

export default function RatingDistribution({ distribution, average, total }: RatingDistributionProps) {
  const maxCount = Math.max(...distribution, 1)

  return (
    <div className="space-y-2">
      {/* Summary */}
      <div className="flex items-baseline gap-2 mb-3">
        <span className="text-3xl font-bold" style={{ color: 'var(--text-primary, #1E293B)' }}>
          {average.toFixed(1)}
        </span>
        <span className="text-sm" style={{ color: 'var(--text-secondary, #64748B)' }}>
          / 5 · 共 {total} 条评价
        </span>
      </div>

      {/* Bars: 5★ → 1★ */}
      {distribution.map((count, i) => {
        const star = 5 - i
        const pct = maxCount > 0 ? (count / maxCount) * 100 : 0
        return (
          <div key={star} className="flex items-center gap-2 text-xs">
            <span className="w-6 text-right shrink-0" style={{ color: 'var(--text-secondary, #64748B)' }}>
              {star} ★
            </span>
            <div className="flex-1 h-2 rounded-full bg-gray-100 overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${pct}%`,
                  backgroundColor: 'var(--accent-gold, #f59e0b)',
                }}
              />
            </div>
            <span className="w-8 text-right shrink-0" style={{ color: 'var(--text-tertiary, #94A3B8)' }}>
              {count}
            </span>
          </div>
        )
      })}
    </div>
  )
}
