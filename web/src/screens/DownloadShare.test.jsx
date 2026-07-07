import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DownloadShare from './DownloadShare'

const { apiMock, useAppMock } = vi.hoisted(() => ({
  apiMock: {
    createShare: vi.fn(),
    docxUrl: vi.fn((runId) => `/api/report/${runId}/docx`),
    pdfUrl: vi.fn((runId) => `/api/report/${runId}/pdf`),
  },
  useAppMock: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../App', () => ({ useApp: useAppMock }))

beforeEach(() => {
  apiMock.createShare.mockReset()
  apiMock.docxUrl.mockClear()
  apiMock.pdfUrl.mockClear()
  useAppMock.mockReset()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('DownloadShare', () => {
  it('hides downloads until report generation and then shows a preview with methods', async () => {
    useAppMock.mockReturnValue({
      ctx: {
        projectId: 7,
        runId: 42,
        results: {
          methods: 'Chi-square methods text for the preview.',
          result_summary: 'A1c goal rates improved after the intervention.',
          figure_base64: 'iVBORw0KGgo=',
        },
        acknowledgedFlags: [{ id: 1 }, { id: 2 }],
        qualityFlags: [{ id: 3 }],
        answers: {},
      },
      update: vi.fn(),
    })

    const user = userEvent.setup()
    render(<DownloadShare />)

    expect(screen.queryByRole('link', { name: /download word/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /download pdf/i })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Generate report' }))

    expect(screen.getByText('Chi-square methods text for the preview.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /download word/i })).toHaveAttribute('href', '/api/report/42/docx')
    expect(screen.getByRole('link', { name: /download pdf/i })).toHaveAttribute('href', '/api/report/42/pdf')
  })
})
