import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MentorView from './MentorView'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getMentorView: vi.fn(),
    addComment: vi.fn(),
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

  it('surfaces mentor share load failures with the request id', async () => {
    apiMock.getMentorView.mockRejectedValue(
      Object.assign(new Error('Share link expired'), { requestId: 'req-share-1' })
    )

    render(<MentorView token="expired-token" />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Share link expired (Request ID: req-share-1)')
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
})
