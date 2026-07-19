/**
 * ScreenshotCarousel —— 技能截图轮播
 * 支持左右切换，lazy 加载图片，无截图时不渲染
 */
import { useState } from 'react'

interface ScreenshotCarouselProps {
  screenshots: string[]
}

export default function ScreenshotCarousel({ screenshots }: ScreenshotCarouselProps) {
  const [idx, setIdx] = useState(0)
  if (!screenshots.length) return null

  const prev = () => setIdx((i) => (i - 1 + screenshots.length) % screenshots.length)
  const next = () => setIdx((i) => (i + 1) % screenshots.length)

  return (
    <div className="relative rounded-xl overflow-hidden shadow-md bg-gray-50 group">
      <img
        src={screenshots[idx]}
        alt={`截图 ${idx + 1}`}
        loading="lazy"
        className="w-full h-auto max-h-[400px] object-contain"
      />

      {screenshots.length > 1 && (
        <>
          <button
            onClick={prev}
            className="absolute left-2 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full bg-black/40 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity hover:bg-black/60"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </button>
          <button
            onClick={next}
            className="absolute right-2 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full bg-black/40 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity hover:bg-black/60"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </button>
          <div className="absolute bottom-2 left-1/2 -translate-x-1/2 flex gap-1.5">
            {screenshots.map((_, i) => (
              <span
                key={i}
                className={`w-1.5 h-1.5 rounded-full transition-colors ${i === idx ? 'bg-white' : 'bg-white/50'}`}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
