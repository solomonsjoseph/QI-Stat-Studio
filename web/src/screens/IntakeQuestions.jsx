import React, { useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'

const QUESTIONS = [
  { key: 'q1', text: 'Project description', type: 'stored' },
  {
    key: 'q2',
    text: 'What are you measuring?',
    type: 'radio',
    hint: "Pick the one that best matches your main outcome. If none fit, 'Something else / not sure' is a valid answer.",
    options: [
      'A rate of events over time (infections per 1,000 catheter-days)',
      'A percentage or proportion (percent of patients screened)',
      'A count (number of falls per month)',
      'An average or median value (average LDL)',
      'A yes/no outcome (did the patient get a flu shot)',
      'Something else / not sure',
    ],
  },
  {
    key: 'q3',
    text: 'Are you comparing before and after something?',
    type: 'radio',
    hint: 'An intervention is any change you made — a new protocol, order set, checklist, or workflow.',
    options: ["Yes — before and after an intervention", "No — I'm just describing one time period", 'More than two periods (phases)', "I'm not sure"],
  },
  {
    key: 'q4',
    text: 'Are you tracking over time, or comparing two groups?',
    type: 'radio',
    hint: 'Tracking over time = months, weeks, or days. Comparing groups = two units, clinics, or cohorts at one point in time.',
    options: ['Tracking over time (months, weeks, days)', 'Comparing groups at one point in time', 'Both', "I'm not sure"],
  },
  { key: 'q5', text: "What's the time unit?", type: 'radio', options: ['Daily', 'Weekly', 'Monthly', 'One row per patient', 'Other', "I'm not sure"], hint: 'How your rows are grouped: one per day, week, month, or one row per patient.' },
  { key: 'q6', text: 'How many time points (or rows) do you have?', type: 'number', hint: "Run and control charts work best with 12 or more time points. Under 12, we'll recommend a simpler summary instead." },
  { key: 'q7', text: 'What was the intervention and when did it start?', type: 'composite', fields: { description: 'textarea', date: 'date' }, labels: { description: 'Intervention description (optional)', date: 'Intervention date (if known)' }, hint: 'We pre-fill this from your project description — just confirm or correct it.' },
  { key: 'q8', text: 'Who are you comparing?', type: 'radio', options: ['Same unit pre vs. post', 'Intervention vs. control', 'Subgroups', "I'm not sure"], hint: "Skipped automatically if you're not comparing anything." },
  { key: 'q9', text: 'Which software should we put in the code export?', type: 'radio', options: ['R', 'SPSS', 'SAS', 'All three'], hint: "You won't need to run any code yourself — everything runs inside the tool. This choice only affects the script you can save for your supplement or send to your mentor." },
  { key: 'q10', text: 'Would you like to share with a mentor? (Optional)', type: 'composite', fields: { email: 'email', deadline: 'date' }, labels: { email: "Mentor's email", deadline: 'Submission deadline' }, hint: 'Optional. Your mentor gets a share link automatically, and the deadline drives reminder emails.' },
]

function errorMessage(err) {
  return `${err.message || 'Could not save answers'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function IntakeQuestions() {
  const { ctx, update, next } = useApp()
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
    <div className="max-w-2xl mx-auto p-8 mt-8">
      <h1 className="text-2xl font-bold mb-2 text-blue-800">Intake Questions</h1>
      <p className="text-sm text-gray-500 mb-6" aria-live="polite" aria-current="step">Intake progress: question {idx + 1} of {visible.length}</p>
      {error && <p role="alert" className="mb-4 text-sm text-red-700">{error}</p>}
      <form onSubmit={handleNext} className="flex flex-col gap-6" aria-labelledby={questionId}>
        <fieldset disabled={saving}>
          <legend id={questionId} className="font-medium mb-2">
            {q.text}
            {suggestions[q.key] && <span className="ml-2 text-xs text-blue-500">(AI suggestion)</span>}
          </legend>

          {q.type === 'radio' && (
            <div className="flex flex-col gap-1">
              {q.options.map(opt => (
                <label key={opt} className="flex items-center gap-2">
                  <input
                    type="radio"
                    name={q.key}
                    value={opt}
                    checked={answers[q.key] === opt}
                    onChange={() => setField(q.key, opt)}
                  />
                  {opt}
                </label>
              ))}
              {q.hint && <p className="text-xs text-gray-500 mt-1 ml-1">{q.hint}</p>}
            </div>
          )}

          {q.type === 'number' && (
            <div className="flex flex-col gap-1">
              <label htmlFor={`${q.key}-number`} className="sr-only">{q.text}</label>
              <input
                id={`${q.key}-number`}
                type="number"
                min="0"
                value={answers[q.key] === "I'm not sure" ? '' : answers[q.key] || ''}
                onChange={e => setField(q.key, e.target.value === '' ? '' : parseInt(e.target.value, 10) || 0)}
                disabled={answers[q.key] === "I'm not sure"}
                className="border rounded px-3 py-2 w-32 disabled:bg-gray-100 disabled:text-gray-500"
              />
              <label className="flex items-center gap-2 mt-2">
                <input
                  type="checkbox"
                  checked={answers[q.key] === "I'm not sure"}
                  onChange={e => setField(q.key, e.target.checked ? "I'm not sure" : '')}
                />
                I'm not sure
              </label>
              {q.hint && <p className="text-xs text-gray-500 mt-1">{q.hint}</p>}
            </div>
          )}

          {q.type === 'composite' && (
            <div className="flex flex-col gap-3 pl-2">
              {Object.entries(q.fields).map(([sub, inputType]) => (
                <label key={sub} className="flex flex-col gap-1">
                  <span className="text-sm text-gray-600">{q.labels[sub]}</span>
                  {inputType === 'textarea' ? (
                    <textarea
                      className="border rounded px-3 py-2 h-20 text-sm"
                      value={answers[q.key]?.[sub] || ''}
                      onChange={e => setSubField(q.key, sub, e.target.value)}
                    />
                  ) : (
                    <input
                      type={inputType}
                      className="border rounded px-3 py-2 text-sm"
                      value={answers[q.key]?.[sub] || ''}
                      onChange={e => setSubField(q.key, sub, e.target.value)}
                    />
                  )}
                </label>
              ))}
              {q.hint && <p className="text-xs text-gray-500 mt-1">{q.hint}</p>}
            </div>
          )}
        </fieldset>

        <div className="flex gap-3">
          {idx > 0 && (
            <button type="button" onClick={() => setIdx(i => i - 1)} disabled={saving}
              className="px-4 py-2 border border-gray-300 rounded font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">
              ← Back
            </button>
          )}
          <button type="submit" disabled={saving}
            className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 disabled:opacity-50">
            {saving ? 'Saving…' : isLast ? 'Continue' : 'Next →'}
          </button>
        </div>
      </form>
    </div>
  )
}
