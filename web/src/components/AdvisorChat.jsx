import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import Spinner from './Spinner'

const MODE_LABELS = { propose: 'Proposed changes', undo: 'Proposed undo', revise: 'Proposed revision' }
const REPROPOSE_TEXT = 'Please propose the changes again based on the current state of the data.'

// Plain-English line for one step: prefer the server's dry-run description.
function describeStep(step, dry) {
  if (dry?.description) return dry.description
  const args = Object.entries(step)
    .filter(([k]) => !['op', 'warning_ids', 'note'].includes(k))
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : String(v)}`)
  return `${step.op}${args.length ? ` (${args.join('; ')})` : ''}`
}

function problemText(err) {
  if (err.code === 'HTTP_429') return 'You have reached the hourly limit for QI Stat Advisor messages. Wait a while, then try again.'
  if (err.code === 'step_rejected') return `${err.message} Nothing was changed.`
  if (err.code === 'stale_proposal' || err.code === 'no_pending_proposal') {
    return 'That proposal is no longer current. Ask the QI Stat Advisor to propose the changes again.'
  }
  return `${err.message || 'Something went wrong.'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

// Conversation for one Clarify group. Nothing is applied until the user presses Confirm.
// Props: groupId, flagIds, flagLabels ({id: text}), resume (reopen an existing thread),
// onChanged (refetch flag states), onRolesChanged (server column roles after a confirm), onUnavailable, onClose.
export default function AdvisorChat({ groupId, flagIds = [], flagLabels = {}, resume = false, onChanged, onRolesChanged, onUnavailable, onClose }) {
  const [turns, setTurns] = useState([])
  const [pending, setPending] = useState(null)
  const [input, setInput] = useState('')
  const [target, setTarget] = useState('')
  const [busy, setBusy] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [unavailable, setUnavailable] = useState(false)
  const [canRepropose, setCanRepropose] = useState(false)
  const [notice, setNotice] = useState('')
  const headingRef = useRef(null)
  const started = useRef(false)
  const inFlight = useRef(false)

  function fail(err) {
    if (err.code === 'advisor_unavailable') {
      setUnavailable(true)
      setError('The QI Stat Advisor is not available right now. You can close this panel and Acknowledge warnings instead.')
      if (onUnavailable) onUnavailable()
      return
    }
    setError(problemText(err))
    setCanRepropose(['stale_proposal', 'no_pending_proposal', 'step_rejected'].includes(err.code))
    if (err.code === 'stale_proposal' || err.code === 'no_pending_proposal') setPending(null)
  }

  async function send(text, warningId, { show = true } = {}) {
    setBusy(true)
    setSending(true)
    setError('')
    setCanRepropose(false)
    setNotice('')
    if (show) setTurns(t => [...t, { role: 'user', text, warning_id: warningId || null }])
    try {
      const reply = await api.sendAdvisorMessage(groupId, text, warningId)
      setTurns(t => [...t, { role: 'advisor', text: reply.message, warning_id: warningId || null }])
      // The server clears the pending proposal on any non-proposal reply, so only the latest reply can be pending.
      setPending(reply.needs_user_confirmation && reply.proposal_id ? reply : null)
      if (onChanged) await onChanged()
    } catch (err) {
      fail(err)
    } finally {
      setSending(false)
      setBusy(false)
    }
  }

  useEffect(() => {
    headingRef.current?.focus()
    if (started.current) return
    started.current = true
    if (resume) {
      setBusy(true)
      api.getAdvisorThread(groupId)
        .then(th => {
          setTurns((th.turns || []).map(t => ({ role: t.role, text: t.text, warning_id: t.warning_id })))
          setPending(th.pending && th.pending.needs_user_confirmation ? th.pending : null)
          if (th.advisor_available === false) setUnavailable(true)
        })
        .catch(fail)
        .finally(() => setBusy(false))
    } else {
      send('start', null, { show: false })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function submit(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text || busy) return
    setInput('')
    await send(text, target || null)
  }

  async function confirm() {
    if (inFlight.current) return
    inFlight.current = true
    setBusy(true)
    setError('')
    try {
      const roleCols = (pending.proposals || []).flatMap(p => p.steps || []).filter(st => st.op === 'set_role').map(st => st.column)
      const out = await api.confirmAdvisorProposal(groupId, pending.proposal_id)
      setPending(null)
      if (out.column_roles && onRolesChanged) onRolesChanged(out.column_roles, roleCols)
      const blocked = (out.flag_states?.flags || []).filter(f => flagIds.includes(f.flag_id) && f.severity === 'ERROR' && f.state !== 'resolved')
      setNotice(
        `Applied as revision ${out.handoff_revision}. The group is now ${out.group_status}.` +
        (blocked.length ? ' An error in this group is still not resolved: the check still fires on the cleaned data, so Continue stays blocked.' : ''),
      )
      if (onChanged) await onChanged()
    } catch (err) {
      fail(err)
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  async function decline() {
    setBusy(true)
    setError('')
    try {
      await api.declineAdvisorProposal(groupId, pending.proposal_id)
      setPending(null)
      setNotice('Proposal dropped. Nothing was changed.')
      if (onChanged) await onChanged()
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  const label = id => flagLabels[id] || id

  return (
    <section className="card mb-6" aria-labelledby={`advisor-heading-${groupId}`}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 id={`advisor-heading-${groupId}`} ref={headingRef} tabIndex={-1} className="font-semibold text-ink">QI Stat Advisor</h2>
        <button type="button" className="btn-secondary" onClick={onClose}>Close chat</button>
      </div>
      <p className="mb-2 text-sm text-ink-soft">Discussing:</p>
      <ul className="mb-3 list-disc pl-5 text-sm">{flagIds.map(id => <li key={id}>{label(id)}</li>)}</ul>
      {resume && <p className="mb-3 text-sm text-ink-soft">Ask the QI Stat Advisor to undo or revise what was applied. These warnings stay unhandled until you confirm again.</p>}

      <div role="log" aria-live="polite" aria-label="Conversation with the QI Stat Advisor" className="mb-3 flex flex-col gap-2">
        {turns.map((t, n) => (
          <div key={n} className={t.role === 'user' ? 'rounded bg-surface-sunken p-3 text-sm' : 'alert-info whitespace-pre-wrap text-sm'}>
            <p className="mb-1 text-xs font-semibold">{t.role === 'user' ? 'You' : 'QI Stat Advisor'}{t.warning_id ? ` (about: ${label(t.warning_id)})` : ''}</p>
            <p className="whitespace-pre-wrap">{t.text}</p>
          </div>
        ))}
        {busy && <p className="flex items-center gap-2 text-sm text-ink-soft"><Spinner />Waiting for the QI Stat Advisor…</p>}
      </div>

      {error && <p role="alert" className="alert-error mb-3">{error}</p>}
      {notice && <p role="status" className="alert-ok mb-3">{notice}</p>}
      {canRepropose && !unavailable && (
        <button type="button" className="btn-secondary mb-3" disabled={busy} onClick={() => send(REPROPOSE_TEXT, null)}>Ask the QI Stat Advisor to propose again</button>
      )}

      {pending && !sending && (
        <div className="mb-3 rounded border border-line p-3" aria-labelledby={`readback-${groupId}`} role="group">
          <h3 id={`readback-${groupId}`} className="mb-2 font-medium text-ink">{MODE_LABELS[pending.mode] || 'Proposed changes'}: read-back</h3>
          {pending.proposals.map(p => (
            <div key={p.warning_id} className="mb-2">
              <p className="text-sm font-medium">For warning: {label(p.warning_id)}</p>
              {p.summary && <p className="text-sm">{p.summary}</p>}
              {p.steps.length === 0
                ? <p className="text-sm text-ink-soft">No data change. Your decision will be recorded as a note.</p>
                : (
                  <ol className="list-decimal pl-5 text-sm">
                    {p.steps.map((s, i) => {
                      const dry = p.dry_run?.[i]
                      if (s.op === 'set_role') {
                        return (
                          <li key={i}>
                            {describeStep(s, dry)} No data changes.
                            {dry?.note && <span className="block text-ink-soft">{dry.note}</span>}
                          </li>
                        )
                      }
                      return (
                        <li key={i}>{describeStep(s, dry)}{dry ? ` (${dry.rows_changed} rows affected)` : ''}</li>
                      )
                    })}
                  </ol>
                )}
            </div>
          ))}
          {pending.unapplied_notes?.length > 0 && (
            <p className="text-sm text-ink-soft">Not applied (outside what the QI Stat Advisor can change): {pending.unapplied_notes.join('; ')}</p>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            <button type="button" className="btn-primary" disabled={busy} onClick={confirm}>Confirm these changes</button>
            <button type="button" className="btn-secondary" disabled={busy} onClick={decline}>Decline</button>
          </div>
        </div>
      )}

      <form onSubmit={submit} className="flex flex-col gap-2">
        <label htmlFor={`advisor-target-${groupId}`} className="text-sm font-medium text-ink">Reply about</label>
        <select id={`advisor-target-${groupId}`} className="input" value={target} onChange={e => setTarget(e.target.value)} disabled={unavailable || busy}>
          <option value="">All warnings in this group</option>
          {flagIds.map(id => <option key={id} value={id}>{label(id)}</option>)}
        </select>
        <label htmlFor={`advisor-input-${groupId}`} className="text-sm font-medium text-ink">Your reply to the QI Stat Advisor</label>
        <textarea id={`advisor-input-${groupId}`} className="input" rows={3} maxLength={4000} value={input}
          onChange={e => setInput(e.target.value)} disabled={unavailable || busy} />
        <div>
          <button type="submit" className="btn-primary" disabled={unavailable || busy || !input.trim()}>Send</button>
        </div>
      </form>
    </section>
  )
}
