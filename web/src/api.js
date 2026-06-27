const BASE = '/api'

async function req(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } }
  if (body !== undefined) opts.body = JSON.stringify(body)
  const res = await fetch(`${BASE}${path}`, opts)
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status}`)
  return res.json()
}

export const api = {
  // Projects
  createProject: (data) => req('POST', '/projects', data),
  getProject: (id) => req('GET', `/projects/${id}`),
  listProjects: () => req('GET', '/projects'),

  // Intake
  saveAnswers: (projectId, answers) => req('POST', `/intake/${projectId}`, { answers }),
  getAnswers: (projectId) => req('GET', `/intake/${projectId}`),

  // Upload
  upload: async (projectId, file) => {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch(`${BASE}/upload/${projectId}`, { method: 'POST', body: fd })
    if (!res.ok) throw new Error(`upload → ${res.status}`)
    return res.json()
  },
  confirmColTypes: (uploadId, colTypes) =>
    req('PUT', `/upload/${uploadId}/column-types`, { col_types: colTypes }),

  // Analysis
  runAnalysis: (projectId, uploadId, template, params) =>
    req('POST', '/analyze/run', { project_id: projectId, upload_id: uploadId, template, params }),

  // AI
  chat: (projectId, messages, model) =>
    req('POST', '/ai/chat', { project_id: projectId, messages, model }),

  // Report
  docxUrl: (runId) => `${BASE}/report/${runId}/docx`,
  pdfUrl: (runId) => `${BASE}/report/${runId}/pdf`,

  // Share
  createShare: (projectId, mentorEmail) =>
    req('POST', `/share/${projectId}/create${mentorEmail ? `?mentor_email=${encodeURIComponent(mentorEmail)}` : ''}`),
  getMentorView: (token) => req('GET', `/share/view/${token}`),
  addComment: (token, author, text) =>
    req('POST', `/share/view/${token}/comment`, { author, text }),

  // Settings
  getSettings: () => req('GET', '/settings'),
  saveSetting: (key, value) => req('PUT', '/settings', { key, value }),
}
