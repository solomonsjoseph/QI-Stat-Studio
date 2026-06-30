import React, { useEffect, useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'

const TEMPLATES = [
  { id: 'descriptive_summary', label: 'Descriptive Summary', desc: 'Summarize data by group — means, medians, counts, SDs.' },
  { id: 'before_after_mean', label: 'Before/After: Mean', desc: 'Compare average values before and after an intervention (t-test or Wilcoxon).' },
  { id: 'before_after_pct', label: 'Before/After: Proportion', desc: "Compare percentages before and after (chi-square or Fisher's exact)." },
  { id: 'run_chart', label: 'Run Chart', desc: 'Track a measure over time; detect signal runs (≥8 consecutive).' },
  { id: 'p_chart', label: 'p-Chart', desc: 'Control chart for proportions with 3σ limits (≥12 data points).' },
  { id: 'u_c_chart', label: 'u/c-Chart', desc: 'Control chart for rates or counts with 3σ limits (≥12 data points).' },
]

const LABEL = Object.fromEntries(TEMPLATES.map(t => [t.id, t]))

export default function AnalysisSelection() {
  const { ctx, update, next } = useApp()
  const selected = ctx.template || ''
  const [ranked, setRanked] = useState(null)

  useEffect(() => {
    api.recommend(ctx.projectId)
      .then(setRanked)
      .catch(() => setRanked(
        TEMPLATES.slice(0, 3).map((t, i) => ({ template: t.id, description: t.desc, recommended: i === 0 }))
      ))
  }, [])

  const options = ranked ?? []

  return (
    <div className="max-w-2xl mx-auto p-8 mt-8">
      <h2 className="text-2xl font-bold mb-2 text-blue-800">Choose Your Analysis</h2>
      <p className="text-gray-500 text-sm mb-6">
        Based on your answers, we recommend the highlighted option. You can choose any.
      </p>
      <div className="flex flex-col gap-3 mb-8">
        {options.length === 0 ? (
          <p className="text-gray-400 text-sm">Loading recommendations…</p>
        ) : (
          options.map((opt) => {
            const tmpl = LABEL[opt.template] || { label: opt.template, desc: opt.description }
            return (
              <button
                key={opt.template}
                onClick={() => update({ template: opt.template })}
                className={`text-left px-4 py-3 border rounded-lg transition
                  ${selected === opt.template ? 'border-blue-600 bg-blue-50' : 'border-gray-200 hover:border-blue-300'}
                  ${opt.recommended ? 'ring-2 ring-blue-200' : ''}`}
              >
                <div className="font-medium">
                  {tmpl.label}
                  {opt.recommended && <span className="text-xs text-blue-600 ml-1">Recommended</span>}
                </div>
                <div className="text-sm text-gray-500">{opt.description || tmpl.desc}</div>
              </button>
            )
          })
        )}
      </div>
      <button
        onClick={next}
        disabled={!selected}
        className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 disabled:opacity-50"
      >
        Continue
      </button>
    </div>
  )
}
