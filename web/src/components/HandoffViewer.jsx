import React, { useEffect, useState } from 'react'
import { api } from '../api'

const KIND_LABELS = {
  created: 'Created', apply: 'Change applied', undo: 'Change undone',
  revise: 'Revised', keep_from_previous: 'Kept from earlier upload',
}

const cells = line => line.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim())
const isSep = line => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line)

// A warning's "Examples: a; b; c" line shows the first example and folds the rest into a native <details>.
function renderItem(text) {
  const m = /^Examples:\s+(.*)$/.exec(text)
  const parts = m ? m[1].split('; ') : []
  if (parts.length < 2) return text
  const more = parts.slice(1)
  return (
    <>
      Example: {parts[0]}
      <details className="mt-1">
        <summary className="cursor-pointer text-xs text-ink-soft">Show {more.length} more example{more.length === 1 ? '' : 's'}</summary>
        <ul className="list-disc pl-5">{more.map((e, n) => <li key={n}>{e}</li>)}</ul>
      </details>
    </>
  )
}

// Tiny markdown renderer: headings, lists, tables, fenced code, paragraphs.
// Builds React elements only, so every string is escaped. No HTML is ever injected.
export function renderMarkdown(md) {
  const lines = String(md || '').split('\n')
  const out = []
  let i = 0
  const key = () => out.length
  while (i < lines.length) {
    const line = lines[i]
    if (/^\s*```/.test(line)) {
      const code = []
      i++
      while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++])
      i++
      out.push(<pre key={key()} className="overflow-x-auto rounded bg-surface-sunken p-3 font-mono text-xs">{code.join('\n')}</pre>)
    } else if (/^#{1,6}\s/.test(line)) {
      const level = line.match(/^#+/)[0].length
      const Tag = `h${Math.min(level + 1, 6)}`
      out.push(<Tag key={key()} className="mt-3 font-semibold text-ink">{line.replace(/^#+\s*/, '')}</Tag>)
      i++
    } else if (line.includes('|') && i + 1 < lines.length && isSep(lines[i + 1])) {
      const head = cells(line)
      const rows = []
      i += 2
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(cells(lines[i++]))
      out.push(
        <div key={key()} className="overflow-x-auto">
          <table className="table-clean">
            <thead><tr>{head.map((h, c) => <th key={c}>{h}</th>)}</tr></thead>
            <tbody>{rows.map((r, ri) => <tr key={ri}>{r.map((c, ci) => <td key={ci}>{c}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      )
    } else if (/^\s*([-*]|\d+\.)\s/.test(line)) {
      const ordered = /^\s*\d+\./.test(line)
      const items = []
      while (i < lines.length && /^\s*([-*]|\d+\.)\s/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ''))
      const List = ordered ? 'ol' : 'ul'
      out.push(<List key={key()} className={`${ordered ? 'list-decimal' : 'list-disc'} pl-5 text-sm`}>{items.map((t, n) => <li key={n}>{renderItem(t)}</li>)}</List>)
    } else if (!line.trim()) {
      i++
    } else {
      const para = []
      while (i < lines.length && lines[i].trim() && !/^(\s*```|#{1,6}\s|\s*([-*]|\d+\.)\s)/.test(lines[i])) para.push(lines[i++])
      out.push(<p key={key()} className="text-sm text-ink">{para.join(' ')}</p>)
    }
  }
  return out
}

// Read-only: handoff markdown plus change log. No edit controls, no chat.
// Pass `handoff` (already loaded) or `uploadId` (fetched here).
export default function HandoffViewer({ handoff: given, uploadId }) {
  const [fetched, setFetched] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    if (given || !uploadId) return
    let live = true
    api.getHandoff(uploadId).then(h => live && setFetched(h)).catch(e => live && setError(e.message || 'Could not load the handoff document'))
    return () => { live = false }
  }, [given, uploadId])

  const handoff = given || fetched
  if (error) return <p role="alert" className="alert-error">{error}</p>
  if (!handoff) return <p aria-live="polite" className="text-sm text-ink-soft">Loading the handoff document…</p>
  const log = handoff.change_log || []
  return (
    <div className="flex flex-col gap-4">
      {handoff.revision != null && <p className="text-sm text-ink-soft">Revision {handoff.revision}</p>}
      {handoff.markdown
        ? <div className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4" tabIndex={0} role="region" aria-label="Handoff document">{renderMarkdown(handoff.markdown)}</div>
        : <p className="text-sm text-ink-soft">The handoff document was deleted. The change log below is kept.</p>}
      <section aria-labelledby={`changelog-${handoff.upload_id}`}>
        <h3 id={`changelog-${handoff.upload_id}`} className="mb-2 font-semibold text-ink">Change log</h3>
        {log.length === 0 ? <p className="text-sm text-ink-soft">No changes recorded.</p> : (
          <ol className="flex flex-col gap-2 text-sm">
            {log.map(e => (
              <li key={`${e.revision}-${e.created_at}`} className="card p-3">
                <span className="font-medium text-ink">Revision {e.revision}: {KIND_LABELS[e.kind] || e.kind}</span>
                <span className="ml-2 text-xs text-ink-faint">{e.created_at ? new Date(e.created_at).toLocaleString() : ''} · {e.actor}</span>
                {e.summary && <p className="mt-1 text-ink-soft">{e.summary}</p>}
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  )
}
