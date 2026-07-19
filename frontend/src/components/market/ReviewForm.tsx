/**
 * ReviewForm —— 写评价表单
 * 可交互星级 + textarea 评论框 + 提交按钮
 */
import { useState } from 'react'

interface ReviewFormProps {
  onSubmit: (rating: number, comment: string) => void
  loading?: boolean
}

function InteractiveStars({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const [hover, setHover] = useState(0)
  return (
    <div className="inline-flex items-center gap-1">
      {Array.from({ length: 5 }, (_, i) => {
        const pos = i + 1
        const filled = pos <= (hover || value)
        return (
          <span
            key={pos}
            className="cursor-pointer transition-transform hover:scale-110"
            onMouseEnter={() => setHover(pos)}
            onMouseLeave={() => setHover(0)}
            onClick={() => onChange(pos)}
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill={filled ? '#f59e0b' : '#CBD5E1'}>
              <path d="M12 2l3.09 6.26L22 9.27l-5 4.87L18.18 22 12 18.27 5.82 22 7 14.14l-5-4.87 6.91-1.01L12 2z" />
            </svg>
          </span>
        )
      })}
    </div>
  )
}

export default function ReviewForm({ onSubmit, loading }: ReviewFormProps) {
  const [rating, setRating] = useState(0)
  const [comment, setComment] = useState('')

  const canSubmit = rating > 0 && comment.trim().length > 0 && !loading

  const handleSubmit = () => {
    if (!canSubmit) return
    onSubmit(rating, comment.trim())
    setRating(0)
    setComment('')
  }

  return (
    <div className="space-y-3">
      <h4 className="text-[14px] font-medium" style={{ color: 'var(--text-primary, #1E293B)' }}>
        写评价
      </h4>
      <div className="flex items-center gap-2">
        <InteractiveStars value={rating} onChange={setRating} />
        {rating > 0 && (
          <span className="text-xs" style={{ color: 'var(--text-secondary, #64748B)' }}>
            {rating} 星
          </span>
        )}
      </div>
      <textarea
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder="分享你的使用体验..."
        rows={3}
        className="w-full rounded-lg border px-3 py-2 text-[13px] resize-none focus:outline-none focus:ring-2 focus:ring-blue-500/30"
        style={{
          borderColor: 'var(--border-light, #E2E8F0)',
          color: 'var(--text-primary, #1E293B)',
          backgroundColor: 'var(--bg-primary, #fff)',
        }}
      />
      <button
        onClick={handleSubmit}
        disabled={!canSubmit}
        className="px-4 py-1.5 rounded-lg text-[12.5px] font-medium text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        style={{ backgroundColor: 'var(--primary-500, #3B82F6)' }}
      >
        {loading ? '提交中...' : '提交评价'}
      </button>
    </div>
  )
}
