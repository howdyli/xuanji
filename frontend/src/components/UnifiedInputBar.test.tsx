import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UnifiedInputBar, extractSkillHints } from './UnifiedInputBar'

// useExperts() fetches /experts via apiFetch; stub it so the picker / @ list
// and the active-expert chip can resolve a display name.
vi.mock('../api/client', () => ({
  apiFetch: vi.fn(async () => ({
    experts: [
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
    ],
  })),
}))

const HOME_PLACEHOLDER = '描述你的任务或问题，或输入 @ 召唤专家…'

function renderBar(overrides: Partial<Parameters<typeof UnifiedInputBar>[0]> = {}) {
  const onSend = vi.fn()
  const onSelectExpert = vi.fn()
  const props = {
    isHome: true,
    loading: false,
    onSend,
    sessionId: null,
    inputRef: { current: null },
    activeExpert: null,
    onSelectExpert,
    ...overrides,
  }
  render(<UnifiedInputBar {...props} />)
  return { onSend, onSelectExpert }
}

describe('UnifiedInputBar', () => {
  it('renders the home placeholder', () => {
    renderBar()
    expect(screen.getByPlaceholderText(HOME_PLACEHOLDER)).toBeInTheDocument()
  })

  it('sends trimmed text on Enter and clears the input', async () => {
    const user = userEvent.setup()
    const { onSend } = renderBar()
    const textarea = screen.getByPlaceholderText(HOME_PLACEHOLDER)

    await user.type(textarea, '  你好世界  {Enter}')

    expect(onSend).toHaveBeenCalledTimes(1)
    expect(onSend).toHaveBeenCalledWith('你好世界')
    expect(textarea).toHaveValue('')
  })

  it('does not send when the input is only whitespace', async () => {
    const user = userEvent.setup()
    const { onSend } = renderBar()
    const textarea = screen.getByPlaceholderText(HOME_PLACEHOLDER)

    await user.type(textarea, '   {Enter}')

    expect(onSend).not.toHaveBeenCalled()
  })

  it('keeps the send button disabled until text is entered, then sends on click', async () => {
    const user = userEvent.setup()
    const { onSend } = renderBar()
    // The send button is the last control in the bar (attachment/voice are
    // always disabled, so target the send button by position).
    const buttons = screen.getAllByRole('button')
    const sendBtn = buttons[buttons.length - 1] as HTMLButtonElement
    expect(sendBtn).toBeTruthy()
    expect(sendBtn).toBeDisabled()

    await user.type(screen.getByPlaceholderText(HOME_PLACEHOLDER), '发送测试')
    expect(sendBtn).toBeEnabled()

    await user.click(sendBtn)
    expect(onSend).toHaveBeenCalledWith('发送测试')
  })

  it('does not send while loading', async () => {
    const user = userEvent.setup()
    const { onSend } = renderBar({ loading: true })
    const textarea = screen.getByPlaceholderText(HOME_PLACEHOLDER)

    // Textarea is disabled while loading; Enter must not trigger a send.
    await user.type(textarea, 'hi{Enter}')
    expect(onSend).not.toHaveBeenCalled()
  })

  it('shows the active-expert chip and clears it via ✕', async () => {
    const user = userEvent.setup()
    const { onSelectExpert } = renderBar({ activeExpert: 'dev_team' })

    // display_name resolves once /experts loads
    expect(await screen.findByText('当前专家：技术交付专家团')).toBeInTheDocument()

    await user.click(screen.getByTitle('取消召唤'))
    expect(onSelectExpert).toHaveBeenCalledWith(null)
  })

  it('opens the @ expert popover and activates the picked expert (dropping the @token)', async () => {
    const user = userEvent.setup()
    const { onSelectExpert } = renderBar()
    const textarea = screen.getByPlaceholderText(HOME_PLACEHOLDER)

    await user.type(textarea, '@')
    const option = await screen.findByText('技术交付专家团')
    await user.click(option)

    expect(onSelectExpert).toHaveBeenCalledWith('dev_team')
    // @token is dropped from the text (only a summoning gesture, no literal mention)
    expect(textarea).toHaveValue('')
  })

  it('makes / and @ popovers mutually exclusive in chat mode', async () => {
    const user = userEvent.setup()
    renderBar({ isHome: false })
    const textarea = screen.getByPlaceholderText(
      '继续对话，或输入 / 调用指令、@ 召唤专家…',
    )

    // slash popup first
    await user.type(textarea, '/')
    expect(await screen.findByText('日报生成')).toBeInTheDocument()

    // switch to @ — slash popup hides, expert list shows
    await user.clear(textarea)
    await user.type(textarea, '@')
    expect(await screen.findByText('技术交付专家团')).toBeInTheDocument()
    expect(screen.queryByText('日报生成')).not.toBeInTheDocument()
  })
})

describe('extractSkillHints', () => {
  const enabled = ['memory-save', 'web_browse', 'code-review']

  it('picks only @tokens that exactly match enabled skill names', () => {
    expect(extractSkillHints('@memory-save 记一下 @unknown 内容', enabled)).toEqual([
      'memory-save',
    ])
  })

  it('returns empty when no @token matches', () => {
    expect(extractSkillHints('你好 @nobody', enabled)).toEqual([])
    expect(extractSkillHints('没有提及', enabled)).toEqual([])
  })

  it('dedupes while preserving order', () => {
    expect(
      extractSkillHints('@web_browse 先查 @memory-save 再存 @web_browse', enabled),
    ).toEqual(['web_browse', 'memory-save'])
  })

  it('caps at three hints', () => {
    const many = ['s1', 's2', 's3', 's4']
    expect(extractSkillHints('@s1 @s2 @s3 @s4', many)).toEqual(['s1', 's2', 's3'])
  })
})
