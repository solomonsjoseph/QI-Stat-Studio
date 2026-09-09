import React, { useState } from 'react'
import { useApp } from '../App'
import BackButton from '../components/BackButton'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'

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

function errorMessage(err) {
  return `${err.message || 'Could not save acknowledgements'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

function primaryRoleFor(col, profile) {
  const candidateRoles = profile?.candidate_roles || {}
  for (const [role, cols] of Object.entries(candidateRoles)) {
    if (Array.isArray(cols) && cols.includes(col)) return role
  }
  return ''
}

export default function DataReview() {
  const { ctx, update, next, prev } = useApp()
  const flags = ctx.qualityFlags || []
  const colTypes = ctx.colTypes || {}
  const missingPct = ctx.missingPct || {}
  const rowCount = ctx.profile?.row_count ?? ctx.rowCount
  const collectionRecs = ctx.collectionRecs || []

  const errors = flags.filter(f => f.severity === 'ERROR')
  const warnings = flags.filter(f => f.severity !== 'ERROR')

  const [acknowledged, setAcknowledged] = useState(() => {
    const acked = new Set((ctx.acknowledgedFlags || []).map(f => f.msg))
    const init = {}
    warnings.forEach((f, i) => { if (acked.has(f.msg)) init[i] = true })
    return init
  })
  const [columnRoles, setColumnRoles] = useState(() => {
    const init = { ...(ctx.columnRoles || {}) }
    Object.keys(colTypes).forEach(col => {
      if (!(col in init)) {
        init[col] = primaryRoleFor(col, ctx.profile)
      }
    })
    return init
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  function toggleAck(i) {
    setAcknowledged(a => ({ ...a, [i]: !a[i] }))
  }

  function setRole(col, role) {
    setColumnRoles(r => ({ ...r, [col]: role }))
  }

  const allWarningsAcked = warnings.every((_, i) => acknowledged[i])
  const canContinue = errors.length === 0 && (warnings.length === 0 || allWarningsAcked)

  const groupedRecs = NECESSITY_GROUPS.map(g => ({
    ...g,
    items: collectionRecs.filter(r => r.necessity === g.key),
  })).filter(g => g.items.length > 0)

  async function proceed() {
    setSaving(true)
    setError('')
    try {
      const ackedFlags = warnings.filter((_, i) => acknowledged[i])
      if (ctx.uploadId) {
        await api.saveAcknowledgedFlags(ctx.uploadId, ackedFlags)
        await api.confirmColTypes(ctx.uploadId, colTypes, ctx.columnMap || {}, columnRoles)
      }
      update({ acknowledgedFlags: ackedFlags, columnRoles })
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
      {error && <p role="alert" className="alert-error mb-4">{error}</p>}
      {saving && <p aria-live="polite" className="mb-4 flex items-center gap-2 text-sm text-ink-soft"><Spinner />Saving acknowledgements…</p>}

      {(rowCount != null || Object.keys(colTypes).length > 0) && (
        <p className="mb-4 text-sm text-ink-soft">
          {rowCount != null ? `${rowCount.toLocaleString()} rows` : 'Rows loaded'} · {Object.keys(colTypes).length.toLocaleString()} columns
        </p>
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
                  <td>{missingPct[col] != null ? `${missingPct[col].toFixed(1)}%` : '—'}</td>
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
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {errors.length > 0 && (
        <div className="alert-error mb-6">
          <h2 className="mb-2 font-semibold">Data Errors (must fix before continuing)</h2>
          {errors.map((flag, i) => (
            <div key={i} className="mb-3">
              <p className="mb-1"><span className="font-semibold mr-1">ERROR:</span>{flag.msg}</p>
              {flag.why && <p className="text-sm ml-4">Why this matters: {flag.why}</p>}
              {flag.suggestion && <p className="text-sm ml-4">Suggestion: {flag.suggestion}</p>}
              {flag.blocks && <p className="text-sm ml-4 font-medium">This prevents: {flag.blocks}</p>}
            </div>
          ))}
          <button type="button" onClick={prev} className="btn-danger mt-3">
            Re-upload corrected file
          </button>
        </div>
      )}

      {warnings.length > 0 && (
        <section className="mb-6" aria-labelledby="quality-warnings-heading">
          <h2 id="quality-warnings-heading" className="mb-2 font-semibold text-warn-ink">Data Quality Warnings</h2>
          <p className="mb-3 text-sm text-ink-soft">
            Please acknowledge each issue before proceeding. Acknowledged warnings appear in report limitations, but selected outcome columns with more than 30% missing values are blocked during analysis and require a different outcome column or corrected upload.
          </p>
          <div className="flex flex-col gap-2">
            {warnings.map((flag, i) => (
              <label key={i} className="choice items-start">
                <input type="checkbox" checked={!!acknowledged[i]} onChange={() => toggleAck(i)} disabled={saving} className="mt-0.5 h-4 w-4 text-brand" />
                <span>
                  <span className="mr-2 text-xs font-semibold text-warn-ink">WARNING</span><span className="text-ink">{flag.msg}</span>
                  {flag.why && <span className="block text-xs text-ink-soft mt-1">Why this matters: {flag.why}</span>}
                  {flag.suggestion && <span className="block text-xs text-ink-soft">Suggestion: {flag.suggestion}</span>}
                  {flag.blocks && <span className="block text-xs font-medium text-warn-ink mt-1">This prevents: {flag.blocks}</span>}
                </span>
              </label>
            ))}
          </div>
        </section>
      )}

      {flags.length === 0 && <p className="alert-ok mb-6">No data quality issues detected.</p>}

      <div className="flex flex-wrap gap-3">
        <BackButton onClick={prev} disabled={saving} />
        {errors.length === 0 && (
          <button type="button" onClick={proceed} disabled={!canContinue || saving} className="btn-primary">
            {saving && <Spinner />}
            {saving ? 'Saving…' : 'Continue to Analysis Selection'}
          </button>
        )}
      </div>
    </div>
  )
}
