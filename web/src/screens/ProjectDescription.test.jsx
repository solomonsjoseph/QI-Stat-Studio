import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import ProjectDescription from './ProjectDescription'
import { AppCtx } from '../App'

vi.mock('../api', () => ({ api: { updateProject: vi.fn(), saveAnswers: vi.fn(), prefillIntake: vi.fn() } }))

function renderScreen() {
  return render(
    <AppCtx.Provider value={{ ctx: { projectId: 1, answers: {} }, update: vi.fn(), next: vi.fn(), prev: vi.fn() }}>
      <ProjectDescription />
    </AppCtx.Provider>,
  )
}

describe('ProjectDescription guide wording', () => {
  it('uses the guide-verbatim project description prompt', () => {
    renderScreen()

    expect(screen.getByRole('heading', { name: 'Tell us about your project.' })).toBeInTheDocument()
    expect(screen.getByText("In one or two sentences, what is your QA/QI project about? Imagine you're explaining it to a co-resident in the cafeteria. No jargon needed.")).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Describe your QI initiative in one or two sentences...')).toBeInTheDocument()
  })
})
