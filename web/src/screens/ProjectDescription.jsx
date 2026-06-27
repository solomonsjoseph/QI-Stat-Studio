import React, { useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'

export default function ProjectDescription() {
  const { ctx, update, next } = useApp()
  const [title, setTitle] = useState('')
  const [desc, setDesc] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setLoading(true)
    // Save title/description to project
    await api.saveAnswers(ctx.projectId, { q1: desc })
    update({ projectTitle: title, projectDesc: desc })

    // AI pre-fill Q2–Q7
    try {
      const optionHints = 'Q2: percent/rate/average/yes-no/count. Q3: yes(before-after)/no(one-period)/multi. Q4: time/groups/both. Q7: date of intervention.'
      const aiResp = await api.chat(ctx.projectId, [{
        role: 'user',
        content: `QI project: "${desc}". Suggest JSON answers for Q2-Q7 using these hints: ${optionHints}. Reply ONLY with JSON like {"q2":"percent","q3":"yes","q4":"over time","q6":24,"q7":{"description":"...","date":"YYYY-MM-DD"}}.`,
      }])
      try {
        const suggestions = JSON.parse(aiResp.content.match(/\{[\s\S]+\}/)[0])
        update({ aiSuggestions: suggestions })
      } catch (_) { /* AI response not parseable — proceed without suggestions */ }
    } catch (_) { /* AI unavailable — proceed */ }

    setLoading(false)
    next()
  }

  return (
    <div className="max-w-xl mx-auto p-8 mt-12">
      <h2 className="text-2xl font-bold mb-6 text-blue-800">Describe Your QI Project</h2>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <label className="font-medium">Project Title
          <input
            className="block w-full border rounded px-3 py-2 mt-1"
            value={title}
            onChange={e => setTitle(e.target.value)}
            required
          />
        </label>
        <label className="font-medium">Project Description
          <textarea
            className="block w-full border rounded px-3 py-2 mt-1 h-28"
            value={desc}
            onChange={e => setDesc(e.target.value)}
            placeholder="Describe your QI initiative in 1–3 sentences..."
            required
          />
        </label>
        <button
          type="submit"
          disabled={loading}
          className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 disabled:opacity-50"
        >
          {loading ? 'Analyzing…' : 'Continue'}
        </button>
      </form>
    </div>
  )
}
