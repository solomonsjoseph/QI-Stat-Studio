import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Upload from './Upload'

const { apiMock, useAppMock } = vi.hoisted(() => ({
  apiMock: {
    upload: vi.fn(),
    confirmColTypes: vi.fn(),
  },
  useAppMock: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../App', () => ({ useApp: useAppMock }))

beforeEach(() => {
  apiMock.upload.mockReset()
  apiMock.confirmColTypes.mockReset()
  useAppMock.mockReset()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('Upload', () => {
  it('renders the first five uploaded rows as a data preview table and shows null values as an em dash', async () => {
    const update = vi.fn()
    const user = userEvent.setup()
    const file = new File(['encounter_date,a1c_value,notes\n2026-01-01,8.2,baseline'], 'diabetes.csv', { type: 'text/csv' })
    apiMock.upload.mockResolvedValue({
      id: 42,
      row_count: 5,
      col_types: { encounter_date: 'Date', a1c_value: 'Number', notes: 'Category' },
      missing_pct: { encounter_date: 0, a1c_value: 20, notes: 20 },
      quality_flags: [],
      preview_rows: [
        { encounter_date: '2026-01-01T00:00:00', a1c_value: 8.2, notes: 'baseline' },
        { encounter_date: '2026-02-01T00:00:00', a1c_value: null, notes: 'missing lab' },
        { encounter_date: '2026-03-01T00:00:00', a1c_value: 7.9, notes: null },
        { encounter_date: '2026-04-01T00:00:00', a1c_value: 7.7, notes: 'follow-up' },
        { encounter_date: '2026-05-01T00:00:00', a1c_value: 7.5, notes: 'sustained' },
      ],
    })
    useAppMock.mockReturnValue({
      ctx: { projectId: 12 },
      update,
      next: vi.fn(),
      prev: vi.fn(),
    })

    render(<Upload />)

    await user.upload(screen.getByLabelText('CSV or Excel file'), file)
    await user.click(screen.getByRole('button', { name: 'Upload CSV/Excel' }))

    expect(await screen.findByText('Data preview (first 5 rows)')).toBeInTheDocument()
    const preview = screen.getAllByRole('table').find(table => (
      within(table).queryByRole('columnheader', { name: 'encounter_date' }) &&
      within(table).queryByText('2026-01-01T00:00:00')
    ))
    expect(preview).toBeTruthy()
    expect(within(preview).getByRole('columnheader', { name: 'encounter_date' })).toBeInTheDocument()
    expect(within(preview).getByRole('columnheader', { name: 'a1c_value' })).toBeInTheDocument()
    expect(within(preview).getByRole('columnheader', { name: 'notes' })).toBeInTheDocument()
    expect(within(preview).getByText('2026-01-01T00:00:00')).toBeInTheDocument()
    expect(within(preview).getByText('8.2')).toBeInTheDocument()
    expect(within(preview).getAllByText('—')).toHaveLength(2)
    expect(apiMock.upload).toHaveBeenCalledWith(12, file)
    expect(update).toHaveBeenCalledWith({ uploadId: 42 })
  })
})
