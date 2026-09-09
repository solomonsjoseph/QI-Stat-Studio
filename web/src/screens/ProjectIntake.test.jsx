import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ProjectIntake from './ProjectIntake'
import { AppCtx } from '../App'

const { apiMock } = vi.hoisted(() => ({
  apiMock: { createProjectIntake: vi.fn() },
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

const LONG_DESC = 'We are trying to improve diabetic control and reduce A1c levels across all adult patients.'

async function fillForm(user, { file, dictionary, deadline, omitDictionary = false } = {}) {
  await user.type(screen.getByLabelText(/Project Title/), 'Diabetes care')
  await user.type(screen.getByLabelText(/Project Description/), LONG_DESC)
  if (deadline) {
    await user.type(screen.getByLabelText(/Target Completion/), deadline)
  }
  await user.upload(screen.getByLabelText(/CSV or Excel dataset/), file || new File(['a,b\n1,2'], 'data.csv', { type: 'text/csv' }))
  if (!omitDictionary) {
    await user.upload(screen.getByLabelText(/Data dictionary file/), dictionary || new File(['a: col a'], 'dict.txt', { type: 'text/plain' }))
  }
}

describe('ProjectIntake unified form', () => {
  it('creates the project with dataset and advances to next screen', async () => {
    apiMock.createProjectIntake.mockResolvedValue({
      project: { id: 5, title: 'Diabetes care', description: LONG_DESC, deadline: null },
      upload: { id: 20, col_types: { a: 'Number', b: 'Number' }, quality_flags: [], preview_rows: [{ a: 1, b: 2 }], dataset_profile: {} },
    })
    const user = userEvent.setup()
    const value = renderScreen()

    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    await waitFor(() => {
      expect(apiMock.createProjectIntake).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'Diabetes care', description: LONG_DESC }),
      )
      expect(value.update).toHaveBeenCalledWith(
        expect.objectContaining({ projectId: 5, uploadId: 20 }),
      )
      expect(value.next).toHaveBeenCalled()
    })
  })

  it('allows omitting dictionary and sends null', async () => {
    apiMock.createProjectIntake.mockResolvedValue({
      project: { id: 5, title: 'Diabetes care', description: LONG_DESC },
      upload: { id: 20, col_types: { a: 'Number' } },
    })
    const user = userEvent.setup()
    const value = renderScreen()

    await fillForm(user, { omitDictionary: true })
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    await waitFor(() => {
      expect(apiMock.createProjectIntake).toHaveBeenCalledWith(
        expect.objectContaining({ dictionary: null }),
      )
      expect(value.next).toHaveBeenCalled()
    })
  })

  it('passes deadline to createProjectIntake when provided', async () => {
    apiMock.createProjectIntake.mockResolvedValue({
      project: { id: 5, title: 'Diabetes care', description: LONG_DESC, deadline: '2026-10-15' },
      upload: { id: 20, col_types: {} },
    })
    const user = userEvent.setup()
    const value = renderScreen()

    await fillForm(user, { deadline: '2026-10-15', omitDictionary: true })
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    await waitFor(() => {
      expect(apiMock.createProjectIntake).toHaveBeenCalledWith(
        expect.objectContaining({ deadline: '2026-10-15' }),
      )
      expect(value.next).toHaveBeenCalled()
    })
  })

  it('shows the PHI violation notice, error sentence, and replace file control', async () => {
    const err = Object.assign(new Error('We found information that may identify a patient.'), {
      fieldErrors: {
        patient_name: ['Patient Name: "patient_name" looks like a patient name column. Remove it.'],
        dictionary: ['Patient Name: Document contains a patient name. Remove it.'],
      },
    })
    apiMock.createProjectIntake.mockRejectedValue(err)
    const user = userEvent.setup()
    renderScreen()

    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/We can't process this file because it may contain patient-identifying information/)
    expect(screen.getByRole('alert')).toHaveTextContent(/patient_name/)
    expect(screen.getByRole('alert')).toHaveTextContent(/Data Dictionary/)

    const replaceBtn = screen.getByRole('button', { name: 'Remove file and choose another' })
    expect(replaceBtn).toBeInTheDocument()
    await user.click(replaceBtn)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
