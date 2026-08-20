import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AnalysisPlanStage from './AnalysisPlanStage'
import { AppCtx } from '../App'

const { apiMock } = vi.hoisted(() => ({
  apiMock: { getProject: vi.fn(), recommendPlan: vi.fn(), scrubPreview: vi.fn(), updateColumnMap: vi.fn() },
}))
vi.mock('../api', () => ({ api: apiMock }))

beforeEach(() => {
  apiMock.getProject.mockResolvedValue({ id: 1, ai_analysis_plan: null })
  apiMock.updateColumnMap.mockResolvedValue({ ok: true })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function renderScreen() {
  const value = {
    ctx: { projectId: 1, uploadId: 20, colTypes: { fall_date: 'Date', value: 'Number' } },
    update: vi.fn(),
    next: vi.fn(),
    prev: vi.fn(),
  }
  render(
    <AppCtx.Provider value={value}>
      <AnalysisPlanStage />
    </AppCtx.Provider>,
  )
  return value
}

describe('AnalysisPlanStage', () => {
  it('immediately requests a recommendation on mount without requiring a click, and shows multiple recommended analyses', async () => {
    apiMock.recommendPlan.mockResolvedValue({
      message: "Here's what I recommend...",
      confirmed: false,
      analyses: [
        { template: 'descriptive_summary', rationale: 'Baseline picture.', parameters: { value_cols: ['value'] } },
        { template: 'run_chart', rationale: 'Shows the trend.', parameters: { date_col: 'fall_date', value_col: 'value' } },
      ],
      turns: [{ role: 'ai', content: "Here's what I recommend..." }],
    })
    renderScreen()

    await waitFor(() => expect(apiMock.recommendPlan).toHaveBeenCalledWith(1, null))
    expect(await screen.findByText('Descriptive Summary')).toBeInTheDocument()
    expect(screen.getByText('Run Chart')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
  })

  it('sends a deny message when the resident denies a recommendation and updates the plan from the reply', async () => {
    apiMock.recommendPlan
      .mockResolvedValueOnce({
        message: 'Proposal',
        confirmed: false,
        analyses: [{ template: 'p_chart', rationale: 'not great fit', parameters: {} }],
        turns: [{ role: 'ai', content: 'Proposal' }],
      })
      .mockResolvedValueOnce({
        message: 'Removed p_chart, using run_chart instead.',
        confirmed: false,
        analyses: [{ template: 'run_chart', rationale: 'better fit', parameters: { date_col: 'fall_date', value_col: 'value' } }],
        turns: [{ role: 'ai', content: 'Proposal' }, { role: 'user', content: 'Please remove the p-Chart recommendation from the plan.' }, { role: 'ai', content: 'Removed p_chart, using run_chart instead.' }],
      })
    const user = userEvent.setup()
    renderScreen()

    await screen.findByText('p-Chart')
    await user.click(screen.getByRole('button', { name: 'Deny' }))

    await waitFor(() => {
      expect(apiMock.recommendPlan).toHaveBeenLastCalledWith(1, 'Please remove the p-Chart recommendation from the plan.')
    })
    expect(await screen.findByText('Run Chart')).toBeInTheDocument()
    expect(screen.queryByText('p-Chart')).not.toBeInTheDocument()
  })

  it('enables Continue only once confirmed, and sets ctx.template/params from the first analysis in the confirmed plan', async () => {
    apiMock.recommendPlan.mockResolvedValue({
      message: 'Final plan confirmed.',
      confirmed: true,
      analyses: [
        { template: 'run_chart', rationale: 'Shows the trend.', parameters: { date_col: 'fall_date', value_col: 'value' } },
        { template: 'descriptive_summary', rationale: 'Baseline.', parameters: { value_cols: ['value'] } },
      ],
      turns: [{ role: 'ai', content: 'Final plan confirmed.' }],
    })
    const user = userEvent.setup()
    const value = renderScreen()

    const continueButton = await screen.findByRole('button', { name: 'Continue' })
    await waitFor(() => expect(continueButton).toBeEnabled())
    await user.click(continueButton)

    expect(value.update).toHaveBeenCalledWith(
      expect.objectContaining({
        template: 'run_chart',
        params: { date_col: 'fall_date', value_col: 'value' },
        columnMap: { date_col: 'fall_date', value_col: 'value' },
        analysisPlan: expect.arrayContaining([expect.objectContaining({ template: 'run_chart' })]),
      }),
    )
    expect(value.next).toHaveBeenCalled()
  })

  it('redacts PHI in the chat input and requires a second Share click before sending', async () => {
    apiMock.recommendPlan.mockResolvedValue({
      message: 'ok',
      confirmed: false,
      analyses: [],
      turns: [{ role: 'ai', content: 'ok' }],
    })
    apiMock.scrubPreview.mockResolvedValue({ text: '[REDACTED] wants a t-test', redacted: true, count: 1 })
    const user = userEvent.setup()
    renderScreen()

    await waitFor(() => expect(apiMock.recommendPlan).toHaveBeenCalledTimes(1))
    await user.type(screen.getByPlaceholderText(/Ask for a different analysis/), 'patient Jane Doe wants a t-test')
    await user.click(screen.getByRole('button', { name: 'Share' }))

    expect(await screen.findByText(/We removed what looked like PHI/)).toBeInTheDocument()
    expect(apiMock.recommendPlan).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: 'Share' }))
    await waitFor(() => expect(apiMock.recommendPlan).toHaveBeenCalledWith(1, '[REDACTED] wants a t-test'))
  })
})
