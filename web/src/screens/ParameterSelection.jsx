import React, { useState } from 'react'
import { useApp } from '../App'
import BackButton from '../components/BackButton'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'

const PARAM_FIELDS = {
  descriptive_summary: ['group_col', 'value_cols'],
  before_after_mean: ['group_col', 'value_col', 'pre_val', 'post_val'],
  before_after_pct: ['group_col', 'outcome_col', 'pre_val', 'post_val'],
  run_chart: ['date_col', 'value_col', 'intervention_date'],
  p_chart: ['date_col', 'numerator_col', 'denominator_col', 'intervention_date'],
  u_c_chart: ['date_col', 'count_col', 'denominator_col', 'intervention_date'],
}

const FIELD_LABELS = {
  group_col: 'Group column',
  value_cols: 'Value columns',
  value_col: 'Value column',
  date_col: 'Date column',
  numerator_col: 'Numerator column',
  denominator_col: 'Denominator column (optional)',
  count_col: 'Count column',
  outcome_col: 'Outcome column',
  pre_val: 'Pre-intervention label (e.g. "pre")',
  post_val: 'Post-intervention label (e.g. "post")',
  intervention_date: 'Intervention date',
}

const COL_NAME_FIELDS = new Set(['group_col', 'value_col', 'date_col', 'numerator_col', 'denominator_col', 'count_col', 'outcome_col'])
const SEMANTIC_COLUMN_FIELDS = new Set(['group_col', 'value_col', 'date_col', 'numerator_col', 'denominator_col', 'count_col', 'outcome_col'])

function normalizeValueCols(value) {
  if (Array.isArray(value)) return value
  if (typeof value === 'string') return value.split(',').map(s => s.trim()).filter(Boolean)
  return []
}

function activeParamsFor(fields, source, q7) {
  return fields.reduce((acc, f) => {
    if (f === 'value_cols') acc[f] = normalizeValueCols(source?.[f])
    else if (source?.[f] !== undefined) acc[f] = source[f]
    else acc[f] = f === 'intervention_date' ? q7.date || '' : ''
    return acc
  }, {})
}

function columnMapFor(params) {
  const columnMap = {}
  SEMANTIC_COLUMN_FIELDS.forEach(field => {
    if (params[field]) columnMap[field] = params[field]
  })
  return columnMap
}

function errorMessage(err) {
  return `${err.message || 'Could not save column mapping'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function ParameterSelection() {
  const { ctx, update, next, prev } = useApp()
  const template = ctx.template || 'run_chart'
  const fields = PARAM_FIELDS[template] || []
  const q7 = ctx.answers?.q7 || {}
  const colNames = Object.keys(ctx.colTypes || {})

  const [params, setParams] = useState(() => activeParamsFor(fields, ctx.params || {}, q7))

  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  function setField(f, v) { setParams(p => ({ ...p, [f]: v })) }

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setError('')
    const activeParams = activeParamsFor(fields, params, q7)
    const columnMap = columnMapFor(activeParams)
    try {
      if (ctx.uploadId) await api.updateColumnMap(ctx.uploadId, ctx.colTypes || {}, columnMap)
      update({ params: activeParams, columnMap, results: {}, resultSummary: undefined, runId: undefined, aiInterpretation: '', editedInterp: '', editedCaption: '' })
      next()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="screen max-w-xl">
      <PageIntro step="params" title="Map Your Columns" lead="Tell us which columns in your uploaded dataset correspond to each field." />
      {saving && <p aria-live="polite" className="mb-4 flex items-center gap-2 text-sm text-ink-soft"><Spinner />Saving column mapping…</p>}
      <form onSubmit={submit} className="card flex flex-col gap-4">
        {fields.map(f => {
          const id = `param-${f}`
          return (
            <label key={f} htmlFor={id} className="flex flex-col gap-1">
              <span className="label">{FIELD_LABELS[f] || f}</span>
              {f === 'intervention_date' ? (
                <input id={id} type="date" className="input" value={params[f] || ''} onChange={e => setField(f, e.target.value)} disabled={saving} />
              ) : f === 'value_cols' ? (
                <>
                  <select
                    id={id}
                    multiple
                    className="input min-h-28"
                    value={normalizeValueCols(params[f])}
                    onChange={e => setField(f, Array.from(e.target.selectedOptions, o => o.value))}
                    required
                    disabled={saving}
                  >
                    {colNames.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                  <span className="text-xs text-ink-faint">Hold Ctrl/Cmd to select multiple</span>
                </>
              ) : COL_NAME_FIELDS.has(f) ? (
                <select id={id} className="input" value={params[f] || ''} onChange={e => setField(f, e.target.value)} required={f !== 'denominator_col'} disabled={saving}>
                  <option value="">— select column —</option>
                  {colNames.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              ) : (
                <input id={id} type="text" className="input" value={params[f] || ''} onChange={e => setField(f, e.target.value)} required disabled={saving} />
              )}
            </label>
          )
        })}
        {error && <p role="alert" className="alert-error">{error}</p>}
        <div className="flex flex-wrap gap-3 pt-2">
          <BackButton onClick={prev} disabled={saving} />
          <button type="submit" disabled={saving} className="btn-primary">
            {saving && <Spinner />}
            {saving ? 'Saving…' : 'Run Analysis'}
          </button>
        </div>
      </form>
    </div>
  )
}
