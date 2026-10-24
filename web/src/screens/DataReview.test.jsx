import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DataReview from './DataReview'

const { apiMock, useAppMock } = vi.hoisted(() => ({
  apiMock: {
    saveAcknowledgedFlags: vi.fn(),
    confirmColTypes: vi.fn(),
    getFlagStates: vi.fn(),
    acknowledgeWarnings: vi.fn(),
    createWarningGroup: vi.fn(),
    getHandoff: vi.fn(),
    getAdvisorThread: vi.fn(),
    sendAdvisorMessage: vi.fn(),
    confirmAdvisorProposal: vi.fn(),
    declineAdvisorProposal: vi.fn(),
    cancelWarningGroup: vi.fn(),
  },
  useAppMock: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../App', () => ({ useApp: useAppMock }))

beforeEach(() => {
  apiMock.saveAcknowledgedFlags.mockReset()
  apiMock.confirmColTypes.mockReset()
  apiMock.getFlagStates.mockReset().mockRejectedValue(new Error('no endpoint'))
  apiMock.acknowledgeWarnings.mockReset()
  apiMock.createWarningGroup.mockReset()
  apiMock.cancelWarningGroup.mockReset()
  Object.keys(apiMock).filter(k => /Advisor|getHandoff/.test(k)).forEach(k => apiMock[k].mockReset())
  useAppMock.mockReset()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('DataReview', () => {
  function mountWarnings(ctxExtra = {}, flags) {
    useAppMock.mockReturnValue({
      ctx: {
        uploadId: 42,
        colTypes: { age: 'number' },
        qualityFlags: flags || [
          { id: 'missing_values:age', severity: 'WARNING', msg: 'Age has missing values.' },
          { id: 'duplicate_rows:*', severity: 'WARNING', msg: 'Duplicate rows found.' },
          { id: 'outcome_missing_30pct:readmit', severity: 'ERROR', msg: 'Outcome is 40% missing.' },
        ],
        acknowledgedFlags: [],
        ...ctxExtra,
      },
      advisorOff: ctxExtra.advisorOff ?? false,
      update: vi.fn(), next: vi.fn(), prev: vi.fn(),
    })
  }
  const states = (flags, unhandled, errs) => ({
    upload_id: 42, flags, unhandled_warning_count: unhandled, unresolved_error_count: errs,
  })
  const st = (flag_id, state, severity = 'WARNING', group_id = null, action = null) => ({ flag_id, severity, state, group_id, action })
  const info = (group_id, message) => ({ group_id, group_status: 'discussing', message, proposals: [], needs_user_confirmation: false, proposal_id: null, mode: 'info', unapplied_notes: [] })
  const proposal = (group_id, mode = 'propose') => ({
    group_id, group_status: 'discussing', message: 'I would merge MG into mg. Confirm?', mode,
    needs_user_confirmation: true, proposal_id: `p_${group_id}_3`, unapplied_notes: [],
    proposals: [{
      warning_id: 'category_variants:unit', summary: 'Merge MG into mg',
      steps: [{ op: 'merge_values', column: 'unit', from: ['MG'], to: 'mg', warning_ids: ['category_variants:unit'], note: '' }],
      dry_run: [{ description: "Merge 'MG' into 'mg' in unit", rows_changed: 14 }],
    }],
  })
  const unitFlags = [
    { id: 'category_variants:unit', severity: 'WARNING', msg: 'Unit has case variants.' },
    { id: 'missing_values:age', severity: 'WARNING', msg: 'Age has missing values.' },
  ]
  // Opens the Clarify chat for the unit warning and returns the user event.
  async function openChat(firstReply) {
    const user = userEvent.setup()
    apiMock.getFlagStates.mockResolvedValue(states([
      st('category_variants:unit', 'unhandled'), st('missing_values:age', 'unhandled'),
    ], 2, 0))
    apiMock.createWarningGroup.mockResolvedValue({ id: 8, action: 'clarify', status: 'open' })
    apiMock.sendAdvisorMessage.mockResolvedValueOnce(firstReply)
    mountWarnings({}, unitFlags)
    render(<DataReview />)
    await waitFor(() => expect(apiMock.getFlagStates).toHaveBeenCalled())
    await user.click(screen.getByRole('checkbox', { name: /Unit has case variants/ }))
    await user.click(screen.getByRole('button', { name: 'Clarify with QI Stat Advisor' }))
    return user
  }

  it('shows the instruction line and marks only the handled warning as settled and not selectable', async () => {
    apiMock.getFlagStates.mockResolvedValue(states([
      st('missing_values:age', 'unhandled'), st('duplicate_rows:*', 'handled'),
      st('outcome_missing_30pct:readmit', 'open', 'ERROR'),
    ], 1, 1))
    mountWarnings()
    render(<DataReview />)

    expect(screen.getByText(/Tick the warnings you want to handle/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('state-duplicate_rows:*')).toHaveTextContent('Handled'))
    expect(screen.getByRole('checkbox', { name: /Duplicate rows found/ })).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: /Age has missing values/ })).toBeEnabled()
    expect(screen.getByTestId('state-outcome_missing_30pct:readmit')).toHaveTextContent('Clarify started')
  })

  it('matches flags without an id by message', async () => {
    apiMock.getFlagStates.mockResolvedValue(states([st('Old warning', 'handled')], 0, 0))
    mountWarnings({}, [{ severity: 'WARNING', msg: 'Old warning' }])
    render(<DataReview />)
    await waitFor(() => expect(screen.getByRole('checkbox', { name: /Old warning/ })).toBeDisabled())
  })

  it('selects all, shows the count, and acknowledges the selection in one call', async () => {
    const user = userEvent.setup()
    apiMock.getFlagStates.mockResolvedValue(states([
      st('missing_values:age', 'unhandled'), st('duplicate_rows:*', 'unhandled'),
    ], 2, 0))
    apiMock.acknowledgeWarnings.mockResolvedValue({ id: 10, status: 'handled' })
    mountWarnings({}, [
      { id: 'missing_values:age', severity: 'WARNING', msg: 'Age has missing values.' },
      { id: 'duplicate_rows:*', severity: 'WARNING', msg: 'Duplicate rows found.' },
    ])
    render(<DataReview />)
    await waitFor(() => expect(apiMock.getFlagStates).toHaveBeenCalledWith(42))

    expect(screen.getByRole('button', { name: 'Acknowledge selected' })).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: 'Select all' }))
    expect(screen.getByText('2 selected')).toBeInTheDocument()

    apiMock.getFlagStates.mockResolvedValue(states([
      st('missing_values:age', 'handled'), st('duplicate_rows:*', 'handled'),
    ], 0, 0))
    await user.click(screen.getByRole('button', { name: 'Acknowledge selected' }))

    expect(apiMock.acknowledgeWarnings).toHaveBeenCalledTimes(1)
    expect(apiMock.acknowledgeWarnings).toHaveBeenCalledWith(42, ['missing_values:age', 'duplicate_rows:*'])
    await waitFor(() => expect(screen.getByRole('button', { name: /Continue to Analysis Selection/ })).toBeEnabled())
    expect(screen.getByText('0 selected')).toBeInTheDocument()
  })

  it('disables Acknowledge with a reason when an ERROR is selected, and Clarify creates a group', async () => {
    const user = userEvent.setup()
    const onOpenClarify = vi.fn()
    apiMock.getFlagStates.mockResolvedValue(states([
      st('missing_values:age', 'unhandled'), st('outcome_missing_30pct:readmit', 'unhandled', 'ERROR'),
    ], 1, 1))
    apiMock.createWarningGroup.mockResolvedValue({ id: 9, action: 'clarify', status: 'open' })
    apiMock.sendAdvisorMessage.mockResolvedValue(info(9, 'I see 40% missing outcomes.'))
    mountWarnings({}, [
      { id: 'missing_values:age', severity: 'WARNING', msg: 'Age has missing values.' },
      { id: 'outcome_missing_30pct:readmit', severity: 'ERROR', msg: 'Outcome is 40% missing.' },
    ])
    render(<DataReview onOpenClarify={onOpenClarify} />)
    await waitFor(() => expect(apiMock.getFlagStates).toHaveBeenCalled())

    await user.click(screen.getByRole('checkbox', { name: /Outcome is 40% missing/ }))
    expect(screen.getByRole('button', { name: 'Acknowledge selected' })).toBeDisabled()
    expect(screen.getByText(/Errors can only go through Clarify/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Clarify with QI Stat Advisor' }))
    expect(apiMock.createWarningGroup).toHaveBeenCalledWith(42, ['outcome_missing_30pct:readmit'], 'clarify')
    expect(onOpenClarify).toHaveBeenCalledWith(9, ['outcome_missing_30pct:readmit'])
    expect(await screen.findByText('I see 40% missing outcomes.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Continue to Analysis Selection/ })).toBeDisabled()
  })

  it('keeps Continue disabled while an error is unresolved even with no unhandled warnings', async () => {
    apiMock.getFlagStates.mockResolvedValue(states([st('outcome_missing_30pct:readmit', 'discussing', 'ERROR')], 0, 1))
    mountWarnings({}, [{ id: 'outcome_missing_30pct:readmit', severity: 'ERROR', msg: 'Outcome is 40% missing.' }])
    render(<DataReview />)
    await waitFor(() => expect(apiMock.getFlagStates).toHaveBeenCalled())
    expect(screen.getByRole('button', { name: /Continue to Analysis Selection/ })).toBeDisabled()
  })

  it('keeps Continue disabled with a status while a re-upload choice is pending', async () => {
    apiMock.getFlagStates.mockResolvedValue({ ...states([], 0, 0), pending_choice: true })
    mountWarnings({}, [])
    render(<DataReview />)
    expect(await screen.findByRole('status')).toHaveTextContent('Choose whether to keep your earlier changes or start fresh above.')
    expect(screen.getByRole('button', { name: /Continue to Analysis Selection/ })).toBeDisabled()
  })

  it('disables Clarify but not Acknowledge when the advisor is unavailable', async () => {
    const user = userEvent.setup()
    apiMock.getFlagStates.mockResolvedValue(states([st('missing_values:age', 'unhandled')], 1, 0))
    mountWarnings({ advisorOff: true }, [
      { id: 'missing_values:age', severity: 'WARNING', msg: 'Age has missing values.' },
    ])
    render(<DataReview />)
    await waitFor(() => expect(apiMock.getFlagStates).toHaveBeenCalled())
    await user.click(screen.getByRole('checkbox', { name: /Age has missing values/ }))

    expect(screen.getByText(/The QI Stat Advisor is not available/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Clarify with QI Stat Advisor' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Acknowledge selected' })).toBeEnabled()
  })

  it('shows an error with Retry and keeps Continue off when flag states fail to load', async () => {
    const user = userEvent.setup()
    mountWarnings({ acknowledgedFlags: [{ id: 'duplicate_rows:*', severity: 'WARNING', msg: 'Duplicate rows found.' }] }, [
      { id: 'duplicate_rows:*', severity: 'WARNING', msg: 'Duplicate rows found.' },
    ])
    render(<DataReview />)
    expect(await screen.findByRole('alert')).toHaveTextContent('no endpoint')
    expect(screen.getByRole('button', { name: /Continue to Analysis Selection/ })).toBeDisabled()
    apiMock.getFlagStates.mockResolvedValue(states([st('duplicate_rows:*', 'handled')], 0, 0))
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /Continue to Analysis Selection/ })).toBeEnabled())
  })

  it('renders collection guidance grouped by necessity', () => {
    useAppMock.mockReturnValue({
      ctx: {
        colTypes: { month: 'Date', falls: 'Number' },
        qualityFlags: [],
        acknowledgedFlags: [],
        collectionRecs: [
          { id: 'missing-denominator', title: 'Denominator column needed', why: 'Rate calc requires it', severity: 'important', necessity: 'required' },
          { id: 'no-balancing-measure', title: 'Consider a balancing measure', why: 'Detect harm elsewhere', severity: 'info', necessity: 'optional' },
        ],
      },
      update: vi.fn(),
      next: vi.fn(),
      prev: vi.fn(),
    })

    render(<DataReview />)

    expect(screen.getByText('Required to run an analysis')).toBeInTheDocument()
    expect(screen.getByText('Denominator column needed')).toBeInTheDocument()
    expect(screen.getByText('Optional future improvement')).toBeInTheDocument()
    expect(screen.getByText('Consider a balancing measure')).toBeInTheDocument()
  })

  it('renders a role selector per column seeded from candidate roles', () => {
    useAppMock.mockReturnValue({
      ctx: {
        colTypes: { month: 'Date', falls: 'Number', patient_days: 'Number' },
        qualityFlags: [],
        acknowledgedFlags: [],
        profile: {
          candidate_roles: {
            date: ['month'],
            outcome: ['falls'],
            denominator: ['patient_days'],
          },
        },
      },
      update: vi.fn(),
      next: vi.fn(),
      prev: vi.fn(),
    })

    render(<DataReview />)

    expect(screen.getByLabelText('Role for falls')).toHaveValue('outcome')
    expect(screen.getByLabelText('Role for patient_days')).toHaveValue('denominator')
  })

  it('does not affect canContinue when collection guidance is present', () => {
    const nextMock = vi.fn()
    useAppMock.mockReturnValue({
      ctx: {
        colTypes: { falls: 'Number' },
        qualityFlags: [],
        acknowledgedFlags: [],
        collectionRecs: [
          { id: 'missing-denominator', title: 'Denominator column needed', why: 'Rate calc requires it', severity: 'important', necessity: 'required' },
        ],
      },
      update: vi.fn(),
      next: nextMock,
      prev: vi.fn(),
    })

    render(<DataReview />)

    const continueBtn = screen.getByRole('button', { name: /Continue to Analysis Selection/i })
    expect(continueBtn).toBeEnabled()
  })

  it('the advisor speaks first with "start", then shows the read-back with dry-run counts and applies nothing', async () => {
    await openChat(proposal(8))
    expect(await screen.findByText('I would merge MG into mg. Confirm?')).toBeInTheDocument()
    expect(apiMock.sendAdvisorMessage).toHaveBeenCalledWith(8, 'start', null)
    const readback = screen.getByRole('group', { name: /read-back/ })
    expect(within(readback).getByText(/For warning: Unit has case variants/)).toBeInTheDocument()
    expect(within(readback).getByText(/Merge 'MG' into 'mg' in unit \(14 rows affected\)/)).toBeInTheDocument()
    expect(apiMock.confirmAdvisorProposal).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /Continue to Analysis Selection/ })).toBeDisabled()
  })

  it('maps a reply to the selected warning and shows info replies as plain chat', async () => {
    const user = await openChat(info(8, 'Which spelling do you want?'))
    await screen.findByText('Which spelling do you want?')
    apiMock.sendAdvisorMessage.mockResolvedValueOnce(info(8, 'Noted, no change yet.'))
    await user.selectOptions(screen.getByLabelText('Reply about'), 'category_variants:unit')
    await user.type(screen.getByLabelText('Your reply to the QI Stat Advisor'), 'Use lowercase')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(apiMock.sendAdvisorMessage).toHaveBeenLastCalledWith(8, 'Use lowercase', 'category_variants:unit')
    expect(await screen.findByText('Noted, no change yet.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm these changes' })).not.toBeInTheDocument()
  })

  it('confirm sends the proposal_id and refetches flag states', async () => {
    const user = await openChat(proposal(8))
    await screen.findByRole('button', { name: 'Confirm these changes' })
    apiMock.confirmAdvisorProposal.mockResolvedValue({
      group_id: 8, group_status: 'handled', applied: true, handoff_revision: 4, rows_affected: { 0: 14 },
      flag_states: states([st('category_variants:unit', 'handled', 'WARNING', 8, 'clarify')], 1, 0),
    })
    apiMock.getFlagStates.mockClear()
    apiMock.getFlagStates.mockResolvedValue(states([
      st('category_variants:unit', 'handled', 'WARNING', 8, 'clarify'), st('missing_values:age', 'handled'),
    ], 0, 0))
    await user.click(screen.getByRole('button', { name: 'Confirm these changes' }))
    expect(apiMock.confirmAdvisorProposal).toHaveBeenCalledWith(8, 'p_8_3')
    expect(await screen.findByText(/Applied as revision 4/)).toBeInTheDocument()
    expect(apiMock.getFlagStates).toHaveBeenCalled()
    await waitFor(() => expect(screen.getByRole('button', { name: /Continue to Analysis Selection/ })).toBeEnabled())
  })

  const roleProposal = () => ({
    group_id: 8, group_status: 'discussing', message: 'I would set patient_days as the denominator.', mode: 'propose',
    needs_user_confirmation: true, proposal_id: 'p_8_3', unapplied_notes: [],
    proposals: [{
      warning_id: 'category_variants:unit', summary: 'Use patient_days as the denominator',
      steps: [{ op: 'set_role', column: 'patient_days', role: 'denominator', warning_ids: ['category_variants:unit'], note: '' }],
      dry_run: [{
        op: 'set_role', description: 'Set the role of column patient_days to denominator.', rows_changed: 0,
        note: 'staff_hours is also set as Denominator; the analysis will use patient_days.',
      }],
    }],
  })

  async function openRoleChat(ctxExtra, savedRoles) {
    const user = userEvent.setup()
    apiMock.getFlagStates.mockResolvedValue(states([
      st('category_variants:unit', 'unhandled'), st('missing_values:age', 'unhandled'),
    ], 2, 0))
    apiMock.createWarningGroup.mockResolvedValue({ id: 8, action: 'clarify', status: 'open' })
    apiMock.sendAdvisorMessage.mockResolvedValueOnce(roleProposal())
    mountWarnings({
      colTypes: { falls: 'Number', staff_hours: 'Number', patient_days: 'Number' },
      columnRoles: savedRoles, ...ctxExtra,
    }, unitFlags)
    render(<DataReview />)
    await waitFor(() => expect(apiMock.getFlagStates).toHaveBeenCalled())
    await user.click(screen.getByRole('checkbox', { name: /Unit has case variants/ }))
    await user.click(screen.getByRole('button', { name: 'Clarify with QI Stat Advisor' }))
    return user
  }

  it('shows a role proposal as a role change with the conflict note and no rows-affected wording', async () => {
    await openRoleChat({}, { falls: 'outcome', staff_hours: 'denominator' })
    const readback = await screen.findByRole('group', { name: /read-back/ })
    expect(within(readback).getByText(/Set the role of column patient_days to denominator\. No data changes\./)).toBeInTheDocument()
    expect(within(readback).getByText(/staff_hours is also set as Denominator; the analysis will use patient_days\./)).toBeInTheDocument()
    expect(readback.textContent).not.toMatch(/rows affected/)
  })

  it('refreshes the role table after confirm, marks the advisor role, and Continue keeps it last', async () => {
    const user = await openRoleChat({}, { falls: 'outcome', staff_hours: 'denominator' })
    // The resident edits another row before confirming; that unsaved edit must survive the refresh.
    await user.selectOptions(screen.getByLabelText('Role for falls'), 'numerator')
    apiMock.confirmAdvisorProposal.mockResolvedValue({
      group_id: 8, group_status: 'handled', applied: true, handoff_revision: 4, rows_affected: { 0: 0 },
      flag_states: states([], 0, 0),
      column_roles: { falls: 'outcome', staff_hours: 'denominator', patient_days: 'denominator' },
    })
    apiMock.getFlagStates.mockResolvedValue(states([
      st('category_variants:unit', 'handled', 'WARNING', 8, 'clarify'), st('missing_values:age', 'handled'),
    ], 0, 0))
    await user.click(await screen.findByRole('button', { name: 'Confirm these changes' }))
    await waitFor(() => expect(screen.getByLabelText('Role for patient_days')).toHaveValue('denominator'))
    expect(screen.getByLabelText('Role for falls')).toHaveValue('numerator')
    expect(screen.getByText('Set by the QI Stat Advisor')).toBeInTheDocument()

    apiMock.saveAcknowledgedFlags.mockResolvedValue({})
    apiMock.confirmColTypes.mockResolvedValue({})
    await waitFor(() => expect(screen.getByRole('button', { name: /Continue to Analysis Selection/ })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: /Continue to Analysis Selection/ }))
    await waitFor(() => expect(apiMock.confirmColTypes).toHaveBeenCalled())
    const saved = apiMock.confirmColTypes.mock.calls[0][3]
    expect(saved.patient_days).toBe('denominator')
    expect(Object.keys(saved).pop()).toBe('patient_days')
  })

  it('decline drops the proposal without applying', async () => {
    const user = await openChat(proposal(8))
    apiMock.declineAdvisorProposal.mockResolvedValue({ group_id: 8, group_status: 'discussing', applied: false })
    await user.click(await screen.findByRole('button', { name: 'Decline' }))
    expect(apiMock.declineAdvisorProposal).toHaveBeenCalledWith(8, 'p_8_3')
    expect(apiMock.confirmAdvisorProposal).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Confirm these changes' })).not.toBeInTheDocument()
    expect(screen.getByText(/Nothing was changed/)).toBeInTheDocument()
  })

  it('Revise or undo reopens the thread for a handled group and does not mark it handled by itself', async () => {
    const user = userEvent.setup()
    apiMock.getFlagStates.mockResolvedValue(states([
      st('category_variants:unit', 'handled', 'WARNING', 8, 'clarify'),
    ], 0, 0))
    apiMock.getAdvisorThread.mockResolvedValue({
      group: { id: 8 }, advisor_available: true, pending: null,
      turns: [{ role: 'advisor', text: 'Earlier I merged MG into mg.', warning_id: null }],
    })
    mountWarnings({}, [unitFlags[0]])
    render(<DataReview />)
    await user.click(await screen.findByRole('button', { name: /Revise or undo/ }))
    expect(await screen.findByText('Earlier I merged MG into mg.')).toBeInTheDocument()
    expect(apiMock.getAdvisorThread).toHaveBeenCalledWith(8)
    expect(apiMock.sendAdvisorMessage).not.toHaveBeenCalled()

    apiMock.sendAdvisorMessage.mockResolvedValue(proposal(8, 'undo'))
    apiMock.getFlagStates.mockResolvedValue(states([st('category_variants:unit', 'discussing', 'WARNING', 8, 'clarify')], 1, 0))
    await user.type(screen.getByLabelText('Your reply to the QI Stat Advisor'), 'Undo the merge')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByRole('group', { name: /Proposed undo/ })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('state-category_variants:unit')).toHaveTextContent('Being discussed'))
    expect(screen.getByRole('button', { name: /Continue to Analysis Selection/ })).toBeDisabled()
  })

  it('disables Clarify but keeps Acknowledge when the advisor reports advisor_unavailable', async () => {
    const err = Object.assign(new Error('no key'), { code: 'advisor_unavailable' })
    const user = userEvent.setup()
    apiMock.getFlagStates.mockResolvedValue(states([st('missing_values:age', 'unhandled')], 1, 0))
    apiMock.createWarningGroup.mockResolvedValue({ id: 8, action: 'clarify', status: 'open' })
    apiMock.sendAdvisorMessage.mockRejectedValue(err)
    mountWarnings({}, [unitFlags[1]])
    render(<DataReview />)
    await waitFor(() => expect(apiMock.getFlagStates).toHaveBeenCalled())
    await user.click(screen.getByRole('checkbox', { name: /Age has missing values/ }))
    await user.click(screen.getByRole('button', { name: 'Clarify with QI Stat Advisor' }))
    expect(await screen.findByText(/The QI Stat Advisor is not available right now/)).toBeInTheDocument()
    expect(screen.getByLabelText('Your reply to the QI Stat Advisor')).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: /Age has missing values/ }))
    expect(screen.getByRole('button', { name: 'Clarify with QI Stat Advisor' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Acknowledge selected' })).toBeEnabled()
  })

  it('stale_proposal and step_rejected show plain messages and offer to re-propose', async () => {
    const user = await openChat(proposal(8))
    apiMock.confirmAdvisorProposal.mockRejectedValue(Object.assign(new Error('x'), { code: 'stale_proposal' }))
    await user.click(await screen.findByRole('button', { name: 'Confirm these changes' }))
    expect(await screen.findByText(/no longer current/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm these changes' })).not.toBeInTheDocument()
    apiMock.sendAdvisorMessage.mockResolvedValue(info(8, 'Here is a fresh view.'))
    await user.click(screen.getByRole('button', { name: 'Ask the QI Stat Advisor to propose again' }))
    expect(apiMock.sendAdvisorMessage).toHaveBeenLastCalledWith(8, expect.stringMatching(/propose the changes again/), null)
    expect(await screen.findByText('Here is a fresh view.')).toBeInTheDocument()
  })

  it('shows a rate limit message for HTTP 429', async () => {
    const user = await openChat(info(8, 'Hello'))
    await screen.findByText('Hello')
    apiMock.sendAdvisorMessage.mockRejectedValue(Object.assign(new Error('AI rate limit exceeded'), { code: 'HTTP_429' }))
    await user.type(screen.getByLabelText('Your reply to the QI Stat Advisor'), 'again')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/hourly limit/)
  })

  it('shows the handoff document from the viewer button', async () => {
    const user = userEvent.setup()
    apiMock.getFlagStates.mockResolvedValue(states([], 0, 0))
    apiMock.getHandoff.mockResolvedValue({ upload_id: 42, revision: 3, markdown: '# Handoff\n\n- one', change_log: [] })
    mountWarnings({}, [])
    render(<DataReview />)
    await user.click(screen.getByRole('button', { name: 'View handoff document' }))
    expect(apiMock.getHandoff).toHaveBeenCalledWith(42)
    expect(await screen.findByText('Revision 3')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Handoff' })).toBeInTheDocument()
  })

  it('cancels an open clarification, refetches, and makes the warning selectable again', async () => {
    const user = userEvent.setup()
    apiMock.getFlagStates.mockResolvedValue(states([st('category_variants:unit', 'open', 'WARNING', 8, 'clarify')], 1, 0))
    apiMock.cancelWarningGroup.mockResolvedValue({})
    mountWarnings({}, [unitFlags[0]])
    render(<DataReview />)
    const cancelBtn = await screen.findByRole('button', { name: /Cancel this clarification/ })
    apiMock.getFlagStates.mockResolvedValue(states([st('category_variants:unit', 'unhandled')], 1, 0))
    await user.click(cancelBtn)
    expect(apiMock.cancelWarningGroup).toHaveBeenCalledWith(42, 8)
    await waitFor(() => expect(screen.queryByRole('button', { name: /Cancel this clarification/ })).not.toBeInTheDocument())
    expect(screen.getByRole('checkbox', { name: /Unit has case variants/ })).toBeEnabled()
    expect(screen.getByTestId('state-category_variants:unit')).toHaveTextContent('Not handled')
  })

  it('offers no cancel on a handled group', async () => {
    apiMock.getFlagStates.mockResolvedValue(states([st('category_variants:unit', 'handled', 'WARNING', 8, 'clarify')], 0, 0))
    mountWarnings({}, [unitFlags[0]])
    render(<DataReview />)
    await screen.findByRole('button', { name: /Revise or undo/ })
    expect(screen.queryByRole('button', { name: /Cancel this clarification/ })).not.toBeInTheDocument()
  })

  it('acknowledging across an open group shows a note and still acknowledges', async () => {
    const user = userEvent.setup()
    apiMock.getFlagStates.mockResolvedValue(states([st('category_variants:unit', 'discussing', 'WARNING', 8, 'clarify')], 1, 0))
    apiMock.acknowledgeWarnings.mockResolvedValue({ id: 10, status: 'handled' })
    mountWarnings({}, [unitFlags[0]])
    render(<DataReview />)
    const box = await screen.findByRole('checkbox', { name: /Unit has case variants/ })
    expect(box).toBeEnabled()
    await user.click(box)
    expect(screen.getByText('This will end the clarification in progress for these warnings.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Acknowledge selected' }))
    expect(apiMock.acknowledgeWarnings).toHaveBeenCalledWith(42, ['category_variants:unit'])
  })

  it('hides Confirm after a later info reply', async () => {
    const user = await openChat(proposal(8))
    await screen.findByRole('button', { name: 'Confirm these changes' })
    apiMock.sendAdvisorMessage.mockResolvedValueOnce(info(8, 'Just a question.'))
    await user.type(screen.getByLabelText('Your reply to the QI Stat Advisor'), 'Why?')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText('Just a question.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm these changes' })).not.toBeInTheDocument()
  })

  it('disables Confirm while in flight and confirms once on double click', async () => {
    const user = await openChat(proposal(8))
    const btn = await screen.findByRole('button', { name: 'Confirm these changes' })
    let release
    apiMock.confirmAdvisorProposal.mockReturnValue(new Promise(r => { release = r }))
    apiMock.getFlagStates.mockResolvedValue(states([st('category_variants:unit', 'handled', 'WARNING', 8, 'clarify')], 0, 0))
    await user.dblClick(btn)
    expect(btn).toBeDisabled()
    expect(apiMock.confirmAdvisorProposal).toHaveBeenCalledTimes(1)
    release({ group_id: 8, group_status: 'handled', applied: true, handoff_revision: 4, flag_states: states([], 0, 0) })
    expect(await screen.findByText(/Applied as revision 4/)).toBeInTheDocument()
    expect(apiMock.confirmAdvisorProposal).toHaveBeenCalledTimes(1)
  })
})
