import React from 'react'
import { useApp } from '../App'

const TEMPLATES = [
  { id: 'descriptive_summary', label: 'Descriptive Summary', desc: 'Summarize data by group — means, medians, counts, SDs.' },
  { id: 'before_after_mean', label: 'Before/After: Mean', desc: 'Compare average values before and after an intervention (t-test or Wilcoxon).' },
  { id: 'before_after_pct', label: 'Before/After: Proportion', desc: "Compare percentages before and after (chi-square or Fisher's exact)." },
  { id: 'run_chart', label: 'Run Chart', desc: 'Track a measure over time; detect signal runs (≥8 consecutive).' },
  { id: 'p_chart', label: 'p-Chart', desc: 'Control chart for proportions with 3σ limits (≥12 data points).' },
  { id: 'u_c_chart', label: 'u/c-Chart', desc: 'Control chart for rates or counts with 3σ limits (≥12 data points).' },
]

export default function AnalysisSelection() {
  const { ctx, update, next } = useApp()
  const selected = ctx.template || ''

  return (
    <div className="max-w-2xl mx-auto p-8 mt-8">
      <h2 className="text-2xl font-bold mb-2 text-blue-800">Choose Your Analysis</h2>
      <p className="text-gray-500 text-sm mb-6">
        Based on your answers, we recommend the first option. You can choose any.
      </p>
      <div className="flex flex-col gap-3 mb-8">
        {TEMPLATES.map((t, i) => (
          <button
            key={t.id}
            onClick={() => update({ template: t.id })}
            className={`text-left px-4 py-3 border rounded-lg transition
              ${selected === t.id ? 'border-blue-600 bg-blue-50' : 'border-gray-200 hover:border-blue-300'}
              ${i === 0 ? 'ring-2 ring-blue-200' : ''}`}
          >
            <div className="font-medium">{t.label} {i === 0 && <span className="text-xs text-blue-600 ml-1">Recommended</span>}</div>
            <div className="text-sm text-gray-500">{t.desc}</div>
          </button>
        ))}
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
