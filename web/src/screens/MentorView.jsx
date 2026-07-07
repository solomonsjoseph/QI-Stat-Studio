import React, { useEffect, useState } from 'react'
import { api } from '../api'

function CommentCard({ comment }) {
  const author = comment.author_name || comment.author || 'Mentor'
  const timestamp = comment.created_at ? new Date(comment.created_at).toLocaleString() : ''
  return (
    <div className="bg-blue-50 rounded px-3 py-2 text-sm">
      <div className="font-medium text-blue-950">{author}{comment.author_email ? ` (${comment.author_email})` : ''}</div>
      {timestamp && <div className="text-xs text-blue-700 mb-1">{timestamp}</div>}
      <p>{comment.text}</p>
    </div>
  )
}

function errorMessage(err, fallback) {
  return `${err.message || fallback}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function MentorView({ token }) {
  const [data, setData] = useState(null)
  const [authorName, setAuthorName] = useState('')
  const [authorEmail, setAuthorEmail] = useState('')
  const [comment, setComment] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function load() {
    setLoading(true)
    setError('')
    try {
      setData(await api.getMentorView(token))
    } catch (err) {
      setError(errorMessage(err, 'Share link not found or expired.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [token])

  async function addComment(e) {
    e.preventDefault()
    setSaving(true)
    setError('')
    setSubmitted(false)
    try {
      await api.addComment(token, authorName, comment, authorEmail || undefined)
      setComment('')
      setSubmitted(true)
      setData(await api.getMentorView(token))
    } catch (err) {
      setError(errorMessage(err, 'Could not save comment'))
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="p-8 text-gray-500" aria-live="polite">Loading mentor review…</div>
  if (error && !data) return <div className="flex items-center justify-center min-h-screen"><p role="alert" className="text-red-600">{error}</p></div>

  const table = data.table || []
  const tableHeaders = table.length > 0 ? Object.keys(table[0]) : []
  const limitations = data.limitations || []
  const docxUrl = api.shareDocxUrl(token)
  const pdfUrl = api.sharePdfUrl(token)

  return (
    <main className="max-w-3xl mx-auto p-8 mt-8">
      <div className="mb-2 text-xs text-blue-600 font-semibold uppercase tracking-wide">Mentor Review</div>
      <h1 className="text-2xl font-bold mb-2">{data.project?.title || 'QI Project'}</h1>
      <p className="text-gray-600 text-sm mb-6">{data.project?.description}</p>

      {error && <p role="alert" className="mb-4 text-sm text-red-700">{error}</p>}
      {submitted && <p className="mb-4 text-green-700 text-sm" aria-live="polite">Comment submitted.</p>}
      {saving && <p className="mb-4 text-gray-500 text-sm" aria-live="polite">Saving comment…</p>}

      <div className="flex flex-wrap gap-3 mb-6">
        <a href={docxUrl} className="px-4 py-2 border border-blue-600 text-blue-700 rounded text-sm font-medium hover:bg-blue-50">Download Word Report</a>
        <a href={pdfUrl} className="px-4 py-2 border border-blue-600 text-blue-700 rounded text-sm font-medium hover:bg-blue-50">Download PDF Report</a>
      </div>

      {data.methods && <section className="mb-4"><h2 className="font-semibold mb-1">Methods</h2><p className="text-sm text-gray-700">{data.methods}</p></section>}
      {data.result_summary && <section className="bg-gray-50 rounded p-4 mb-6"><h2 className="font-semibold text-sm mb-1">Result Summary</h2><p className="text-sm">{data.result_summary}</p></section>}

      {table.length > 0 && (
        <section className="mb-6 overflow-x-auto">
          <h2 className="font-semibold mb-2">Results Table</h2>
          <table className="min-w-full text-sm border">
            <thead><tr>{tableHeaders.map(h => <th key={h} className="border px-2 py-1 text-left bg-gray-50">{h}</th>)}</tr></thead>
            <tbody>{table.map((row, idx) => <tr key={idx}>{tableHeaders.map(h => <td key={h} className="border px-2 py-1">{String(row[h] ?? '')}</td>)}</tr>)}</tbody>
          </table>
        </section>
      )}

      {data.figure_base64 && <section className="mb-6"><h2 className="font-semibold mb-2">Figure</h2><img className="w-full border rounded" src={`data:image/png;base64,${data.figure_base64}`} alt="Analysis figure" />{data.caption && <p className="text-sm text-gray-600 mt-2">{data.caption}</p>}</section>}
      {data.interpretation && <section className="mb-6"><h2 className="font-semibold mb-1">Interpretation</h2><p className="text-sm text-gray-700">{data.interpretation}</p></section>}

      <section className="mb-6">
        <h2 className="font-semibold mb-1">Limitations</h2>
        {limitations.length > 0 ? <ul className="list-disc pl-5 text-sm text-gray-700">{limitations.map((item, idx) => <li key={idx}>{item.msg || item.message || JSON.stringify(item)}</li>)}</ul> : <p className="text-sm text-gray-500">No data quality issues were flagged for this dataset.</p>}
      </section>

      {(data.code_r || data.code_spss || data.code_sas) && <section className="mb-6"><h2 className="font-semibold mb-2">Code Supplement</h2>{data.code_r && <pre className="bg-gray-950 text-gray-50 rounded p-3 text-xs overflow-x-auto mb-2">{data.code_r}</pre>}{data.code_spss && <pre className="bg-gray-950 text-gray-50 rounded p-3 text-xs overflow-x-auto mb-2">{data.code_spss}</pre>}{data.code_sas && <pre className="bg-gray-950 text-gray-50 rounded p-3 text-xs overflow-x-auto">{data.code_sas}</pre>}</section>}

      <section className="border-t pt-6">
        <h2 className="font-semibold mb-3">Mentor Comments</h2>
        {data.comments?.length > 0 ? <div className="flex flex-col gap-2 mb-4">{data.comments.map((c, i) => <CommentCard key={c.id || i} comment={c} />)}</div> : <p className="text-gray-400 text-sm mb-4">No comments yet.</p>}

        <form onSubmit={addComment} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm" htmlFor="mentor-name"><span className="font-medium">Your name</span><input id="mentor-name" className="border rounded px-3 py-2" value={authorName} onChange={e => setAuthorName(e.target.value)} required disabled={saving} /></label>
          <label className="flex flex-col gap-1 text-sm" htmlFor="mentor-email"><span className="font-medium">Email (optional, used if you edit your comment later)</span><input id="mentor-email" className="border rounded px-3 py-2" type="email" value={authorEmail} onChange={e => setAuthorEmail(e.target.value)} disabled={saving} /></label>
          <label className="flex flex-col gap-1 text-sm" htmlFor="mentor-comment"><span className="font-medium">Comment</span><textarea id="mentor-comment" className="border rounded px-3 py-2 min-h-24" value={comment} onChange={e => setComment(e.target.value)} placeholder="Add a comment…" required disabled={saving} /></label>
          <button type="submit" disabled={saving} className="px-4 py-2 bg-blue-700 text-white rounded text-sm font-medium hover:bg-blue-800 disabled:opacity-50 self-start">{saving ? 'Sending…' : 'Send Comment'}</button>
        </form>
      </section>
    </main>
  )
}
