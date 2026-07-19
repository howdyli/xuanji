/**
 * RatingStars —— 星级评分组件
 * 支持展示（readonly）和交互（可点击）两种模式
 */
import { useState } from 'react'

interface RatingStarsProps {
  value: number
  max?: number
  readonly?: boolean
  onChange?: (rating: number) => void
  size?: 'sm' | 'md' | 'lg'
}

const sizeMap = { sm: 14, md: 18, lg: 24 }

function StarSvg({ filled, half, size, color }: { filled: boolean; half?: boolean; size: number; color: string }) {
  const emptyColor = 'var(--text-tertiary, #94A3B8)'
  const fillColor = color || 'var(--accent-gold, #f59e0b)'
  const id = half ? `half-${Math.random().toString(36).slice(2, 8)}` : undefined

  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      {half && id && (
        <defs>
          <linearGradient id={id}>
            <stop offset="50%" stopColor={fillColor} />
            <stop offset="50%" stopColor={emptyColor} />
          </linearGradient>
        </defs>
      )}
      <path
        d="M12 2l3.09 6.26L22 9.27l-5 4.87L18.18 22 12 18.27 5.82 22 7 14.14l-5-4.87 6.91-1.01L12 2z"
        fill={half && id ? `url(#${id})` : filled ? fillColor : emptyColor}
        stroke={filled || half ? fillColor : emptyColor}
        strokeWidth="1"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export default function RatingStars({ value, max = 5, readonly = true, onChange, size = 'md' }: RatingStarsProps) {
  const [hover, setHover] = useState<number>(0)
  const px = sizeMap[size]

  const stars = Array.from({ length: max }, (_, i) => {
    const pos = i + 1
    const displayVal = hover || value
    const filled = pos <= Math.floor(displayVal)
    const half = !filled && pos === Math.ceil(displayVal) && displayVal % 1 >= 0.3
    return { filled, half, pos }
  })

  const handleClick = (pos: number) => {
    if (!readonly && onChange) onChange(pos)
  }

  return (
    <div className="inline-flex items-center gap-0.5">
      {stars.map(({ filled, half, pos }) => (
        <span
          key={pos}
          className={readonly ? 'inline-flex' : 'inline-flex cursor-pointer'}
          onMouseEnter={() => !readonly && setHover(pos)}
          onMouseLeave={() => !readonly && setHover(0)}
          onClick={() => handleClick(pos)}
        >
          <StarSvg filled={filled} half={half} size={px} color="" />
        </span>
      ))}
      {readonly && (
        <span className="ml-1 text-xs font-medium" style={{ color: 'var(--text-secondary, #475569)' }}>
          {value.toFixed(1)}
        </span>
      )}
    </div>
  )
}
