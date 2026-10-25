import React, { useCallback, useEffect, useState } from 'react'
import Spinner from './Spinner'
import { api } from '../api'
import { plural } from '../plural'

function describe(err, fallback) {
  return `${err.message || fallback}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

function status(c) {
  if (c.resolved_at) return 'Resolved by the mentor'
  if (c.addressed_at) return 'Addressed, waiting for the mentor'
  return 'Open'
}

function Comment({ projectId, comment, onChanged, setError }) {
  const [reply, setReply] = useState(comment.resident_reply || '')
  const [busy, setBusy] = useState(false)

  async function send(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api.replyToComment(projectId, comment.id, reply)
      await onChanged()
    } catch (err) {
      setError(describe(err, 'Could not save your reply'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className="card p-4 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-ink">{comment.author_name}</span>
        <span className="rounded border border-line px-2 py-0.5 text-xs text-ink-soft" data-testid="review-status">{status(comment)}</span>
      </div>
      <p className="mt-2 leading-6 text-ink-soft">{comment.text}</p>
      <form onSubmit={send} className="mt-3 flex flex-col gap-2">
        <label htmlFor={`reply-${comment.id}`} className="label">What did you do about this?</label>
        <textarea id={`reply-${comment.id}`} className="input min-h-16" value={reply} onChange={e => setReply(e.target.value)} disabled={busy} />
        <button type="submit" className="btn-secondary self-start" disabled={busy}>
          {busy ? 'Saving…' : comment.addressed_at ? 'Update reply' : 'Mark addressed'}
        </button>
      </form>
    </article>
  )
}

// The resident's side of the mentor review: every comment with its status, a reply box, and the approval.
export default function MentorReviewPanel({ projectId, refreshKey }) {
  const [review, setReview] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setReview(await api.getMentorReview(projectId))
    } catch (err) {
      setError(describe(err, 'Could not load the mentor review'))
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => { load() }, [load, refreshKey])

  const comments = review?.comments || []
  const open = comments.filter(c => !c.resolved_at).length

  return (
    <section className="card mb-8 flex flex-col gap-3" aria-labelledby="mentor-review-heading">
      <div className="flex items-center justify-between gap-2">
        <h2 id="mentor-review-heading" className="text-lg font-semibold text-ink">Mentor review</h2>
        <button type="button" className="btn-secondary px-3 py-1.5" onClick={load} disabled={loading}>Check for new comments</button>
      </div>
      {loading && <p aria-live="polite" className="flex items-center gap-2 text-sm text-ink-soft"><Spinner />Loading…</p>}
      {error && <p role="alert" className="alert-error">{error}</p>}
      {review?.approval && (
        <p className="alert-ok" aria-live="polite">
          Approved by {review.approval.approved_by_name} on {new Date(review.approval.approved_at).toLocaleString()}.
          {review.approval.approved_note ? ` ${review.approval.approved_note}` : ''}
        </p>
      )}
      {review && comments.length === 0 && <p className="text-sm text-ink-soft">No mentor comments yet. Send the link, then come back here.</p>}
      {comments.length > 0 && (
        <p className="text-sm text-ink-soft">
          {open === 0 ? 'The mentor has resolved every comment.' : `${open} of ${plural(comments.length, 'comment')} not resolved yet.`} Use Back to change the report, then reply here. The mentor sees your reply on the same link and marks it resolved.
        </p>
      )}
      {comments.map(c => <Comment key={c.id} projectId={projectId} comment={c} onChanged={load} setError={setError} />)}
    </section>
  )
}
