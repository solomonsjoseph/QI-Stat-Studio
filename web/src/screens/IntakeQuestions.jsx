import React, { useEffect, useState } from 'react'
import { useApp } from '../App'
import BackButton from '../components/BackButton'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'

const QUESTIONS = [
  { id: 'q1', key: 'q1', text: 'Project description', type: 'stored' },
  { id: 'q2', key: 'q2', text: 'What are you measuring?', type: 'radio', aiType: 'radio', options: ['A rate of events over time (infections per 1,000 catheter-days)', 'A percentage or proportion (percent of patients screened)', 'A count (number of falls per month)', 'An average or median value (average LDL)', 'A yes/no outcome (did the patient get a flu shot)', 'Something else / not sure'], hint: 'Choose the option closest to your primary outcome.' },
  { id: 'q3', key: 'q3', text: 'Are you comparing before and after something?', type: 'radio', aiType: 'radio', options: ['Yes — before and after an intervention', "No — I'm just describing one time period", 'More than two periods (phases)', "I'm not sure"], hint: 'This decides whether we recommend comparison tests or descriptive summaries.' },
  { id: 'q4', key: 'q4', text: 'Are you tracking over time, or comparing two groups?', type: 'radio', aiType: 'radio', options: ['Tracking over time (months, weeks, days)', 'Comparing groups at one point in time', 'Both', "I'm not sure"], hint: 'Run/control charts need a time column.' },
  { id: 'q5', key: 'q5', text: "What's the time unit?", type: 'radio', aiType: 'radio', options: ['Daily', 'Weekly', 'Monthly', 'One row per patient', 'Other', "I'm not sure"], hint: 'How your rows are grouped: one per day, week, month, or one row per patient.' },
  { id: 'q6', key: 'q6', text: 'How many time points (or rows) do you have?', type: 'number', aiType: 'number', hint: "Run and control charts work best with 12 or more time points. If your data turns out to have fewer, the tool will use a run chart instead and say so in your Methods section." },
  { id: 'q7', key: 'q7', text: 'What was the intervention and when did it start?', type: 'composite', aiType: 'intervention', fields: { description: 'textarea', date: 'date' }, labels: { description: 'Intervention description (optional)', date: 'Intervention date (if known)' }, hint: 'We pre-fill this from your project description — just confirm or correct it.' },
  { id: 'q8', key: 'q8', text: 'Who are you comparing?', type: 'radio', aiType: 'radio', options: ['Same unit pre vs. post', 'Intervention vs. control', 'Subgroups', "I'm not sure"], hint: "Skipped automatically if you're not comparing anything." },
  { id: 'q9', key: 'q9', text: 'Which software should we put in the code export?', type: 'radio', aiType: 'radio', options: ['R', 'SPSS', 'SAS', 'All three', "I'm not sure"], hint: "You won't need to run any code yourself — everything runs inside the tool. This choice only affects the script you can save for your supplement or send to your mentor. Not sure? We'll include all three so you're covered." },
  { id: 'q10-deadline', key: 'q10', subKey: 'deadline', text: 'When is your abstract deadline?', type: 'date', aiType: 'date', hint: 'Optional. The deadline drives reminder emails.' },
  { id: 'q10-email', key: 'q10', subKey: 'email', text: "Your mentor's email (optional)", type: 'email', aiType: null, hint: 'Your mentor gets a share link automatically once you add this.' },
]

function errorMessage(err) {
  return `${err.message || 'Could not save answers'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

const NO_COMPARISON = "No — I'm just describing one time period"

export default function IntakeQuestions() {
  const { ctx, update, next, prev } = useApp()
  const suggestions = ctx.aiSuggestions || {}
  const savedAnswers = ctx.answers || {}
  const [answers, setAnswers] = useState(() => {
    const init = { q1: savedAnswers.q1 || ctx.projectDesc || '' }
    QUESTIONS.forEach(q => {
      if (q.key === 'q1' || q.subKey) return
      if (savedAnswers[q.key] !== undefined) init[q.key] = savedAnswers[q.key]
      else if (suggestions[q.key] !== undefined) init[q.key] = suggestions[q.key]
      else if (q.type === 'composite') init[q.key] = {}
      else init[q.key] = ''
    })
    init.q10 = savedAnswers.q10 || {}
    return init
  })
  const [idx, setIdx] = useState(0)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const [explainText, setExplainText] = useState('')
  const [pendingRedacted, setPendingRedacted] = useState(null)
  const [aiLoading, setAiLoading] = useState(false)
  const [aiMessage, setAiMessage] = useState('')
  const [aiError, setAiError] = useState('')

  const visible = QUESTIONS.filter(
    q => q.id !== 'q1' && !((q.key === 'q7' || q.key === 'q8') && answers.q3 === NO_COMPARISON)
  )
  const current = visible[idx] || visible[visible.length - 1]
  const isLast = idx === visible.length - 1
  const progressPct = `${((idx + 1) / visible.length) * 100}%`

  useEffect(() => {
    setExplainText('')
    setPendingRedacted(null)
    setAiMessage('')
    setAiError('')
  }, [idx])

  function getValue(q) {
    return q.subKey ? answers[q.key]?.[q.subKey] : answers[q.key]
  }

  function setField(key, value) {
    setAnswers(a => {
      const nextAnswers = { ...a, [key]: value }
      if (key === 'q3' && value === NO_COMPARISON) {
        delete nextAnswers.q7
        delete nextAnswers.q8
      }
      return nextAnswers
    })
  }

  function setValue(q, value) {
    if (q.subKey) {
      setAnswers(a => ({ ...a, [q.key]: { ...(a[q.key] || {}), [q.subKey]: value } }))
    } else {
      setField(q.key, value)
    }
  }

  function setSubField(key, subKey, value) {
    setAnswers(a => ({ ...a, [key]: { ...a[key], [subKey]: value } }))
  }

  async function advance(latestAnswers) {
    if (!isLast) { setIdx(i => i + 1); return }
    setSaving(true)
    setError('')
    try {
      const final = { ...latestAnswers, q1: latestAnswers.q1 || ctx.projectDesc || '' }
      if (final.q3 === NO_COMPARISON) {
        delete final.q7
        delete final.q8
      }
      if (final.q7?.date === "I'm not sure") {
        final.q7 = { ...final.q7 }
        delete final.q7.date
      }
      await api.saveAnswers(ctx.projectId, final)
      update({ answers: final })
      next()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  async function handleNext(e) {
    e.preventDefault()
    await advance(answers)
  }

  function applyValueAndAdvance(q, value) {
    // Compute the next answers as a plain value and call the (side-effecting,
    // async) advance() outside of any setState updater -- React's Strict Mode
    // double-invokes updater functions to catch impure updaters, which was
    // silently advancing the question index twice for one AI-resolved answer.
    const nextAnswers = q.subKey
      ? { ...answers, [q.key]: { ...(answers[q.key] || {}), [q.subKey]: value } }
      : { ...answers, [q.key]: value }
    if (q.key === 'q3' && value === NO_COMPARISON) {
      delete nextAnswers.q7
      delete nextAnswers.q8
    }
    setAnswers(nextAnswers)
    advance(nextAnswers)
  }

  async function askAI(q) {
    const text = pendingRedacted ?? explainText
    if (!text.trim()) return
    setAiLoading(true)
    setAiError('')
    if (pendingRedacted === null) {
      try {
        const scan = await api.scrubPreview(text)
        if (scan.redacted) {
          setPendingRedacted(scan.text)
          setAiLoading(false)
          return
        }
      } catch (err) {
        setAiError(errorMessage(err))
        setAiLoading(false)
        return
      }
    }
    try {
      const body = await api.intakeAnswerAI(ctx.projectId, {
        question_key: q.key,
        question_text: q.text,
        question_type: q.aiType,
        options: q.options || null,
        message: text,
      })
      setAiMessage(body.message)
      if (body.resolved) {
        applyValueAndAdvance(q, body.value)
      }
    } catch (err) {
      setAiError(errorMessage(err))
    } finally {
      setAiLoading(false)
    }
  }

  const q = current
  const questionId = `question-${q.id}`
  const value = getValue(q)

  return (
    <div className="screen">
      <PageIntro step="intake" title="Intake Questions" />
      {ctx.prefillPhiRedacted && (
        <div className="alert-warn mb-4">
          Some text was automatically de-identified before being sent to the AI. No PHI left this server.
        </div>
      )}
      <div className="mb-6">
        <div className="mb-2 h-1 rounded-lg bg-line" aria-hidden="true">
          <div className="h-1 rounded-lg bg-brand transition-all duration-200" style={{ width: progressPct }} />
        </div>
        <p className="text-sm text-ink-faint" aria-live="polite" aria-current="step">Intake progress: question {idx + 1} of {visible.length}</p>
      </div>
      {error && <p role="alert" className="alert-error mb-4">{error}</p>}
      <form onSubmit={handleNext} className="flex flex-col gap-6" aria-labelledby={questionId}>
        <fieldset disabled={saving}>
          <legend id={questionId} className="mb-3 text-lg font-medium text-ink">
            {q.text}
            {suggestions[q.key] && <span className="ml-2 inline-flex rounded-lg bg-brand-tint px-2 py-0.5 text-xs font-medium text-brand-deep">AI suggestion</span>}
          </legend>

          {q.type === 'radio' && (
            <div className="flex flex-col gap-2">
              {q.options.map(opt => (
                <label key={opt} className="choice">
                  <input
                    type="radio"
                    name={q.key}
                    value={opt}
                    checked={value === opt}
                    onChange={() => setValue(q, opt)}
                    className="mt-0.5 h-4 w-4 text-brand"
                  />
                  <span className="text-ink">{opt}</span>
                </label>
              ))}
              {q.hint && <p className="mt-2 text-sm text-ink-soft">{q.hint}</p>}
            </div>
          )}

          {q.type === 'number' && (
            <div className="flex flex-col gap-2">
              <label htmlFor={`${q.id}-number`} className="sr-only">{q.text}</label>
              <input
                id={`${q.id}-number`}
                type="number"
                min="0"
                value={value === "I'm not sure" ? '' : value || ''}
                onChange={e => setValue(q, e.target.value === '' ? '' : parseInt(e.target.value, 10) || 0)}
                disabled={value === "I'm not sure"}
                className="input w-32 disabled:bg-canvas disabled:text-ink-faint"
              />
              <label className="choice max-w-xs">
                <input
                  type="checkbox"
                  checked={value === "I'm not sure"}
                  onChange={e => setValue(q, e.target.checked ? "I'm not sure" : '')}
                  className="mt-0.5 h-4 w-4 text-brand"
                />
                <span>I'm not sure</span>
              </label>
              {q.hint && <p className="mt-2 text-sm text-ink-soft">{q.hint}</p>}
            </div>
          )}

          {q.type === 'date' && (
            <div className="flex flex-col gap-2">
              <label htmlFor={`${q.id}-date`} className="sr-only">{q.text}</label>
              <input id={`${q.id}-date`} type="date" className="input w-48" value={value || ''} onChange={e => setValue(q, e.target.value)} />
              {q.hint && <p className="mt-2 text-sm text-ink-soft">{q.hint}</p>}
            </div>
          )}

          {q.type === 'email' && (
            <div className="flex flex-col gap-2">
              <label htmlFor={`${q.id}-email`} className="sr-only">{q.text}</label>
              <input id={`${q.id}-email`} type="email" className="input" value={value || ''} onChange={e => setValue(q, e.target.value)} />
              {q.hint && <p className="mt-2 text-sm text-ink-soft">{q.hint}</p>}
            </div>
          )}

          {q.type === 'composite' && (
            <div className="flex flex-col gap-3">
              {Object.entries(q.fields).map(([sub, inputType]) => {
                const unsureDate = q.key === 'q7' && sub === 'date' && answers[q.key]?.[sub] === "I'm not sure"
                return (
                  <div key={sub} className="flex flex-col gap-2">
                    <label className="flex flex-col gap-1">
                      <span className="label">{q.labels[sub]}</span>
                      {inputType === 'textarea' ? (
                        <textarea className="input min-h-24" value={answers[q.key]?.[sub] || ''} onChange={e => setSubField(q.key, sub, e.target.value)} />
                      ) : (
                        <input type={inputType} className="input disabled:bg-canvas disabled:text-ink-faint" value={unsureDate ? '' : answers[q.key]?.[sub] || ''} onChange={e => setSubField(q.key, sub, e.target.value)} disabled={unsureDate} />
                      )}
                    </label>
                    {q.key === 'q7' && sub === 'date' && (
                      <label className="choice max-w-xs">
                        <input
                          type="checkbox"
                          checked={unsureDate}
                          onChange={e => setSubField(q.key, sub, e.target.checked ? "I'm not sure" : '')}
                          className="mt-0.5 h-4 w-4 text-brand"
                        />
                        <span>I'm not sure when it started</span>
                      </label>
                    )}
                  </div>
                )
              })}
              {q.hint && <p className="mt-2 text-sm text-ink-soft">{q.hint}</p>}
            </div>
          )}

          {q.aiType && (
            <div className="mt-4 border-t border-line pt-4">
              <label className="label" htmlFor={`${q.id}-explain`}>Or explain in your own words</label>
              <p className="text-xs text-ink-faint mb-1">Don't include patient names, MRNs, or other identifying information.</p>
              <textarea
                id={`${q.id}-explain`}
                className="input"
                value={pendingRedacted ?? explainText}
                onChange={e => { setExplainText(e.target.value); setPendingRedacted(null) }}
                disabled={aiLoading}
                placeholder="Describe this in your own words and the AI will fill in the answer..."
              />
              {pendingRedacted !== null && (
                <p role="alert" className="alert-warn mt-2">We removed what looked like PHI. Click Ask AI again to send the redacted version.</p>
              )}
              {aiMessage && <p aria-live="polite" className="mt-2 text-sm text-ink-soft">AI: {aiMessage}</p>}
              {aiError && <p role="alert" className="alert-error mt-2">{aiError}</p>}
              <button type="button" onClick={() => askAI(q)} disabled={aiLoading} className="btn-secondary mt-2">
                {aiLoading && <Spinner />}
                {aiLoading ? 'Thinking…' : 'Ask AI'}
              </button>
            </div>
          )}
        </fieldset>

        <div className="flex flex-wrap gap-3">
          <BackButton onClick={() => (idx > 0 ? setIdx(i => i - 1) : prev())} disabled={saving} />
          <button type="submit" disabled={saving} className="btn-primary">
            {saving && <Spinner />}
            {saving ? 'Saving…' : isLast ? 'Continue' : 'Next →'}
          </button>
        </div>
      </form>
    </div>
  )
}
