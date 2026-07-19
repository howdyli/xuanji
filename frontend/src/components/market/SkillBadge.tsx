/**
 * SkillBadge —— 技能类型/认证徽章
 * 官方 / 社区 / 套件 / NEW 四种类型
 */

interface SkillBadgeProps {
  type: 'official' | 'community' | 'bundle' | 'new'
  label?: string
}

const config: Record<SkillBadgeProps['type'], { bg: string; text: string; defaultLabel: string }> = {
  official:  { bg: 'var(--primary-50, #EFF6FF)',   text: 'var(--primary-700, #1D4ED8)',  defaultLabel: '官方' },
  community: { bg: 'var(--success-50, #ECFDF5)',   text: 'var(--success-700, #047857)',  defaultLabel: '社区' },
  bundle:    { bg: 'var(--info-50, #EEF2FF)',      text: 'var(--info-700, #4338CA)',     defaultLabel: '套件' },
  new:       { bg: 'var(--warning-50, #FFFBEB)',   text: 'var(--warning-700, #B45309)',  defaultLabel: 'NEW' },
}

export default function SkillBadge({ type, label }: SkillBadgeProps) {
  const c = config[type]
  return (
    <span
      className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium leading-tight border"
      style={{
        backgroundColor: c.bg,
        color: c.text,
        borderColor: 'transparent',
      }}
    >
      {label ?? c.defaultLabel}
    </span>
  )
}
