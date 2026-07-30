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

describe('EditReview', () => {
  it('saves edits through api.saveProjectEdit and stops before local state advances when one save fails', async () => {
    const update = vi.fn()
    const next = vi.fn()
    useAppMock.mockReturnValue({
      ctx: {
        projectId: 7,
        projectTitle: 'Original report title',
        editedCaption: 'Original caption',
        aiInterpretation: 'Original interpretation',
      },
      update,
      next,
    })
    apiMock.saveProjectEdit
      .mockResolvedValueOnce({ id: 1 })
      .mockRejectedValueOnce(Object.assign(new Error('Caption edit rejected'), { requestId: 'req-edit-2' }))

    const user = userEvent.setup()
    render(<EditReview />)

    await user.clear(screen.getByLabelText(/report title/i))
    await user.type(screen.getByLabelText(/report title/i), 'Revised report title')
    await user.clear(screen.getByLabelText(/figure caption/i))
    await user.type(screen.getByLabelText(/figure caption/i), 'Revised caption')
    await user.clear(screen.getByLabelText(/interpretation/i))
    await user.type(screen.getByLabelText(/interpretation/i), 'Revised interpretation')
    await user.click(screen.getByRole('button', { name: /save & continue/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Caption edit rejected (Request ID: req-edit-2)')
    await waitFor(() => expect(apiMock.saveProjectEdit).toHaveBeenCalledTimes(2))
    expect(apiMock.saveProjectEdit).toHaveBeenNthCalledWith(1, 7, 'title', 'Original report title', 'Revised report title')
    expect(apiMock.saveProjectEdit).toHaveBeenNthCalledWith(2, 7, 'caption', 'Original caption', 'Revised caption')
    expect(apiMock.saveProjectEdit).not.toHaveBeenCalledWith(7, 'interpretation', expect.any(String), expect.any(String))
    expect(apiMock.updateProject).not.toHaveBeenCalled()
    expect(update).not.toHaveBeenCalled()
    expect(next).not.toHaveBeenCalled()
  })

  it('prefills interpretation from resumed analysis results when aiInterpretation is absent', () => {
    useAppMock.mockReturnValue({
      ctx: {
        projectId: 8,
        projectTitle: 'Resume-backed report',
        results: {
          result_summary: 'Improved.',
          interpretation: 'Server-derived interpretation from latest run.',
        },
      },
      update: vi.fn(),
      next: vi.fn(),
    })

    render(<EditReview />)

    expect(screen.getByLabelText(/interpretation/i)).toHaveValue('Server-derived interpretation from latest run.')
  })
})
