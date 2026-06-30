import React, { useEffect, useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'

export default function Results() {
  const { ctx, update, next } = useApp()
  const [result, setResult] = useState(null)
  const [aiText, setAiText] = useState('')
  const [phiBanner, setPhiBanner] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (result) return
    api.runAnalysis(ctx.projectId, ctx.uploadId, ctx.template, ctx.params)
      .then(async (r) => {
        setResult(r)
        update({ runId: r.run_id, resultSummary: r.result_summary })
        // AI interpretation
        try {
          const chatResp = await api.chat(ctx.projectId, [{
            role: 'user',
            content: `Write a 2-sentence plain-language interpretation of this QI result for a medical resident: ${r.result_summary}. Template: ${ctx.template}.`,
          }])
          setAiText(chatResp.content)
          if (chatResp.phi_redacted) setPhiBanner(true)
          update({ aiInterpretation: chatResp.content })
        } catch (_) {
          setAiText('')
        }
      })
      .catch(e => setError(e.message))
  }, [])

  if (error) return <div className="p-8 text-red-600">Error: {error}</div>
  if (!result) return <div className="p-8 text-gray-500">Running analysis…</div>

  return (
    <div className="max-w-2xl mx-auto p-8 mt-8">
      <h2 className="text-2xl font-bold mb-4 text-blue-800">Results</h2>

      {phiBanner && (
        <div className="bg-yellow-100 border border-yellow-400 text-yellow-800 px-4 py-3 rounded mb-4 text-sm">
          ⚠ Some text was automatically de-identified before being sent to the AI. No PHI left this server.
        </div>
      )}

      <div className="bg-gray-50 rounded-lg p-4 mb-4 text-sm">
        <p className="font-medium mb-1">Summary</p>
        <p>{result.result_summary}</p>
      </div>

      {result.table && result.table.length > 0 && (
        <div className="overflow-x-auto mb-4">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-gray-100">
                {Object.keys(result.table[0]).map(k => (
                  <th key={k} className="border px-3 py-2 text-left capitalize">{k}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.table.map((row, i) => (
                <tr key={i}>
                  {Object.values(row).map((v, j) => (
                    <td key={j} className="border px-3 py-2">{String(v)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {result.figure_base64 && (
        <img
          src={`data:image/png;base64,${result.figure_base64}`}
          alt="Analysis figure"
          className="w-full rounded mb-4 border"
        />
      )}

      {aiText && (
        <div className="bg-blue-50 border border-blue-200 rounded p-4 text-sm mb-4">
          <p className="font-medium text-blue-800 mb-1">AI Interpretation</p>
          <p>{aiText}</p>
        </div>
      )}

      <div className="text-xs text-gray-400 mb-6">
        <p>{result.methods}</p>
      </div>

      <button
        onClick={next}
        className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800"
      >
        Edit & Review
      </button>
    </div>
  )
}
