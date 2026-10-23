import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DataReview from './DataReview'

const { apiMock, useAppMock } = vi.hoisted(() => ({
  apiMock: {
    saveAcknowledgedFlags: vi.fn(),
    confirmColTypes: vi.fn(),
    getFlagStates: vi.fn(),
    acknowledgeWarnings: vi.fn(),
    createWarningGroup: vi.fn(),
  },
  useAppMock: vi.fn(),
}))
vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../App', () => ({ useApp: useAppMock }))

afterEach(() => { cleanup(); vi.clearAllMocks() })

function mount(flags, states) {
  const value = {
    ctx: { uploadId: 42, colTypes: { age: 'number' }, qualityFlags: flags, acknowledgedFlags: [], advisorAvailable: false },
    advisorAvailable: false, advisorOff: true,
    update: vi.fn(), next: vi.fn(), prev: vi.fn(),
  }
  useAppMock.mockReturnValue(value)
  apiMock.getFlagStates.mockResolvedValue({ upload_id: 42, ...states })
  apiMock.saveAcknowledgedFlags.mockResolvedValue({})
  apiMock.confirmColTypes.mockResolvedValue({})
  render(<DataReview />)
  return value
}

describe('DataReview with the advisor off', () => {
  it('disables Clarify and lets the user continue once warnings are acknowledged', async () => {
    const value = mount(
      [{ id: 'missing_values:age', severity: 'WARNING', msg: 'Age has missing values.' }],
      { flags: [{ flag_id: 'missing_values:age', severity: 'WARNING', state: 'handled', group_id: null, action: 'acknowledge' }], unhandled_warning_count: 0, unresolved_error_count: 0 },
    )
    expect(screen.getByRole('button', { name: /Clarify with QI Stat Advisor/ })).toBeDisabled()
    const go = screen.getByRole('button', { name: /Continue to Analysis Selection/ })
    await waitFor(() => expect(go).toBeEnabled())
    await userEvent.click(go)
    await waitFor(() => expect(value.next).toHaveBeenCalled())
  })

  it('blocks on an ERROR and offers re-upload', async () => {
    const value = mount(
      [{ id: 'outcome_missing_30pct:readmit', severity: 'ERROR', msg: 'Outcome is 40% missing.' }],
      { flags: [{ flag_id: 'outcome_missing_30pct:readmit', severity: 'ERROR', state: 'unhandled', group_id: null, action: null }], unhandled_warning_count: 0, unresolved_error_count: 1 },
    )
    expect(screen.getByRole('button', { name: /Continue to Analysis Selection/ })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: /Re-upload corrected file/ }))
    expect(value.prev).toHaveBeenCalled()
  })
})
