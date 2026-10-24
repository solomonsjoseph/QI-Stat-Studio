import React, { useEffect, useState } from 'react'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import HandoffViewer from '../components/HandoffViewer'
import { api } from '../api'

function msg(err) {
  return `${err.message || 'Something went wrong'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}
const fmt = d => (d ? new Date(d).toLocaleDateString() : 'n/a')
const STATUS = { replaced: 'Replaced', deleted: 'Document deleted', current: 'Current' }

export default function History() {
  const [items, setItems] = useState(null)
  const [open, setOpen] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function load() {
    setError('')
    try {
      const projects = await api.listProjects({ limit: 100, order: 'created_desc' })
      const all = await Promise.all(projects.map(async p => {
        const res = await api.getHandoffHistory(p.id)
        return (res.items || []).map(it => ({ ...it, project_title: p.title }))
      }))
      setItems(all.flat())
    } catch (err) {
      setError(msg(err)); setItems([])
    }
  }
  useEffect(() => { load() }, [])

  async function view(item) {
    setBusy(true); setError('')
    try { setOpen(await api.getHandoff(item.upload_id)) } catch (err) { setError(msg(err)) } finally { setBusy(false) }
  }

  async function remove(item) {
    if (!window.confirm('Delete this old handoff document? The change log is kept, and only an administrator can remove it.')) return
    setBusy(true); setError('')
    try {
      await api.deleteHandoff(item.upload_id)
      if (open?.upload_id === item.upload_id) setOpen(null)
      await load()
    } catch (err) { setError(msg(err)) } finally { setBusy(false) }
  }

  return (
    <div className="screen max-w-3xl">
      <PageIntro title="History" lead="Handoff documents from files you have replaced. They are read-only." />
      {error && <p role="alert" className="alert-error mb-4">{error}</p>}
      {items === null && <p className="flex items-center gap-2 text-sm text-ink-soft" aria-live="polite"><Spinner />Loading history…</p>}
      {items && items.length === 0 && <p className="text-sm text-ink-soft">No replaced or deleted handoffs yet.</p>}
      {items && items.length > 0 && (
        <ul className="card divide-y divide-line p-0">
          {items.map(it => (
            <li key={it.upload_id} className="flex flex-col gap-2 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="font-medium text-ink">{it.file_name}{it.project_title ? ` (${it.project_title})` : ''}</p>
                <p className="text-sm text-ink-faint">
                  Uploaded {fmt(it.created_at)} · Replaced {fmt(it.replaced_at)} · Revision {it.revision} · {STATUS[it.status] || it.status}
                </p>
              </div>
              <div className="flex gap-2">
                <button type="button" className="btn-secondary px-4 py-1.5" disabled={busy} onClick={() => view(it)} aria-label={`Open handoff for ${it.file_name}`}>Open</button>
                {it.status === 'replaced' && (
                  <button type="button" className="btn-danger px-4 py-1.5" disabled={busy} onClick={() => remove(it)} aria-label={`Delete handoff document for ${it.file_name}`}>Delete</button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {open && (
        <section className="mt-6" aria-labelledby="history-open-heading">
          <h2 id="history-open-heading" className="mb-3 text-lg font-semibold text-ink">Handoff document (read-only)</h2>
          <HandoffViewer handoff={open} />
        </section>
      )}
    </div>
  )
}
