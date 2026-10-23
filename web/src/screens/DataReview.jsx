import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useApp } from '../App'
import BackButton from '../components/BackButton'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import AdvisorChat from '../components/AdvisorChat'
import HandoffViewer from '../components/HandoffViewer'
import ReuploadChoice from '../components/ReuploadChoice'
import { api } from '../api'
import { denominatorColumns, denominatorUsed } from '../denominators'

const ROLE_OPTIONS = [
  { value: '', label: '(none)' },
  { value: 'outcome', label: 'Outcome' },
  { value: 'numerator', label: 'Numerator' },
  { value: 'denominator', label: 'Denominator' },
  { value: 'grouping', label: 'Grouping' },
  { value: 'identifier', label: 'Identifier' },
  { value: 'pairing_id', label: 'Pairing ID' },
]

const NECESSITY_GROUPS = [
  { key: 'required', label: 'Required to run an analysis' },
  { key: 'recommended', label: 'Recommended for stronger interpretation' },
  { key: 'optional', label: 'Optional future improvement' },
]

function errorMessage(err, fallback = 'Could not save acknowledgements') {
  return `${err.message || fallback}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

const STATE_LABELS = {
  unhandled: 'Not handled',
  open: 'Clarify started',
  discussing: 'Being discussed',
  handled: 'Handled',
  resolved: 'Resolved',
}
const SETTLED = new Set(['handled', 'resolved'])

// Flags from older uploads have no id, so the message is the key.
const flagKey = f => f.id || f.msg

function primaryRoleFor(col, profile) {
  const candidateRoles = profile?.candidate_roles || {}
  for (const [role, cols] of Object.entries(candidateRoles)) {
    if (Array.isArray(cols) && cols.includes(col)) return role
  }
  return ''
}

export default function DataReview({ onOpenClarify } = {}) {
  const { ctx, update, next, prev, advisorOff } = useApp()
  const flags = ctx.qualityFlags || []
  const colTypes = ctx.colTypes || {}
  const missingPct = Object.fromEntries((ctx.profile?.columns || []).map(c => [c.name, c.missing_pct]))
  const rowCount = ctx.profile?.row_count ?? ctx.rowCount
  const collectionRecs = ctx.collectionRecs || []

  const errors = flags.filter(f => f.severity === 'ERROR')
  const warnings = flags.filter(f => f.severity !== 'ERROR')

  const uploadId = ctx.uploadId
  const legacyAcked = new Set((ctx.acknowledgedFlags || []).map(flagKey))
  // flag-states payload: { byKey, unhandled_warning_count, unresolved_error_count } or null when not loaded
  const [flagStates, setFlagStates] = useState(null)
  const [selected, setSelected] = useState(() => new Set())
  const [busy, setBusy] = useState(false)
  const [clarifyGroup, setClarifyGroup] = useState(null)
  const [showHandoff, setShowHandoff] = useState(false)
  const [advisorGone, setAdvisorGone] = useState(false)
  const [statesError, setStatesError] = useState('')
  const [columnRoles, setColumnRoles] = useState(() => {
    const init = { ...(ctx.columnRoles || {}) }
    Object.keys(colTypes).forEach(col => {
      if (!(col in init)) {
        init[col] = primaryRoleFor(col, ctx.profile)
      }
    })
    return init
  })
  // Roles the advisor set this session, in the order set (last one wins a denominator tie), and the last
  // role table the server is known to hold, so a later save cannot overwrite what the advisor changed.
  const [advisorRoles, setAdvisorRoles] = useState({})
  const serverRoles = useRef({ ...(ctx.columnRoles || {}) })
  const [saving, setSaving] = useState(false)
  const denomCols = denominatorColumns(ctx.profile?.candidate_roles, columnRoles)
  const denomUsed = denominatorUsed(denomCols, ctx.design, colTypes)
  const [error, setError] = useState('')

  const refreshStates = useCallback(async () => {
    if (!uploadId) return
    const res = await api.getFlagStates(uploadId)
    setStatesError('')
    const byKey = {}
    ;(res.flags || []).forEach(f => { byKey[f.flag_id] = f })
    setFlagStates({
      byKey,
      unhandled_warning_count: res.unhandled_warning_count,
      unresolved_error_count: res.unresolved_error_count,
      pending_choice: !!res.pending_choice,
    })
  }, [uploadId])

  const loadStates = useCallback(
    () => refreshStates().catch(err => setStatesError(errorMessage(err, 'Could not load warning states'))),
    [refreshStates],
  )

  useEffect(() => { loadStates() }, [loadStates])

  function stateOf(flag) {
    const s = flagStates?.byKey[flagKey(flag)]?.state
    if (s) return s
    return uploadId || !legacyAcked.has(flagKey(flag)) ? 'unhandled' : 'handled'
  }

  function setRole(col, role) {
    setColumnRoles(r => ({ ...r, [col]: role }))
    setAdvisorRoles(a => {
      if (!(col in a)) return a
      const { [col]: _gone, ...rest } = a
      return rest
    })
  }

  // After an advisor confirm: take the server's value for every column it changed, keep other local edits.
  function applyServerRoles(roles, roleCols = []) {
    const before = serverRoles.current
    const cols = new Set([...Object.keys(roles), ...Object.keys(before)])
    const changed = [...cols].filter(c => roles[c] !== before[c])
    serverRoles.current = { ...roles }
    setColumnRoles(local => {
      const merged = { ...local }
      changed.forEach(c => {
        merged[c] = c in roles ? (roles[c] === 'none' ? '' : roles[c]) : primaryRoleFor(c, ctx.profile)
      })
      return merged
    })
    setAdvisorRoles(a => {
      const out = { ...a }
      changed.forEach(c => { delete out[c] })
      Object.keys(roles).filter(c => changed.includes(c) && roleCols.includes(c)).forEach(c => { out[c] = roles[c] })
      return out
    })
    update({ columnRoles: { ...(ctx.columnRoles || {}), ...roles } })
  }

  const selectable = flags.filter(f => !SETTLED.has(stateOf(f)))
  const selectedFlags = selectable.filter(f => selected.has(flagKey(f)))
  const selectedHasError = selectedFlags.some(f => f.severity === 'ERROR')
  const allSelected = selectable.length > 0 && selectedFlags.length === selectable.length
  const advisorDown = advisorOff === true || advisorGone
  const selectedInOpenGroup = selectedFlags.some(f => ['open', 'discussing'].includes(stateOf(f)) && flagStates?.byKey[flagKey(f)]?.group_id != null)

  function toggle(flag) {
    const k = flagKey(flag)
    setSelected(prev => {
      const n = new Set(prev)
      if (n.has(k)) n.delete(k); else n.add(k)
      return n
    })
  }

  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(selectable.map(flagKey)))
  }

  async function runGroup(action) {
    const ids = selectedFlags.map(flagKey)
    setBusy(true)
    setError('')
    try {
      let group
      if (action === 'acknowledge') {
        group = await api.acknowledgeWarnings(uploadId, ids)
      } else {
        group = await api.createWarningGroup(uploadId, ids, 'clarify')
        setClarifyGroup({ groupId: group.id, flagIds: ids, resume: false })
        if (onOpenClarify) onOpenClarify(group.id, ids)
      }
      setSelected(new Set())
      await refreshStates()
    } catch (err) {
      setError(errorMessage(err, 'Could not save your selection'))
    } finally {
      setBusy(false)
    }
  }

  // Server gating decides. Without an upload there is nothing to ask the server, so use local state.
  const canContinue = !uploadId
    ? errors.length === 0 && warnings.every(f => legacyAcked.has(flagKey(f)))
    : !!flagStates && !flagStates.pending_choice && flagStates.unhandled_warning_count === 0 && flagStates.unresolved_error_count === 0

  async function cancelGroup(groupId) {
    setBusy(true)
    setError('')
    try {
      await api.cancelWarningGroup(uploadId, groupId)
      if (clarifyGroup?.groupId === groupId) setClarifyGroup(null)
      await refreshStates()
    } catch (err) {
      setError(errorMessage(err, 'Could not cancel the clarification'))
    } finally {
      setBusy(false)
    }
  }

  function openGroup(groupId) {
    const ids = Object.values(flagStates?.byKey || {}).filter(f => f.group_id === groupId).map(f => f.flag_id)
    setClarifyGroup({ groupId, flagIds: ids, resume: true })
  }
  const flagLabels = Object.fromEntries(flags.map(f => [flagKey(f), f.msg]))

  const groupedRecs = NECESSITY_GROUPS.map(g => ({
    ...g,
    items: collectionRecs.filter(r => r.necessity === g.key),
  })).filter(g => g.items.length > 0)

  async function proceed() {
    setSaving(true)
    setError('')
    try {
      const ackedFlags = warnings.filter(f => stateOf(f) === 'handled')
      // Advisor-set roles go last, in the order set, so the newest denominator wins the plan builder's tie-break.
      const orderedRoles = {}
      Object.entries(columnRoles).filter(([c]) => !(c in advisorRoles)).forEach(([c, r]) => { orderedRoles[c] = r })
      Object.keys(advisorRoles).forEach(c => { if (c in columnRoles) orderedRoles[c] = columnRoles[c] })
      if (ctx.uploadId) {
        await api.saveAcknowledgedFlags(ctx.uploadId, ackedFlags)
        await api.confirmColTypes(ctx.uploadId, colTypes, ctx.columnMap || {}, orderedRoles)
      }
      update({ acknowledgedFlags: ackedFlags, columnRoles: orderedRoles })
      next()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="screen">
      <PageIntro step="review" title="Data Review" />
      <ReuploadChoice onChosen={loadStates} />
      {error && <p role="alert" className="alert-error mb-4">{error}</p>}
      {statesError && (
        <div role="alert" className="alert-error mb-4 flex flex-wrap items-center gap-3">
          <span>{statesError}. Continue stays off until the warning states load.</span>
          <button type="button" className="btn-secondary" onClick={loadStates}>Retry</button>
        </div>
      )}
      {saving && <p aria-live="polite" className="mb-4 flex items-center gap-2 text-sm text-ink-soft"><Spinner />Saving acknowledgements…</p>}

      {(rowCount != null || Object.keys(colTypes).length > 0) && (
        <p className="mb-4 text-sm text-ink-soft">
          {rowCount != null ? `${rowCount.toLocaleString()} rows` : 'Rows loaded'} · {Object.keys(colTypes).length.toLocaleString()} columns
        </p>
      )}

      {uploadId && (
        <div className="mb-4">
          <button type="button" className="btn-secondary" aria-expanded={showHandoff} onClick={() => setShowHandoff(v => !v)}>
            {showHandoff ? 'Hide handoff document' : 'View handoff document'}
          </button>
          {showHandoff && <div className="mt-3"><HandoffViewer uploadId={uploadId} /></div>}
        </div>
      )}

      <p className="alert-info mb-4">
        Acknowledged warnings appear in report limitations. Analysis still blocks selected outcome columns with more than 30% missing values; acknowledgement does not override that safety check.
      </p>

      {groupedRecs.length > 0 && (
        <section className="card mb-6" aria-labelledby="collection-guidance-heading">
          <h2 id="collection-guidance-heading" className="mb-3 font-semibold text-ink">What else you may need to collect</h2>
          <div className="flex flex-col gap-4">
            {groupedRecs.map(group => (
              <div key={group.key}>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-faint">{group.label}</h3>
                <div className="flex flex-col gap-2">
                  {group.items.map(rec => (
                    <div key={rec.id} className={rec.severity === 'important' ? 'alert-warn' : 'alert-info'}>
                      <p className="font-medium">{rec.title}</p>
                      {rec.why && <p className="text-sm mt-1">{rec.why}</p>}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="mb-6" aria-labelledby="column-types-heading">
        <h2 id="column-types-heading" className="mb-2 font-semibold text-ink">Column Types & Roles</h2>
        <div className="overflow-x-auto">
          <table className="table-clean">
            <thead>
              <tr><th>Column</th><th>Type</th><th>Missing %</th><th>Role</th></tr>
            </thead>
            <tbody>
              {Object.entries(colTypes).map(([col, type]) => (
                <tr key={col}>
                  <td className="font-mono">{col}</td>
                  <td>{type}</td>
                  <td>{missingPct[col] != null ? `${missingPct[col].toFixed(1)}%` : '-'}</td>
                  <td>
                    <label className="sr-only" htmlFor={`role-${col}`}>Role for {col}</label>
                    <select
                      id={`role-${col}`}
                      className="input min-w-32"
                      value={columnRoles[col] || ''}
                      onChange={e => setRole(col, e.target.value)}
                      disabled={saving}
                    >
                      {ROLE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                    {col in advisorRoles && <span className="ml-2 text-xs text-ink-soft">Set by the QI Stat Advisor</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {denomCols.length > 1 && (
          <p role="status" className="alert-warn mt-2 text-sm">
            {denomCols.length === 2 ? 'Two columns are' : `${denomCols.length} columns are`} set as Denominator.
            {' '}The analysis will use {denomUsed}. Change the other one if that is wrong.
          </p>
        )}
      </section>

      {flags.length > 0 && (
        <section className="mb-6" aria-labelledby="quality-warnings-heading">
          <h2 id="quality-warnings-heading" className="mb-2 font-semibold text-warn-ink">Data Quality Warnings</h2>
          <p className="mb-3 text-sm text-ink-soft">
            Tick the warnings you want to handle, then choose Acknowledge or Clarify with the QI Stat Advisor. You can do several rounds with different selections. Acknowledged warnings appear in report limitations. Errors can only be fixed through Clarify and keep blocking until the check passes on the cleaned data.
          </p>
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <label className="inline-flex items-center gap-2 text-sm">
              <input type="checkbox" className="h-4 w-4 text-brand" checked={allSelected} disabled={selectable.length === 0 || busy || saving} onChange={toggleAll} />
              Select all
            </label>
            <span aria-live="polite" className="text-sm text-ink-soft">{selectedFlags.length} selected</span>
            <button type="button" className="btn-secondary" onClick={() => runGroup('acknowledge')}
              disabled={selectedFlags.length === 0 || selectedHasError || busy || saving}>
              Acknowledge selected
            </button>
            <button type="button" className="btn-secondary" onClick={() => runGroup('clarify')}
              disabled={selectedFlags.length === 0 || advisorDown || busy || saving}>
              Clarify with QI Stat Advisor
            </button>
          </div>
          {selectedHasError && <p className="mb-2 text-sm text-ink-soft">Acknowledge is off because the selection includes an error. Errors can only go through Clarify.</p>}
          {selectedInOpenGroup && <p className="mb-2 text-sm text-ink-soft">This will end the clarification in progress for these warnings.</p>}
          {advisorDown && <p className="mb-2 text-sm text-ink-soft">The QI Stat Advisor is not available. You can still acknowledge warnings.</p>}
          <ul className="flex flex-col gap-2">
            {flags.map(flag => {
              const k = flagKey(flag)
              const st = stateOf(flag)
              const settled = SETTLED.has(st)
              const isError = flag.severity === 'ERROR'
              return (
                <li key={k}>
                  <label className={`choice items-start ${settled ? 'opacity-60' : ''}`}>
                    <input type="checkbox" className="mt-0.5 h-4 w-4 text-brand"
                      checked={!settled && selected.has(k)} disabled={settled || busy || saving} onChange={() => toggle(flag)} />
                    <span>
                      <span className={`mr-2 text-xs font-semibold ${isError ? 'text-error-ink' : 'text-warn-ink'}`}>{isError ? 'ERROR' : 'WARNING'}</span>
                      <span className="text-ink">{flag.msg}</span>
                      <span className="ml-2 text-xs text-ink-soft" data-testid={`state-${k}`}>({STATE_LABELS[st] || st})</span>
                      {flag.why && <span className="block text-xs text-ink-soft mt-1">Why this matters: {flag.why}</span>}
                      {flag.suggestion && <span className="block text-xs text-ink-soft">Suggestion: {flag.suggestion}</span>}
                      {flag.blocks && <span className="block text-xs font-medium text-warn-ink mt-1">This prevents: {flag.blocks}</span>}
                    </span>
                  </label>
                  {flagStates?.byKey[k]?.action === 'clarify' && flagStates.byKey[k].group_id != null && (
                    <button type="button" className="btn-secondary ml-6 mt-1 text-xs" disabled={advisorDown}
                      onClick={() => openGroup(flagStates.byKey[k].group_id)}>
                      {settled ? 'Revise or undo' : 'Open chat'}<span className="sr-only"> for {flag.msg}</span>
                    </button>
                  )}
                  {!settled && flagStates?.byKey[k]?.action === 'clarify' && flagStates.byKey[k].group_id != null && (
                    <button type="button" className="btn-secondary ml-2 mt-1 text-xs" disabled={busy || saving}
                      onClick={() => cancelGroup(flagStates.byKey[k].group_id)}>
                      Cancel this clarification<span className="sr-only"> for {flag.msg}</span>
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
          {errors.length > 0 && (
            <button type="button" onClick={prev} className="btn-danger mt-3">Re-upload corrected file</button>
          )}
        </section>
      )}

      {clarifyGroup && (
        <AdvisorChat
          key={`${clarifyGroup.groupId}-${clarifyGroup.resume}`}
          groupId={clarifyGroup.groupId}
          flagIds={clarifyGroup.flagIds}
          flagLabels={flagLabels}
          resume={clarifyGroup.resume}
          onChanged={loadStates}
          onRolesChanged={applyServerRoles}
          onUnavailable={() => setAdvisorGone(true)}
          onClose={() => setClarifyGroup(null)}
        />
      )}

      {flags.length === 0 && <p className="alert-ok mb-6">No data quality issues detected.</p>}

      {flagStates?.pending_choice && (
        <p role="status" className="alert-info mb-3">Choose whether to keep your earlier changes or start fresh above.</p>
      )}

      <div className="flex flex-wrap gap-3">
        <BackButton onClick={prev} disabled={saving} />
        <button type="button" onClick={proceed} disabled={!canContinue || saving || busy} className="btn-primary">
          {saving && <Spinner />}
          {saving ? 'Saving…' : 'Continue to Analysis Selection'}
        </button>
      </div>
    </div>
  )
}
