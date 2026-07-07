import React, { useState } from 'react'
import { useApp } from '../App'
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

function errorMessage(err) {
  return `${err.message || 'Could not save column mapping'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function ParameterSelection() {
  const { ctx, update, next } = useApp()
  const template = ctx.template || 'run_chart'
  const fields = PARAM_FIELDS[template] || []
  const q7 = ctx.answers?.q7 || {}
  const colNames = Object.keys(ctx.colTypes || {})

  const [params, setParams] = useState(() => {
    const init = { ...(ctx.params || {}) }
    fields.forEach(f => {
      if (init[f] === undefined) init[f] = f === 'intervention_date' ? q7.date || '' : ''
    })
    return init
  })

  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  function setField(f, v) { setParams(p => ({ ...p, [f]: v })) }

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setError('')
    const columnMap = {}
    SEMANTIC_COLUMN_FIELDS.forEach(field => {
      if (params[field]) columnMap[field] = params[field]
    })
    try {
      if (ctx.uploadId) await api.updateColumnMap(ctx.uploadId, ctx.colTypes || {}, columnMap)
      update({ params, columnMap })
      next()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-xl mx-auto p-8 mt-8">
      <h1 className="text-2xl font-bold mb-2 text-blue-800">Map Your Columns</h1>
      <p className="text-sm text-gray-500 mb-6">Tell us which columns in your uploaded dataset correspond to each field.</p>
      {saving && <p aria-live="polite" className="mb-4 text-sm text-gray-500">Saving column mapping…</p>}
      <form onSubmit={submit} className="flex flex-col gap-4">
        {fields.map(f => {
          const id = `param-${f}`
          return (
            <label key={f} htmlFor={id} className="flex flex-col gap-1">
              <span className="font-medium text-sm">{FIELD_LABELS[f] || f}</span>
              {f === 'intervention_date' ? (
                <input id={id} type="date" className="border rounded px-3 py-2 text-sm" value={params[f] || ''} onChange={e => setField(f, e.target.value)} disabled={saving} />
              ) : f === 'value_cols' ? (
                <select
                  id={id}
                  multiple
                  className="border rounded px-3 py-2 text-sm"
                  value={params[f] ? params[f].split(',').map(s => s.trim()) : []}
                  onChange={e => setField(f, Array.from(e.target.selectedOptions, o => o.value).join(','))}
                  required
                  disabled={saving}
                >
                  {colNames.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              ) : COL_NAME_FIELDS.has(f) ? (
                <select id={id} className="border rounded px-3 py-2 text-sm" value={params[f] || ''} onChange={e => setField(f, e.target.value)} required={f !== 'denominator_col'} disabled={saving}>
                  <option value="">— select column —</option>
                  {colNames.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              ) : (
                <input id={id} type="text" className="border rounded px-3 py-2 text-sm" value={params[f] || ''} onChange={e => setField(f, e.target.value)} required disabled={saving} />
              )}
            </label>
          )
        })}
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        <button type="submit" disabled={saving} className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 disabled:opacity-50 self-start mt-2">
          {saving ? 'Saving…' : 'Run Analysis'}
        </button>
      </form>
    </div>
  )
}
