import React, { useState } from 'react'
import { useApp } from '../App'
import BackButton from '../components/BackButton'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'
import { TEMPLATE_LABELS } from '../templateLabels'

function errorMessage(err) {
  return `${err.message || 'Could not create share link'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

function FileIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M6 2h9l5 5v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Z" stroke="currentColor" strokeWidth="1.5" />
      <path d="M14 2v5h5" stroke="currentColor" strokeWidth="1.5" />
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
  const [mentorEmail, setMentorEmail] = useState('')

  const runs = ctx.runs || []
  const limitations = ctx.acknowledgedFlags || []
  const abstractDraft = ctx.abstractDraft || ''
  const shareUrl = shareToken ? `${window.location.origin}/mentor/${shareToken}` : ''

  function generateReport() {
    // Reports are generated on-demand by the download endpoints; this only reveals the preview/download UI.
    setGenerated(true)
  }

  async function createShare() {
    setSaving(true)
    setError('')
    try {
      const resp = await api.createShare(ctx.projectId, mentorEmail)
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

          {abstractDraft && (
            <section aria-labelledby="abstract-preview-heading" className="card mb-6">
              <h2 id="abstract-preview-heading" className="mb-2 text-lg font-semibold text-ink">Abstract Draft</h2>
              <p className="text-sm leading-6 text-ink-soft whitespace-pre-wrap">{abstractDraft}</p>
            </section>
          )}

          <section aria-labelledby="report-preview-heading" className="card mb-8 divide-y divide-line">
            <div className="pb-4">
              <h2 id="report-preview-heading" className="text-lg font-semibold text-ink">Report preview</h2>
            </div>

            {runs.map(run => (
              <div key={run.run_id} className="py-4 text-sm leading-6 text-ink-soft">
                <h3 className="mb-1 font-semibold text-ink">{TEMPLATE_LABELS[run.template] || run.template}</h3>
                {run.result_summary && <p className="mb-2">{run.result_summary}</p>}
                {Array.isArray(run.table) && run.table.length > 0 && (
                  <div className="mb-2 overflow-x-auto">
                    <table className="table-clean">
                      <thead>
                        <tr>{Object.keys(run.table[0]).map(h => <th key={h}>{h}</th>)}</tr>
                      </thead>
                      <tbody>
                        {run.table.map((row, idx) => (
                          <tr key={idx}>{Object.keys(run.table[0]).map(h => <td key={h}>{String(row[h] ?? '')}</td>)}</tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {run.figure_base64 && (
                  <img
                    src={`data:image/png;base64,${run.figure_base64}`}
                    alt={`${TEMPLATE_LABELS[run.template] || run.template} figure preview`}
                    className="max-w-full rounded-lg mb-2"
                  />
                )}
                {(run.ai_interpretation || run.interpretation) && (
                  <p>{run.ai_interpretation || run.interpretation}</p>
                )}
              </div>
            ))}

            {runs.length === 0 && (
              <div className="py-4 text-sm leading-6 text-ink-soft">
                <p>Results will appear here once analysis results are available.</p>
              </div>
            )}

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
              <p>Includes R, SPSS, and SAS code supplements. The downloaded report also contains the full audit trail.</p>
            </div>
          </section>

          <div className="mb-8 grid gap-3 sm:grid-cols-2">
            <a href={api.projectDocxUrl(ctx.projectId)} download className="btn-secondary"><FileIcon />Download Word (.docx)</a>
            <a href={api.projectPdfUrl(ctx.projectId)} download className="btn-secondary"><FileIcon />Download PDF</a>
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
                <label className="flex flex-col gap-1 mb-3" htmlFor="mentor-email">
                  <span className="label">Mentor Email (optional)</span>
                  <input
                    id="mentor-email"
                    type="email"
                    className="input"
                    value={mentorEmail}
                    onChange={e => setMentorEmail(e.target.value)}
                    placeholder="mentor@hospital.edu"
                    disabled={saving}
                  />
                </label>
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
