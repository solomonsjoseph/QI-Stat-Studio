import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MentorView from './MentorView'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getMentorView: vi.fn(),
    getMentorHandoff: vi.fn(),
    addComment: vi.fn(),
    editComment: vi.fn(),
    deleteComment: vi.fn(),
    resolveComment: vi.fn(),
    approveReview: vi.fn(),
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
    results: [
      {
        run_id: 1,
        template: 'run_chart',
        methods: 'Weekly fall counts were reviewed.',
        result_summary: 'Falls decreased after the intervention.',
        table: [{ week: '1', falls: 4 }],
      },
    ],
    limitations: [],
    comments: [],
    ...overrides,
  }
}

beforeEach(() => {
  apiMock.getMentorView.mockReset()
  apiMock.getMentorHandoff.mockReset()
  apiMock.getMentorHandoff.mockRejectedValue(new Error('none'))
  apiMock.addComment.mockReset()
  apiMock.editComment.mockReset()
  apiMock.deleteComment.mockReset()
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
    expect(screen.queryByRole('link', { name: /Download Word Report/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Download PDF Report/i })).not.toBeInTheDocument()
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

  it('lets a mentor edit and delete only the comment they wrote, using the secret kept in their browser', async () => {
    window.localStorage.setItem('qiss:comment:mentor-token:12', 'secret-12')
    apiMock.getMentorView
      .mockResolvedValueOnce(mentorPayload({ comments: [
        { id: 12, author_name: 'Dr Mentor', text: 'Original note.' },
        { id: 13, author_name: 'Someone else', text: 'Not mine.' },
      ] }))
      .mockResolvedValueOnce(mentorPayload({ comments: [
        { id: 12, author_name: 'Dr Mentor', text: 'Updated note.' },
        { id: 13, author_name: 'Someone else', text: 'Not mine.' },
      ] }))
      .mockResolvedValueOnce(mentorPayload({ comments: [{ id: 13, author_name: 'Someone else', text: 'Not mine.' }] }))
    apiMock.editComment.mockResolvedValue({})
    apiMock.deleteComment.mockResolvedValue({})
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)

    const user = userEvent.setup()
    render(<MentorView token="mentor-token" />)

    expect(await screen.findByRole('heading', { name: 'Mentor Project' })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Edit' })).toHaveLength(1)  // only the mentor's own comment
    expect(screen.queryByText(/@/)).not.toBeInTheDocument()  // no email shown to other link holders
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    await user.clear(screen.getByLabelText('Edit comment'))
    await user.type(screen.getByLabelText('Edit comment'), 'Updated note.')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(apiMock.editComment).toHaveBeenCalledWith('mentor-token', 12, 'secret-12', 'Updated note.')
    expect(await screen.findByText('Updated note.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Delete' }))

    expect(confirm).toHaveBeenCalledWith('Delete this comment?')
    expect(apiMock.deleteComment).toHaveBeenCalledWith('mentor-token', 12, 'secret-12')
    expect(await screen.findByText('Not mine.')).toBeInTheDocument()
    expect(window.localStorage.getItem('qiss:comment:mentor-token:12')).toBeNull()

    confirm.mockRestore()
  })

  it('shows the resident reply and status, lets the author resolve their comment, and records the sign-off', async () => {
    window.localStorage.setItem('qiss:comment:mentor-token:21', 'secret-21')
    const answered = { id: 21, author_name: 'Dr Mentor', text: 'Please add the date.', resident_reply: 'Added January 2025 to the caption.', addressed_at: '2026-10-24T10:00:00', resolved_at: null }
    apiMock.getMentorView
      .mockResolvedValueOnce(mentorPayload({ comments: [answered], approval: null }))
      .mockResolvedValueOnce(mentorPayload({ comments: [{ ...answered, resolved_at: '2026-10-24T11:00:00' }], approval: null }))
      .mockResolvedValueOnce(mentorPayload({ comments: [{ ...answered, resolved_at: '2026-10-24T11:00:00' }], approval: { approved_at: '2026-10-24T12:00:00', approved_by_name: 'Dr Mentor', approved_note: 'Good work.' } }))
    apiMock.resolveComment.mockResolvedValue({})
    apiMock.approveReview.mockResolvedValue({})
    const user = userEvent.setup()
    render(<MentorView token="mentor-token" />)

    expect(await screen.findByText('Added January 2025 to the caption.')).toBeInTheDocument()
    expect(screen.getByTestId('comment-status')).toHaveTextContent('Addressed by the resident')
    await user.click(screen.getByRole('button', { name: 'Mark resolved' }))
    expect(apiMock.resolveComment).toHaveBeenCalledWith('mentor-token', 21, 'secret-21', true)
    expect(await screen.findByRole('button', { name: 'Reopen' })).toBeInTheDocument()

    await user.type(screen.getByLabelText('Name for the sign-off'), 'Dr Mentor')
    await user.type(screen.getByLabelText('Note (optional)'), 'Good work.')
    await user.click(screen.getByRole('button', { name: 'Approve: good work' }))
    expect(apiMock.approveReview).toHaveBeenCalledWith('mentor-token', 'Dr Mentor', 'Good work.')
    expect(await screen.findByText(/Approved by Dr Mentor/)).toBeInTheDocument()
  })
})
