import React, { useState } from 'react'
import { useApp } from '../App'
import BackButton from '../components/BackButton'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'

function errorMessage(err) {
  return `${err.message || 'Could not create share link'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

function codeSupplementNote(q9Answer) {
  const answer = String(q9Answer || 'R').toLowerCase()
  if (answer.includes('all') || answer.includes('not sure')) return 'Includes R, SPSS, and SAS code supplements.'
  if (answer.includes('spss')) return 'Includes an SPSS code supplement.'
  if (answer.includes('sas')) return 'Includes a SAS code supplement.'
  return 'Includes an R code supplement.'
}

function FileIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M7 3h6l4 4v14H7V3Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
      <path d="M13 3v5h5" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
    </svg>
  )
}

export default function DownloadShare() {
  const { ctx, update, prev } = useApp()
  const [shareToken, setShareToken] = useState(ctx.shareToken || '')
  const [generated, setGenerated] = useState(false)
  const [notificationStatus, setNotificationStatus] = useState('')
  const [copyStatus, setCopyStatus] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const runId = ctx.runId
  const resultSummary = ctx.resultSummary || ctx.results?.result_summary
  const previewTable = Array.isArray(ctx.results?.table) ? ctx.results.table : []
  const tableHeaders = previewTable.length > 0 ? Object.keys(previewTable[0]) : []
  const limitations = ctx.acknowledgedFlags?.length ? ctx.acknowledgedFlags : (ctx.qualityFlags || [])
  const interpretation = ctx.editedInterp || ctx.aiInterpretation || ctx.results?.interpretation
  const caption = ctx.editedCaption
  const q10 = ctx.answers?.q10
  const mentorEmail = q10 && typeof q10 === 'object' ? q10.email : ''
  const codeNote = codeSupplementNote(ctx.answers?.q9)
  const shareUrl = shareToken ? `${window.location.origin}/mentor/${shareToken}` : ''

  function generateReport() {
    // Reports are generated on-demand by the download endpoints; this only reveals the preview/download UI.
    setGenerated(true)
  }

  async function createShare() {
    const q10 = ctx.answers?.q10 || {}
    const email = typeof q10 === 'object' ? q10.email : ''
    setSaving(true)
    setError('')
    try {
      const resp = await api.createShare(ctx.projectId, email)
      setShareToken(resp.token)
      update({ shareToken: resp.token })
      if (resp.notification_status) setNotificationStatus(resp.notification_status)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  async function copyShareLink() {
    setCopyStatus('')
    try {
      await navigator.clipboard.writeText(shareUrl)
      setCopyStatus('Copied')
      window.setTimeout(() => setCopyStatus(''), 2000)
    } catch {
      setCopyStatus('Copy failed, select the text manually')
    }
  }

  return (
    <div className="screen max-w-xl">
      <PageIntro step="download" title="Download & Share" />
      {error && <p role="alert" className="alert-error mb-4">{error}</p>}
      {saving && <p aria-live="polite" className="mb-4 flex items-center gap-2 text-sm text-ink-soft"><Spinner />Creating mentor share link…</p>}

      {!generated ? (
        <div className="flex flex-wrap gap-3">
          <BackButton onClick={prev} disabled={saving} />
          <button type="button" onClick={generateReport} className="btn-primary">
            Generate report
          </button>
        </div>
      ) : (
        <>
          <div className="mb-4">
            <BackButton onClick={prev} disabled={saving} />
          </div>
          <section aria-labelledby="report-preview-heading" className="card mb-8 divide-y divide-line">
            <div className="pb-4">
              <h2 id="report-preview-heading" className="text-lg font-semibold text-ink">Report preview</h2>
            </div>
            <div className="py-4 text-sm leading-6 text-ink-soft">
              <h3 className="mb-1 font-semibold text-ink">Methods</h3>
              <p>{ctx.results?.methods || 'Methods will appear here once analysis results are available.'}</p>
            </div>
            <div className="py-4 text-sm leading-6 text-ink-soft">
              <h3 className="mb-1 font-semibold text-ink">Result summary</h3>
              <p>{resultSummary || 'Result summary will appear here once analysis results are available.'}</p>
            </div>
            {previewTable.length > 0 && (
              <div className="py-4">
                <h3 className="mb-2 font-semibold text-ink">Results table</h3>
                <div className="overflow-x-auto">
                  <table className="table-clean">
                    <thead>
                      <tr>{tableHeaders.map(h => <th key={h}>{h}</th>)}</tr>
                    </thead>
                    <tbody>
                      {previewTable.map((row, idx) => (
                        <tr key={idx}>{tableHeaders.map(h => <td key={h}>{String(row[h] ?? '')}</td>)}</tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
            {ctx.results?.figure_base64 && (
              <div className="py-4">
                <img
                  src={`data:image/png;base64,${ctx.results.figure_base64}`}
                  alt="Generated report figure preview"
                  className="max-w-full rounded-lg"
                />
                {caption && <p className="mt-2 text-sm text-ink-soft">{caption}</p>}
              </div>
            )}
            <div className="py-4 text-sm leading-6 text-ink-soft">
              <h3 className="mb-1 font-semibold text-ink">Interpretation</h3>
              <p>{interpretation || 'Interpretation will appear here once analysis results are available.'}</p>
            </div>
            <div className="py-4 text-sm leading-6 text-ink-soft">
              <h3 className="mb-1 font-semibold text-ink">Limitations</h3>
              {limitations.length > 0 ? (
                <ul className="list-disc pl-5">
                  {limitations.map((flag, idx) => <li key={idx}>{flag.msg || flag.message || String(flag)}</li>)}
                </ul>
              ) : (
                <p>No data quality issues were flagged.</p>
              )}
            </div>
            <div className="pt-4 text-sm leading-6 text-ink-soft">
              <h3 className="mb-1 font-semibold text-ink">Code supplement</h3>
              <p>{codeNote} The downloaded report also contains the full audit trail.</p>
            </div>
          </section>

          <div className="mb-8 grid gap-3 sm:grid-cols-2">
            <a href={runId ? api.docxUrl(runId) : '#'} aria-disabled={!runId} download className={`btn-secondary ${!runId ? 'opacity-50 pointer-events-none' : ''}`}><FileIcon />Download Word (.docx)</a>
            <a href={runId ? api.pdfUrl(runId) : '#'} aria-disabled={!runId} download className={`btn-secondary ${!runId ? 'opacity-50 pointer-events-none' : ''}`}><FileIcon />Download PDF</a>
          </div>

          <section className="border-t border-line pt-6" aria-labelledby="share-heading">
            <h2 id="share-heading" className="mb-3 font-semibold text-ink">Share with Mentor</h2>
            {notificationStatus && <p className="mb-2 text-sm text-ink-soft">Notification status: {notificationStatus}</p>}
            {shareToken ? (
              <div>
                <p className="mb-2 text-sm text-ink-soft">Share this link:</p>
                <code className="block rounded-lg border border-line bg-canvas px-3 py-2 text-sm break-all text-ink">{shareUrl}</code>
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <button type="button" onClick={copyShareLink} className="btn-secondary">Copy link</button>
                  {copyStatus && <span className="text-sm text-ink-soft" aria-live="polite">{copyStatus}</span>}
                </div>
              </div>
            ) : (
              <>
                {mentorEmail && <p className="mb-3 text-sm text-ink-soft">A read-only link will be emailed to {mentorEmail}.</p>}
                <button type="button" onClick={createShare} disabled={saving} className="btn-primary">
                  {saving && <Spinner />}
                  {saving ? 'Creating…' : 'Share with mentor'}
                </button>
              </>
            )}
          </section>
        </>
      )}
    </div>
  )
}
