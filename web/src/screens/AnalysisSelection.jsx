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

function fallbackRecommendations() {
  return TEMPLATES.slice(0, 3).map((t, i) => ({ template: t.id, description: t.desc, recommended: i === 0 }))
}

export default function AnalysisSelection() {
  const { ctx, update, next } = useApp()
  const selected = ctx.template || ''
  const [ranked, setRanked] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    api.recommend(ctx.projectId)
      .then(data => { if (!cancelled) setRanked(data) })
      .catch(err => {
        if (!cancelled) {
          setRanked(fallbackRecommendations())
          setError(`${err.message || 'Could not load recommendations'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}. Showing default options.`)
        }
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [ctx.projectId])

  const options = ranked ?? []

  return (
    <div className="max-w-2xl mx-auto p-8 mt-8">
      <h1 className="text-2xl font-bold mb-2 text-blue-800">Choose Your Analysis</h1>
      <p className="text-gray-500 text-sm mb-6">Based on your answers, we recommend the highlighted option. You can choose any.</p>
      {loading && <p aria-live="polite" className="text-gray-500 text-sm mb-4">Loading recommendations…</p>}
      {error && <p role="alert" className="text-yellow-800 bg-yellow-50 border border-yellow-200 rounded p-3 text-sm mb-4">{error}</p>}
      <div className="flex flex-col gap-3 mb-8" role="radiogroup" aria-label="Analysis template">
        {options.map((opt, i) => {
          const tmpl = LABEL[opt.template] || { label: opt.template, desc: opt.description }
          return (
            <button
              type="button"
              key={opt.template}
              onClick={() => update({ template: opt.template })}
              aria-pressed={selected === opt.template}
              className={`text-left px-4 py-3 border rounded-lg transition ${selected === opt.template ? 'border-blue-600 bg-blue-50' : 'border-gray-200 hover:border-blue-300'} ${opt.recommended ? 'ring-2 ring-blue-200' : ''}`}
            >
              <div className="font-medium">{i + 1}. {tmpl.label}{opt.recommended && <span className="text-xs text-blue-600 ml-1">Recommended</span>}</div>
              <div className="text-sm text-gray-500">{opt.description || tmpl.desc}</div>
            </button>
          )
        })}
      </div>
      <button
        type="button"
        onClick={next}
        disabled={!selected || loading}
        className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 disabled:opacity-50"
      >
        Continue
      </button>
    </div>
  )
}
