import React, { useEffect, useState } from 'react'
import { api } from '../api'

export default function MentorView({ token }) {
  const [data, setData] = useState(null)
  const [comment, setComment] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api.getMentorView(token).then(setData).catch(e => setError(e.message))
  }, [token])

  async function addComment(e) {
    e.preventDefault()
    await api.addComment(token, 'Mentor', comment)
    setComment('')
    setSubmitted(true)
    const updated = await api.getMentorView(token)
    setData(updated)
  }

  if (error) return (
    <div className="flex items-center justify-center min-h-screen">
      <p className="text-red-600">Share link not found or expired.</p>
    </div>
  )
  if (!data) return <div className="p-8 text-gray-500">Loading…</div>

  return (
    <div className="max-w-2xl mx-auto p-8 mt-8">
      <div className="mb-2 text-xs text-blue-600 font-semibold uppercase tracking-wide">Mentor Review</div>
      <h1 className="text-2xl font-bold mb-2">{data.project?.title || 'QI Project'}</h1>
      <p className="text-gray-600 text-sm mb-6">{data.project?.description}</p>

      {data.methods && (
        <div className="mb-4">
          <h3 className="font-semibold mb-1">Methods</h3>
          <p className="text-sm text-gray-700">{data.methods}</p>
        </div>
      )}

      {data.result_summary && (
        <div className="bg-gray-50 rounded p-4 mb-6">
          <p className="font-medium text-sm mb-1">Result Summary</p>
          <p className="text-sm">{data.result_summary}</p>
        </div>
      )}

      <div className="border-t pt-6">
        <h3 className="font-semibold mb-3">Mentor Comments</h3>
        {data.comments?.length > 0 ? (
          <div className="flex flex-col gap-2 mb-4">
            {data.comments.map((c, i) => (
              <div key={i} className="bg-blue-50 rounded px-3 py-2 text-sm">
                <span className="font-medium">{c.author}: </span>{c.text}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-gray-400 text-sm mb-4">No comments yet.</p>
        )}

        {!submitted ? (
          <form onSubmit={addComment} className="flex gap-2">
            <input
              className="flex-1 border rounded px-3 py-2 text-sm"
              value={comment}
              onChange={e => setComment(e.target.value)}
              placeholder="Add a comment…"
              required
            />
            <button type="submit" className="px-4 py-2 bg-blue-700 text-white rounded text-sm font-medium hover:bg-blue-800">
              Send
            </button>
          </form>
        ) : (
          <p className="text-green-700 text-sm">Comment submitted.</p>
        )}
      </div>
    </div>
  )
}
