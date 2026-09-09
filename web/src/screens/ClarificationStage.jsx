import React, { useEffect, useState } from 'react'
import { useApp } from '../App'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'

function parseNumberedQuestions(text) {
  if (!text) return []
  const lines = text.split('\n')
  const questions = []
  let current = null

  for (const rawLine of lines) {
    const line = rawLine.trim()
    const match = line.match(/^(\d+)[\.\)]\s*(.*)$/)
    if (match) {
      if (current) questions.push(current)
      current = { num: match[1], text: match[2] }
    } else if (current && line) {
      current.text += ' ' + line
    }
  }
  if (current) questions.push(current)
  return questions
}

function StatusChip({ status }) {
  const st = status || 'unknown'
  const styles = {
    'user-confirmed': 'bg-emerald-50 text-emerald-700 border-emerald-200',
    'user-corrected': 'bg-sky-50 text-sky-700 border-sky-200',
    inferred: 'bg-amber-50 text-amber-700 border-amber-200',
    unknown: 'bg-gray-50 text-gray-500 border-gray-200',
  }
  const labels = {
    'user-confirmed': 'Confirmed',
    'user-corrected': 'Corrected',
    inferred: 'Inferred by AI',
    unknown: 'Unknown',
  }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${styles[st] || styles.unknown}`}>
      {labels[st] || st}
    </span>
  )
}

export default function ClarificationStage() {
  const { ctx, update, next } = useApp()
  const [turns, setTurns] = useState([])
  const [confirmed, setConfirmed] = useState(false)
  const [isStale, setIsStale] = useState(false)
  const [suggestion, setSuggestion] = useState(null)
  const [design, setDesign] = useState(ctx.design || {})
  const [editingDesign, setEditingDesign] = useState(false)
  const [editDesignDraft, setEditDesignDraft] = useState({})
  const [questionAnswers, setQuestionAnswers] = useState({})
  const [singleAnswer, setSingleAnswer] = useState('')
  const [pendingRedacted, setPendingRedacted] = useState(null)
  const [loading, setLoading] = useState(false)
  const [savingDesign, setSavingDesign] = useState(false)
  const [hydrated, setHydrated] = useState(false)
  const [error, setError] = useState('')
  const colNames = Object.keys(ctx.colTypes || {})
  const aiTurnCount = turns.filter(t => t.role === 'ai').length
  const lastAiTurn = [...turns].reverse().find(t => t.role === 'ai')
  const parsedQuestions = parseNumberedQuestions(lastAiTurn?.content || '')

  useEffect(() => {
    let cancelled = false
    async function hydrate() {
      try {
        const project = await api.getProject(ctx.projectId)
        if (cancelled) return
        const state = project.ai_clarification_state
        if (state) {
          if (state.turns) setTurns(state.turns)
          if (state.confirmed) setConfirmed(true)
          if (state.stale) setIsStale(true)
        }
        if (project.ai_project_design) {
          setDesign(project.ai_project_design)
          update({ design: project.ai_project_design })
        }
      } catch {
        // Fresh start
      } finally {
        if (!cancelled) setHydrated(true)
      }
    }
    hydrate()
    return () => { cancelled = true }
  }, [ctx.projectId])

  // Automatically start opening turn if no turns exist after hydration
  useEffect(() => {
    if (hydrated && turns.length === 0 && !loading && !error) {
      startOpeningTurn()
    }
  }, [hydrated, turns.length])


  async function startOpeningTurn() {
    setLoading(true)
    setError('')
    try {
      const body = await api.clarify(ctx.projectId, null)
      applyClarifyResult(body)
    } catch (err) {
      setError(err.message || 'AI service error. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  function applyClarifyResult(body) {
    setTurns(body.turns || [])
    setConfirmed(!!body.confirmed)
    setQuestionAnswers({})
    setSingleAnswer('')
    if (body.suggested_title || body.suggested_description) {
      setSuggestion({
        title: body.suggested_title || ctx.projectTitle,
        description: body.suggested_description || ctx.projectDesc,
      })
    }
    if (body.design) {
      setDesign(body.design)
      update({ design: body.design })
    }
  }

  async function sendResponse(e) {
    if (e) e.preventDefault()
    let messageText = ''
    if (parsedQuestions.length > 0) {
      const parts = parsedQuestions
        .map(q => {
          const ans = questionAnswers[q.num]?.trim()
          return ans ? `${q.num}. ${ans}` : null
        })
        .filter(Boolean)
      messageText = parts.join('\n')
    } else {
      messageText = singleAnswer.trim()
    }

    if (!messageText) return

    setLoading(true)
    setError('')
    try {
      const scan = await api.scrubPreview(messageText)
      if (scan.redacted && pendingRedacted === null) {
        setPendingRedacted(scan.text)
        setLoading(false)
        return
      }

      const textToSend = pendingRedacted ?? messageText
      const body = await api.clarify(ctx.projectId, textToSend)
      applyClarifyResult(body)
      setPendingRedacted(null)
    } catch (err) {
      setError(err.message || 'AI service error. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  async function handleConfirmAndProceed() {
    setLoading(true)
    setError('')
    try {
      await api.confirmClarification(ctx.projectId)
      setConfirmed(true)
      let guidanceRecs = []
      try {
        const guidance = await api.collectionGuidance(ctx.projectId)
        guidanceRecs = guidance.recommendations || []
      } catch {
        // Non-blocking advisory call
      }
      update({ collectionRecs: guidanceRecs, design })
      next()
    } catch (err) {
      setError(err.message || 'Could not confirm clarification.')
    } finally {
      setLoading(false)
    }
  }

  function startEditDesign() {
    setEditDesignDraft(JSON.parse(JSON.stringify(design || {})))
    setEditingDesign(true)
  }

  async function saveDesignEdit(e) {
    e.preventDefault()
    setSavingDesign(true)
    setError('')
    try {
      const updated = await api.updateDesign(ctx.projectId, editDesignDraft)
      const newDesign = updated.ai_project_design || editDesignDraft
      setDesign(newDesign)
      update({ design: newDesign })
      setEditingDesign(false)
    } catch (err) {
      setError(err.message || 'Failed to update project design')
    } finally {
      setSavingDesign(false)
    }
  }

  return (
    <div className="screen max-w-2xl space-y-6">
      <PageIntro
        step="clarify"
        title="Project Clarification"
        lead="Work with the AI to clarify and confirm your project definition before selecting an analysis."
      />

      {isStale && (
        <div className="alert-warn" role="alert">
          Your project inputs changed — review the updated project understanding or re-run clarification.
        </div>
      )}

      {error && (
        <div className="alert-error flex flex-col gap-2" role="alert">
          <p>{error}</p>
          <button type="button" onClick={() => (turns.length === 0 ? startOpeningTurn() : sendResponse())} className="btn-secondary self-start text-xs">
            Try again
          </button>
        </div>
      )}

      {/* Suggested title/description rewrite card */}
      {suggestion && (
        <div className="card alert-info">
          <h3 className="font-semibold text-ink mb-1">Suggested Project Refinement</h3>
          <p className="text-xs text-ink-soft mb-3">The AI suggested more specific titles and descriptions based on your data:</p>
          <div className="space-y-3 mb-4">
            <div>
              <label className="text-xs font-medium text-ink">Title</label>
              <input
                className="input mt-1"
                value={suggestion.title}
                onChange={e => setSuggestion(s => ({ ...s, title: e.target.value }))}
              />
            </div>
            <div>
              <label className="text-xs font-medium text-ink">Description</label>
              <textarea
                className="input mt-1 min-h-20"
                value={suggestion.description}
                onChange={e => setSuggestion(s => ({ ...s, description: e.target.value }))}
              />
            </div>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={async () => {
                await api.updateProject(ctx.projectId, { title: suggestion.title, description: suggestion.description })
                update({ projectTitle: suggestion.title, projectDesc: suggestion.description })
                setSuggestion(null)
              }}
              className="btn-primary text-xs"
            >
              Accept rewrite
            </button>
            <button type="button" onClick={() => setSuggestion(null)} className="btn-secondary text-xs">
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Structured Understanding Card */}
      <div className="card space-y-4" aria-labelledby="understanding-heading">
        <div className="flex items-center justify-between border-b border-line pb-3">
          <h2 id="understanding-heading" className="text-lg font-semibold text-ink">
            Here is my understanding of your project
          </h2>
          <button
            type="button"
            onClick={() => (editingDesign ? setEditingDesign(false) : startEditDesign())}
            className="btn-secondary text-xs"
          >
            {editingDesign ? 'Cancel' : 'Edit Definition'}
          </button>
        </div>

        {editingDesign ? (
          <form onSubmit={saveDesignEdit} className="space-y-4 pt-2">
            <div>
              <label htmlFor="edit-aim" className="label">Aim</label>
              <input
                id="edit-aim"
                className="input"
                value={editDesignDraft.aim || ''}
                onChange={e => setEditDesignDraft({ ...editDesignDraft, aim: e.target.value })}
              />
            </div>
            <div>
              <label htmlFor="edit-population" className="label">Population</label>
              <input
                id="edit-population"
                className="input"
                value={editDesignDraft.population || ''}
                onChange={e => setEditDesignDraft({ ...editDesignDraft, population: e.target.value })}
              />
            </div>
            <div>
              <label htmlFor="edit-setting" className="label">Setting</label>
              <input
                id="edit-setting"
                className="input"
                value={editDesignDraft.setting || ''}
                onChange={e => setEditDesignDraft({ ...editDesignDraft, setting: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="edit-outcome-col" className="label">Primary Outcome Column</label>
                <select
                  id="edit-outcome-col"
                  className="input"
                  value={editDesignDraft.primary_outcome?.column || ''}
                  onChange={e => setEditDesignDraft({
                    ...editDesignDraft,
                    primary_outcome: { ...(editDesignDraft.primary_outcome || { label: 'Primary' }), column: e.target.value || null },
                  })}
                >
                  <option value="">(None)</option>
                  {colNames.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="edit-denom-col" className="label">Denominator Column</label>
                <select
                  id="edit-denom-col"
                  className="input"
                  value={editDesignDraft.primary_outcome?.denominator_column || ''}
                  onChange={e => setEditDesignDraft({
                    ...editDesignDraft,
                    primary_outcome: { ...(editDesignDraft.primary_outcome || { label: 'Primary' }), denominator_column: e.target.value || null },
                  })}
                >
                  <option value="">(None)</option>
                  {colNames.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="edit-date-col" className="label">Date Column</label>
                <select
                  id="edit-date-col"
                  className="input"
                  value={editDesignDraft.time_structure?.date_column || ''}
                  onChange={e => setEditDesignDraft({
                    ...editDesignDraft,
                    time_structure: { ...(editDesignDraft.time_structure || { has_dates: true }), date_column: e.target.value || null },
                  })}
                >
                  <option value="">(None)</option>
                  {colNames.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="edit-group-col" className="label">Grouping Column</label>
                <select
                  id="edit-group-col"
                  className="input"
                  value={editDesignDraft.group_column || ''}
                  onChange={e => setEditDesignDraft({ ...editDesignDraft, group_column: e.target.value || null })}
                >
                  <option value="">(None)</option>
                  {colNames.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            </div>
            <div>
              <label htmlFor="edit-pairing-col" className="label">Pairing ID Column (if paired)</label>
              <select
                id="edit-pairing-col"
                className="input"
                value={editDesignDraft.pairing_id_column || ''}
                onChange={e => setEditDesignDraft({ ...editDesignDraft, pairing_id_column: e.target.value || null, paired: !!e.target.value })}
              >
                <option value="">(None - Unpaired)</option>
                {colNames.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div className="flex gap-2">
              <button type="submit" disabled={savingDesign} className="btn-primary text-xs">
                {savingDesign ? 'Saving…' : 'Save Definition'}
              </button>
              <button type="button" onClick={() => setEditingDesign(false)} className="btn-secondary text-xs">
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <>
            {design.plain_restatement && (
              <p className="text-sm text-ink-soft italic">{design.plain_restatement}</p>
            )}
            <dl className="divide-y divide-line text-sm">
            <div className="py-2 flex items-center justify-between">
              <dt className="text-ink-soft w-1/3">Aim</dt>
              <dd className="text-ink font-medium flex-1">{design.aim || 'Not specified'}</dd>
              <dd><StatusChip status={design.status?.['aim']} /></dd>
            </div>
            <div className="py-2 flex items-center justify-between">
              <dt className="text-ink-soft w-1/3">Population</dt>
              <dd className="text-ink font-medium flex-1">{design.population || 'Not specified'}</dd>
              <dd><StatusChip status={design.status?.['population']} /></dd>
            </div>
            <div className="py-2 flex items-center justify-between">
              <dt className="text-ink-soft w-1/3">Setting</dt>
              <dd className="text-ink font-medium flex-1">{design.setting || 'Not specified'}</dd>
              <dd><StatusChip status={design.status?.['setting']} /></dd>
            </div>
            <div className="py-2 flex items-center justify-between">
              <dt className="text-ink-soft w-1/3">Primary Outcome</dt>
              <dd className="text-ink font-medium flex-1">
                {design.primary_outcome?.label || design.primary_outcome || 'Not specified'}
                {design.primary_outcome?.column && (
                  <span className="text-xs text-ink-soft ml-2 font-mono">({design.primary_outcome.column})</span>
                )}
              </dd>
              <dd><StatusChip status={design.status?.['primary_outcome.column']} /></dd>
            </div>
            <div className="py-2 flex items-center justify-between">
              <dt className="text-ink-soft w-1/3">Comparison</dt>
              <dd className="text-ink font-medium flex-1 capitalize">{design.comparison || 'none'}</dd>
              <dd><StatusChip status={design.status?.['comparison']} /></dd>
            </div>
            <div className="py-2 flex items-center justify-between">
              <dt className="text-ink-soft w-1/3">Time Structure</dt>
              <dd className="text-ink font-medium flex-1">
                {design.time_structure?.has_dates ? (
                  <span>{design.time_structure.granularity || 'Over time'} <span className="font-mono text-xs">({design.time_structure.date_column})</span></span>
                ) : 'No time periods'}
              </dd>
              <dd><StatusChip status={design.status?.['time_structure.date_column']} /></dd>
            </div>
            <div className="py-2 flex items-center justify-between">
              <dt className="text-ink-soft w-1/3">Design Type</dt>
              <dd className="text-ink font-medium flex-1">{design.design_type || (design.paired ? 'Paired Comparison' : 'Standard')}</dd>
              <dd><StatusChip status={design.status?.['design_type']} /></dd>
            </div>
          </dl>
          </>
        )}
      </div>

      {/* Conversation Turns List */}
      <div className="card space-y-3">
        <h3 className="font-medium text-ink">Clarification Dialogue</h3>
        <div className="space-y-3 max-h-80 overflow-y-auto pr-1">
          {turns.map((turn, idx) => (
            <div
              key={idx}
              className={`p-3 rounded-lg text-sm ${turn.role === 'ai' ? 'bg-canvas border border-line text-ink' : 'bg-primary/5 text-ink-soft ml-8'}`}
            >
              <p className="font-semibold text-xs text-ink-soft mb-1">{turn.role === 'ai' ? 'AI Advisor' : 'You'}</p>
              <div className="whitespace-pre-wrap">{turn.content}</div>
            </div>
          ))}
          {loading && (
            <div className="p-3 bg-canvas border border-line rounded-lg text-sm flex items-center gap-2 text-ink-soft">
              <Spinner /> Thinking…
            </div>
          )}
        </div>

        {/* Input Form for resident answers */}
        {!confirmed && (
          <form onSubmit={sendResponse} className="pt-3 border-t border-line space-y-3">
            <p className="text-xs font-medium text-ink-soft">Answer the questions above to refine your project:</p>

            {parsedQuestions.length > 0 ? (
              <div className="space-y-3">
                {parsedQuestions.map(q => (
                  <div key={q.num}>
                    <label htmlFor={`q-${q.num}`} className="text-xs font-medium text-ink block mb-1">
                      {q.num}. {q.text}
                    </label>
                    <input
                      id={`q-${q.num}`}
                      className="input w-full"
                      value={questionAnswers[q.num] || ''}
                      onChange={e => setQuestionAnswers({ ...questionAnswers, [q.num]: e.target.value })}
                      disabled={loading}
                      placeholder="Your answer..."
                    />
                  </div>
                ))}
              </div>
            ) : (
              <div>
                <textarea
                  className="input w-full min-h-24"
                  value={pendingRedacted ?? singleAnswer}
                  onChange={e => { setSingleAnswer(e.target.value); setPendingRedacted(null) }}
                  placeholder="Provide clarification or ask the AI a question..."
                  disabled={loading}
                />
              </div>
            )}

            {pendingRedacted && (
              <p className="text-xs text-amber-700 bg-amber-50 p-2 rounded border border-amber-200">
                Redacted potential identifiers. Click Submit to send scrubbed text.
              </p>
            )}

            <div className="flex items-center justify-between pt-1">
              <button
                type="submit"
                disabled={loading || (parsedQuestions.length > 0 ? Object.values(questionAnswers).every(a => !a?.trim()) : !singleAnswer.trim())}
                className="btn-secondary text-xs"
              >
                {loading ? <Spinner /> : 'Submit Answers'}
              </button>

              {(aiTurnCount >= 4 || design.sufficient_to_continue) && (
                <div className="flex flex-col items-end gap-1">
                  <p className="text-xs text-ink-soft max-w-xs text-right">
                    Confirming marks every field above (aim, population, outcome, comparison, etc.) as reviewed by you. Edit any field first if it is wrong.
                  </p>
                  <button
                    type="button"
                    onClick={handleConfirmAndProceed}
                    disabled={loading}
                    className="btn-primary text-xs"
                  >
                    Confirm project definition →
                  </button>
                </div>
              )}
            </div>
          </form>
        )}

        {confirmed && (
          <div className="pt-3 border-t border-line flex items-center justify-between">
            <span className="text-xs text-emerald-700 font-medium">✓ Project definition confirmed</span>
            <button
              type="button"
              onClick={handleConfirmAndProceed}
              disabled={loading}
              className="btn-primary text-xs"
            >
              Continue to Data Review →
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
