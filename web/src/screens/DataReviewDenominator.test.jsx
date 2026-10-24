import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DataReview from './DataReview'

const { apiMock, useAppMock } = vi.hoisted(() => ({
  apiMock: { getFlagStates: vi.fn(), confirmColTypes: vi.fn() },
  useAppMock: vi.fn(),
}))
vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../App', () => ({ useApp: useAppMock }))

const colTypes = { falls: 'Number', staff: 'Number', days: 'Number', beds: 'Number' }

function mount(columnRoles, design = {}, guessed = ['staff', 'days', 'beds']) {
  useAppMock.mockReturnValue({
    ctx: {
      uploadId: 1, colTypes, qualityFlags: [], acknowledgedFlags: [], design,
      profile: { candidate_roles: { denominator: guessed } },
      columnRoles,
    },
    advisorOff: true, update: vi.fn(), next: vi.fn(), prev: vi.fn(),
  })
  render(<DataReview />)
}

beforeEach(() => { apiMock.getFlagStates.mockReset().mockResolvedValue({ flags: [], unhandled_warning_count: 0, unresolved_error_count: 0 }) })
afterEach(cleanup)

describe('denominator conflict note', () => {
  it('names the column the backend picks for two denominators and keeps Continue enabled', async () => {
    // Backend: saved roles are inserted at the front in saved order, so the last saved wins.
    mount({ falls: 'outcome', staff: 'denominator', days: 'denominator', beds: '' })
    const note = screen.getByRole('status')
    expect(note.textContent).toContain('Two columns are set as Denominator.')
    expect(note.textContent).toContain('The analysis will use days.')
    expect(await screen.findByRole('button', { name: /continue/i })).toBeEnabled()
  })

  it('says N columns for three and names the same winner', () => {
    mount({ falls: 'outcome', staff: 'denominator', days: 'denominator', beds: 'denominator' })
    const note = screen.getByRole('status')
    expect(note.textContent).toContain('3 columns are set as Denominator.')
    expect(note.textContent).toContain('The analysis will use beds.')
  })

  it('prefers the project definition denominator when it exists', () => {
    mount({ staff: 'denominator', days: 'denominator', falls: 'outcome', beds: '' },
      { primary_outcome: { denominator_column: 'staff' } })
    expect(screen.getByRole('status').textContent).toContain('The analysis will use staff.')
  })

  it('shows no note for one denominator and updates when a second is chosen', async () => {
    mount({ falls: 'outcome', staff: 'denominator', days: '', beds: '' }, {}, [])
    expect(screen.queryByText(/set as Denominator/)).toBeNull()
    await userEvent.selectOptions(screen.getByLabelText('Role for days'), 'denominator')
    expect(screen.getByRole('status').textContent).toContain('The analysis will use days.')
  })
})
