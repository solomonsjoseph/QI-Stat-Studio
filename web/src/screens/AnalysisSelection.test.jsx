import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useCallback, useState } from 'react'
import AnalysisSelection from './AnalysisSelection'

const { apiMock, useAppMock } = vi.hoisted(() => ({
  apiMock: {
    recommend: vi.fn(),
  },
  useAppMock: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../App', () => ({ useApp: useAppMock }))

beforeEach(() => {
  apiMock.recommend.mockReset()
  useAppMock.mockReset()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function renderWithApp(ctx, overrides = {}) {
  const update = overrides.update ?? vi.fn()
  const next = overrides.next ?? vi.fn()
  const prev = overrides.prev ?? vi.fn()

  function AppHarness() {
    const [state, setState] = useState(ctx)
    const appUpdate = useCallback((patch) => {
      update(patch)
      setState(current => ({ ...current, ...patch }))
    }, [])

    useAppMock.mockReturnValue({
      ctx: state,
      update: appUpdate,
      next,
      prev,
    })

    return <AnalysisSelection />
  }

  return { ...render(<AppHarness />), update, next, prev }
}

describe('AnalysisSelection', () => {
  it('loads API recommendations in order with rank badges and marks only the recommended option', async () => {
    apiMock.recommend.mockResolvedValue([
      { template: 'run_chart', description: 'Track weekly wait times.', recommended: false },
      { template: 'before_after_mean', description: 'Compare average wait before and after.', recommended: true },
      { template: 'descriptive_summary', description: 'Summarize measures by service line.', recommended: false },
    ])

    renderWithApp({ projectId: 41 })

    await waitFor(() => expect(apiMock.recommend).toHaveBeenCalledWith(41))
    const group = screen.getByRole('radiogroup', { name: /analysis template/i })
    const options = within(group).getAllByRole('button')

    expect(options).toHaveLength(3)
    expect(within(options[0]).getByText('1')).toBeInTheDocument()
    expect(options[0]).toHaveTextContent('Run Chart')
    expect(options[0]).toHaveTextContent('Track weekly wait times.')
    expect(within(options[1]).getByText('2')).toBeInTheDocument()
    expect(options[1]).toHaveTextContent('Before/After: Mean')
    expect(options[1]).toHaveTextContent('Compare average wait before and after.')
    expect(within(options[2]).getByText('3')).toBeInTheDocument()
    expect(options[2]).toHaveTextContent('Descriptive Summary')
    expect(options[2]).toHaveTextContent('Summarize measures by service line.')

    expect(screen.getAllByText('Recommended')).toHaveLength(1)
    expect(within(options[0]).queryByText('Recommended')).not.toBeInTheDocument()
    expect(within(options[1]).getByText('Recommended')).toBeInTheDocument()
    expect(within(options[2]).queryByText('Recommended')).not.toBeInTheDocument()
  })

  it('selecting an option stores its template and clears downstream analysis state', async () => {
    const update = vi.fn()
    const user = userEvent.setup()
    apiMock.recommend.mockResolvedValue([
      { template: 'before_after_pct', description: 'Compare percent at goal before and after.', recommended: true },
      { template: 'p_chart', description: 'Track monthly proportion at goal.', recommended: false },
    ])

    renderWithApp({
      projectId: 42,
      template: 'descriptive_summary',
      params: { group_col: 'unit', value_cols: ['hba1c'] },
      columnMap: { group_col: 'unit', value_cols: ['hba1c'] },
      results: { stale: true },
      resultSummary: 'Stale summary must be cleared.',
      runId: 99,
      aiInterpretation: 'Stale AI interpretation must be cleared.',
      editedInterp: 'Stale edited interpretation must be cleared.',
      editedCaption: 'Stale edited caption must be cleared.',
    }, { update })

    await user.click(await screen.findByRole('button', { name: /before\/after: proportion/i }))

    await waitFor(() => expect(update).toHaveBeenCalledTimes(1))
    expect(update.mock.calls[0][0]).toEqual({
      template: 'before_after_pct',
      params: {},
      columnMap: {},
      results: {},
      resultSummary: undefined,
      runId: undefined,
      aiInterpretation: '',
      editedInterp: '',
      editedCaption: '',
    })
  })

  it('falls back to default recommendations and explains that default options are shown when recommendations fail', async () => {
    apiMock.recommend.mockRejectedValue(Object.assign(new Error('Recommendation service unavailable'), { requestId: 'REQ-9' }))

    renderWithApp({ projectId: 43 })

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Recommendation service unavailable')
    expect(alert).toHaveTextContent('Request ID: REQ-9')
    expect(alert).toHaveTextContent('Showing default options.')

    const group = screen.getByRole('radiogroup', { name: /analysis template/i })
    const options = within(group).getAllByRole('button')
    expect(options).toHaveLength(3)
    expect(options[0]).toHaveTextContent('Descriptive Summary')
    expect(options[1]).toHaveTextContent('Before/After: Mean')
    expect(options[2]).toHaveTextContent('Before/After: Proportion')
    expect(screen.getAllByText('Recommended')).toHaveLength(1)
    expect(within(options[0]).getByText('Recommended')).toBeInTheDocument()
    expect(within(options[1]).queryByText('Recommended')).not.toBeInTheDocument()
    expect(within(options[2]).queryByText('Recommended')).not.toBeInTheDocument()
  })

  it('keeps Continue disabled until an option is selected', async () => {
    const user = userEvent.setup()
    apiMock.recommend.mockResolvedValue([
      { template: 'run_chart', description: 'Track a measure over time.', recommended: true },
    ])

    renderWithApp({ projectId: 44 })

    const continueButton = screen.getByRole('button', { name: /continue/i })
    expect(continueButton).toBeDisabled()

    await user.click(await screen.findByRole('button', { name: /run chart/i }))

    await waitFor(() => expect(continueButton).toBeEnabled())
  })
})
