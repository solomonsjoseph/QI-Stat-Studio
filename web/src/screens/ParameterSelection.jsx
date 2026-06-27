import React, { useState } from 'react'
import { useApp } from '../App'

// Fields per template — col names populated from uploaded colTypes
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
  value_cols: 'Value columns (comma-separated)',
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

export default function ParameterSelection() {
  const { ctx, update, next } = useApp()
  const template = ctx.template || 'run_chart'
  const fields = PARAM_FIELDS[template] || []
  const q7 = ctx.answers?.q7 || {}

  const [params, setParams] = useState(() => {
    const init = {}
    fields.forEach(f => {
      if (f === 'intervention_date') init[f] = q7.date || ''
      else init[f] = ''
    })
    return init
  })

  function setField(f, v) { setParams(p => ({ ...p, [f]: v })) }

  function submit(e) {
    e.preventDefault()
    update({ params })
    next()
  }

  return (
    <div className="max-w-xl mx-auto p-8 mt-8">
      <h2 className="text-2xl font-bold mb-2 text-blue-800">Map Your Columns</h2>
      <p className="text-sm text-gray-500 mb-6">
        Tell us which columns in your CSV correspond to each field.
      </p>
      <form onSubmit={submit} className="flex flex-col gap-4">
        {fields.map(f => (
          <label key={f} className="flex flex-col gap-1">
            <span className="font-medium text-sm">{FIELD_LABELS[f] || f}</span>
            <input
              type={f === 'intervention_date' ? 'date' : 'text'}
              className="border rounded px-3 py-2 text-sm"
              value={params[f] || ''}
              onChange={e => setField(f, e.target.value)}
              required={!f.includes('optional') && f !== 'denominator_col' && f !== 'intervention_date'}
            />
          </label>
        ))}
        <button
          type="submit"
          className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 self-start mt-2"
        >
          Run Analysis
        </button>
      </form>
    </div>
  )
}
