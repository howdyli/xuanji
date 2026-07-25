import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MentionPicker } from './MentionPicker'
import type { Expert } from './ExpertManagerView'

// ExpertPickerList 内部不发请求（experts 由 props 传入），仅 useSessionSkills
// 会走 apiFetch —— 本测试直接以 props 注入 skills，无需网络。
vi.mock('../api/client', () => ({ apiFetch: vi.fn(async () => ({})) }))

const EXPERTS = [
  {
    id: 1,
    name: 'dev_team',
    display_name: '技术交付专家团',
    description: '',
    icon: 'dev',
    system_prompt: 'x',
    skills: [],
    category: '技术工程',
    tags: [],
    team: '玄机团队',
    usage_count: 0,
    avatar_url: '',
    created_at: '',
    updated_at: '',
  },
] as unknown as Expert[]

const SKILLS = [
  { name: 'memory-save', source: 'builtin' as const, enabled: true },
  { name: 'web_browse', source: 'builtin' as const, enabled: true },
]

function renderPicker(overrides: Partial<Parameters<typeof MentionPicker>[0]> = {}) {
  const onSelectExpert = vi.fn()
  const onSelectSkill = vi.fn()
  const onClose = vi.fn()
  const props = {
    open: true,
    anchorEl: null,
    query: '',
    experts: EXPERTS,
    expertsLoading: false,
    skills: SKILLS,
    skillsLoading: false,
    activeExpert: null,
    onSelectExpert,
    onSelectSkill,
    onClose,
    ...overrides,
  }
  render(<MentionPicker {...props} />)
  return { onSelectExpert, onSelectSkill, onClose }
}

describe('MentionPicker', () => {
  it('shows the expert tab by default', () => {
    renderPicker()
    expect(screen.getByText('技术交付专家团')).toBeInTheDocument()
    expect(screen.queryByText('memory-save')).not.toBeInTheDocument()
  })

  it('switches to the skill tab and lists session skills', async () => {
    const user = userEvent.setup()
    renderPicker()
    await user.click(screen.getByRole('button', { name: '技能' }))
    expect(screen.getByText('memory-save')).toBeInTheDocument()
    expect(screen.getByText('web_browse')).toBeInTheDocument()
  })

  it('fires onSelectSkill with the skill name', async () => {
    const user = userEvent.setup()
    const { onSelectSkill } = renderPicker()
    await user.click(screen.getByRole('button', { name: '技能' }))
    await user.click(screen.getByText('memory-save'))
    expect(onSelectSkill).toHaveBeenCalledWith('memory-save')
  })

  it('filters the skill tab by query', async () => {
    const user = userEvent.setup()
    renderPicker({ query: 'memo' })
    await user.click(screen.getByRole('button', { name: '技能' }))
    expect(screen.getByText('memory-save')).toBeInTheDocument()
    expect(screen.queryByText('web_browse')).not.toBeInTheDocument()
  })

  it('shows an empty hint when no skill matches', async () => {
    const user = userEvent.setup()
    renderPicker({ skills: [] })
    await user.click(screen.getByRole('button', { name: '技能' }))
    expect(screen.getByText('未找到可用技能')).toBeInTheDocument()
  })

  it('renders nothing when closed', () => {
    renderPicker({ open: false })
    expect(screen.queryByText('专家')).not.toBeInTheDocument()
  })
})
