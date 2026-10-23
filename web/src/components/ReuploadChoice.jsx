import React, { useState } from 'react'
import { useApp } from '../App'
import Spinner from './Spinner'
import { api } from '../api'

function msg(err) {
  return `${err.message || 'Something went wrong'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

// Replace the data file. If the files are identical the user picks keep or fresh;
// if they differ a new handoff is already started and the old one is in History.
export default function ReuploadChoice() {
  const { ctx, update } = useApp()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [pending, setPending] = useState(null) // upload awaiting keep/fresh
  const [notice, setNotice] = useState('')

  async function onFile(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file || !ctx.projectId || !ctx.uploadId) return
    setBusy(true); setError(''); setNotice(''); setPending(null)
    try {
      const res = await api.replaceUpload(ctx.projectId, ctx.uploadId, file)
      update({ uploadId: res.id, colTypes: res.col_types || {}, qualityFlags: res.quality_flags || [] })
      if (res.choice_required) setPending(res)
      else if (res.started_fresh) setNotice('A new handoff was started for this file. The old one is saved in History.')
    } catch (err) {
      setError(msg(err))
    } finally {
      setBusy(false)
    }
  }

  async function choose(choice) {
    setBusy(true); setError('')
    try {
      await api.reuploadChoice(pending.id, choice)
      setPending(null)
      setNotice(choice === 'keep' ? 'Your earlier changes were kept.' : 'Started fresh. The old handoff is saved in History.')
    } catch (err) {
      setError(msg(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card mb-6" aria-labelledby="reupload-heading">
      <h2 id="reupload-heading" className="mb-2 font-semibold text-ink">Replace data file</h2>
      <label className="flex flex-col gap-1">
        <span className="label">Choose a replacement file</span>
        <input type="file" accept=".csv,.xlsx,.xls" onChange={onFile} disabled={busy || !!pending} className="input" />
      </label>
      {busy && <p className="mt-2 flex items-center gap-2 text-sm text-ink-soft" aria-live="polite"><Spinner />Working…</p>}
      {error && <p role="alert" className="alert-error mt-3">{error}</p>}
      {notice && <p role="status" className="alert-info mt-3">{notice}</p>}
      {pending && (
        <div role="alertdialog" aria-labelledby="reupload-q" className="alert-warn mt-3">
          <p id="reupload-q" className="mb-3 font-medium">This looks like the exact files you used last time. Keep all the changes you made, or start fresh?</p>
          <div className="flex gap-2">
            <button type="button" className="btn-primary px-4 py-2" disabled={busy} onClick={() => choose('keep')}>Keep</button>
            <button type="button" className="btn-secondary px-4 py-2" disabled={busy} onClick={() => choose('fresh')}>Start fresh</button>
          </div>
        </div>
      )}
    </section>
  )
}
