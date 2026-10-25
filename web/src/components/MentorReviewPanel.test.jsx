import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MentorReviewPanel from './MentorReviewPanel'

const { apiMock } = vi.hoisted(() => ({ apiMock: { getMentorReview: vi.fn(), replyToComment: vi.fn() } }))
vi.mock('../api', () => ({ api: apiMock }))

const OPEN = { id: 5, author_name: 'Dr Rivera', text: 'State how missing A1c was handled.', resident_reply: null, addressed_at: null, resolved_at: null }

beforeEach(() => {
  apiMock.getMentorReview.mockReset()
  apiMock.replyToComment.mockReset().mockResolvedValue({})
})
afterEach(cleanup)

describe('MentorReviewPanel', () => {
  it('lists comments with their status and sends the resident reply, then reloads', async () => {
    apiMock.getMentorReview
      .mockResolvedValueOnce({ comments: [OPEN], approval: null })
      .mockResolvedValueOnce({ comments: [{ ...OPEN, resident_reply: 'Added to methods.', addressed_at: '2026-10-24T10:00:00' }], approval: null })
    const user = userEvent.setup()
    render(<MentorReviewPanel projectId={7} refreshKey="" />)

    expect(await screen.findByText('State how missing A1c was handled.')).toBeInTheDocument()
    expect(screen.getByTestId('review-status')).toHaveTextContent('Open')
    await user.type(screen.getByLabelText('What did you do about this?'), 'Added to methods.')
    await user.click(screen.getByRole('button', { name: 'Mark addressed' }))

    expect(apiMock.replyToComment).toHaveBeenCalledWith(7, 5, 'Added to methods.')
    expect(await screen.findByText('Addressed, waiting for the mentor')).toBeInTheDocument()
  })

  it('shows the approval and says when every comment is resolved', async () => {
    apiMock.getMentorReview.mockResolvedValue({
      comments: [{ ...OPEN, addressed_at: '2026-10-24T10:00:00', resolved_at: '2026-10-24T11:00:00' }],
      approval: { approved_at: '2026-10-24T12:00:00', approved_by_name: 'Dr Rivera', approved_note: 'Good work.' },
    })
    render(<MentorReviewPanel projectId={7} refreshKey="" />)
    expect(await screen.findByText(/Approved by Dr Rivera/)).toBeInTheDocument()
    expect(screen.getByText(/The mentor has resolved every comment/)).toBeInTheDocument()
  })

  it('shows what went wrong when the review cannot be loaded', async () => {
    apiMock.getMentorReview.mockRejectedValue(Object.assign(new Error('Not found'), { requestId: 'req-3' }))
    render(<MentorReviewPanel projectId={7} refreshKey="" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Not found (Request ID: req-3)')
  })
})
