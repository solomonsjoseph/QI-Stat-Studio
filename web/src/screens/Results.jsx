import React, { useEffect, useState } from 'react'
import { useApp } from '../App'
import BackButton from '../components/BackButton'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'
import { TEMPLATE_LABELS } from '../templateLabels'

function errorMessage(err, fallback = 'Analysis failed') {
  return `${err.message || fallback}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

function ResultCard({ run, single }) {
  const templateLabel = TEMPLATE_LABELS[run.template] || run.template
  const interpretation = run.ai_interpretation || run.interpretation
  const headingId = `run-${run.run_id}-heading`

  return (
    <div className="mb-6">
      <section className="card mb-4" aria-labelledby={headingId}>
        <h2 id={headingId} className="mb-1 font-medium text-ink">{single ? 'Summary' : templateLabel}</h2>
        <p className="text-sm leading-6 text-ink-soft">{run.result_summary}</p>
      </section>

  {run.table && run.table.length > 0 && (
    <div className="mb-4 overflow-x-auto">
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
        <div className="card mb-4 p-2">
          <img src={`data:image/png;base64,${run.figure_base64}`} alt={single ? 'Analysis figure' : `${templateLabel} figure`} className="w-full rounded-lg" />
        </div>
      )}

      {(run.n_dropped_unpaired != null || run.n_pairs != null) && (
        <p className="text-xs text-ink-faint mb-2">
          {run.n_pairs != null && `${run.n_pairs} paired observation(s). `}
          {run.n_dropped_unpaired != null && run.n_dropped_unpaired > 0 && `${run.n_dropped_unpaired} record(s) excluded (unpaired).`}
        </p>
      )}

      {interpretation && (
        <div className="alert-info mb-4">
          <h2 className="mb-1 font-medium">AI Interpretation</h2>
          <p>{interpretation}</p>
        </div>
      )}

      <div className="text-sm text-ink-soft"><p>{run.methods}</p></div>
    </div>
  )
}

export default function Results() {
  const { ctx, update, next, prev } = useApp()
  const [runs, setRuns] = useState(ctx.runs?.length ? ctx.runs : [])
  const [failures, setFailures] = useState([])
  const [narrative, setNarrative] = useState(null)
  const [interpretationLoading, setInterpretationLoading] = useState(false)
  const [interpretationError, setInterpretationError] = useState('')
  const [interpretationOff, setInterpretationOff] = useState(false)
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

        const planRuns = runResp.runs || []
        setRuns(planRuns)
        setLoading(false)
        update({ runs: planRuns })

        setInterpretationLoading(true)
        setInterpretationError('')
        try {
          const interpResp = await api.interpretResults(ctx.projectId)
          if (cancelled) return
          const interpretations = Object.fromEntries((interpResp.interpretations || []).map(i => [i.run_id, i.text]))
          const narrativeData = { limitations: interpResp.limitations || [], abstract_draft: interpResp.abstract_draft || '' }
          const mergedRuns = planRuns.map(r => ({ ...r, ai_interpretation: interpretations[r.run_id] || r.ai_interpretation }))
          setRuns(mergedRuns)
          setNarrative(narrativeData)
          update({ runs: mergedRuns, abstractDraft: narrativeData.abstract_draft })
        } catch (err) {
          if (cancelled) return
          if (err.code === 'advisor_unavailable') setInterpretationOff(true)
          else setInterpretationError(errorMessage(err, 'Could not generate AI interpretation'))
        } finally {
          if (!cancelled) setInterpretationLoading(false)
        }
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
            <BackButton onClick={prev}>← Back to analysis plan</BackButton>
          </div>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="screen flex items-center justify-center gap-2 text-sm text-ink-soft" aria-live="polite">
        <Spinner />
        Running your analysis — this usually takes 5–30 seconds.
      </div>
    )
  }

  const allLimitations = [...(narrative?.limitations || [])]
  runs.forEach(r => (r.limitations || []).forEach(l => { if (!allLimitations.includes(l)) allLimitations.push(l) }))

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

      {runs.map(r => <ResultCard key={r.run_id} run={r} single={runs.length === 1} />)}

      {interpretationLoading && (
        <p className="mb-4 flex items-center gap-2 text-sm text-ink-soft" aria-live="polite"><Spinner />Preparing AI interpretation…</p>
      )}

      {interpretationOff && (
        <p role="status" className="alert-warn mb-4">AI interpretation is off. You can write your own on the next screen.</p>
      )}

      {interpretationError && (
        <p role="alert" className="alert-error mb-4">
          Could not generate AI interpretation: {interpretationError}
        </p>
      )}

      {allLimitations.length > 0 && (
        <div className="alert-warn mb-6">
          <h2 className="mb-1 font-medium">Limitations</h2>
          <ul className="list-disc pl-5 text-sm">
            {allLimitations.map((l, i) => <li key={i}>{l}</li>)}
          </ul>
        </div>
      )}

      <button type="button" onClick={next} className="btn-primary">Edit & Review</button>
    </div>
  )
}
