import React, { useState } from 'react'
import { useApp } from '../App'
import BackButton from '../components/BackButton'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'

function errorMessage(err) {
  return `${err.message || 'Could not save acknowledgements'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function DataReview() {
  const { ctx, update, next, prev } = useApp()
  const flags = ctx.qualityFlags || []
  const colTypes = ctx.colTypes || {}
  const missingPct = ctx.missingPct || {}
  const rowCount = ctx.rowCount

  const errors = flags.filter(f => f.severity === 'ERROR')
  const warnings = flags.filter(f => f.severity !== 'ERROR')

  const [acknowledged, setAcknowledged] = useState(() => {
    const acked = new Set((ctx.acknowledgedFlags || []).map(f => f.msg))
    const init = {}
    warnings.forEach((f, i) => { if (acked.has(f.msg)) init[i] = true })
    return init
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  function toggleAck(i) {
    setAcknowledged(a => ({ ...a, [i]: !a[i] }))
  }

  const allWarningsAcked = warnings.every((_, i) => acknowledged[i])
  const canContinue = errors.length === 0 && (warnings.length === 0 || allWarningsAcked)

  async function proceed() {
    setSaving(true)
    setError('')
    try {
      const ackedFlags = warnings.filter((_, i) => acknowledged[i])
      if (ctx.uploadId) await api.saveAcknowledgedFlags(ctx.uploadId, ackedFlags)
      update({ acknowledgedFlags: ackedFlags })
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

      <section className="mb-6" aria-labelledby="column-types-heading">
        <h2 id="column-types-heading" className="mb-2 font-semibold text-ink">Column Types</h2>
        <div className="overflow-x-auto">
          <table className="table-clean">
            <thead>
              <tr><th>Column</th><th>Type</th><th>Missing %</th></tr>
            </thead>
            <tbody>
              {Object.entries(colTypes).map(([col, type]) => (
                <tr key={col}>
                  <td className="font-mono">{col}</td>
                  <td>{type}</td>
                  <td>{missingPct[col] != null ? `${missingPct[col].toFixed(1)}%` : '—'}</td>
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
            <p key={i} className="mb-1"><span className="font-semibold mr-1">ERROR:</span>{flag.msg}</p>
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
              <label key={i} className="choice">
                <input type="checkbox" checked={!!acknowledged[i]} onChange={() => toggleAck(i)} disabled={saving} className="mt-0.5 h-4 w-4 text-brand" />
                <span><span className="mr-2 text-xs font-semibold text-warn-ink">WARNING</span><span className="text-ink">{flag.msg}</span></span>
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
