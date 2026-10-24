const BASE = '/api'

function attachErrorDetails(error, envelope) {
  if (!envelope) return error
  error.code = envelope.code
  error.requestId = envelope.request_id
  if (envelope.key_source) error.keySource = envelope.key_source
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
  quit: () => req('POST', '/dev/quit'),
  me: () => req('GET', '/auth/me'),

  // Projects
  createProject: (data) => req('POST', '/projects', data),
  createProjectIntake: async ({ title, description, file, dictionary, deadline }) => {
    const fd = new FormData()
    fd.append('title', title)
    fd.append('description', description || '')
    fd.append('file', file)
    if (dictionary) fd.append('dictionary', dictionary)
    if (deadline) fd.append('deadline', deadline)
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
  saveProjectEdit: (projectId, field, originalText, editedText, runId = null) =>
    req('POST', `/projects/${projectId}/edits`, { field, original_text: originalText, edited_text: editedText, run_id: runId }),
  updateDesign: (projectId, design) => req('PUT', `/projects/${projectId}/design`, design),

  // AI clarification & guidance
  scrubPreview: (text) => req('POST', '/ai/scrub-preview', { text }),
  clarify: (projectId, message) => req('POST', `/ai/clarify/${projectId}`, { message: message || null }),
  confirmClarification: (projectId) => req('POST', `/ai/clarify/${projectId}`, { confirm: true }),
  collectionGuidance: (projectId) => req('POST', `/ai/collection-guidance/${projectId}`),

  // AI analysis-plan recommendation & override
  recommendPlan: (projectId, message) => req('POST', `/ai/recommend-plan/${projectId}`, { message: message || null }),
  confirmPlan: (projectId, analyses) => req('POST', `/ai/recommend-plan/${projectId}`, { confirm: true, analyses }),
  overridePlan: (projectId, instruction) => req('POST', `/ai/override-plan/${projectId}`, { instruction }),
  interpretResults: (projectId) => req('POST', `/ai/interpret-results/${projectId}`),
  // Upload
  upload: async (projectId, file) => {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch(`${BASE}/upload/${projectId}`, { method: 'POST', body: fd, credentials: 'include' })
    if (!res.ok) await parseError(res, `upload → ${res.status}`)
    return readResponse(res)
  },
  confirmColTypes: (uploadId, colTypes, columnMap = {}, columnRoles = {}) =>
    req('PUT', `/upload/${uploadId}/column-types`, { col_types: colTypes, column_map: columnMap, column_roles: columnRoles }),
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
  updateColumnMap: (uploadId, colTypes, columnMap = {}, columnRoles = {}) =>
    req('PUT', `/upload/${uploadId}/column-types`, { col_types: colTypes, column_map: columnMap, column_roles: columnRoles }),

  // Analysis
  validatePlan: (projectId, uploadId, analyses) =>
    req('POST', `/analyze/validate-plan/${projectId}`, { upload_id: uploadId, analyses }),
  runPlan: (projectId, uploadId, analyses) =>
    req('POST', `/analyze/run-plan/${projectId}`, { upload_id: uploadId, analyses }),
  runAnalysis: (projectId, uploadId, template, params) =>
    req('POST', '/analyze/run', { project_id: projectId, upload_id: uploadId, template, parameters: params }),

  // AI
  chat: (projectId, messages, model) =>
    req('POST', '/ai/chat', { project_id: projectId, messages, model }),

  // Report
  projectDocxUrl: (projectId) => `${BASE}/report/project/${projectId}/docx`,
  projectPdfUrl: (projectId) => `${BASE}/report/project/${projectId}/pdf`,
  // Share
  createShare: (projectId, mentorEmail, expiresAt) =>
    req('POST', `/share/${projectId}/create`, { mentor_email: mentorEmail || null, expires_at: expiresAt || null }),
  revokeShare: (projectId, token) => req('POST', `/share/${projectId}/revoke`, { token }),
  regenerateShare: (projectId, token) => req('POST', `/share/${projectId}/regenerate`, { token }),
  getMentorView: (token) => req('GET', `/share/view/${token}`),
  addComment: (token, authorName, text, authorEmail) =>
    req('POST', `/share/view/${token}/comment`, { author_name: authorName, author_email: authorEmail || null, text }),
  editComment: (token, commentId, editToken, text) =>
    req('PATCH', `/share/view/${token}/comment/${commentId}`, { edit_token: editToken, text }),
  deleteComment: (token, commentId, editToken) =>
    req('DELETE', `/share/view/${token}/comment/${commentId}`, { edit_token: editToken }),

  // Settings
  getSettings: () => req('GET', '/settings'),
  saveSetting: (key, value) => req('PUT', '/settings', { key, value }),

  // --- AI key (T10) ---
  getAiKeyStatus: () => req('GET', '/settings/ai-key'),
  saveAiKey: (key) => req('PUT', '/settings/ai-key', { key }),
  clearAiKey: () => req('DELETE', '/settings/ai-key'),
  // --- end AI key ---

  // --- Warning groups and flag states (T11; contract in docs/api-contract-handoff.md, backend not built yet) ---
  getFlagStates: (uploadId) => req('GET', `/upload/${uploadId}/flag-states`),
  acknowledgeWarnings: (uploadId, flagIds, text) =>
    req('POST', `/upload/${uploadId}/warnings/acknowledge`, { flag_ids: flagIds, text: text || null }),
  createWarningGroup: (uploadId, flagIds, action, text) =>
    req('POST', `/upload/${uploadId}/warning-groups`, { flag_ids: flagIds, action, text: text || null }),
  // --- end warning groups ---
  // --- Re-upload choice, history, mentor handoff (T21) ---
  reuploadChoice: (uploadId, choice) => req('POST', `/upload/${uploadId}/reupload-choice`, { choice }),
  getHandoffHistory: (projectId) => req('GET', `/projects/${projectId}/handoff-history`),
  getHandoff: (uploadId) => req('GET', `/upload/${uploadId}/handoff`),
  deleteHandoff: (uploadId) => req('DELETE', `/upload/${uploadId}/handoff`),
  getMentorHandoff: (token) => req('GET', `/share/${token}/handoff`),
  // --- end re-upload / history ---
  // --- QI Stat Advisor chat (T20); the handoff viewer reuses getHandoff above ---
  getAdvisorThread: (groupId) => req('GET', `/ai/advisor/groups/${groupId}`),
  sendAdvisorMessage: (groupId, message, warningId) =>
    req('POST', `/ai/advisor/groups/${groupId}/messages`, { message, warning_id: warningId || null }),
  confirmAdvisorProposal: (groupId, proposalId) =>
    req('POST', `/ai/advisor/groups/${groupId}/confirm`, { proposal_id: proposalId }),
  declineAdvisorProposal: (groupId, proposalId) =>
    req('POST', `/ai/advisor/groups/${groupId}/confirm`, { proposal_id: proposalId, decline: true }),
  // --- end advisor chat ---
  // --- Cancel a clarification (M8) ---
  cancelWarningGroup: (uploadId, groupId) => req('DELETE', `/upload/${uploadId}/warning-groups/${groupId}`),
  // --- end cancel clarification ---
}
