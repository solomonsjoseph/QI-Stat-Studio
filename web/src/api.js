const BASE = '/api'

function attachErrorDetails(error, envelope) {
  if (!envelope) return error
  error.code = envelope.code
  error.requestId = envelope.request_id
  error.fieldErrors = envelope.field_errors || {}
  return error
}

async function parseError(res, fallback) {
  let data = null
  try {
    data = await res.json()
  } catch {
    // Non-JSON error response; fall back to status text below.
  }

  if (data?.error) {
    throw attachErrorDetails(new Error(data.error.message || fallback), data.error)
  }

  throw new Error(data?.message || fallback)
}

async function readResponse(res) {
  if (res.status === 204) return null
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

async function req(method, path, body) {
  const opts = { method, credentials: 'include' }
  if (body !== undefined) {
    opts.headers = { 'Content-Type': 'application/json' }
    opts.body = JSON.stringify(body)
  }
  const res = await fetch(`${BASE}${path}`, opts)
  if (!res.ok) await parseError(res, `${method} ${path} → ${res.status}`)
  return readResponse(res)
}

function normalizeProjectList(response) {
  if (Array.isArray(response)) return response
  return response?.items || []
}

export const api = {
  // Auth
  register: (email, password) => req('POST', '/auth/register', { email, password }),
  login: (email, password) => req('POST', '/auth/login', { email, password }),
  logout: () => req('POST', '/auth/logout'),
  me: () => req('GET', '/auth/me'),

  // Projects
  createProject: (data) => req('POST', '/projects', data),
  createProjectIntake: async ({ title, description, file, dictionary }) => {
    const fd = new FormData()
    fd.append('title', title)
    fd.append('description', description || '')
    fd.append('file', file)
    fd.append('dictionary', dictionary)
    const res = await fetch(`${BASE}/projects/intake`, { method: 'POST', body: fd, credentials: 'include' })
    if (!res.ok) await parseError(res, `projects/intake → ${res.status}`)
    return readResponse(res)
  },
  getProject: (id) => req('GET', `/projects/${id}`),
  listProjects: async (params = {}) => {
    const search = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') search.set(key, value)
    })
    return normalizeProjectList(await req('GET', `/projects${search.toString() ? `?${search}` : ''}`))
  },
  updateProject: (id, data) => req('PATCH', `/projects/${id}`, data),
  deleteProject: (id, purge = false) => req('DELETE', `/projects/${id}${purge ? '?purge=true' : ''}`),
  resumeProject: (id) => req('GET', `/projects/${id}/resume`),
  saveProjectEdit: (projectId, field, originalText, editedText) =>
    req('POST', `/projects/${projectId}/edits`, { field, original_text: originalText, edited_text: editedText }),

  // Intake
  saveAnswers: (projectId, answers) => req('POST', `/intake/${projectId}`, { answers }),
  getAnswers: (projectId) => req('GET', `/intake/${projectId}`),

  // Upload
  upload: async (projectId, file) => {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch(`${BASE}/upload/${projectId}`, { method: 'POST', body: fd, credentials: 'include' })
    if (!res.ok) await parseError(res, `upload → ${res.status}`)
    return readResponse(res)
  },
  confirmColTypes: (uploadId, colTypes, columnMap = {}) =>
    req('PUT', `/upload/${uploadId}/column-types`, { col_types: colTypes, column_map: columnMap }),
  saveAcknowledgedFlags: (uploadId, flags) =>
    req('PATCH', `/upload/${uploadId}/acknowledged-flags`, { flags }),
  listUploads: (projectId) => req('GET', `/upload/project/${projectId}`),
  getUpload: (uploadId) => req('GET', `/upload/${uploadId}`),
  replaceUpload: async (projectId, uploadId, file) => {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch(`${BASE}/upload/${projectId}/replace/${uploadId}`, { method: 'POST', body: fd, credentials: 'include' })
    if (!res.ok) await parseError(res, `replace upload → ${res.status}`)
    return readResponse(res)
  },
  deleteUpload: (uploadId) => req('DELETE', `/upload/${uploadId}`),
  updateColumnMap: (uploadId, colTypes, columnMap) =>
    req('PUT', `/upload/${uploadId}/column-types`, { col_types: colTypes, column_map: columnMap }),

  // Analysis
  recommend: (projectId) => req('GET', `/analyze/${projectId}/recommend`),
  runAnalysis: (projectId, uploadId, template, params) =>
    req('POST', '/analyze/run', { project_id: projectId, upload_id: uploadId, template, parameters: params }),

  // AI
  chat: (projectId, messages, model) =>
    req('POST', '/ai/chat', { project_id: projectId, messages, model }),
  prefillIntake: (projectId, description) =>
    req('POST', '/ai/intake-prefill', { project_id: projectId, description }),

  // Report
  docxUrl: (runId) => `${BASE}/report/${runId}/docx`,
  pdfUrl: (runId) => `${BASE}/report/${runId}/pdf`,

  // Share
  createShare: (projectId, mentorEmail, expiresAt) =>
    req('POST', `/share/${projectId}/create`, { mentor_email: mentorEmail || null, expires_at: expiresAt || null }),
  revokeShare: (projectId, token) => req('POST', `/share/${projectId}/revoke`, { token }),
  regenerateShare: (projectId, token) => req('POST', `/share/${projectId}/regenerate`, { token }),
  getMentorView: (token) => req('GET', `/share/view/${token}`),
  addComment: (token, authorName, text, authorEmail) =>
    req('POST', `/share/view/${token}/comment`, { author_name: authorName, author_email: authorEmail || null, text }),
  editComment: (token, commentId, authorEmail, text) =>
    req('PATCH', `/share/view/${token}/comment/${commentId}`, { author_email: authorEmail || null, text }),
  deleteComment: (token, commentId, authorEmail) =>
    req('DELETE', `/share/view/${token}/comment/${commentId}`, { author_email: authorEmail || null }),

  // Settings
  getSettings: () => req('GET', '/settings'),
  saveSetting: (key, value) => req('PUT', '/settings', { key, value }),
}
