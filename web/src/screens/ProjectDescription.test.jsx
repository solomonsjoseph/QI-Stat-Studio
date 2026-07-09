import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ProjectDescription from './ProjectDescription'
import { AppCtx } from '../App'

const { apiMock } = vi.hoisted(() => ({
  apiMock: { updateProject: vi.fn(), saveAnswers: vi.fn(), prefillIntake: vi.fn() },
}))
vi.mock('../api', () => ({ api: apiMock }))

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function renderScreen() {
  const value = { ctx: { projectId: 1, answers: {} }, update: vi.fn(), next: vi.fn(), prev: vi.fn() }
  render(
    <AppCtx.Provider value={value}>
      <ProjectDescription />
    </AppCtx.Provider>,
  )
  return value
}

describe('ProjectDescription guide wording', () => {
  it('uses the guide-verbatim project description prompt', () => {
    renderScreen()

    expect(screen.getByRole('heading', { name: 'Tell us about your project.' })).toBeInTheDocument()
    expect(screen.getByText("In one or two sentences, what is your QA/QI project about? Imagine you're explaining it to a co-resident in the cafeteria. No jargon needed.")).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Describe your QI initiative in one or two sentences...')).toBeInTheDocument()
  })
})

  it('stores the PHI redaction flag returned by intake prefill', async () => {
    apiMock.updateProject.mockResolvedValue({})
    apiMock.saveAnswers.mockResolvedValue({})
    apiMock.prefillIntake.mockResolvedValue({ answers: { q2: 'Something else / not sure' }, phi_redacted: true })
    const user = userEvent.setup()
    const value = renderScreen()

    await user.type(screen.getByLabelText('Project Title'), 'Diabetes care')
    await user.type(screen.getByLabelText('Project Description'), 'Improve A1c for Jane Doe')
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    await waitFor(() => {
      expect(value.update).toHaveBeenCalledWith({ aiSuggestions: { q2: 'Something else / not sure' }, prefillPhiRedacted: true })
    })
  })
