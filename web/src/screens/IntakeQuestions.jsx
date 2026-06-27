import React, { useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'

const QUESTIONS = [
  {
    key: 'q2',
    text: 'What type of outcome are you measuring?',
    type: 'radio',
    options: [
      'A percentage or proportion',
      'A rate (events per unit)',
      'An average (mean or median)',
      'A yes/no outcome',
      'A count of events',
      'Something else',
      'Not sure',
    ],
  },
  {
    key: 'q3',
    text: 'Are you comparing two time periods?',
    type: 'radio',
    options: [
      "Yes — before and after an intervention",
      "No — I'm just describing one time period",
      "More than two periods (phases)",
    ],
  },
  {
    key: 'q4',
    text: 'What is the main purpose of this analysis?',
    type: 'radio',
    options: [
      'Tracking a measure over time',
      'Comparing groups at one time point',
      'Both',
    ],
  },
  {
    key: 'q5',
    text: 'Is your data from a single clinic or multiple sites?',
    type: 'radio',
    options: ['Single site', 'Multiple sites', 'Not sure'],
  },
  {
    key: 'q6',
    text: 'Approximately how many data points (months/time periods) do you have?',
    type: 'radio',
    options: ['Less than 12', '12 or more'],
  },
  {
    key: 'q7',
    text: 'Did you implement an intervention? If so, describe it.',
    type: 'composite',
    fields: { description: 'textarea', date: 'date' },
    labels: { description: 'Intervention description (optional)', date: 'Intervention date (if known)' },
  },
  {
    key: 'q8',
    text: 'Do you have any special concerns about your data quality?',
    type: 'radio',
    options: ['No concerns', 'Missing data', 'Outliers', 'Multiple concerns', 'Not sure'],
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
    // Pre-fill from AI suggestions
    const init = {}
    QUESTIONS.forEach(q => {
      if (q.type === 'composite') init[q.key] = suggestions[q.key] || {}
      else init[q.key] = suggestions[q.key] || ''
    })
    return init
  })

  function setField(key, value) {
    setAnswers(a => ({ ...a, [key]: value }))
  }
  function setSubField(key, subKey, value) {
    setAnswers(a => ({ ...a, [key]: { ...a[key], [subKey]: value } }))
  }

  async function submit(e) {
    e.preventDefault()
    // Convert q6 radio to number
    const final = { ...answers }
    if (final.q6 === 'Less than 12') final.q6 = 6
    else if (final.q6 === '12 or more') final.q6 = 12
    await api.saveAnswers(ctx.projectId, final)
    update({ answers: final })
    next()
  }

  return (
    <div className="max-w-2xl mx-auto p-8 mt-8">
      <h2 className="text-2xl font-bold mb-6 text-blue-800">Intake Questions</h2>
      <form onSubmit={submit} className="flex flex-col gap-8">
        {QUESTIONS.map(q => (
          <div key={q.key}>
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
        ))}

        <button
          type="submit"
          className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 self-start"
        >
          Continue
        </button>
      </form>
    </div>
  )
}
