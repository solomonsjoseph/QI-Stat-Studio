import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DownloadShare from './DownloadShare'

const { apiMock, useAppMock } = vi.hoisted(() => ({
  apiMock: {
    createShare: vi.fn(),
    projectDocxUrl: vi.fn((projectId) => `/api/report/project/${projectId}/docx`),
    projectPdfUrl: vi.fn((projectId) => `/api/report/project/${projectId}/pdf`),
  },
  useAppMock: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../App', () => ({ useApp: useAppMock }))

beforeEach(() => {
  apiMock.createShare.mockReset()
  apiMock.projectDocxUrl.mockClear()
  apiMock.projectPdfUrl.mockClear()
  useAppMock.mockReset()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function multiRunCtx(overrides = {}) {
  return {
    projectId: 7,
    runs: [
      {
        run_id: 1,
        template: 'descriptive_summary',
        result_summary: 'A1c goal rates improved after the intervention.',
        table: [{ measure: 'A1c at goal', pre: '42%', post: '61%' }],
        figure_base64: 'iVBORw0KGgo=',
        ai_interpretation: 'The intervention was associated with improved goal rates.',
      },
      {
        run_id: 2,
        template: 'run_chart',
        result_summary: 'Median wait time fell after the intervention.',
        table: [{ period: 'Baseline', median: 10 }],
        ai_interpretation: 'No special-cause signal detected.',
      },
    ],
    acknowledgedFlags: [{ msg: 'Two months had missing denominator values.' }],
    abstractDraft: 'Background: Falls reduction initiative. Methods: ...',
    ...overrides,
  }
}

describe('DownloadShare multi-run preview', () => {
  it('hides downloads until report generation and then shows a section per run, abstract draft, and project-scoped download links', async () => {
    useAppMock.mockReturnValue({ ctx: multiRunCtx(), update: vi.fn(), prev: vi.fn() })

    const user = userEvent.setup()
    render(<DownloadShare />)

    expect(screen.queryByRole('link', { name: /download word/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /download pdf/i })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Generate report' }))

    expect(screen.getByText('Background: Falls reduction initiative. Methods: ...')).toBeInTheDocument()
    expect(screen.getByText('A1c goal rates improved after the intervention.')).toBeInTheDocument()
    expect(screen.getByText('Median wait time fell after the intervention.')).toBeInTheDocument()
    expect(screen.getByText('A1c at goal')).toBeInTheDocument()
    expect(screen.getByText('The intervention was associated with improved goal rates.')).toBeInTheDocument()
    expect(screen.getByText('No special-cause signal detected.')).toBeInTheDocument()
    expect(screen.getByText('Two months had missing denominator values.')).toBeInTheDocument()
    expect(screen.getByText('Includes R, SPSS, and SAS code supplements. The downloaded report also contains the full audit trail.')).toBeInTheDocument()

    expect(screen.getByRole('link', { name: /download word/i })).toHaveAttribute('href', '/api/report/project/7/docx')
    expect(screen.getByRole('link', { name: /download pdf/i })).toHaveAttribute('href', '/api/report/project/7/pdf')
  })

  it('lets the resident type a mentor email before sharing, and posts it to createShare', async () => {
    useAppMock.mockReturnValue({ ctx: multiRunCtx(), update: vi.fn(), prev: vi.fn() })
    apiMock.createShare.mockResolvedValue({ token: 'tok-123' })

    const user = userEvent.setup()
    render(<DownloadShare />)
    await user.click(screen.getByRole('button', { name: 'Generate report' }))

    const emailInput = screen.getByLabelText(/mentor email/i)
    await user.type(emailInput, 'mentor@example.edu')
    await user.click(screen.getByRole('button', { name: 'Share with mentor' }))

    expect(apiMock.createShare).toHaveBeenCalledWith(7, 'mentor@example.edu')
    expect(await screen.findByText(/mentor\/tok-123/)).toBeInTheDocument()
  })
})
