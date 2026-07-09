import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MentorView from './MentorView'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getMentorView: vi.fn(),
    addComment: vi.fn(),
    editComment: vi.fn(),
    deleteComment: vi.fn(),
    shareDocxUrl: vi.fn(),
    sharePdfUrl: vi.fn(),
  },
}))

vi.mock('../api', () => ({ api: apiMock }))

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function mentorPayload(overrides = {}) {
  return {
    project: { title: 'Mentor Project', description: 'Reduce falls on Ward A.' },
    methods: 'Weekly fall counts were reviewed.',
    result_summary: 'Falls decreased after the intervention.',
    table: [{ week: '1', falls: 4 }],
    limitations: [],
    comments: [],
    ...overrides,
  }
}

beforeEach(() => {
  apiMock.getMentorView.mockReset()
  apiMock.addComment.mockReset()
  apiMock.editComment.mockReset()
  apiMock.deleteComment.mockReset()
  apiMock.shareDocxUrl.mockImplementation(token => `/api/share/view/${token}/report/docx`)
  apiMock.sharePdfUrl.mockImplementation(token => `/api/share/view/${token}/report/pdf`)
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('MentorView', () => {
  it('shows a loading state while the mentor share is being fetched', () => {
    apiMock.getMentorView.mockReturnValue(new Promise(() => {}))

    render(<MentorView token="mentor-token" />)

    expect(screen.getByText('Loading mentor review…')).toBeInTheDocument()
  })

  it('retries a failed initial mentor share load and renders the recovered share', async () => {
    apiMock.getMentorView
      .mockRejectedValueOnce({ requestId: 'req-share-1' })
      .mockResolvedValueOnce(mentorPayload({ project: { title: 'Recovered Mentor Project', description: 'Retry loaded this share.' } }))
    const user = userEvent.setup()

    render(<MentorView token="expired-token" />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Share link not found or expired. (Request ID: req-share-1)')
    await user.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByRole('heading', { name: 'Recovered Mentor Project' })).toBeInTheDocument()
    expect(apiMock.getMentorView).toHaveBeenCalledTimes(2)
  })

  it('shows comment saving progress and keeps the draft visible when saving the comment fails', async () => {
    const saveComment = deferred()
    apiMock.getMentorView.mockResolvedValue(mentorPayload())
    apiMock.addComment.mockReturnValue(saveComment.promise)

    const user = userEvent.setup()
    render(<MentorView token="mentor-token" />)

    expect(await screen.findByRole('heading', { name: 'Mentor Project' })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/your name/i), 'Dr Mentor')
    await user.type(screen.getByLabelText(/^comment$/i), 'Please clarify the denominator for week 1.')
    await user.click(screen.getByRole('button', { name: /send comment/i }))

    expect(screen.getByText('Saving comment…')).toBeInTheDocument()

    await act(async () => {
      saveComment.reject(Object.assign(new Error('Comment was not saved'), { requestId: 'req-comment-7' }))
      await saveComment.promise.catch(() => null)
    })

    expect(await screen.findByRole('alert')).toHaveTextContent('Comment was not saved (Request ID: req-comment-7)')
    expect(screen.getByLabelText(/^comment$/i)).toHaveValue('Please clarify the denominator for week 1.')
  })

  it('edits and deletes comments using the current mentor email', async () => {
    apiMock.getMentorView
      .mockResolvedValueOnce(mentorPayload({ comments: [{ id: 12, author_name: 'Dr Mentor', author_email: 'mentor@example.edu', text: 'Original note.' }] }))
      .mockResolvedValueOnce(mentorPayload({ comments: [{ id: 12, author_name: 'Dr Mentor', author_email: 'mentor@example.edu', text: 'Updated note.' }] }))
      .mockResolvedValueOnce(mentorPayload({ comments: [] }))
    apiMock.editComment.mockResolvedValue({})
    apiMock.deleteComment.mockResolvedValue({})
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)

    const user = userEvent.setup()
    render(<MentorView token="mentor-token" />)

    expect(await screen.findByRole('heading', { name: 'Mentor Project' })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/email \(optional/i), 'mentor@example.edu')
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    await user.clear(screen.getByLabelText('Edit comment'))
    await user.type(screen.getByLabelText('Edit comment'), 'Updated note.')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(apiMock.editComment).toHaveBeenCalledWith('mentor-token', 12, 'mentor@example.edu', 'Updated note.')
    expect(await screen.findByText('Updated note.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Delete' }))

    expect(confirm).toHaveBeenCalledWith('Delete this comment?')
    expect(apiMock.deleteComment).toHaveBeenCalledWith('mentor-token', 12, 'mentor@example.edu')
    expect(await screen.findByText('No comments yet.')).toBeInTheDocument()
    expect(apiMock.getMentorView).toHaveBeenCalledTimes(3)

    confirm.mockRestore()
  })
})
