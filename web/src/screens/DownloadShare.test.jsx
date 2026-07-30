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
  it('hides downloads until report generation and then shows the richer preview and mentor share affordance', async () => {
    useAppMock.mockReturnValue({
      ctx: {
        projectId: 7,
        runId: 42,
        results: {
          methods: 'Chi-square methods text for the preview.',
          result_summary: 'A1c goal rates improved after the intervention.',
          table: [{ measure: 'A1c at goal', pre: '42%', post: '61%' }],
          figure_base64: 'iVBORw0KGgo=',
        },
        editedCaption: 'Figure 1. A1c goal rates before and after the intervention.',
        editedInterp: 'The intervention was associated with improved goal rates.',
        acknowledgedFlags: [{ msg: 'Two months had missing denominator values.' }],
        qualityFlags: [{ msg: 'Fallback quality flag should not render when acknowledgements exist.' }],
        answers: { q9: "I'm not sure", q10: { email: 'mentor@example.edu' } },
      },
      update: vi.fn(),
    })

    const user = userEvent.setup()
    render(<DownloadShare />)

    expect(screen.queryByRole('link', { name: /download word/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /download pdf/i })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Generate report' }))

    expect(screen.getByText('Chi-square methods text for the preview.')).toBeInTheDocument()
    expect(screen.getByText('A1c at goal')).toBeInTheDocument()
    expect(screen.getByText('Figure 1. A1c goal rates before and after the intervention.')).toBeInTheDocument()
    expect(screen.getByText('The intervention was associated with improved goal rates.')).toBeInTheDocument()
    expect(screen.getByText('Two months had missing denominator values.')).toBeInTheDocument()
    expect(screen.getByText('Includes R, SPSS, and SAS code supplements. The downloaded report also contains the full audit trail.')).toBeInTheDocument()
    expect(screen.getByText('A read-only link will be emailed to mentor@example.edu.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Share with mentor' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /download word/i })).toHaveAttribute('href', '/api/report/42/docx')
    expect(screen.getByRole('link', { name: /download pdf/i })).toHaveAttribute('href', '/api/report/42/pdf')
  })
})
