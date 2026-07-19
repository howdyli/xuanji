import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UnifiedInputBar } from './UnifiedInputBar'

function renderBar(overrides: Partial<Parameters<typeof UnifiedInputBar>[0]> = {}) {
  const onSend = vi.fn()
  const props = {
    isHome: true,
    loading: false,
    onSend,
    sessionId: null,
    inputRef: { current: null },
    ...overrides,
  }
  render(<UnifiedInputBar {...props} />)
  return { onSend }
}

describe('UnifiedInputBar', () => {
  it('renders the home placeholder', () => {
    renderBar()
    expect(
      screen.getByPlaceholderText('描述你的任务或问题…'),
    ).toBeInTheDocument()
  })

  it('sends trimmed text on Enter and clears the input', async () => {
    const user = userEvent.setup()
    const { onSend } = renderBar()
    const textarea = screen.getByPlaceholderText('描述你的任务或问题…')

    await user.type(textarea, '  你好世界  {Enter}')

    expect(onSend).toHaveBeenCalledTimes(1)
    expect(onSend).toHaveBeenCalledWith('你好世界')
    expect(textarea).toHaveValue('')
  })

  it('does not send when the input is only whitespace', async () => {
    const user = userEvent.setup()
    const { onSend } = renderBar()
    const textarea = screen.getByPlaceholderText('描述你的任务或问题…')

    await user.type(textarea, '   {Enter}')

    expect(onSend).not.toHaveBeenCalled()
  })

  it('keeps the send button disabled until text is entered, then sends on click', async () => {
    const user = userEvent.setup()
    const { onSend } = renderBar()
    // The send button is the only control that starts disabled.
    const sendBtn = screen
      .getAllByRole('button')
      .find((b) => (b as HTMLButtonElement).disabled) as HTMLButtonElement
    expect(sendBtn).toBeTruthy()
    expect(sendBtn).toBeDisabled()

    await user.type(screen.getByPlaceholderText('描述你的任务或问题…'), '发送测试')
    expect(sendBtn).toBeEnabled()

    await user.click(sendBtn)
    expect(onSend).toHaveBeenCalledWith('发送测试')
  })

  it('does not send while loading', async () => {
    const user = userEvent.setup()
    const { onSend } = renderBar({ loading: true })
    const textarea = screen.getByPlaceholderText('描述你的任务或问题…')

    // Textarea is disabled while loading; Enter must not trigger a send.
    await user.type(textarea, 'hi{Enter}')
    expect(onSend).not.toHaveBeenCalled()
  })
})
