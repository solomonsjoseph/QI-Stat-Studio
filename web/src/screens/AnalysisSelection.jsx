import React, { useEffect, useState } from 'react'
import { useApp } from '../App'
import BackButton from '../components/BackButton'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
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
  const { ctx, update, next, prev } = useApp()
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
    <div className="screen">
      <PageIntro step="analysis" title="Choose Your Analysis" lead="Based on your answers, we recommend the highlighted option. You can choose any." />
      {loading && <p aria-live="polite" className="mb-4 flex items-center gap-2 text-sm text-ink-soft"><Spinner />Loading recommendations…</p>}
      {error && <p role="alert" className="alert-warn mb-4">{error}</p>}
      <div className="mb-8 flex flex-col gap-3" role="radiogroup" aria-label="Analysis template">
        {options.map((opt, i) => {
          const tmpl = LABEL[opt.template] || { label: opt.template, desc: opt.description }
          const isSelected = selected === opt.template
          return (
            <button
              type="button"
              key={opt.template}
              onClick={() => update({ template: opt.template, params: {}, columnMap: {}, results: {}, resultSummary: undefined, runId: undefined, aiInterpretation: '', editedInterp: '', editedCaption: '' })}
              aria-pressed={isSelected}
              className={`flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-left text-sm transition hover:border-brand-ring ${isSelected ? 'border-brand bg-brand-tint' : 'border-line bg-surface'}`}
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-line bg-canvas text-xs font-medium text-ink-soft">{i + 1}</span>
              <span className="min-w-0">
                <span className="block font-medium text-ink">
                  {tmpl.label}
                  {opt.recommended && <span className="ml-2 inline-flex rounded-lg bg-brand-tint px-2 py-0.5 text-xs font-medium text-brand-deep">Recommended</span>}
                </span>
                <span className="mt-1 block text-ink-soft">{opt.description || tmpl.desc}</span>
              </span>
            </button>
          )
        })}
      </div>
      <div className="flex flex-wrap gap-3">
        <BackButton onClick={prev} disabled={loading} />
        <button type="button" onClick={next} disabled={!selected || loading} className="btn-primary">
          Continue
        </button>
      </div>
    </div>
  )
}
