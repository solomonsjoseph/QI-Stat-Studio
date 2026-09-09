import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import EditReview from './EditReview'

const { apiMock, useAppMock } = vi.hoisted(() => ({
  apiMock: {
    saveProjectEdit: vi.fn(),
    updateProject: vi.fn(),
  },
  useAppMock: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../App', () => ({ useApp: useAppMock }))

beforeEach(() => {
  apiMock.saveProjectEdit.mockReset()
  apiMock.updateProject.mockReset()
  useAppMock.mockReset()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function runsCtx(overrides = {}) {
  return {
    projectId: 7,
    projectTitle: 'Original report title',
    runs: [
      { run_id: 1, template: 'descriptive_summary', caption: 'Original caption', ai_interpretation: 'Original interpretation' },
      { run_id: 2, template: 'run_chart', caption: 'Second caption', ai_interpretation: 'Second interpretation' },
    ],
    ...overrides,
  }
}

describe('EditReview per-run edits', () => {
  it('saves a per-run caption and interpretation edit posting run_id, and title separately', async () => {
    const update = vi.fn()
    const next = vi.fn()
    useAppMock.mockReturnValue({ ctx: runsCtx(), update, next, prev: vi.fn() })
    apiMock.saveProjectEdit.mockResolvedValue({ ok: true })
    apiMock.updateProject.mockResolvedValue({})

    const user = userEvent.setup()
    render(<EditReview />)

    await user.clear(screen.getByLabelText(/report title/i))
    await user.type(screen.getByLabelText(/report title/i), 'Revised report title')

    const captionInput = screen.getByLabelText(/figure caption/i, { selector: '#edit-caption-1' }) || screen.getAllByLabelText(/figure caption/i)[0]
    await user.clear(captionInput)
    await user.type(captionInput, 'Revised caption')

    await user.click(screen.getByRole('button', { name: /save & continue/i }))

    await waitFor(() => {
      expect(apiMock.saveProjectEdit).toHaveBeenCalledWith(7, 'title', 'Original report title', 'Revised report title')
      expect(apiMock.saveProjectEdit).toHaveBeenCalledWith(7, 'caption', 'Original caption', 'Revised caption', 1)
      expect(apiMock.updateProject).toHaveBeenCalledWith(7, { title: 'Revised report title' })
      expect(next).toHaveBeenCalled()
    })
  })

  it('renders one caption + interpretation editor per run', async () => {
    useAppMock.mockReturnValue({ ctx: runsCtx(), update: vi.fn(), next: vi.fn(), prev: vi.fn() })

    render(<EditReview />)

    const captionFields = screen.getAllByLabelText(/figure caption/i)
    const interpFields = screen.getAllByLabelText(/interpretation/i)
    expect(captionFields).toHaveLength(2)
    expect(interpFields).toHaveLength(2)
    expect(captionFields[0]).toHaveValue('Original caption')
    expect(captionFields[1]).toHaveValue('Second caption')
  })

  it('always records an interpretation review, even when accepted as-is, so resume does not bounce back to edit', async () => {
    const update = vi.fn()
    const next = vi.fn()
    useAppMock.mockReturnValue({ ctx: runsCtx(), update, next, prev: vi.fn() })
    apiMock.saveProjectEdit.mockResolvedValue({ ok: true })

    const user = userEvent.setup()
    render(<EditReview />)

    // Resident touches nothing and accepts the AI interpretation as-is.
    await user.click(screen.getByRole('button', { name: /save & continue/i }))

    await waitFor(() => {
      expect(apiMock.saveProjectEdit).toHaveBeenCalledWith(7, 'interpretation', 'Original interpretation', 'Original interpretation', 1)
      expect(apiMock.saveProjectEdit).toHaveBeenCalledWith(7, 'interpretation', 'Second interpretation', 'Second interpretation', 2)
      expect(next).toHaveBeenCalled()
    })
  })

  it('surfaces a save error and does not advance', async () => {
    useAppMock.mockReturnValue({ ctx: runsCtx(), update: vi.fn(), next: vi.fn(), prev: vi.fn() })
    apiMock.saveProjectEdit.mockRejectedValue(Object.assign(new Error('Caption edit rejected'), { requestId: 'req-edit-2' }))

    const user = userEvent.setup()
    render(<EditReview />)

    const captionFields = screen.getAllByLabelText(/figure caption/i)
    await user.clear(captionFields[0])
    await user.type(captionFields[0], 'Revised caption')

    await user.click(screen.getByRole('button', { name: /save & continue/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Caption edit rejected (Request ID: req-edit-2)')
  })
})
