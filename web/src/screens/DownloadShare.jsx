import React, { useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'

export default function DownloadShare() {
  const { ctx } = useApp()
  const [shareToken, setShareToken] = useState('')
  const runId = ctx.runId
  const q9 = ctx.answers?.q9 || ''
  const showSpssNote = q9.includes('SPSS') || q9.includes('SAS') || q9.includes('All')

  async function createShare() {
    const q10 = ctx.answers?.q10 || {}
    const email = typeof q10 === 'object' ? q10.email : ''
    const resp = await api.createShare(ctx.projectId, email)
    setShareToken(resp.token)
  }

  return (
    <div className="max-w-xl mx-auto p-8 mt-8">
      <h2 className="text-2xl font-bold mb-6 text-blue-800">Download & Share</h2>

      {showSpssNote && (
        <div className="bg-blue-50 border border-blue-200 rounded p-3 text-sm text-blue-800 mb-6">
          Your R code supplement is included in the report. SPSS/SAS export is coming in a future update.
        </div>
      )}

      <div className="flex flex-col gap-4 mb-8">
        <a
          href={runId ? api.docxUrl(runId) : '#'}
          download
          className={`px-5 py-3 border border-blue-600 text-blue-700 rounded font-medium text-center hover:bg-blue-50 ${!runId && 'opacity-50 pointer-events-none'}`}
        >
          Download Word (.docx)
        </a>
        <a
          href={runId ? api.pdfUrl(runId) : '#'}
          download
          className={`px-5 py-3 border border-blue-600 text-blue-700 rounded font-medium text-center hover:bg-blue-50 ${!runId && 'opacity-50 pointer-events-none'}`}
        >
          Download PDF
        </a>
      </div>

      <div className="border-t pt-6">
        <h3 className="font-semibold mb-3">Share with Mentor</h3>
        {shareToken ? (
          <div>
            <p className="text-sm text-gray-600 mb-2">Share this link:</p>
            <code className="block bg-gray-100 rounded px-3 py-2 text-sm break-all">
              {window.location.origin}/mentor/{shareToken}
            </code>
          </div>
        ) : (
          <button
            onClick={createShare}
            className="px-5 py-2 bg-green-600 text-white rounded font-medium hover:bg-green-700"
          >
            Create Share Link
          </button>
        )}
      </div>
    </div>
  )
}
