import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { act } from 'react'
import Results from './Results'

const { apiMock, useAppMock } = vi.hoisted(() => ({
  apiMock: {
    runAnalysis: vi.fn(),
    chat: vi.fn(),
  },
  useAppMock: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../App', () => ({ useApp: useAppMock }))

beforeEach(() => {
  apiMock.runAnalysis.mockReset()
  apiMock.chat.mockReset()
  useAppMock.mockReset()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('Results', () => {
  it('never blocks Edit & Review on AI interpretation loading, and surfaces chat errors with request id', async () => {
    const update = vi.fn()
    const next = vi.fn()
    let rejectChat
    useAppMock.mockReturnValue({
      ctx: {
        projectId: 3,
        uploadId: 4,
        template: 'run_chart',
        params: { date_col: 'week', value_col: 'falls' },
      },
      update,
      next,
    })
    apiMock.runAnalysis.mockResolvedValue({
      run_id: 55,
      result_summary: 'Falls decreased after the intervention.',
      methods: 'Run chart methods.',
    })
    apiMock.chat.mockReturnValue(new Promise((_, reject) => { rejectChat = reject }))

    render(<Results />)

    const editButton = await screen.findByRole('button', { name: /edit & review/i })
    expect(editButton).not.toBeDisabled()
    expect(next).not.toHaveBeenCalled()

    await act(async () => {
      rejectChat(Object.assign(new Error('OpenRouter unavailable'), { requestId: 'req-ai-7' }))
    })

    expect(await screen.findByRole('alert')).toHaveTextContent('OpenRouter unavailable (Request ID: req-ai-7)')
    expect(screen.getByRole('button', { name: /edit & review/i })).not.toBeDisabled()
  })

  it('uses a resumed result interpretation as the edit fallback when no AI interpretation is in context', async () => {
    const update = vi.fn()
    const next = vi.fn()
    const user = userEvent.setup()
    useAppMock.mockReturnValue({
      ctx: {
        projectId: 9,
        results: {
          result_summary: 'Screening improved from 60% to 78%.',
          interpretation: 'Server interpretation from the resumed latest run.',
          methods: 'Before/after proportion methods.',
        },
      },
      update,
      next,
    })

    render(<Results />)

    expect(screen.getByText('Server interpretation from the resumed latest run.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /edit & review/i }))

    expect(update).toHaveBeenCalledWith({ aiInterpretation: 'Server interpretation from the resumed latest run.' })
    expect(next).toHaveBeenCalledTimes(1)
    expect(apiMock.runAnalysis).not.toHaveBeenCalled()
    expect(apiMock.chat).not.toHaveBeenCalled()
  })
  it('lets a failed analysis retry and keeps the column-mapping back action available', async () => {
    const update = vi.fn()
    const next = vi.fn()
    const prev = vi.fn()
    const user = userEvent.setup()
    useAppMock.mockReturnValue({
      ctx: {
        projectId: 11,
        uploadId: 22,
        template: 'run_chart',
        params: { date_col: 'week', value_col: 'falls', intervention_date: '2026-01-15' },
      },
      update,
      next,
      prev,
    })
    apiMock.runAnalysis.mockRejectedValueOnce(Object.assign(new Error('Analysis backend timed out'), { requestId: 'req-analysis-42' }))
    apiMock.chat.mockResolvedValue({ content: 'Falls improved after the intervention.', phi_redacted: false })

    render(<Results />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Analysis backend timed out (Request ID: req-analysis-42)')
    const retryButton = screen.getByRole('button', { name: 'Try again' })
    const backButton = screen.getByRole('button', { name: '← Back to column mapping' })

    await user.click(backButton)
    expect(prev).toHaveBeenCalledTimes(1)

    apiMock.runAnalysis.mockResolvedValueOnce({
      run_id: 88,
      result_summary: 'Falls decreased from 12 to 7 per month after the intervention.',
      methods: 'Run chart methods.',
    })
    await user.click(retryButton)

    await waitFor(() => expect(apiMock.runAnalysis).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('Falls decreased from 12 to 7 per month after the intervention.')).toBeInTheDocument()
  })
})
