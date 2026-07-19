/**
 * HeroBanner —— 精选推荐轮播横幅
 * 渐变背景 + 白色文字 + 左右切换按钮
 */
import { useState } from 'react'
import type { MarketSkillV2 } from '../MarketplaceView'
import RatingStars from './RatingStars'

interface HeroBannerProps {
  featured: MarketSkillV2[]
  onSkillClick: (name: string) => void
}

export default function HeroBanner({ featured, onSkillClick }: HeroBannerProps) {
  const [index, setIndex] = useState(0)

  if (!featured || featured.length === 0) return null

  const skill = featured[index]
  const hasMultiple = featured.length > 1

  const prev = () => setIndex(i => (i - 1 + featured.length) % featured.length)
  const next = () => setIndex(i => (i + 1) % featured.length)

  return (
    <div
      className="relative rounded-2xl overflow-hidden px-8 py-8"
      style={{
        background: 'linear-gradient(135deg, var(--primary-500, #3B82F6), var(--primary-700, #1D4ED8))',
      }}
    >
      {/* Content */}
      <div className="relative z-10 max-w-lg">
        <span className="inline-block px-2 py-0.5 rounded text-[10px] font-semibold tracking-wide uppercase mb-3"
          style={{ backgroundColor: 'rgba(255,255,255,0.2)', color: '#fff' }}>
          精选推荐
        </span>

        <h2 className="text-[22px] font-bold text-white leading-tight mb-2">
          {skill.name}
        </h2>

        <p className="text-[14px] leading-relaxed mb-3" style={{ color: 'rgba(255,255,255,0.85)' }}>
          {skill.description || '暂无描述'}
        </p>

        <div className="flex items-center gap-3 mb-4">
          <RatingStars value={skill.rating_avg} size="sm" />
          <span className="text-[12px]" style={{ color: 'rgba(255,255,255,0.7)' }}>
            {skill.rating_count} 评价 · {skill.install_count} 安装
          </span>
        </div>

        <button
          onClick={() => onSkillClick(skill.name)}
          className="px-4 py-2 rounded-lg text-[13px] font-medium text-white transition-colors"
          style={{ backgroundColor: 'rgba(255,255,255,0.18)' }}
          onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.28)')}
          onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.18)')}
        >
          查看详情 →
        </button>
      </div>

      {/* Decorative circle */}
      <div className="absolute -right-8 -top-8 w-48 h-48 rounded-full opacity-10" style={{ backgroundColor: '#fff' }} />
      <div className="absolute -right-4 -bottom-10 w-32 h-32 rounded-full opacity-5" style={{ backgroundColor: '#fff' }} />

      {/* Nav buttons */}
      {hasMultiple && (
        <>
          <button
            onClick={prev}
            className="absolute left-3 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full flex items-center justify-center transition-colors"
            style={{ backgroundColor: 'rgba(255,255,255,0.15)', color: '#fff' }}
            onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.3)')}
            onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.15)')}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </button>
          <button
            onClick={next}
            className="absolute right-3 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full flex items-center justify-center transition-colors"
            style={{ backgroundColor: 'rgba(255,255,255,0.15)', color: '#fff' }}
            onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.3)')}
            onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.15)')}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </button>

          {/* Dots */}
          <div className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-1.5">
            {featured.map((_, i) => (
              <span
                key={i}
                className="w-1.5 h-1.5 rounded-full transition-colors"
                style={{ backgroundColor: i === index ? '#fff' : 'rgba(255,255,255,0.4)' }}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
