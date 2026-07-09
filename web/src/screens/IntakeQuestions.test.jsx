import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import IntakeQuestions from './IntakeQuestions'
import { AppCtx } from '../App'

const { apiMock } = vi.hoisted(() => ({ apiMock: { saveAnswers: vi.fn() } }))
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

  it('uses the guide-verbatim Q10 mentor labels', async () => {
    renderScreen()

    await advance(8)

    expect(screen.getByRole('group', { name: /Your mentor and timeline \(optional\)/ })).toBeInTheDocument()
    expect(screen.getByText("Mentor's email (so they get a share link)")).toBeInTheDocument()
    expect(screen.getByText('Abstract deadline')).toBeInTheDocument()
  })
})
