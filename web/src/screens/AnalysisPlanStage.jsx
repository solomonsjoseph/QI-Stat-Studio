import React, { useEffect, useRef, useState } from 'react'
import { useApp } from '../App'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'

const DATE_PARAM_KEYS = new Set(['intervention_date'])
const TEXT_PARAM_KEYS = new Set(['pre_val', 'post_val', 'intervention_label'])
const COLUMN_PARAM_KEYS = new Set([
  'group_col', 'value_col', 'date_col', 'numerator_col', 'denominator_col',
  'count_col', 'outcome_col', 'id_col',
])

function errorMessage(err) {
  return `${err.message || 'AI analysis planning failed'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

function ConfidenceChip({ level }) {
  if (!level) return null
  const styles = {
    high: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    medium: 'bg-amber-50 text-amber-700 border-amber-200',
    low: 'bg-red-50 text-red-700 border-red-200',
  }
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border ${styles[level] || styles.medium}`}>
      {level}
    </span>
  )
}

function ParamControl({ paramKey, value, onChange, colNames, disabled }) {
  const id = `param-${paramKey}`
  if (COLUMN_PARAM_KEYS.has(paramKey)) {
    return (
      <select id={id} className="input" value={value || ''} onChange={e => onChange(e.target.value)} disabled={disabled}>
        <option value="">(select column)</option>
        {colNames.map(c => <option key={c} value={c}>{c}</option>)}
      </select>
    )
  }
  if (DATE_PARAM_KEYS.has(paramKey)) {
    return <input id={id} type="date" className="input" value={value || ''} onChange={e => onChange(e.target.value)} disabled={disabled} />
  }
  if (Array.isArray(value)) {
    return (
      <select
        id={id}
        multiple
        className="input"
        value={value}
        onChange={e => onChange(Array.from(e.target.selectedOptions).map(o => o.value))}
        disabled={disabled}
      >
        {colNames.map(c => <option key={c} value={c}>{c}</option>)}
      </select>
    )
  }
  return <input id={id} type="text" className="input" value={value ?? ''} onChange={e => onChange(e.target.value)} disabled={disabled} />
}

export default function AnalysisPlanStage() {
  const { ctx, update, next } = useApp()
  const [turns, setTurns] = useState([])
  const [analyses, setAnalyses] = useState([])
  const [confirmed, setConfirmed] = useState(false)
  const [feasibleTemplates, setFeasibleTemplates] = useState([])
  const [expanded, setExpanded] = useState({})
  const [editAll, setEditAll] = useState(false)
  const [overrideInput, setOverrideInput] = useState('')
  const [overrideChanges, setOverrideChanges] = useState([])
  const [planHistoryInitial, setPlanHistoryInitial] = useState(null)
  const [showFinalConfirm, setShowFinalConfirm] = useState(false)
  const [addTemplate, setAddTemplate] = useState('')
  const [loading, setLoading] = useState(false)
  const [starting, setStarting] = useState(true)
  const [error, setError] = useState('')

  const colNames = Object.keys(ctx.colTypes || {})
  const debounceRef = useRef({})

  function applyPlanResult(body) {
    setTurns(body.turns || [])
    setAnalyses(body.analyses || [])
    setConfirmed(!!body.confirmed)
  }

  async function refreshValidation(currentAnalyses) {
    if (!ctx.uploadId || currentAnalyses.length === 0) return
    try {
      const res = await api.validatePlan(
        ctx.projectId,
        ctx.uploadId,
        currentAnalyses.map(a => ({ template: a.template, parameters: a.parameters })),
      )
      const ids = currentAnalyses.map(a => a.id)
      setAnalyses(prev => prev.map(a => {
        const idx = ids.indexOf(a.id)
        const verdict = idx === -1 ? null : res.items?.[idx]
        if (!verdict) return a
        return { ...a, executable: verdict.ok, errors: verdict.errors || [], missing_params: verdict.missing_params || [] }
      }))
      setFeasibleTemplates(res.feasible_templates || [])
    } catch {
      // Advisory validation call -- non-blocking
    }
  }

  useEffect(() => {
    let cancelled = false
    async function start() {
      try {
        const project = await api.getProject(ctx.projectId)
        const plan = project.ai_analysis_plan
        if (project.ai_plan_history?.initial) {
          setPlanHistoryInitial(project.ai_plan_history.initial)
        }
        if (!cancelled && plan?.turns?.length) {
          setTurns(plan.turns)
          setAnalyses(plan.analyses || [])
          setConfirmed(!!plan.confirmed)
          if (plan.analyses?.length) await refreshValidation(plan.analyses)
          return
        }
      } catch {
        // fall through to starting a fresh recommendation
      }
      if (cancelled) return
      try {
        const body = await api.recommendPlan(ctx.projectId, null)
        if (!cancelled) {
          applyPlanResult(body)
          if (body.analyses?.length) await refreshValidation(body.analyses)
        }
      } catch (err) {
        if (!cancelled) setError(errorMessage(err))
      }
    }
    start().finally(() => { if (!cancelled) setStarting(false) })
    return () => { cancelled = true }
  }, [ctx.projectId])

  function toggleExpand(id) {
    setExpanded(e => ({ ...e, [id]: !e[id] }))
  }

  function removeAnalysis(id) {
    const next = analyses.filter(a => a.id !== id)
    setAnalyses(next)
    refreshValidation(next)
  }

  function addAnalysisFromFeasible() {
    if (!addTemplate) return
    const newItem = {
      id: `${addTemplate}-${Date.now()}`,
      template: addTemplate,
      display_name: addTemplate.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
      question: '',
      rationale: 'Manually added by resident.',
      parameters: {},
      param_confidence: {},
      assumptions: [],
      limitations: [],
      needs_clarification: true,
      executable: false,
      errors: [],
      missing_params: [],
    }
    const next = [...analyses, newItem]
    setAnalyses(next)
    refreshValidation(next)
    setAddTemplate('')
  }

  function updateParam(analysisId, paramKey, value) {
    const next = analyses.map(a => a.id === analysisId ? { ...a, parameters: { ...a.parameters, [paramKey]: value }, needs_clarification: false } : a)
    setAnalyses(next)
    const key = `${analysisId}`
    clearTimeout(debounceRef.current[key])
    debounceRef.current[key] = setTimeout(() => refreshValidation(next), 400)
  }

  function acknowledgeClarification(analysisId) {
    setAnalyses(prev => prev.map(a => a.id === analysisId ? { ...a, needs_clarification: false } : a))
  }

  async function submitOverride() {
    if (!overrideInput.trim()) return
    setLoading(true)
    setError('')
    try {
      const body = await api.overridePlan(ctx.projectId, overrideInput)
      setAnalyses(body.analyses || [])
      setConfirmed(!!body.confirmed)
      setOverrideChanges(body.changes || [])
      setOverrideInput('')
      if (body.analyses?.length) await refreshValidation(body.analyses)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  function restoreInitial() {
    if (!planHistoryInitial) return
    setAnalyses(planHistoryInitial)
    setOverrideChanges([])
    refreshValidation(planHistoryInitial)
  }

  const allExecutable = analyses.length > 0 && analyses.every(a => a.executable && !a.needs_clarification)

  function goToFinalConfirm() {
    setShowFinalConfirm(true)
  }

  async function confirmAndRun() {
    setLoading(true)
    setError('')
    try {
      await api.confirmPlan(ctx.projectId, analyses)
      update({ analysisPlan: analyses })
      next()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  if (showFinalConfirm) {
    return (
      <div className="screen">
        <PageIntro step="analysis" title="Final Confirmation" lead="Review every analysis and its exact parameters before running." />
        <div className="flex flex-col gap-4 mb-6">
          {analyses.map(a => (
            <div key={a.id} className="card">
              <p className="font-medium text-ink">{a.display_name || a.template}</p>
              <p className="text-sm text-ink-soft mt-1">{a.question}</p>
              <dl className="mt-2 text-xs text-ink-soft grid grid-cols-2 gap-1">
                {Object.entries(a.parameters || {}).map(([k, v]) => (
                  <React.Fragment key={k}>
                    <dt className="font-mono">{k}</dt>
                    <dd>{Array.isArray(v) ? v.join(', ') : String(v)}</dd>
                  </React.Fragment>
                ))}
              </dl>
            </div>
          ))}
        </div>
        <div className="flex flex-wrap gap-3">
          <button type="button" onClick={() => setShowFinalConfirm(false)} className="btn-secondary">
            Go back and edit
          </button>
          <button type="button" onClick={confirmAndRun} disabled={loading || !allExecutable} className="btn-primary">
            {loading && <Spinner />}
            Run these analyses
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="screen">
      <PageIntro
        step="analysis"
        title="Analysis Plan"
        lead="The AI recommends analyses based on your confirmed project definition. Review, edit parameters, add or remove analyses, then confirm."
      />
      {starting && <p aria-live="polite" className="mb-4 flex items-center gap-2 text-sm text-ink-soft"><Spinner />Reviewing your project and dataset…</p>}
      {error && <p role="alert" className="alert-error mb-4">{error}</p>}

      {analyses.length > 0 && (
        <div className="flex justify-end mb-3">
          <button type="button" onClick={() => setEditAll(v => !v)} className="btn-secondary text-xs">
            {editAll ? 'Collapse all parameters' : 'Edit all parameters'}
          </button>
        </div>
      )}

      {analyses.length > 0 && (
        <div className="mb-6 flex flex-col gap-3">
          {analyses.map(a => {
            const isExpanded = editAll || expanded[a.id]
            return (
              <div key={a.id} className="card">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="font-medium text-ink">{a.display_name || a.template}</p>
                    {a.question && <p className="text-sm text-ink-soft mt-0.5">{a.question}</p>}
                  </div>
                  <span className={a.executable && !a.needs_clarification ? 'text-xs font-medium text-emerald-700' : 'text-xs font-medium text-amber-700'}>
                    {a.executable && !a.needs_clarification ? 'Ready' : 'Needs your input'}
                  </span>
                </div>

                {a.rationale && <p className="mt-2 text-sm text-ink-soft">{a.rationale}</p>}

                {(a.errors?.length > 0 || a.missing_params?.length > 0) && (
                  <div className="alert-warn mt-2 text-xs">
                    {a.errors?.map((e, i) => <p key={i}>{e}</p>)}
                    {a.missing_params?.length > 0 && <p>Missing: {a.missing_params.join(', ')}</p>}
                  </div>
                )}

                {a.executable && a.needs_clarification && (
                  <div className="alert-warn mt-2 text-xs flex items-center justify-between gap-2">
                    <span>The AI was not confident about one or more parameters above. Review them before running.</span>
                    <button type="button" onClick={() => acknowledgeClarification(a.id)} className="btn-secondary text-xs whitespace-nowrap">
                      I've reviewed this
                    </button>
                  </div>
                )}

                <button type="button" onClick={() => toggleExpand(a.id)} className="mt-2 text-xs text-brand underline">
                  {isExpanded ? 'Hide details' : 'Show assumptions, limitations & parameters'}
                </button>

                {isExpanded && (
                  <div className="mt-3 space-y-3">
                    {a.assumptions?.length > 0 && (
                      <div>
                        <p className="text-xs font-medium text-ink-soft">Assumptions</p>
                        <ul className="list-disc pl-5 text-xs text-ink-soft">
                          {a.assumptions.map((x, i) => <li key={i}>{x}</li>)}
                        </ul>
                      </div>
                    )}
                    {a.limitations?.length > 0 && (
                      <div>
                        <p className="text-xs font-medium text-ink-soft">Limitations</p>
                        <ul className="list-disc pl-5 text-xs text-ink-soft">
                          {a.limitations.map((x, i) => <li key={i}>{x}</li>)}
                        </ul>
                      </div>
                    )}
                    <div>
                      <p className="text-xs font-medium text-ink-soft mb-1">Parameters</p>
                      <div className="grid grid-cols-2 gap-3">
                        {Object.entries(a.parameters || {}).map(([k, v]) => {
                          const confidence = a.param_confidence?.[k]
                          return (
                            <div key={k}>
                              <label htmlFor={`param-${k}-${a.id}`} className="text-xs font-mono text-ink-soft flex items-center gap-1">
                                {k} <ConfidenceChip level={confidence} />
                              </label>
                              <ParamControl
                                paramKey={k}
                                value={v}
                                onChange={val => updateParam(a.id, k, val)}
                                colNames={colNames}
                                disabled={loading}
                              />
                            </div>
                          )
                        })}
                      </div>
                    </div>
                    <button type="button" onClick={() => removeAnalysis(a.id)} className="btn-danger text-xs">
                      Remove this analysis
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {feasibleTemplates.filter(t => !analyses.some(a => a.template === t)).length > 0 && (
        <div className="card mb-6 flex items-center gap-3">
          <label htmlFor="add-analysis-select" className="label mb-0">Add an analysis</label>
          <select id="add-analysis-select" className="input flex-1" value={addTemplate} onChange={e => setAddTemplate(e.target.value)}>
            <option value="">Select a feasible template…</option>
            {feasibleTemplates.filter(t => !analyses.some(a => a.template === t)).map(t => (
              <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
            ))}
          </select>
          <button type="button" onClick={addAnalysisFromFeasible} disabled={!addTemplate} className="btn-secondary">
            Add
          </button>
        </div>
      )}

      <div className="card flex flex-col gap-2 mb-6">
        <h3 className="font-medium text-ink text-sm">Ask for a different approach</h3>
        <p className="text-xs text-ink-faint">Don't include patient names, MRNs, or other identifying information in your messages.</p>
        {overrideChanges.length > 0 && (
          <div className="alert-info text-xs">
            <p className="font-medium mb-1">What changed:</p>
            <ul className="list-disc pl-5">
              {overrideChanges.map((c, i) => <li key={i}>{c}</li>)}
            </ul>
          </div>
        )}
        <textarea
          className="input"
          value={overrideInput}
          onChange={e => setOverrideInput(e.target.value)}
          placeholder="e.g. Use a paired test instead, or drop the run chart..."
          disabled={loading}
        />
        <div className="flex items-center gap-2">
          <button type="button" onClick={submitOverride} disabled={loading || !overrideInput.trim()} className="btn-primary">
            {loading && <Spinner />}
            Submit request
          </button>
          {planHistoryInitial && (
            <button type="button" onClick={restoreInitial} disabled={loading} className="btn-secondary">
              Restore AI recommendation
            </button>
          )}
        </div>
      </div>

      {turns.length > 0 && (
        <div className="card flex flex-col gap-2 mb-6">
          <h3 className="font-medium text-ink text-sm">Conversation history</h3>
          {turns.map((turn, i) => (
            <p key={i} className={turn.role === 'ai' ? 'text-ink text-sm' : 'text-ink-soft text-sm'}>
              <strong>{turn.role === 'ai' ? 'AI' : 'You'}:</strong> {turn.content}
            </p>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-3">
        <button type="button" onClick={goToFinalConfirm} disabled={!allExecutable || loading} className="btn-primary">
          Continue
        </button>
      </div>
      {!allExecutable && analyses.length > 0 && <p className="mt-2 text-sm text-ink-faint">Every analysis must be ready before continuing.</p>}
    </div>
  )
}
