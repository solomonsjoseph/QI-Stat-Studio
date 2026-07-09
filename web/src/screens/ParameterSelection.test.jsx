import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ParameterSelection from './ParameterSelection'

const { apiMock, useAppMock } = vi.hoisted(() => ({
  apiMock: {
    updateColumnMap: vi.fn(),
  },
  useAppMock: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../App', () => ({ useApp: useAppMock }))

beforeEach(() => {
  apiMock.updateColumnMap.mockReset()
  useAppMock.mockReset()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('ParameterSelection', () => {
  it('clears stale analysis outputs when valid parameters are submitted without clearing the edited title', async () => {
    const update = vi.fn()
    const next = vi.fn()
    const prev = vi.fn()
    const user = userEvent.setup()
    useAppMock.mockReturnValue({
      ctx: {
        uploadId: 17,
        template: 'run_chart',
        colTypes: { week: 'date', falls: 'number', unit: 'text' },
        params: { date_col: 'week', value_col: 'falls', intervention_date: '2026-01-15' },
        results: { result_summary: 'Stale result should not survive.' },
        resultSummary: 'Stale summary should not survive.',
        runId: 4,
        aiInterpretation: 'Stale AI interpretation should not survive.',
        editedInterp: 'Stale edited interpretation should not survive.',
        editedCaption: 'Stale edited caption should not survive.',
        editedTitle: 'Resident-edited title must survive.',
      },
      update,
      next,
      prev,
    })
    apiMock.updateColumnMap.mockResolvedValue({ ok: true })

    render(<ParameterSelection />)
    await user.click(screen.getByRole('button', { name: /run analysis/i }))

    await waitFor(() => expect(update).toHaveBeenCalledTimes(1))
    expect(update).toHaveBeenCalledWith({
      params: { date_col: 'week', value_col: 'falls', intervention_date: '2026-01-15' },
      columnMap: { date_col: 'week', value_col: 'falls' },
      results: {},
      resultSummary: undefined,
      runId: undefined,
      aiInterpretation: '',
      editedInterp: '',
      editedCaption: '',
    })
    expect(update.mock.calls[0][0]).not.toHaveProperty('editedTitle')
    expect(next).toHaveBeenCalledTimes(1)
  })

  it('renders resumed descriptive summary value columns stored as a list', () => {
    const update = vi.fn()
    const next = vi.fn()
    const prev = vi.fn()
    useAppMock.mockReturnValue({
      ctx: {
        uploadId: 18,
        template: 'descriptive_summary',
        colTypes: { unit: 'text', hba1c: 'number', ldl: 'number' },
        params: { group_col: 'unit', value_cols: ['hba1c', 'ldl'] },
      },
      update,
      next,
      prev,
    })

    render(<ParameterSelection />)

    const valueCols = screen.getByRole('listbox', { name: /value columns/i })
    expect(Array.from(valueCols.selectedOptions, option => option.value)).toEqual(['hba1c', 'ldl'])
  })

  it('submits only parameters visible for the active template', async () => {
    const update = vi.fn()
    const next = vi.fn()
    const prev = vi.fn()
    const user = userEvent.setup()
    useAppMock.mockReturnValue({
      ctx: {
        uploadId: 19,
        template: 'before_after_pct',
        colTypes: { period: 'text', a1c_at_goal: 'boolean', month: 'date', wait_days: 'number' },
        params: {
          date_col: 'month',
          value_col: 'wait_days',
          intervention_date: '2026-01-15',
          group_col: 'period',
          outcome_col: 'a1c_at_goal',
          pre_val: 'pre',
          post_val: 'post',
        },
      },
      update,
      next,
      prev,
    })
    apiMock.updateColumnMap.mockResolvedValue({ ok: true })

    render(<ParameterSelection />)
    await user.click(screen.getByRole('button', { name: /run analysis/i }))

    await waitFor(() => expect(update).toHaveBeenCalledTimes(1))
    expect(apiMock.updateColumnMap).toHaveBeenCalledWith(
      19,
      { period: 'text', a1c_at_goal: 'boolean', month: 'date', wait_days: 'number' },
      { group_col: 'period', outcome_col: 'a1c_at_goal' },
    )
    expect(update.mock.calls[0][0].params).toEqual({
      group_col: 'period',
      outcome_col: 'a1c_at_goal',
      pre_val: 'pre',
      post_val: 'post',
    })
  })
})
