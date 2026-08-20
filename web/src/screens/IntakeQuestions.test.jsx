import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import IntakeQuestions from './IntakeQuestions'
import { AppCtx } from '../App'

const { apiMock } = vi.hoisted(() => ({
  apiMock: { saveAnswers: vi.fn(), intakeAnswerAI: vi.fn(), scrubPreview: vi.fn() },
}))
vi.mock('../api', () => ({ api: apiMock }))

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function renderScreen(ctx = {}) {
  const value = {
    ctx: { projectId: 1, projectDesc: 'Improve A1c', answers: {}, ...ctx },
    update: vi.fn(),
    next: vi.fn(),
    prev: vi.fn(),
  }
  render(
    <AppCtx.Provider value={value}>
      <IntakeQuestions />
    </AppCtx.Provider>,
  )
  return value
}

async function advance(times) {
  const user = userEvent.setup()
  for (let i = 0; i < times; i += 1) {
    await user.click(screen.getByRole('button', { name: /Next/i }))
  }
}

describe('IntakeQuestions guide wording', () => {
  it('uses the guide-verbatim Q2-Q4 stems', async () => {
    renderScreen()

    expect(screen.getByRole('group', { name: /What are you measuring\?/ })).toBeInTheDocument()
    await advance(1)
    expect(screen.getByRole('group', { name: /Are you comparing before and after something\?/ })).toBeInTheDocument()
    await advance(1)
    expect(screen.getByRole('group', { name: /Are you tracking over time, or comparing two groups\?/ })).toBeInTheDocument()
  })

  it('asks the abstract deadline and mentor email as two separate final steps', async () => {
    renderScreen()

    await advance(8)
    expect(screen.getByRole('group', { name: /When is your abstract deadline\?/ })).toBeInTheDocument()

    await advance(1)
    expect(screen.getByRole('group', { name: /Your mentor's email \(optional\)/ })).toBeInTheDocument()
  })
})

describe('IntakeQuestions Q7 unsure date', () => {
  it('clears and omits q7 date when the resident is not sure when the intervention started', async () => {
    apiMock.saveAnswers.mockResolvedValue({})
    const user = userEvent.setup()
    renderScreen()

    await advance(5)
    await user.type(screen.getByLabelText('Intervention description (optional)'), 'Standing orders')
    const dateInput = screen.getByLabelText('Intervention date (if known)')
    await user.type(dateInput, '2025-01-01')

    await user.click(screen.getByRole('checkbox', { name: "I'm not sure when it started" }))

    expect(dateInput).toBeDisabled()
    expect(dateInput).toHaveValue('')

    await advance(4)
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    expect(apiMock.saveAnswers).toHaveBeenCalledTimes(1)
    const saved = apiMock.saveAnswers.mock.calls[0][1]
    expect(saved.q7).toEqual({ description: 'Standing orders' })
    expect(saved.q7).not.toHaveProperty('date')
  })
})

describe('IntakeQuestions PHI banner', () => {
  it('shows the prefill PHI banner only when text was de-identified before AI prefill', () => {
    const banner = 'Some text was automatically de-identified before being sent to the AI. No PHI left this server.'

    renderScreen()
    expect(screen.queryByText(banner)).not.toBeInTheDocument()
    cleanup()

    renderScreen({ prefillPhiRedacted: true })
    expect(screen.getByText(banner)).toBeInTheDocument()
  })
})

describe('IntakeQuestions AI-assisted answers', () => {
  it('lets the resident explain a radio question in free text and auto-advances when the AI resolves it', async () => {
    apiMock.scrubPreview.mockResolvedValue({ text: 'we count falls each month', redacted: false, count: 0 })
    apiMock.intakeAnswerAI.mockResolvedValue({
      value: 'A count (number of falls per month)',
      message: 'Got it, tracking a monthly falls count.',
      resolved: true,
    })
    const user = userEvent.setup()
    renderScreen()

    await user.type(screen.getByLabelText('Or explain in your own words'), 'we count falls each month')
    await user.click(screen.getByRole('button', { name: 'Ask AI' }))

    await waitFor(() => {
      expect(apiMock.intakeAnswerAI).toHaveBeenCalledWith(1, expect.objectContaining({
        question_key: 'q2',
        question_type: 'radio',
        message: 'we count falls each month',
      }))
    })
    // Resolved -> auto-advances to the next question (q3)
    await waitFor(() => {
      expect(screen.getByRole('group', { name: /Are you comparing before and after something\?/ })).toBeInTheDocument()
    })
  })

  it('shows the AI clarifying message and stays on the question when it cannot resolve an answer', async () => {
    apiMock.scrubPreview.mockResolvedValue({ text: 'something vague', redacted: false, count: 0 })
    apiMock.intakeAnswerAI.mockResolvedValue({
      value: null,
      message: 'Could you say more about what you are counting or measuring?',
      resolved: false,
    })
    const user = userEvent.setup()
    renderScreen()

    await user.type(screen.getByLabelText('Or explain in your own words'), 'something vague')
    await user.click(screen.getByRole('button', { name: 'Ask AI' }))

    expect(await screen.findByText(/Could you say more about what you are counting/)).toBeInTheDocument()
    expect(screen.getByRole('group', { name: /What are you measuring\?/ })).toBeInTheDocument()
  })

  it('redacts PHI in the explanation and requires a second Ask AI click before sending', async () => {
    apiMock.scrubPreview.mockResolvedValue({ text: '[REDACTED] falls per month', redacted: true, count: 1 })
    const user = userEvent.setup()
    renderScreen()

    await user.type(screen.getByLabelText('Or explain in your own words'), 'patient Jane Doe falls per month')
    await user.click(screen.getByRole('button', { name: 'Ask AI' }))

    expect(await screen.findByText(/We removed what looked like PHI/)).toBeInTheDocument()
    expect(apiMock.intakeAnswerAI).not.toHaveBeenCalled()
  })

  it('never offers an AI helper for the mentor email question', async () => {
    renderScreen()

    await advance(9)

    expect(screen.getByRole('group', { name: /Your mentor's email \(optional\)/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Ask AI' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Or explain in your own words')).not.toBeInTheDocument()
  })
})
