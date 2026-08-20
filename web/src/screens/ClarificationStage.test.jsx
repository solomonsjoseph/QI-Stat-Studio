import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ClarificationStage from './ClarificationStage'
import { AppCtx } from '../App'

const { apiMock } = vi.hoisted(() => ({
  apiMock: { getProject: vi.fn(), clarify: vi.fn(), scrubPreview: vi.fn(), updateProject: vi.fn() },
}))
vi.mock('../api', () => ({ api: apiMock }))

beforeEach(() => {
  apiMock.getProject.mockResolvedValue({ id: 1, ai_clarification_state: null })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function renderScreen(ctxOverrides = {}) {
  const value = {
    ctx: { projectId: 1, projectTitle: 'Falls prevention pilot', projectDesc: 'We tried a new tool.', ...ctxOverrides },
    update: vi.fn(),
    next: vi.fn(),
    prev: vi.fn(),
  }
  render(
    <AppCtx.Provider value={value}>
      <ClarificationStage />
    </AppCtx.Provider>,
  )
  return value
}

describe('ClarificationStage', () => {
  it('keeps Continue from advancing until the AI confirms agreement, opening the panel and starting the conversation instead', async () => {
    apiMock.clarify.mockResolvedValue({
      message: "Here's what I understood...",
      reasoning: 'Checked the dataset schema.',
      suggested_title: 'Better title',
      suggested_description: 'Better description',
      confirmed: false,
      turns: [{ role: 'ai', content: "Here's what I understood...", reasoning: 'Checked the dataset schema.' }],
    })
    const user = userEvent.setup()
    const value = renderScreen()

    await waitFor(() => expect(apiMock.getProject).toHaveBeenCalled())
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    await waitFor(() => expect(apiMock.clarify).toHaveBeenCalledWith(1, null))
    expect(await screen.findByRole('dialog', { name: 'AI Clarification' })).toBeInTheDocument()
    expect(screen.getByText(/Here's what I understood/)).toBeInTheDocument()
    expect(value.next).not.toHaveBeenCalled()
  })

  it('shows Accept/Dismiss for a suggested title and description, applying it via updateProject on Accept', async () => {
    apiMock.clarify.mockResolvedValue({
      message: 'Proposed rewrite',
      confirmed: false,
      suggested_title: 'Fall-Risk Screening Impact on Falls Rate, Unit 3W',
      suggested_description: 'Clarified description.',
      turns: [{ role: 'ai', content: 'Proposed rewrite' }],
    })
    apiMock.updateProject.mockResolvedValue({})
    const user = userEvent.setup()
    const value = renderScreen()

    await user.click(screen.getByRole('button', { name: 'Chat with AI' }))
    await screen.findByDisplayValue('Fall-Risk Screening Impact on Falls Rate, Unit 3W')

    await user.click(screen.getByRole('button', { name: 'Accept' }))

    await waitFor(() => {
      expect(apiMock.updateProject).toHaveBeenCalledWith(1, {
        title: 'Fall-Risk Screening Impact on Falls Rate, Unit 3W',
        description: 'Clarified description.',
      })
    })
    expect(value.update).toHaveBeenCalledWith({
      projectTitle: 'Fall-Risk Screening Impact on Falls Rate, Unit 3W',
      projectDesc: 'Clarified description.',
    })
  })

  it('redacts PHI in the chat input and requires a second Share click before sending', async () => {
    apiMock.clarify.mockResolvedValue({
      message: 'ok',
      confirmed: false,
      turns: [{ role: 'ai', content: 'ok' }],
    })
    apiMock.scrubPreview.mockResolvedValue({ text: '[REDACTED] was screened', redacted: true, count: 1 })
    const user = userEvent.setup()
    renderScreen()

    await user.click(screen.getByRole('button', { name: 'Chat with AI' }))
    await waitFor(() => expect(apiMock.clarify).toHaveBeenCalledTimes(1)) // the AI's opening move
    await user.type(screen.getByPlaceholderText('Type your message...'), 'patient Jane Doe was screened')
    await user.click(screen.getByRole('button', { name: 'Share' }))

    expect(await screen.findByText(/We removed what looked like PHI/)).toBeInTheDocument()
    expect(apiMock.clarify).toHaveBeenCalledTimes(1) // still just the opening move -- redaction blocked the send

    await user.click(screen.getByRole('button', { name: 'Share' }))
    await waitFor(() => expect(apiMock.clarify).toHaveBeenCalledWith(1, '[REDACTED] was screened'))
  })

  it('lets Continue proceed immediately once the AI has already confirmed agreement', async () => {
    apiMock.getProject.mockResolvedValue({
      id: 1,
      ai_clarification_state: { turns: [{ role: 'ai', content: 'Agreed.' }], confirmed: true },
    })
    const user = userEvent.setup()
    const value = renderScreen()

    await waitFor(() => {
      expect(screen.queryByText(/Chat with the AI to confirm/)).not.toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    expect(apiMock.clarify).not.toHaveBeenCalled()
    expect(value.next).toHaveBeenCalled()
  })

  it('lets the resident edit the AI suggested title/description before accepting', async () => {
    apiMock.clarify.mockResolvedValue({
      message: 'Proposed rewrite',
      confirmed: false,
      suggested_title: 'AI suggested title',
      suggested_description: 'AI suggested description.',
      turns: [{ role: 'ai', content: 'Proposed rewrite' }],
    })
    apiMock.updateProject.mockResolvedValue({})
    const user = userEvent.setup()
    const value = renderScreen()

    await user.click(screen.getByRole('button', { name: 'Chat with AI' }))
    const titleInput = await screen.findByDisplayValue('AI suggested title')
    await user.clear(titleInput)
    await user.type(titleInput, 'My edited title')

    await user.click(screen.getByRole('button', { name: 'Accept' }))

    await waitFor(() => {
      expect(apiMock.updateProject).toHaveBeenCalledWith(1, {
        title: 'My edited title',
        description: 'AI suggested description.',
      })
    })
    expect(value.update).toHaveBeenCalledWith({
      projectTitle: 'My edited title',
      projectDesc: 'AI suggested description.',
    })
  })
})
