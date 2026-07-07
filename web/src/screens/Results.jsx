import React, { useEffect, useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'

function errorMessage(err, fallback = 'Analysis failed') {
  return `${err.message || fallback}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function Results() {
  const { ctx, update, next } = useApp()
  const initialResult = ctx.results?.result_summary ? ctx.results : null
  const initialInterpretation = ctx.aiInterpretation || initialResult?.interpretation || ''
  const [result, setResult] = useState(initialResult)
  const [aiText, setAiText] = useState(initialInterpretation)
  const [phiBanner, setPhiBanner] = useState(false)
  const [error, setError] = useState('')
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
  }, [ctx.projectId, ctx.uploadId, ctx.template, ctx.params])

  if (error) return <div className="p-8 text-red-700" role="alert">Error: {error}</div>
  if (!result) return <div className="p-8 text-gray-500" aria-live="polite">Running analysis…</div>


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
    <div className="max-w-2xl mx-auto p-8 mt-8">
      <h1 className="text-2xl font-bold mb-4 text-blue-800">Results</h1>

      {phiBanner && (
        <div className="bg-yellow-100 border border-yellow-400 text-yellow-800 px-4 py-3 rounded mb-4 text-sm">
          ⚠ Some text was automatically de-identified before being sent to the AI. No PHI left this server.
        </div>
      )}

      <div className="bg-gray-50 rounded-lg p-4 mb-4 text-sm">
        <h2 className="font-medium mb-1">Summary</h2>
        <p>{result.result_summary}</p>
      </div>

      {result.table && result.table.length > 0 && (
        <div className="overflow-x-auto mb-4">
          <table className="w-full text-sm border-collapse">
            <thead><tr className="bg-gray-100">{Object.keys(result.table[0]).map(k => <th key={k} className="border px-3 py-2 text-left capitalize">{k}</th>)}</tr></thead>
            <tbody>{result.table.map((row, i) => <tr key={i}>{Object.values(row).map((v, j) => <td key={j} className="border px-3 py-2">{String(v)}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}

      {result.figure_base64 && <img src={`data:image/png;base64,${result.figure_base64}`} alt="Analysis figure" className="w-full rounded mb-4 border" />}

      {aiText && (
        <div className="bg-blue-50 border border-blue-200 rounded p-4 text-sm mb-4">
          <h2 className="font-medium text-blue-800 mb-1">AI Interpretation</h2>
          <p>{aiText}</p>
        </div>
      )}

      {interpretationLoading && (
        <p className="text-sm text-gray-500 mb-4" aria-live="polite">Preparing AI interpretation…</p>
      )}

      {interpretationError && (
        <p role="alert" className="text-sm text-red-700 mb-4">
          Could not generate AI interpretation: {interpretationError}
        </p>
      )}

      <div className="text-xs text-gray-500 mb-6"><p>{result.methods}</p></div>

      <button type="button" onClick={continueToEdit} disabled={editDisabled} className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 disabled:opacity-50">{editDisabled ? 'Preparing interpretation…' : 'Edit & Review'}</button>
    </div>
  )
}
