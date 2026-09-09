import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import DataReview from './DataReview'

const { apiMock, useAppMock } = vi.hoisted(() => ({
  apiMock: {
    saveAcknowledgedFlags: vi.fn(),
    confirmColTypes: vi.fn(),
  },
  useAppMock: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../App', () => ({ useApp: useAppMock }))

beforeEach(() => {
  apiMock.saveAcknowledgedFlags.mockReset()
  apiMock.confirmColTypes.mockReset()
  useAppMock.mockReset()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('DataReview', () => {
  it('checks only the resumed warning whose message is already acknowledged', () => {
    useAppMock.mockReturnValue({
      ctx: {
        colTypes: { week: 'date', falls: 'number' },
        qualityFlags: [
          { severity: 'WARNING', msg: 'Outcome column has 25% missing values.' },
          { severity: 'WARNING', msg: 'Date column has irregular intervals.' },
        ],
        acknowledgedFlags: [
          { severity: 'WARNING', msg: 'Date column has irregular intervals.' },
        ],
      },
      update: vi.fn(),
      next: vi.fn(),
      prev: vi.fn(),
    })

    render(<DataReview />)

    expect(screen.getByRole('checkbox', { name: /Outcome column has 25% missing values\./i })).not.toBeChecked()
    expect(screen.getByRole('checkbox', { name: /Date column has irregular intervals\./i })).toBeChecked()
  })

  it('renders collection guidance grouped by necessity', () => {
    useAppMock.mockReturnValue({
      ctx: {
        colTypes: { month: 'Date', falls: 'Number' },
        qualityFlags: [],
        acknowledgedFlags: [],
        collectionRecs: [
          { id: 'missing-denominator', title: 'Denominator column needed', why: 'Rate calc requires it', severity: 'important', necessity: 'required' },
          { id: 'no-balancing-measure', title: 'Consider a balancing measure', why: 'Detect harm elsewhere', severity: 'info', necessity: 'optional' },
        ],
      },
      update: vi.fn(),
      next: vi.fn(),
      prev: vi.fn(),
    })

    render(<DataReview />)

    expect(screen.getByText('Required to run an analysis')).toBeInTheDocument()
    expect(screen.getByText('Denominator column needed')).toBeInTheDocument()
    expect(screen.getByText('Optional future improvement')).toBeInTheDocument()
    expect(screen.getByText('Consider a balancing measure')).toBeInTheDocument()
  })

  it('renders a role selector per column seeded from candidate roles', () => {
    useAppMock.mockReturnValue({
      ctx: {
        colTypes: { month: 'Date', falls: 'Number', patient_days: 'Number' },
        qualityFlags: [],
        acknowledgedFlags: [],
        profile: {
          candidate_roles: {
            date: ['month'],
            outcome: ['falls'],
            denominator: ['patient_days'],
          },
        },
      },
      update: vi.fn(),
      next: vi.fn(),
      prev: vi.fn(),
    })

    render(<DataReview />)

    expect(screen.getByLabelText('Role for falls')).toHaveValue('outcome')
    expect(screen.getByLabelText('Role for patient_days')).toHaveValue('denominator')
  })

  it('does not affect canContinue when collection guidance is present', () => {
    const nextMock = vi.fn()
    useAppMock.mockReturnValue({
      ctx: {
        colTypes: { falls: 'Number' },
        qualityFlags: [],
        acknowledgedFlags: [],
        collectionRecs: [
          { id: 'missing-denominator', title: 'Denominator column needed', why: 'Rate calc requires it', severity: 'important', necessity: 'required' },
        ],
      },
      update: vi.fn(),
      next: nextMock,
      prev: vi.fn(),
    })

    render(<DataReview />)

    const continueBtn = screen.getByRole('button', { name: /Continue to Analysis Selection/i })
    expect(continueBtn).toBeEnabled()
  })
})
