import React, { useState } from 'react'
import { useApp } from '../App'
import BackButton from '../components/BackButton'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'

const QUESTIONS = [
  { key: 'q1', text: 'Project description', type: 'stored' },
  { key: 'q2', text: 'What are you measuring?', type: 'radio', options: ['A rate of events over time (infections per 1,000 catheter-days)', 'A percentage or proportion (percent of patients screened)', 'A count (number of falls per month)', 'An average or median value (average LDL)', 'A yes/no outcome (did the patient get a flu shot)', 'Something else / not sure'], hint: 'Choose the option closest to your primary outcome.' },
  { key: 'q3', text: 'Are you comparing before and after something?', type: 'radio', options: ['Yes — before and after an intervention', "No — I'm just describing one time period", 'More than two periods (phases)', "I'm not sure"], hint: 'This decides whether we recommend comparison tests or descriptive summaries.' },
  { key: 'q4', text: 'Are you tracking over time, or comparing two groups?', type: 'radio', options: ['Tracking over time (months, weeks, days)', 'Comparing groups at one point in time', 'Both', "I'm not sure"], hint: 'Run/control charts need a time column.' },
  { key: 'q5', text: "What's the time unit?", type: 'radio', options: ['Daily', 'Weekly', 'Monthly', 'One row per patient', 'Other', "I'm not sure"], hint: 'How your rows are grouped: one per day, week, month, or one row per patient.' },
  { key: 'q6', text: 'How many time points (or rows) do you have?', type: 'number', hint: "Run and control charts work best with 12 or more time points. Under 12, we'll recommend a simpler summary instead." },
  { key: 'q7', text: 'What was the intervention and when did it start?', type: 'composite', fields: { description: 'textarea', date: 'date' }, labels: { description: 'Intervention description (optional)', date: 'Intervention date (if known)' }, hint: 'We pre-fill this from your project description — just confirm or correct it.' },
  { key: 'q8', text: 'Who are you comparing?', type: 'radio', options: ['Same unit pre vs. post', 'Intervention vs. control', 'Subgroups', "I'm not sure"], hint: "Skipped automatically if you're not comparing anything." },
  { key: 'q9', text: 'Which software should we put in the code export?', type: 'radio', options: ['R', 'SPSS', 'SAS', 'All three', "I'm not sure"], hint: "You won't need to run any code yourself — everything runs inside the tool. This choice only affects the script you can save for your supplement or send to your mentor. Not sure? We'll include all three so you're covered." },
  { key: 'q10', text: 'Your mentor and timeline (optional)', type: 'composite', fields: { email: 'email', deadline: 'date' }, labels: { email: "Mentor's email (so they get a share link)", deadline: 'Abstract deadline' }, hint: 'Optional. Your mentor gets a share link automatically, and the deadline drives reminder emails.' },
]

function errorMessage(err) {
  return `${err.message || 'Could not save answers'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function IntakeQuestions() {
  const { ctx, update, next, prev } = useApp()
  const suggestions = ctx.aiSuggestions || {}
  const savedAnswers = ctx.answers || {}
  const [answers, setAnswers] = useState(() => {
    const init = { q1: savedAnswers.q1 || ctx.projectDesc || '' }
    QUESTIONS.forEach(q => {
      if (q.key === 'q1') return
      if (savedAnswers[q.key] !== undefined) init[q.key] = savedAnswers[q.key]
      else if (suggestions[q.key] !== undefined) init[q.key] = suggestions[q.key]
      else if (q.type === 'composite') init[q.key] = {}
      else init[q.key] = ''
    })
    return init
  })
  const [idx, setIdx] = useState(0)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const NO_COMPARISON = "No — I'm just describing one time period"
  const visible = QUESTIONS.filter(
    q => q.key !== 'q1' && !((q.key === 'q7' || q.key === 'q8') && answers.q3 === NO_COMPARISON)
  )
  const current = visible[idx] || visible[visible.length - 1]
  const isLast = idx === visible.length - 1
  const progressPct = `${((idx + 1) / visible.length) * 100}%`

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

  function setSubField(key, subKey, value) {
    setAnswers(a => ({ ...a, [key]: { ...a[key], [subKey]: value } }))
  }

  async function handleNext(e) {
    e.preventDefault()
    setError('')
    if (!isLast) { setIdx(i => i + 1); return }
    setSaving(true)
    try {
      const final = { ...answers, q1: answers.q1 || ctx.projectDesc || '' }
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

  const q = current
  const questionId = `question-${q.key}`

  return (
    <div className="screen">
      <PageIntro step="intake" title="Intake Questions" />
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
                    checked={answers[q.key] === opt}
                    onChange={() => setField(q.key, opt)}
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
              <label htmlFor={`${q.key}-number`} className="sr-only">{q.text}</label>
              <input
                id={`${q.key}-number`}
                type="number"
                min="0"
                value={answers[q.key] === "I'm not sure" ? '' : answers[q.key] || ''}
                onChange={e => setField(q.key, e.target.value === '' ? '' : parseInt(e.target.value, 10) || 0)}
                disabled={answers[q.key] === "I'm not sure"}
                className="input w-32 disabled:bg-canvas disabled:text-ink-faint"
              />
              <label className="choice max-w-xs">
                <input
                  type="checkbox"
                  checked={answers[q.key] === "I'm not sure"}
                  onChange={e => setField(q.key, e.target.checked ? "I'm not sure" : '')}
                  className="mt-0.5 h-4 w-4 text-brand"
                />
                <span>I'm not sure</span>
              </label>
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
