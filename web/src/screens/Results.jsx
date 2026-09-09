import React, { useEffect, useState } from 'react'
import { useApp } from '../App'
import BackButton from '../components/BackButton'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'
import { TEMPLATE_LABELS } from '../templateLabels'

const DESCRIPTIVE_TEMPLATES = new Set(['descriptive_summary', 'run_chart', 'p_chart', 'u_c_chart'])
const STATISTICAL_TEMPLATES = new Set(['before_after_mean', 'before_after_pct', 'before_after_paired'])

function errorMessage(err, fallback = 'Analysis failed') {
  return `${err.message || fallback}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

function ResultCard({ run }) {
  const templateLabel = TEMPLATE_LABELS[run.template] || run.template
  const interpretation = run.ai_interpretation || run.interpretation

  return (
    <section className="card mb-4" aria-labelledby={`run-${run.run_id}-heading`}>
      <h3 id={`run-${run.run_id}-heading`} className="mb-1 font-medium text-ink">{templateLabel}</h3>
      {run.result_summary && <p className="text-sm leading-6 text-ink-soft mb-3">{run.result_summary}</p>}

      {run.table && run.table.length > 0 && (
        <div className="mb-3 overflow-x-auto">
          <table className="table-clean">
            <thead>
              <tr>
                {Object.keys(run.table[0]).map(k => (
                  <th key={k} className="capitalize">
                    {({
                      mean_ci_low: 'Mean CI low',
                      mean_ci_high: 'Mean CI high',
                      median_ci_low: 'Median CI low',
                      median_ci_high: 'Median CI high',
                    })[k] || k}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {run.table.map((row, i) => (
                <tr key={i}>
                  {Object.values(row).map((v, j) => (
                    <td key={j}>{v == null ? '—' : String(v)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {run.figure_base64 && (
        <div className="mb-3 p-2 border border-line rounded-lg">
          <img src={`data:image/png;base64,${run.figure_base64}`} alt={`${templateLabel} figure`} className="w-full rounded-lg" />
        </div>
      )}

      {(run.n_dropped_unpaired != null || run.n_pairs != null) && (
        <p className="text-xs text-ink-faint mb-2">
          {run.n_pairs != null && `${run.n_pairs} paired observation(s). `}
          {run.n_dropped_unpaired != null && run.n_dropped_unpaired > 0 && `${run.n_dropped_unpaired} record(s) excluded (unpaired).`}
        </p>
      )}

      {interpretation && (
        <div className="alert-info mb-2">
          <p className="text-sm">{interpretation}</p>
        </div>
      )}

      {run.methods && <p className="text-xs text-ink-faint">{run.methods}</p>}
    </section>
  )
}

export default function Results() {
  const { ctx, update, next, prev } = useApp()
  const [runs, setRuns] = useState(ctx.runs?.length ? ctx.runs : [])
  const [failures, setFailures] = useState([])
  const [narrative, setNarrative] = useState(null)
  const [loading, setLoading] = useState(!ctx.runs?.length)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (ctx.runs?.length) {
      // Already hydrated from resume -- do not re-execute the plan.
      setRuns(ctx.runs)
      setLoading(false)
      return
    }

    let cancelled = false
    setLoading(true)
    setError('')

    async function runAndInterpret() {
      try {
        const analyses = (ctx.analysisPlan || []).map(a => ({ template: a.template, parameters: a.parameters }))
        const runResp = await api.runPlan(ctx.projectId, ctx.uploadId, analyses)
        if (cancelled) return
        setFailures(runResp.failures || [])

        let interpretations = {}
        let narrativeData = null
        try {
          const interpResp = await api.interpretResults(ctx.projectId)
          interpretations = Object.fromEntries((interpResp.interpretations || []).map(i => [i.run_id, i.text]))
          narrativeData = { limitations: interpResp.limitations || [], abstract_draft: interpResp.abstract_draft || '' }
        } catch {
          // Interpretation is advisory -- results still render without it.
        }

        if (cancelled) return
        const mergedRuns = (runResp.runs || []).map(r => ({ ...r, ai_interpretation: interpretations[r.run_id] || r.ai_interpretation }))
        setRuns(mergedRuns)
        setNarrative(narrativeData)
        update({ runs: mergedRuns, abstractDraft: narrativeData?.abstract_draft || '' })
      } catch (err) {
        if (!cancelled) setError(errorMessage(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    runAndInterpret()
    return () => { cancelled = true }
  }, [ctx.projectId, ctx.uploadId, attempt])

  if (error) {
    return (
      <div className="screen" role="alert">
        <PageIntro step="results" title="Results" />
        <div className="alert-error">
          <p className="mb-4">{error}</p>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => {
                setError('')
                setRuns([])
                setAttempt(a => a + 1)
              }}
              className="btn-primary"
            >
              Try again
            </button>
            <BackButton onClick={prev}>← Back to plan</BackButton>
          </div>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="screen flex items-center justify-center gap-2 text-sm text-ink-soft" aria-live="polite">
        <Spinner />
        Running your analyses — this usually takes 5–30 seconds.
      </div>
    )
  }

  const descriptiveRuns = runs.filter(r => DESCRIPTIVE_TEMPLATES.has(r.template))
  const statisticalRuns = runs.filter(r => STATISTICAL_TEMPLATES.has(r.template))
  const otherRuns = runs.filter(r => !DESCRIPTIVE_TEMPLATES.has(r.template) && !STATISTICAL_TEMPLATES.has(r.template))

  return (
    <div className="screen">
      <PageIntro step="results" title="Results" />

      {failures.length > 0 && (
        <div className="alert-error mb-4">
          <h2 className="mb-2 font-medium">Some analyses could not be run</h2>
          {failures.map((f, i) => (
            <div key={i} className="mb-2">
              <p className="font-medium">{TEMPLATE_LABELS[f.template] || f.template}</p>
              {(f.errors || []).map((e, j) => <p key={j} className="text-sm">{e}</p>)}
            </div>
          ))}
          <button type="button" onClick={prev} className="btn-secondary mt-2 text-xs">Back to plan</button>
        </div>
      )}

      {descriptiveRuns.length > 0 && (
        <section className="mb-6">
          <h2 className="mb-3 font-semibold text-ink text-lg">What the data show (descriptive)</h2>
          {descriptiveRuns.map(r => <ResultCard key={r.run_id} run={r} />)}
        </section>
      )}

      {statisticalRuns.length > 0 && (
        <section className="mb-6">
          <h2 className="mb-3 font-semibold text-ink text-lg">Statistical tests</h2>
          {statisticalRuns.map(r => <ResultCard key={r.run_id} run={r} />)}
        </section>
      )}

      {otherRuns.map(r => <ResultCard key={r.run_id} run={r} />)}

      {narrative?.limitations?.length > 0 && (
        <div className="alert-warn mb-6">
          <h2 className="mb-1 font-medium">Limitations</h2>
          <ul className="list-disc pl-5 text-sm">
            {narrative.limitations.map((l, i) => <li key={i}>{l}</li>)}
          </ul>
        </div>
      )}

      <button type="button" onClick={next} className="btn-primary">Edit & Review</button>
    </div>
  )
}
