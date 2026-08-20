import React, { useEffect, useState } from 'react'
import { useApp } from '../App'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'

const TEMPLATE_LABELS = {
  descriptive_summary: 'Descriptive Summary',
  before_after_mean: 'Before/After: Mean',
  before_after_pct: 'Before/After: Proportion',
  run_chart: 'Run Chart',
  p_chart: 'p-Chart',
  u_c_chart: 'u/c-Chart',
}

const SEMANTIC_COLUMN_FIELDS = new Set(['group_col', 'value_col', 'date_col', 'numerator_col', 'denominator_col', 'count_col', 'outcome_col'])

function columnMapFor(params) {
  const columnMap = {}
  SEMANTIC_COLUMN_FIELDS.forEach(field => {
    if (params?.[field]) columnMap[field] = params[field]
  })
  return columnMap
}

function errorMessage(err) {
  return `${err.message || 'AI analysis planning failed'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function AnalysisPlanStage() {
  const { ctx, update, next } = useApp()
  const [turns, setTurns] = useState([])
  const [analyses, setAnalyses] = useState([])
  const [confirmed, setConfirmed] = useState(false)
  const [input, setInput] = useState('')
  const [pendingRedacted, setPendingRedacted] = useState(null)
  const [loading, setLoading] = useState(false)
  const [starting, setStarting] = useState(true)
  const [error, setError] = useState('')

  function applyPlanResult(body) {
    setTurns(body.turns)
    setAnalyses(body.analyses)
    setConfirmed(body.confirmed)
  }

  useEffect(() => {
    let cancelled = false
    async function start() {
      try {
        const project = await api.getProject(ctx.projectId)
        const plan = project.ai_analysis_plan
        if (!cancelled && plan?.turns?.length) {
          setTurns(plan.turns)
          setAnalyses(plan.analyses || [])
          setConfirmed(!!plan.confirmed)
          return
        }
      } catch {
        // fall through to starting a fresh recommendation
      }
      if (cancelled) return
      try {
        const body = await api.recommendPlan(ctx.projectId, null)
        if (!cancelled) applyPlanResult(body)
      } catch (err) {
        if (!cancelled) setError(errorMessage(err))
      }
    }
    start().finally(() => { if (!cancelled) setStarting(false) })
    return () => { cancelled = true }
  }, [ctx.projectId])

  async function send(text) {
    if (!text.trim()) return
    setLoading(true)
    setError('')
    try {
      const body = await api.recommendPlan(ctx.projectId, text)
      applyPlanResult(body)
      setInput('')
      setPendingRedacted(null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function share() {
    const text = pendingRedacted ?? input
    if (!text.trim()) return
    if (pendingRedacted === null) {
      setLoading(true)
      setError('')
      try {
        const scan = await api.scrubPreview(text)
        if (scan.redacted) {
          setPendingRedacted(scan.text)
          setLoading(false)
          return
        }
      } catch (err) {
        setError(errorMessage(err))
        setLoading(false)
        return
      }
    }
    await send(text)
  }

  function accept(template) {
    send(`I accept the ${TEMPLATE_LABELS[template] || template} recommendation.`)
  }

  function deny(template) {
    send(`Please remove the ${TEMPLATE_LABELS[template] || template} recommendation from the plan.`)
  }

  function handleContinue() {
    const first = analyses[0]
    if (!first) return
    const columnMap = columnMapFor(first.parameters)
    if (ctx.uploadId) api.updateColumnMap(ctx.uploadId, ctx.colTypes || {}, columnMap).catch(() => {})
    update({
      template: first.template,
      params: first.parameters || {},
      columnMap,
      analysisPlan: analyses,
      results: {},
      resultSummary: undefined,
      runId: undefined,
      aiInterpretation: '',
      editedInterp: '',
      editedCaption: '',
    })
    next()
  }

  const lastAiTurn = [...turns].reverse().find(t => t.role === 'ai')

  return (
    <div className="screen">
      <PageIntro
        step="analysis"
        title="Analysis Plan"
        lead="The AI recommends analyses based on your confirmed project definition. Accept, deny, or ask for something different."
      />
      {starting && <p aria-live="polite" className="mb-4 flex items-center gap-2 text-sm text-ink-soft"><Spinner />Reviewing your project and dataset…</p>}
      {error && <p role="alert" className="alert-error mb-4">{error}</p>}

      {analyses.length > 0 && (
        <div className="mb-6 flex flex-col gap-3">
          {analyses.map((a, i) => (
            <div key={`${a.template}-${i}`} className="card">
              <p className="font-medium text-ink">{TEMPLATE_LABELS[a.template] || a.template}</p>
              {a.rationale && <p className="mt-1 text-sm text-ink-soft">{a.rationale}</p>}
              <div className="mt-2 flex gap-2">
                <button type="button" onClick={() => accept(a.template)} disabled={loading} className="btn-secondary px-3 py-1">Accept</button>
                <button type="button" onClick={() => deny(a.template)} disabled={loading} className="btn-secondary px-3 py-1">Deny</button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="card flex flex-col gap-2 mb-6">
        {turns.map((turn, i) => (
          <p key={i} className={turn.role === 'ai' ? 'text-ink' : 'text-ink-soft'}>
            <strong>{turn.role === 'ai' ? 'AI' : 'You'}:</strong> {turn.content}
          </p>
        ))}
        {pendingRedacted !== null && (
          <p role="alert" className="alert-warn">
            We removed what looked like PHI from your message. Click Share again to send the redacted version below.
          </p>
        )}
        <textarea
          className="input"
          value={pendingRedacted ?? input}
          onChange={e => { setInput(e.target.value); setPendingRedacted(null) }}
          placeholder="Ask for a different analysis, or say it looks good..."
          disabled={loading}
        />
        <div className="flex items-center justify-between">
          {lastAiTurn?.reasoning ? (
            <span title={lastAiTurn.reasoning} aria-label="AI thinking" className="text-sm text-ink-faint" style={{ cursor: 'help' }}>
              (i) AI thinking
            </span>
          ) : <span />}
          <button type="button" onClick={share} disabled={loading} className="btn-primary">
            {loading && <Spinner />}
            Share
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        <button type="button" onClick={handleContinue} disabled={!confirmed || loading} className="btn-primary">
          Continue
        </button>
      </div>
      {!confirmed && <p className="mt-2 text-sm text-ink-faint">Confirm the plan with the AI before continuing.</p>}
    </div>
  )
}
