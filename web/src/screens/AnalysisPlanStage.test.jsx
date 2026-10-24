import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AnalysisPlanStage from './AnalysisPlanStage'
import { AppCtx } from '../App'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getProject: vi.fn(),
    recommendPlan: vi.fn(),
    confirmPlan: vi.fn(),
    overridePlan: vi.fn(),
    validatePlan: vi.fn(),
  },
}))
vi.mock('../api', () => ({ api: apiMock }))

function makeItem(overrides = {}) {
  return {
    id: 'descriptive_summary-1',
    template: 'descriptive_summary',
    display_name: 'Summary of Falls',
    question: 'What was the average falls count?',
    rationale: 'Establishes baseline distribution.',
    parameters: { value_cols: ['falls'] },
    param_confidence: { value_cols: 'high' },
    assumptions: ['Non-negative counts'],
    limitations: ['No temporal ordering'],
    needs_clarification: false,
    executable: true,
    errors: [],
    missing_params: [],
    ...overrides,
  }
}

beforeEach(() => {
  apiMock.getProject.mockResolvedValue({ id: 1, ai_analysis_plan: null, ai_plan_history: null })
  apiMock.validatePlan.mockResolvedValue({ items: [], feasible_templates: ['descriptive_summary', 'run_chart'] })
  apiMock.confirmPlan.mockResolvedValue({ confirmed: true })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function renderScreen(ctxOverrides = {}, extra = {}) {
  const value = {
    ...extra,
    ctx: {
      projectId: 1,
      uploadId: 10,
      colTypes: { month: 'Date', falls: 'Number' },
      ...ctxOverrides,
    },
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

describe('AnalysisPlanStage rich plan review', () => {
  it('enables Continue only once all analyses are executable, and confirmed plan holds the full array', async () => {
    const item1 = makeItem()
    const item2 = makeItem({ id: 'run_chart-2', template: 'run_chart', display_name: 'Run Chart', executable: true })
    apiMock.recommendPlan.mockResolvedValue({
      message: 'Here is your plan',
      confirmed: false,
      analyses: [item1, item2],
      turns: [{ role: 'ai', content: 'Here is your plan' }],
    })
    const user = userEvent.setup()
    const value = renderScreen()

    await waitFor(() => expect(apiMock.recommendPlan).toHaveBeenCalled())
    expect(await screen.findByText('Summary of Falls')).toBeInTheDocument()
    expect(screen.getByText('Run Chart')).toBeInTheDocument()

    const continueBtn = screen.getByRole('button', { name: 'Continue' })
    expect(continueBtn).toBeEnabled()

    await user.click(continueBtn)
    expect(await screen.findByRole('heading', { name: 'Final Confirmation' })).toBeInTheDocument()

    const runBtn = screen.getByRole('button', { name: 'Run these analyses' })
    await user.click(runBtn)

    await waitFor(() => {
      expect(apiMock.confirmPlan).toHaveBeenCalledWith(1, expect.arrayContaining([
        expect.objectContaining({ id: 'descriptive_summary-1' }),
        expect.objectContaining({ id: 'run_chart-2' }),
      ]))
      expect(value.update).toHaveBeenCalledWith(expect.objectContaining({
        analysisPlan: expect.arrayContaining([
          expect.objectContaining({ template: 'descriptive_summary' }),
          expect.objectContaining({ template: 'run_chart' }),
        ]),
      }))
      expect(value.next).toHaveBeenCalled()
    })
  })

  it('removes an analysis card and updates the plan', async () => {
    const item1 = makeItem()
    const item2 = makeItem({ id: 'run_chart-2', template: 'run_chart', display_name: 'Run Chart' })
    apiMock.recommendPlan.mockResolvedValue({
      message: 'Plan',
      confirmed: false,
      analyses: [item1, item2],
      turns: [],
    })
    const user = userEvent.setup()
    renderScreen()

    await screen.findByText('Summary of Falls')
    expect(screen.getByText('Run Chart')).toBeInTheDocument()

    const showDetailsButtons = screen.getAllByRole('button', { name: /Show assumptions, limitations & parameters/ })
    await user.click(showDetailsButtons[0])

    const removeBtn = screen.getByRole('button', { name: 'Remove this analysis' })
    await user.click(removeBtn)

    await waitFor(() => {
      expect(screen.queryByText('Summary of Falls')).not.toBeInTheDocument()
      expect(screen.getByText('Run Chart')).toBeInTheDocument()
    })
  })

  it('adds a feasible analysis via the picker', async () => {
    const item1 = makeItem()
    apiMock.recommendPlan.mockResolvedValue({
      message: 'Plan',
      confirmed: false,
      analyses: [item1],
      turns: [],
    })
    apiMock.validatePlan.mockResolvedValue({ items: [], feasible_templates: ['descriptive_summary', 'run_chart'] })
    const user = userEvent.setup()
    renderScreen()

    await screen.findByText('Summary of Falls')

    const addSelect = await screen.findByLabelText('Add an analysis')
    await user.selectOptions(addSelect, 'run_chart')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    await waitFor(() => {
      expect(screen.getByText('Run Chart')).toBeInTheDocument()
    })
  })

  it('blocks Continue while any analysis is not executable due to low confidence or missing params', async () => {
    const blockedItem = makeItem({
      id: 'run_chart-2',
      template: 'run_chart',
      display_name: 'Run Chart',
      executable: false,
      missing_params: ['date_col'],
      param_confidence: { value_col: 'low' },
    })
    apiMock.recommendPlan.mockResolvedValue({
      message: 'Plan',
      confirmed: false,
      analyses: [makeItem(), blockedItem],
      turns: [],
    })
    renderScreen()

    await screen.findByText('Run Chart')
    expect(screen.getByText('Needs your input')).toBeInTheDocument()

    const continueBtn = screen.getByRole('button', { name: 'Continue' })
    expect(continueBtn).toBeDisabled()
  })

  it('blocks Continue for a low-confidence executable item until the user acknowledges it', async () => {
    const lowConfidenceItem = makeItem({
      id: 'run_chart-2',
      template: 'run_chart',
      display_name: 'Run Chart',
      executable: true,
      needs_clarification: true,
      param_confidence: { value_col: 'low' },
    })
    apiMock.recommendPlan.mockResolvedValue({
      message: 'Plan',
      confirmed: false,
      analyses: [makeItem(), lowConfidenceItem],
      turns: [],
    })
    const user = userEvent.setup()
    renderScreen()

    await screen.findByText('Run Chart')
    const continueBtn = screen.getByRole('button', { name: 'Continue' })
    expect(continueBtn).toBeDisabled()

    const showDetailsButtons = screen.getAllByRole('button', { name: /Show assumptions, limitations & parameters/ })
    await user.click(showDetailsButtons[1])
    const ackBtn = screen.getByRole('button', { name: "I've reviewed this" })
    await user.click(ackBtn)

    await waitFor(() => expect(continueBtn).toBeEnabled())

    await user.click(continueBtn)
    await user.click(await screen.findByRole('button', { name: 'Run these analyses' }))
    await waitFor(() => expect(apiMock.confirmPlan).toHaveBeenCalled())
    const sent = apiMock.confirmPlan.mock.calls[0][1]
    expect(sent.filter(a => a.flag_reviewed).length).toBe(1)
  })

  it('submits an override request and shows what changed', async () => {
    apiMock.recommendPlan.mockResolvedValue({
      message: 'Plan',
      confirmed: false,
      analyses: [makeItem()],
      turns: [],
    })
    apiMock.overridePlan.mockResolvedValue({
      message: 'Adjusted',
      changes: ['Added run chart for simplified timeline plotting.'],
      confirmed: false,
      analyses: [makeItem({ id: 'run_chart-1', template: 'run_chart', display_name: 'Run Chart' })],
    })
    const user = userEvent.setup()
    renderScreen()

    await screen.findByText('Summary of Falls')

    const overrideBox = screen.getByPlaceholderText(/Use a paired test instead/)
    await user.type(overrideBox, 'Use a run chart instead')
    await user.click(screen.getByRole('button', { name: 'Submit request' }))

    await waitFor(() => {
      expect(apiMock.overridePlan).toHaveBeenCalledWith(1, 'Use a run chart instead')
      expect(screen.getByText('Added run chart for simplified timeline plotting.')).toBeInTheDocument()
    })
  })
})

describe('AnalysisPlanStage with the advisor off', () => {
  it('shows a plain message instead of a crash when override-plan returns advisor_unavailable', async () => {
    apiMock.recommendPlan.mockResolvedValue({
      message: 'Plan', confirmed: false, analyses: [makeItem()], turns: [{ role: 'ai', content: 'Plan' }],
    })
    apiMock.overridePlan.mockRejectedValue(Object.assign(new Error('Advisor unavailable'), { code: 'advisor_unavailable' }))
    const user = userEvent.setup()
    renderScreen()
    await user.type(await screen.findByPlaceholderText(/paired test instead/), 'drop the run chart')
    await user.click(screen.getByRole('button', { name: 'Submit request' }))
    expect(await screen.findByText('The QI Stat Advisor is off; edit the plan items directly')).toBeInTheDocument()
    expect(screen.getByText('Summary of Falls')).toBeInTheDocument()
  })

  it('hides the advisor request box and conversation when the advisor is off', async () => {
    apiMock.recommendPlan.mockResolvedValue({
      message: 'Here is your plan',
      confirmed: false,
      analyses: [makeItem({ needs_clarification: true })],
      turns: [{ role: 'ai', content: 'Here is your plan' }],
    })
    renderScreen({}, { advisorOff: true })

    expect(await screen.findByText('Summary of Falls')).toBeInTheDocument()
    expect(screen.queryByText('Ask for a different approach')).not.toBeInTheDocument()
    expect(screen.queryByText('Conversation history')).not.toBeInTheDocument()
    expect(screen.getByText(/chosen automatically and are not certain/)).toBeInTheDocument()
  })

  it('names the templates in the add-analysis list the way the rest of the app does', async () => {
    apiMock.recommendPlan.mockResolvedValue({
      message: 'Here is your plan', confirmed: false, analyses: [makeItem()], turns: [],
    })
    renderScreen()
    expect(await screen.findByRole('option', { name: 'Run Chart' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'run chart' })).not.toBeInTheDocument()
  })

  it('puts a visible Remove button next to an analysis that cannot run', async () => {
    apiMock.recommendPlan.mockResolvedValue({
      message: 'Plan', confirmed: false, turns: [],
      analyses: [makeItem(), makeItem({ id: 'before_after_mean-2', template: 'before_after_mean', display_name: 'Before/after mean', executable: false, errors: ["Pre group 'x' is not present in column 'unit'"] })],
    })
    const user = userEvent.setup()
    renderScreen()
    const remove = await screen.findByRole('button', { name: /cannot run on your data. Remove it/ })
    await user.click(remove)
    expect(screen.queryByText('Before/after mean')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled()
  })
})
