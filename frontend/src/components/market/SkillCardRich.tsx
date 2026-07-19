/**
 * SkillCardRich —— 增强型技能卡片
 * 网格视图中的单个卡片，含图标、徽章、评分、安装量、安装按钮
 */
import { useState } from 'react'
import type { MarketSkillV2 } from '../MarketplaceView'
import RatingStars from './RatingStars'
import InstallButton from './InstallButton'

interface SkillCardRichProps {
  skill: MarketSkillV2
  onInstall: (name: string) => void
  onClick: (name: string) => void
  installed?: boolean
}

const GRADIENTS = [
  'from-violet-400 to-fuchsia-500',
  'from-sky-400 to-blue-500',
  'from-orange-400 to-rose-500',
  'from-amber-400 to-yellow-500',
  'from-pink-400 to-rose-500',
  'from-teal-400 to-emerald-500',
]

function gradientOf(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return GRADIENTS[h % GRADIENTS.length]
}

function formatCount(n: number): string {
  if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k'
  return String(n)
}

export default function SkillCardRich({ skill, onInstall, onClick, installed }: SkillCardRichProps) {
  const [installing, setInstalling] = useState(false)
  const isInstalled = installed ?? skill.installed

  const handleInstall = () => {
    setInstalling(true)
    onInstall(skill.name)
    // Reset after a short delay — parent should manage real state
    setTimeout(() => setInstalling(false), 1200)
  }

  return (
    <div
      className="group bg-white border rounded-xl p-4 flex flex-col gap-2.5 cursor-pointer transition-all hover:-translate-y-0.5 hover:shadow-md"
      style={{ borderColor: 'var(--border-light, #E2E8F0)' }}
      onClick={() => onClick(skill.name)}
    >
      {/* Top: icon + badge */}
      <div className="flex items-start justify-between gap-2">
        {skill.icon_url ? (
          <img src={skill.icon_url} alt="" className="w-9 h-9 rounded-lg object-cover shrink-0" />
        ) : (
          <div
            className={`w-9 h-9 rounded-lg bg-gradient-to-br ${gradientOf(skill.name)} flex items-center justify-center text-white text-sm font-semibold shrink-0`}
          >
            {skill.name.charAt(0).toUpperCase()}
          </div>
        )}
        {skill.featured && (
          <span
            className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium"
            style={{ backgroundColor: 'var(--warning-50, #FFFBEB)', color: 'var(--warning-700, #B45309)' }}
          >
            精选
          </span>
        )}
      </div>

      {/* Name */}
      <h3 className="text-[14px] font-medium truncate" style={{ color: 'var(--text-primary, #1E293B)' }}>
        {skill.name}
      </h3>

      {/* Description */}
      <p
        className="text-[12.5px] leading-relaxed line-clamp-2 min-h-[36px]"
        style={{ color: 'var(--text-secondary, #475569)' }}
      >
        {skill.description || '暂无描述'}
      </p>

      {/* Rating */}
      <div className="flex items-center gap-1.5">
        <RatingStars value={skill.rating_avg} size="sm" />
        <span className="text-[11px]" style={{ color: 'var(--text-tertiary, #94A3B8)' }}>
          ({skill.rating_count})
        </span>
      </div>

      {/* Bottom: author + install count + button */}
      <div className="flex items-center justify-between mt-auto pt-1">
        <div className="flex items-center gap-3 text-[11.5px]" style={{ color: 'var(--text-tertiary, #94A3B8)' }}>
          <span className="flex items-center gap-0.5">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="7" r="4" /><path d="M5.5 21a7.5 7.5 0 0 1 13 0" />
            </svg>
            {skill.author || '匿名'}
          </span>
          <span className="flex items-center gap-0.5">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 5v14M5 12l7 7 7-7" />
            </svg>
            {formatCount(skill.install_count)}
          </span>
        </div>
        <div onClick={e => e.stopPropagation()}>
          <InstallButton
            installed={isInstalled}
            loading={installing}
            onInstall={handleInstall}
          />
        </div>
      </div>
    </div>
  )
}
