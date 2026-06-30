import React, { useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'

const QUESTIONS = [
  {
    key: 'q2',
    text: 'What are you measuring?',
    type: 'radio',
    options: [
      'A percentage or proportion',
      'A rate of events over time',
      'An average or median value',
      'A yes/no outcome',
      'A count of events',
      'Something else',
      "I'm not sure",
    ],
  },
  {
    key: 'q3',
    text: 'Are you comparing before and after something?',
    type: 'radio',
    options: [
      "Yes — before and after an intervention",
      "No — I'm just describing one time period",
      "More than two periods (phases)",
      "I'm not sure",
    ],
  },
  {
    key: 'q4',
    text: 'Are you tracking over time, or comparing two groups?',
    type: 'radio',
    options: [
      'Tracking a measure over time',
      'Comparing groups at one time point',
      'Both',
      "I'm not sure",
    ],
  },
  {
    key: 'q5',
    text: "What's the time unit?",
    type: 'radio',
    options: ['Daily', 'Weekly', 'Monthly', 'One row per patient', 'Other', "I'm not sure"],
  },
  {
    key: 'q6',
    text: 'Approximately how many data points (months/time periods) do you have?',
    type: 'radio',
    options: ['Less than 12', '12 or more'],
    hint: 'Run and control charts work best with 12 or more time points. Under 10, we\'ll recommend a simpler summary instead.',
  },
  {
    key: 'q7',
    text: 'What was the intervention and when did it start?',
    type: 'composite',
    fields: { description: 'textarea', date: 'date' },
    labels: { description: 'Intervention description (optional)', date: 'Intervention date (if known)' },
  },
  {
    key: 'q8',
    text: 'Who are you comparing?',
    type: 'radio',
    options: ['Same unit pre vs. post', 'Intervention vs. control', 'Subgroups', "I'm not sure"],
  },
  {
    key: 'q9',
    text: 'Which statistical software would you like code generated for?',
    type: 'radio',
    options: ['R', 'SPSS', 'SAS', 'All three'],
    hint: "You won't need to run any code yourself — everything runs inside the tool. This choice only affects the script you can save for your supplement or send to your mentor.",
  },
  {
    key: 'q10',
    text: 'Would you like to share with a mentor? (Optional)',
    type: 'composite',
    fields: { email: 'email', deadline: 'date' },
    labels: { email: "Mentor's email", deadline: 'Submission deadline' },
  },
]

export default function IntakeQuestions() {
  const { ctx, update, next } = useApp()
  const suggestions = ctx.aiSuggestions || {}
  const [answers, setAnswers] = useState(() => {
    const init = {}
    QUESTIONS.forEach(q => {
      if (q.type === 'composite') init[q.key] = suggestions[q.key] || {}
      else init[q.key] = suggestions[q.key] || ''
    })
    return init
  })
  const [idx, setIdx] = useState(0)

  // Q8 hidden when user said they're not comparing periods
  const visible = QUESTIONS.filter(
    q => q.key !== 'q8' || answers.q3 !== "No — I'm just describing one time period"
  )
  const current = visible[idx]
  const isLast = idx === visible.length - 1

  function setField(key, value) {
    setAnswers(a => ({ ...a, [key]: value }))
  }
  function setSubField(key, subKey, value) {
    setAnswers(a => ({ ...a, [key]: { ...a[key], [subKey]: value } }))
  }

  async function handleNext(e) {
    e.preventDefault()
    if (!isLast) { setIdx(i => i + 1); return }
    const final = { ...answers }
    if (final.q6 === 'Less than 12') final.q6 = 6
    else if (final.q6 === '12 or more') final.q6 = 12
    await api.saveAnswers(ctx.projectId, final)
    update({ answers: final })
    next()
  }

  const q = current
  return (
    <div className="max-w-2xl mx-auto p-8 mt-8">
      <h2 className="text-2xl font-bold mb-2 text-blue-800">Intake Questions</h2>
      <p className="text-sm text-gray-500 mb-6">Question {idx + 1} of {visible.length}</p>
      <form onSubmit={handleNext} className="flex flex-col gap-6">
        <div>
          <p className="font-medium mb-2">
            {q.text}
            {suggestions[q.key] && (
              <span className="ml-2 text-xs text-blue-500">(AI suggestion)</span>
            )}
          </p>

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
              {q.hint && (
                <p className="text-xs text-gray-500 mt-1 ml-1">{q.hint}</p>
              )}
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
            </div>
          )}
        </div>

        <div className="flex gap-3">
          {idx > 0 && (
            <button type="button" onClick={() => setIdx(i => i - 1)}
              className="px-4 py-2 border border-gray-300 rounded font-medium text-gray-700 hover:bg-gray-50">
              ← Back
            </button>
          )}
          <button type="submit"
            className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800">
            {isLast ? 'Continue' : 'Next →'}
          </button>
        </div>
      </form>
    </div>
  )
}
