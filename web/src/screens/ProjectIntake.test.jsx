import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ProjectIntake from './ProjectIntake'
import { AppCtx } from '../App'

const { apiMock } = vi.hoisted(() => ({
  apiMock: { createProjectIntake: vi.fn(), confirmColTypes: vi.fn() },
}))
vi.mock('../api', () => ({ api: apiMock }))

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function renderScreen() {
  const value = { ctx: {}, update: vi.fn(), next: vi.fn(), prev: vi.fn() }
  render(
    <AppCtx.Provider value={value}>
      <ProjectIntake />
    </AppCtx.Provider>,
  )
  return value
}

async function fillForm(user, { file, dictionary } = {}) {
  await user.type(screen.getByLabelText('Project Title'), 'Diabetes care')
  await user.type(screen.getByLabelText('Project Description'), 'Improve A1c control')
  await user.upload(screen.getByLabelText('CSV or Excel dataset'), file || new File(['a,b\n1,2'], 'data.csv', { type: 'text/csv' }))
  await user.upload(screen.getByLabelText('Data dictionary file'), dictionary || new File(['a: col a'], 'dict.txt', { type: 'text/plain' }))
}

describe('ProjectIntake unified form', () => {
  it('creates the project with dataset and dictionary in one step and shows detected column types', async () => {
    apiMock.createProjectIntake.mockResolvedValue({
      project: { id: 5, title: 'Diabetes care', description: 'Improve A1c control' },
      upload: { id: 20, col_types: { a: 'Number', b: 'Number' }, quality_flags: [], preview_rows: [{ a: 1, b: 2 }] },
    })
    const user = userEvent.setup()
    const value = renderScreen()

    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    expect(await screen.findByRole('heading', { name: 'Confirm Column Types' })).toBeInTheDocument()
    expect(apiMock.createProjectIntake).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Diabetes care', description: 'Improve A1c control' }),
    )
    await waitFor(() => {
      expect(value.update).toHaveBeenCalledWith(
        expect.objectContaining({ projectId: 5, uploadId: 20 }),
      )
    })
  })

  it('shows the per-column PHI violation list and blocks continuation when the backend rejects the file', async () => {
    const err = Object.assign(new Error('We found information that may identify a patient. Remove it and upload again.'), {
      fieldErrors: { patient_name: ['Patient Name: "patient_name" looks like a patient name column. Remove it.'] },
    })
    apiMock.createProjectIntake.mockRejectedValue(err)
    const user = userEvent.setup()
    renderScreen()

    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/patient_name/)
    expect(screen.queryByRole('heading', { name: 'Confirm Column Types' })).not.toBeInTheDocument()
  })
})
