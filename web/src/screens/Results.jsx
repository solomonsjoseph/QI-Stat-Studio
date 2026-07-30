import React, { useEffect, useState } from 'react'
import { useApp } from '../App'
import BackButton from '../components/BackButton'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'

function errorMessage(err, fallback = 'Analysis failed') {
  return `${err.message || fallback}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function Results() {
  const { ctx, update, next, prev } = useApp()
  const initialResult = ctx.results?.result_summary ? ctx.results : null
  const initialInterpretation = ctx.aiInterpretation || initialResult?.interpretation || ''
  const [result, setResult] = useState(initialResult)
  const [aiText, setAiText] = useState(initialInterpretation)
  const [phiBanner, setPhiBanner] = useState(false)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [interpretationLoading, setInterpretationLoading] = useState(false)
  const [interpretationError, setInterpretationError] = useState('')
  useEffect(() => {
    if (result) return
    let cancelled = false
    setError('')
    api.runAnalysis(ctx.projectId, ctx.uploadId, ctx.template, ctx.params)
      .then(async (r) => {
        if (cancelled) return
        setResult(r)
        const fallbackInterpretation = r.interpretation || ''
        setAiText(fallbackInterpretation)
        update({
          runId: r.run_id || r.id,
          resultSummary: r.result_summary,
          results: r,
          ...(fallbackInterpretation ? { aiInterpretation: fallbackInterpretation } : {}),
        })
        setInterpretationLoading(true)
        setInterpretationError('')
        try {
          const chatResp = await api.chat(ctx.projectId, [{
            role: 'user',
            content: `Write a 2-sentence plain-language interpretation of this QI result for a medical resident: ${r.result_summary}. Template: ${ctx.template}.`,
          }])
          if (cancelled) return
          setAiText(chatResp.content)
          if (chatResp.phi_redacted) setPhiBanner(true)
          update({ aiInterpretation: chatResp.content })
        } catch (err) {
          if (!cancelled) setInterpretationError(errorMessage(err, 'Could not generate AI interpretation'))
        } finally {
          if (!cancelled) setInterpretationLoading(false)
        }
      })
      .catch(err => { if (!cancelled) setError(errorMessage(err)) })
    return () => { cancelled = true }
  }, [ctx.projectId, ctx.uploadId, ctx.template, ctx.params, attempt])

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
                setResult(null)
                setAttempt(a => a + 1)
              }}
              className="btn-primary"
            >
              Try again
            </button>
            <BackButton onClick={prev}>← Back to column mapping</BackButton>
          </div>
        </div>
      </div>
    )
  }
  if (!result) {
    return (
      <div className="screen flex items-center justify-center gap-2 text-sm text-ink-soft" aria-live="polite">
        <Spinner />
        Running your analysis — this usually takes 5–30 seconds.
      </div>
    )
  }

  const hasInterpretation = Boolean((aiText || result.interpretation || '').trim())
  const editDisabled = interpretationLoading && !hasInterpretation
  const continueToEdit = () => {
    const fallbackInterpretation = aiText || result.interpretation || ''
    if (fallbackInterpretation && fallbackInterpretation !== ctx.aiInterpretation) {
      update({ aiInterpretation: fallbackInterpretation })
    }
    next()
  }

  return (
    <div className="screen">
      <PageIntro step="results" title="Results" />

      {phiBanner && (
        <div className="alert-warn mb-4">
          Some text was automatically de-identified before being sent to the AI. No PHI left this server.
        </div>
      )}

      <section className="card mb-4" aria-labelledby="results-summary-heading">
        <h2 id="results-summary-heading" className="mb-1 font-medium text-ink">Summary</h2>
        <p className="text-sm leading-6 text-ink-soft">{result.result_summary}</p>
      </section>

      {result.table && result.table.length > 0 && (
        <div className="mb-4 overflow-x-auto">
          <table className="table-clean">
            <thead><tr>{Object.keys(result.table[0]).map(k => <th key={k} className="capitalize">{k}</th>)}</tr></thead>
            <tbody>{result.table.map((row, i) => <tr key={i}>{Object.values(row).map((v, j) => <td key={j}>{String(v)}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}

      {result.figure_base64 && (
        <div className="card mb-4 p-2">
          <img src={`data:image/png;base64,${result.figure_base64}`} alt="Analysis figure" className="w-full rounded-lg" />
        </div>
      )}

      {aiText && (
        <div className="alert-info mb-4">
          <h2 className="mb-1 font-medium">AI Interpretation</h2>
          <p>{aiText}</p>
        </div>
      )}

      {interpretationLoading && (
        <p className="mb-4 flex items-center gap-2 text-sm text-ink-soft" aria-live="polite"><Spinner />Preparing AI interpretation…</p>
      )}

      {interpretationError && (
        <p role="alert" className="alert-error mb-4">
          Could not generate AI interpretation: {interpretationError}
        </p>
      )}

      <div className="mb-6 text-sm text-ink-soft"><p>{result.methods}</p></div>

      <button type="button" onClick={continueToEdit} disabled={editDisabled} className="btn-primary">{editDisabled ? 'Preparing interpretation…' : 'Edit & Review'}</button>
    </div>
  )
}
