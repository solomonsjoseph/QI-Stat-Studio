import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import Results from './Results'

const { apiMock, useAppMock } = vi.hoisted(() => ({
  apiMock: {
    runPlan: vi.fn(),
    interpretResults: vi.fn(),
  },
  useAppMock: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../App', () => ({ useApp: useAppMock }))

beforeEach(() => {
  apiMock.runPlan.mockReset()
  apiMock.interpretResults.mockReset()
  useAppMock.mockReset()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function baseCtx(overrides = {}) {
  return {
    projectId: 1,
    uploadId: 10,
    analysisPlan: [
      { template: 'descriptive_summary', parameters: { value_cols: ['falls'] } },
      { template: 'before_after_mean', parameters: { group_col: 'period', value_col: 'falls', pre_val: 'pre', post_val: 'post' } },
    ],
    ...overrides,
  }
}

describe('Results multi-run rendering', () => {
  it('executes run-plan and interpret-results, then renders one section per run grouped by category', async () => {
    const update = vi.fn()
    const next = vi.fn()
    useAppMock.mockReturnValue({ ctx: baseCtx(), update, next, prev: vi.fn() })

    apiMock.runPlan.mockResolvedValue({
      runs: [
        { run_id: 1, template: 'descriptive_summary', status: 'ok', result_summary: 'Average falls: 2.5', table: [], figure_base64: null },
        { run_id: 2, template: 'before_after_mean', status: 'ok', result_summary: 'Mean decreased from 3 to 1', table: [], figure_base64: null },
      ],
      failures: [],
    })
    apiMock.interpretResults.mockResolvedValue({
      interpretations: [
        { run_id: 1, text: 'Falls were stable at baseline.' },
        { run_id: 2, text: 'The decrease was statistically significant.' },
      ],
      limitations: ['Single site, no randomization'],
      abstract_draft: 'Background: ...',
    })

    render(<Results />)

    expect(await screen.findByText('What the data show (descriptive)')).toBeInTheDocument()
    expect(screen.getByText('Statistical tests')).toBeInTheDocument()
    expect(screen.getByText('Average falls: 2.5')).toBeInTheDocument()
    expect(screen.getByText('Mean decreased from 3 to 1')).toBeInTheDocument()
    expect(screen.getByText('Falls were stable at baseline.')).toBeInTheDocument()
    expect(screen.getByText('The decrease was statistically significant.')).toBeInTheDocument()

    await waitFor(() => {
      expect(apiMock.runPlan).toHaveBeenCalledWith(1, 10, [
        { template: 'descriptive_summary', parameters: { value_cols: ['falls'] } },
        { template: 'before_after_mean', parameters: { group_col: 'period', value_col: 'falls', pre_val: 'pre', post_val: 'post' } },
      ])
      expect(apiMock.interpretResults).toHaveBeenCalledWith(1)
      expect(update).toHaveBeenCalledWith(expect.objectContaining({ runs: expect.any(Array) }))
    })
  })

  it('renders failures with a back-to-plan link naming the errors, without blocking successful runs', async () => {
    useAppMock.mockReturnValue({ ctx: baseCtx(), update: vi.fn(), next: vi.fn(), prev: vi.fn() })

    apiMock.runPlan.mockResolvedValue({
      runs: [
        { run_id: 1, template: 'descriptive_summary', status: 'ok', result_summary: 'Average falls: 2.5' },
      ],
      failures: [
        { template: 'before_after_mean', status: 'error', errors: ['Column not found: bogus_col'] },
      ],
    })
    apiMock.interpretResults.mockResolvedValue({ interpretations: [], limitations: [], abstract_draft: '' })

    render(<Results />)

    expect(await screen.findByText('Some analyses could not be run')).toBeInTheDocument()
    expect(screen.getByText('Column not found: bogus_col')).toBeInTheDocument()
    expect(screen.getByText('Average falls: 2.5')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Back to plan' })).toBeInTheDocument()
  })

  it('does not re-execute the plan when ctx.runs is already hydrated from resume', async () => {
    const hydratedRuns = [
      { run_id: 5, template: 'descriptive_summary', status: 'ok', result_summary: 'Resumed summary', ai_interpretation: 'Resumed interpretation' },
    ]
    useAppMock.mockReturnValue({
      ctx: baseCtx({ runs: hydratedRuns }),
      update: vi.fn(),
      next: vi.fn(),
      prev: vi.fn(),
    })

    render(<Results />)

    expect(await screen.findByText('Resumed summary')).toBeInTheDocument()
    expect(screen.getByText('Resumed interpretation')).toBeInTheDocument()
    expect(apiMock.runPlan).not.toHaveBeenCalled()
    expect(apiMock.interpretResults).not.toHaveBeenCalled()
  })

  it('surfaces run-plan errors with a retry action', async () => {
    useAppMock.mockReturnValue({ ctx: baseCtx(), update: vi.fn(), next: vi.fn(), prev: vi.fn() })

    apiMock.runPlan.mockRejectedValue(Object.assign(new Error('Upload not found'), { requestId: 'req-9' }))

    render(<Results />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Upload not found (Request ID: req-9)')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
