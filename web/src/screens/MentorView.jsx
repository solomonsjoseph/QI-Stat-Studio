import React, { useEffect, useState } from 'react'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'
import { TEMPLATE_LABELS } from '../templateLabels'

function CommentCard({ comment, token, authorEmail, load, setError }) {
  const author = comment.author_name || comment.author || 'Mentor'
  const timestamp = comment.created_at ? new Date(comment.created_at).toLocaleString() : ''
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(comment.text || '')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setText(comment.text || '')
  }, [comment.text])

  async function saveEdit(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api.editComment(token, comment.id, authorEmail || undefined, text)
      setEditing(false)
      setBusy(false)
      await load()
    } catch (err) {
      setError(errorMessage(err, 'Could not update comment'))
      setBusy(false)
    }
  }

  async function deleteComment() {
    if (!window.confirm('Delete this comment?')) return
    setBusy(true)
    setError('')
    try {
      await api.deleteComment(token, comment.id, authorEmail || undefined)
      setBusy(false)
      await load()
    } catch (err) {
      setError(errorMessage(err, 'Could not delete comment'))
      setBusy(false)
    }
  }

  function cancelEdit() {
    setText(comment.text || '')
    setEditing(false)
  }

  return (
    <article className="card p-4 text-sm">
      <div className="font-medium text-ink">{author}{comment.author_email ? ` (${comment.author_email})` : ''}</div>
      {timestamp && <div className="mb-2 text-xs text-ink-faint">{timestamp}</div>}
      {editing ? (
        <form onSubmit={saveEdit} className="flex flex-col gap-2">
          <label className="sr-only" htmlFor={`comment-edit-${comment.id}`}>Edit comment</label>
          <textarea id={`comment-edit-${comment.id}`} value={text} onChange={e => setText(e.target.value)} disabled={busy} required className="input min-h-20" />
          <div className="flex gap-2">
            <button type="submit" disabled={busy} className="btn-primary px-4 py-2">Save</button>
            <button type="button" onClick={cancelEdit} disabled={busy} className="btn-secondary px-4 py-2">Cancel</button>
          </div>
        </form>
      ) : (
        <>
          <p className="leading-6 text-ink-soft">{comment.text}</p>
          <div className="mt-3 flex gap-3">
            <button type="button" onClick={() => setEditing(true)} disabled={busy || !comment.id} className="text-sm font-medium text-brand hover:text-brand-deep disabled:opacity-50">Edit</button>
            <button type="button" onClick={deleteComment} disabled={busy || !comment.id} className="text-sm font-medium text-error-ink disabled:opacity-50">Delete</button>
          </div>
        </>
      )}
    </article>
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

  if (loading) {
    return <div className="flex min-h-screen items-center justify-center gap-2 text-sm text-ink-soft" aria-live="polite"><Spinner />Loading mentor review…</div>
  }
  if (error && !data) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas px-6">
        <div className="max-w-md text-center">
          <p role="alert" className="alert-error mb-4 text-left">{error}</p>
          <button type="button" onClick={load} className="btn-primary">
            Try again
          </button>
        </div>
      </div>
    )
  }

  const results = data.results || []
  const limitations = data.limitations || []

  return (
    <main className="screen max-w-3xl">
      <PageIntro title={data.project?.title || 'QI Project'} lead={data.project?.description} />

      {error && <p role="alert" className="alert-error mb-4">{error}</p>}
      {submitted && <p className="alert-ok mb-4" aria-live="polite">Comment submitted.</p>}
      {saving && <p className="mb-4 flex items-center gap-2 text-sm text-ink-soft" aria-live="polite"><Spinner />Saving comment…</p>}

      {results.map(run => {
        const table = run.table || []
        const tableHeaders = table.length > 0 ? Object.keys(table[0]) : []
        return (
          <section key={run.run_id} className="mb-8 border-b border-line pb-6">
            <h2 className="mb-2 text-lg font-semibold text-ink">{TEMPLATE_LABELS[run.template] || run.template}</h2>
            {run.methods && <div className="mb-4"><h3 className="mb-1 font-semibold text-ink">Methods</h3><p className="text-sm leading-6 text-ink-soft">{run.methods}</p></div>}
            {run.result_summary && <div className="alert-info mb-4"><h3 className="mb-1 text-sm font-semibold">Result Summary</h3><p>{run.result_summary}</p></div>}

            {table.length > 0 && (
              <div className="mb-4 overflow-x-auto">
                <h3 className="mb-2 font-semibold text-ink">Results Table</h3>
                <table className="table-clean">
                  <thead><tr>{tableHeaders.map(h => <th key={h}>{h}</th>)}</tr></thead>
                  <tbody>{table.map((row, idx) => <tr key={idx}>{tableHeaders.map(h => <td key={h}>{String(row[h] ?? '')}</td>)}</tr>)}</tbody>
                </table>
              </div>
            )}

            {run.figure_base64 && <div className="mb-4"><h3 className="mb-2 font-semibold text-ink">Figure</h3><img className="w-full rounded-lg border border-line" src={`data:image/png;base64,${run.figure_base64}`} alt="Analysis figure" />{run.caption && <p className="mt-2 text-sm text-ink-soft">{run.caption}</p>}</div>}
            {run.interpretation && <div className="mb-4"><h3 className="mb-1 font-semibold text-ink">Interpretation</h3><p className="text-sm leading-6 text-ink-soft">{run.interpretation}</p></div>}

            {(run.code_r || run.code_spss || run.code_sas) && (
              <div>
                <h3 className="mb-2 font-semibold text-ink">Code Supplement</h3>
                {run.code_r && <pre className="mb-2 overflow-x-auto rounded-lg border border-line bg-gray-950 p-3 text-xs text-gray-50">{run.code_r}</pre>}
                {run.code_spss && <pre className="mb-2 overflow-x-auto rounded-lg border border-line bg-gray-950 p-3 text-xs text-gray-50">{run.code_spss}</pre>}
                {run.code_sas && <pre className="overflow-x-auto rounded-lg border border-line bg-gray-950 p-3 text-xs text-gray-50">{run.code_sas}</pre>}
              </div>
            )}
          </section>
        )
      })}

      {results.length === 0 && <p className="mb-6 text-sm text-ink-soft">No analysis results are available yet.</p>}

      <section className="mb-6">
        <h2 className="mb-1 font-semibold text-ink">Limitations</h2>
        {limitations.length > 0 ? <ul className="list-disc pl-5 text-sm leading-6 text-ink-soft">{limitations.map((item, idx) => <li key={idx}>{item.msg || item.message || JSON.stringify(item)}</li>)}</ul> : <p className="text-sm text-ink-soft">No data quality issues were flagged for this dataset.</p>}
      </section>

      <section className="border-t border-line pt-6">
        <h2 className="mb-3 font-semibold text-ink">Mentor Comments</h2>
        {data.comments?.length > 0 ? <div className="mb-4 flex flex-col gap-2">{data.comments.map((c, i) => <CommentCard key={c.id || i} comment={c} token={token} authorEmail={authorEmail} load={load} setError={setError} />)}</div> : <p className="mb-4 text-sm text-ink-soft">No comments yet.</p>}

        <form onSubmit={addComment} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1" htmlFor="mentor-name"><span className="label">Your name</span><input id="mentor-name" className="input" value={authorName} onChange={e => setAuthorName(e.target.value)} required disabled={saving} /></label>
          <label className="flex flex-col gap-1" htmlFor="mentor-email"><span className="label">Email (optional, used if you edit your comment later)</span><input id="mentor-email" className="input" type="email" value={authorEmail} onChange={e => setAuthorEmail(e.target.value)} disabled={saving} /></label>
          <label className="flex flex-col gap-1" htmlFor="mentor-comment"><span className="label">Comment</span><textarea id="mentor-comment" className="input min-h-24" value={comment} onChange={e => setComment(e.target.value)} placeholder="Add a comment…" required disabled={saving} /></label>
          <button type="submit" disabled={saving} className="btn-primary self-start">
            {saving && <Spinner />}
            {saving ? 'Sending…' : 'Send Comment'}
          </button>
        </form>
      </section>
    </main>
  )
}
