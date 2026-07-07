import React, { useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'

function errorMessage(err) {
  return `${err.message || 'Could not create share link'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function DownloadShare() {
  const { ctx, update } = useApp()
  const [shareToken, setShareToken] = useState(ctx.shareToken || '')
  const [generated, setGenerated] = useState(false)
  const [notificationStatus, setNotificationStatus] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const runId = ctx.runId
  const resultSummary = ctx.resultSummary || ctx.results?.result_summary
  const limitationCount = ctx.acknowledgedFlags?.length ?? ctx.qualityFlags?.length ?? 0

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

  return (
    <div className="max-w-xl mx-auto p-8 mt-8">
      <h1 className="text-2xl font-bold mb-6 text-blue-800">Download & Share</h1>
      {error && <p role="alert" className="mb-4 text-sm text-red-700">{error}</p>}
      {saving && <p aria-live="polite" className="mb-4 text-sm text-gray-500">Creating mentor share link…</p>}

      {!generated ? (
        <button type="button" onClick={generateReport} className="px-5 py-3 bg-blue-700 text-white rounded font-medium hover:bg-blue-800">
          Generate report
        </button>
      ) : (
        <>
          <section aria-labelledby="report-preview-heading" className="mb-8 rounded border border-gray-200 bg-white p-5">
            <h2 id="report-preview-heading" className="text-lg font-semibold mb-4 text-gray-900">Report preview</h2>
            <div className="space-y-4 text-sm text-gray-700">
              <div>
                <h3 className="font-semibold text-gray-900">Methods</h3>
                <p>{ctx.results?.methods || 'Methods will appear here once analysis results are available.'}</p>
              </div>
              <div>
                <h3 className="font-semibold text-gray-900">Result summary</h3>
                <p>{resultSummary || 'Result summary will appear here once analysis results are available.'}</p>
              </div>
              {ctx.results?.figure_base64 && (
                <img
                  src={`data:image/png;base64,${ctx.results.figure_base64}`}
                  alt="Generated report figure preview"
                  className="max-w-full rounded border border-gray-200"
                />
              )}
              <p>Limitations include {limitationCount} acknowledged or flagged quality issue{limitationCount === 1 ? '' : 's'}.</p>
            </div>
          </section>

          <div className="flex flex-col gap-4 mb-8">
            <a href={runId ? api.docxUrl(runId) : '#'} aria-disabled={!runId} download className={`px-5 py-3 border border-blue-600 text-blue-700 rounded font-medium text-center hover:bg-blue-50 ${!runId ? 'opacity-50 pointer-events-none' : ''}`}>Download Word (.docx)</a>
            <a href={runId ? api.pdfUrl(runId) : '#'} aria-disabled={!runId} download className={`px-5 py-3 border border-blue-600 text-blue-700 rounded font-medium text-center hover:bg-blue-50 ${!runId ? 'opacity-50 pointer-events-none' : ''}`}>Download PDF</a>
          </div>

          <div className="border-t pt-6">
            <h2 className="font-semibold mb-3">Share with Mentor</h2>
            {notificationStatus && <p className="text-sm text-gray-600 mb-2">Notification status: {notificationStatus}</p>}
            {shareToken ? (
              <div>
                <p className="text-sm text-gray-600 mb-2">Share this link:</p>
                <code className="block bg-gray-100 rounded px-3 py-2 text-sm break-all">{window.location.origin}/mentor/{shareToken}</code>
              </div>
            ) : (
              <button type="button" onClick={createShare} disabled={saving} className="px-5 py-2 bg-green-600 text-white rounded font-medium hover:bg-green-700 disabled:opacity-50">
                {saving ? 'Creating…' : 'Create Share Link'}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}
