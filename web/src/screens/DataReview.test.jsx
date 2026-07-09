import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import DataReview from './DataReview'

const { apiMock, useAppMock } = vi.hoisted(() => ({
  apiMock: {
    saveAcknowledgedFlags: vi.fn(),
  },
  useAppMock: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../App', () => ({ useApp: useAppMock }))

beforeEach(() => {
  apiMock.saveAcknowledgedFlags.mockReset()
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
})
