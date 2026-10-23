import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

describe('api.runAnalysis', () => {
  it('posts the analysis request with backend field names and nested parameters', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ run_id: 77, result_summary: 'Mean improved.' }), { status: 200 })
    )

    const result = await api.runAnalysis(12, 34, 'run_chart', {
      date_col: 'week',
      value_col: 'falls',
      intervention_date: '2026-01-15',
    })

    expect(globalThis.fetch).toHaveBeenCalledWith('/api/analyze/run', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_id: 12,
        upload_id: 34,
        template: 'run_chart',
        parameters: {
          date_col: 'week',
          value_col: 'falls',
          intervention_date: '2026-01-15',
        },
      }),
    })
    expect(result).toEqual({ run_id: 77, result_summary: 'Mean improved.' })
  })
})

describe('api error envelopes', () => {
  it('throws backend envelope details with code, request id, and field errors', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        error: {
          code: 'VALIDATION_ERROR',
          message: 'Template is required',
          request_id: 'req-123',
          field_errors: { template: ['Field required'] },
        },
      }), { status: 422 })
    )

    await expect(api.runAnalysis(12, 34, '', {})).rejects.toMatchObject({
      message: 'Template is required',
      code: 'VALIDATION_ERROR',
      requestId: 'req-123',
      fieldErrors: { template: ['Field required'] },
    })
  })

  it('surfaces advisor_unavailable code and key source, and sends the key as {key}', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: { code: 'advisor_unavailable', message: 'No key', key_source: 'none' } }), { status: 503 })
    )
    await expect(api.saveAiKey('sk-abcdefgh')).rejects.toMatchObject({ code: 'advisor_unavailable', keySource: 'none' })
    const [url, opts] = globalThis.fetch.mock.calls[0]
    expect(url).toBe('/api/settings/ai-key')
    expect(opts.method).toBe('PUT')
    expect(JSON.parse(opts.body)).toEqual({ key: 'sk-abcdefgh' })
  })
})

describe('api warning groups', () => {
  it('uses the contract paths and bodies', async () => {
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    await api.getFlagStates(42)
    await api.acknowledgeWarnings(42, ['a'], 'note')
    await api.createWarningGroup(42, ['b'], 'clarify')
    await api.cancelWarningGroup(42, 7)
    const calls = fetchMock.mock.calls.map(([url, init]) => [init.method, url.replace(/^.*(?=\/upload)/, ''), init.body])
    expect(calls).toEqual([
      ['GET', '/upload/42/flag-states', undefined],
      ['POST', '/upload/42/warnings/acknowledge', JSON.stringify({ flag_ids: ['a'], text: 'note' })],
      ['POST', '/upload/42/warning-groups', JSON.stringify({ flag_ids: ['b'], action: 'clarify', text: null })],
      ['DELETE', '/upload/42/warning-groups/7', undefined],
    ])
  })
})
