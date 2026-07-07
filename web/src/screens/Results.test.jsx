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
  it('blocks Edit & Review while AI interpretation is loading without a backend fallback and surfaces chat errors with request id', async () => {
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

    const pendingButton = await screen.findByRole('button', { name: /preparing interpretation/i })
    expect(pendingButton).toBeDisabled()
    expect(next).not.toHaveBeenCalled()

    await act(async () => {
      rejectChat(Object.assign(new Error('OpenRouter unavailable'), { requestId: 'req-ai-7' }))
    })

    expect(await screen.findByRole('alert')).toHaveTextContent('OpenRouter unavailable (Request ID: req-ai-7)')
    await waitFor(() => expect(screen.getByRole('button', { name: /edit & review/i })).not.toBeDisabled())
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
})
