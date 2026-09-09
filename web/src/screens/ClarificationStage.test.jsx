import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ClarificationStage from './ClarificationStage'
import { AppCtx } from '../App'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getProject: vi.fn(),
    clarify: vi.fn(),
    confirmClarification: vi.fn(),
    scrubPreview: vi.fn(),
    updateProject: vi.fn(),
    updateDesign: vi.fn(),
    collectionGuidance: vi.fn(),
  },
}))
vi.mock('../api', () => ({ api: apiMock }))

beforeEach(() => {
  apiMock.getProject.mockResolvedValue({ id: 1, ai_clarification_state: null, ai_project_design: null })
  apiMock.confirmClarification.mockResolvedValue({ confirmed: true })
  apiMock.collectionGuidance.mockResolvedValue({ recommendations: [] })
  apiMock.scrubPreview.mockResolvedValue({ redacted: false, text: '' })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function renderScreen(ctxOverrides = {}) {
  const value = {
    ctx: {
      projectId: 1,
      projectTitle: 'Falls QI',
      projectDesc: 'Reduce falls on 3W',
      colTypes: { month: 'Date', falls: 'Number' },
      ...ctxOverrides,
    },
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

describe('ClarificationStage with design editor', () => {
  it('loads opening turn and renders understanding card with provenance chips', async () => {
    apiMock.clarify.mockResolvedValue({
      message: "1. What is your intervention?\n2. What is your primary outcome?",
      reasoning: "Reviewing project context.",
      confirmed: false,
      design: {
        aim: "Reduce falls by 30%",
        population: "Inpatients on 3W",
        plain_restatement: "Tracking monthly falls on 3W over time.",
        status: { aim: "inferred", population: "inferred" },
      },
      turns: [{ role: "ai", content: "1. What is your intervention?\n2. What is your primary outcome?" }],
    })
    renderScreen()

    expect(await screen.findByText(/Here is my understanding of your project/)).toBeInTheDocument()
    expect(await screen.findByText('Reduce falls by 30%')).toBeInTheDocument()
    expect(screen.getByText('Tracking monthly falls on 3W over time.')).toBeInTheDocument()
    expect(screen.getAllByText('Inferred by AI').length).toBeGreaterThanOrEqual(1)

    // Numbered questions rendered as form inputs
    expect(screen.getByLabelText(/What is your intervention\?/)).toBeInTheDocument()
    expect(screen.getByLabelText(/What is your primary outcome\?/)).toBeInTheDocument()
  })

  it('submits form answers joined as numbered list', async () => {
    apiMock.clarify.mockResolvedValue({
      message: "1. What is your intervention?\n2. What is your primary outcome?",
      confirmed: false,
      turns: [{ role: "ai", content: "1. What is your intervention?\n2. What is your primary outcome?" }],
    })
    const user = userEvent.setup()
    renderScreen()

    const q1Input = await screen.findByLabelText(/What is your intervention\?/)
    const q2Input = screen.getByLabelText(/What is your primary outcome\?/)

    await user.type(q1Input, 'Fall risk assessment tool')
    await user.type(q2Input, 'Monthly falls count')

    apiMock.clarify.mockResolvedValueOnce({
      message: "Got it. Your definition looks complete.",
      confirmed: true,
      turns: [
        { role: "ai", content: "1. What is your intervention?\n2. What is your primary outcome?" },
        { role: "user", content: "1. Fall risk assessment tool\n2. Monthly falls count" },
        { role: "ai", content: "Got it. Your definition looks complete." },
      ],
    })

    await user.click(screen.getByRole('button', { name: 'Submit Answers' }))

    await waitFor(() => {
      expect(apiMock.clarify).toHaveBeenCalledWith(1, '1. Fall risk assessment tool\n2. Monthly falls count')
    })
  })

  it('allows editing definition and saves via updateDesign', async () => {
    apiMock.getProject.mockResolvedValue({
      id: 1,
      ai_project_design: { aim: "Old Aim", status: { aim: "inferred" } },
    })
    apiMock.clarify.mockResolvedValue({
      message: "Reviewing...",
      confirmed: false,
      turns: [{ role: "ai", content: "Reviewing..." }],
    })
    apiMock.updateDesign.mockResolvedValue({
      ai_project_design: { aim: "User Corrected Aim", status: { aim: "user-corrected" } },
    })

    const user = userEvent.setup()
    const value = renderScreen()

    const editBtn = await screen.findByRole('button', { name: 'Edit Definition' })
    await user.click(editBtn)

    const aimInput = screen.getByLabelText('Aim')
    await user.clear(aimInput)
    await user.type(aimInput, 'User Corrected Aim')

    await user.click(screen.getByRole('button', { name: 'Save Definition' }))

    await waitFor(() => {
      expect(apiMock.updateDesign).toHaveBeenCalledWith(1, expect.objectContaining({ aim: 'User Corrected Aim' }))
      expect(value.update).toHaveBeenCalledWith(expect.objectContaining({ design: expect.anything() }))
    })
  })

  it('renders staleness banner when clarification state is marked stale', async () => {
    apiMock.getProject.mockResolvedValue({
      id: 1,
      ai_clarification_state: { turns: [], confirmed: false, stale: true },
    })
    apiMock.clarify.mockResolvedValue({ message: "Hello", turns: [{ role: "ai", content: "Hello" }] })
    renderScreen()

    expect(await screen.findByText(/Your project inputs changed/)).toBeInTheDocument()
  })

  it('confirms and calls collectionGuidance on confirm button click', async () => {
    apiMock.getProject.mockResolvedValue({
      id: 1,
      ai_clarification_state: {
        turns: [
          { role: "ai", content: "1" }, { role: "user", content: "1" },
          { role: "ai", content: "2" }, { role: "user", content: "2" },
          { role: "ai", content: "3" }, { role: "user", content: "3" },
          { role: "ai", content: "4" }, { role: "user", content: "4" },
        ],
        confirmed: false,
      },
    })
    apiMock.collectionGuidance.mockResolvedValue({ recommendations: [{ id: "guidance-1" }] })

    const user = userEvent.setup()
    const value = renderScreen()

    const confirmBtn = await screen.findByRole('button', { name: /Confirm project definition/ })
    expect(confirmBtn).toBeInTheDocument()

    await user.click(confirmBtn)

    await waitFor(() => {
      expect(apiMock.confirmClarification).toHaveBeenCalledWith(1)
      expect(apiMock.collectionGuidance).toHaveBeenCalledWith(1)
      expect(value.update).toHaveBeenCalledWith(expect.objectContaining({ collectionRecs: [{ id: "guidance-1" }] }))
      expect(value.next).toHaveBeenCalled()
    })
  })
})
