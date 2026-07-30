import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    me: vi.fn(),
    resumeProject: vi.fn(),
    logout: vi.fn(),
    listProjects: vi.fn(),
    createProject: vi.fn(),
    deleteProject: vi.fn(),
  },
}))

vi.mock('./api', () => ({ api: apiMock }))
vi.mock('./screens/Auth', () => ({ default: () => <h1>Auth screen</h1> }))
vi.mock('./screens/ProjectDescription', () => ({ default: () => <h1>Screen description</h1> }))
vi.mock('./screens/IntakeQuestions', () => ({ default: () => <h1>Screen intake</h1> }))
vi.mock('./screens/Upload', () => ({ default: () => <h1>Screen upload</h1> }))
vi.mock('./screens/DataReview', () => ({ default: () => <h1>Screen review</h1> }))
vi.mock('./screens/AnalysisSelection', () => ({ default: () => <h1>Screen analysis</h1> }))
vi.mock('./screens/ParameterSelection', () => ({ default: () => <h1>Screen params</h1> }))
vi.mock('./screens/Results', () => ({ default: () => <h1>Screen results</h1> }))
vi.mock('./screens/DownloadShare', () => ({ default: () => <h1>Screen download</h1> }))
vi.mock('./screens/Settings', () => ({ default: () => <h1>Screen settings</h1> }))
vi.mock('./screens/MentorView', () => ({ default: ({ token }) => <h1>Mentor {token}</h1> }))

function resumePayload({ id, currentScreen }) {
  return {
    project: { id, title: `Project ${id}`, description: 'A resident QI project' },
    answers: { q1: 'Aim statement' },
    latest_upload: { id: 20, col_types: { week: 'date' }, column_map: {}, quality_flags: [], acknowledged_flags: [] },
    latest_run: { id: 30, template: 'run_chart', parameters: { date_col: 'week' }, result: { result_summary: 'Improved.', interpretation: 'Server interpretation.' } },
    latest_share: { token: 'mentor-token' },
    current_screen: currentScreen,
  }
}

beforeEach(() => {
  apiMock.me.mockResolvedValue({ email: 'resident@example.test' })
  apiMock.resumeProject.mockReset()
  apiMock.logout.mockReset()
  apiMock.listProjects.mockResolvedValue([])
  apiMock.createProject.mockReset()
  apiMock.deleteProject.mockReset()
  window.localStorage.clear()
  window.history.pushState({}, '', '/')
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  window.localStorage.clear()
  window.history.pushState({}, '', '/')
})

describe('App resume hydration', () => {
  it('hydrates the project id from the /app URL and lets the URL screen override the backend resume screen', async () => {
    window.localStorage.setItem('qiss:lastProjectId', '99')
    window.history.pushState({}, '', '/app/42/results')
    apiMock.resumeProject.mockResolvedValue(resumePayload({ id: 42, currentScreen: 'edit' }))

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Screen results' })).toBeInTheDocument()
    expect(apiMock.resumeProject).toHaveBeenCalledWith(42)
    expect(window.localStorage.getItem('qiss:lastProjectId')).toBe('42')
    expect(window.location.pathname).toBe('/app/42/results')
  })

  it('hydrates from the stored project id and opens the backend resume screen when no /app route is present', async () => {
    window.localStorage.setItem('qiss:lastProjectId', '99')
    apiMock.resumeProject.mockResolvedValue(resumePayload({ id: 99, currentScreen: 'edit' }))

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Edit & Review' })).toBeInTheDocument()
    expect(apiMock.resumeProject).toHaveBeenCalledWith(99)
    expect(window.location.pathname).toBe('/app/99/edit')
  })

  it('maps the server interpretation from the latest run into hydrated context for edit review', async () => {
    window.localStorage.setItem('qiss:lastProjectId', '44')
    apiMock.resumeProject.mockResolvedValue(resumePayload({ id: 44, currentScreen: 'edit' }))

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Edit & Review' })).toBeInTheDocument()
    expect(screen.getByLabelText(/interpretation/i)).toHaveValue('Server interpretation.')
    await waitFor(() => {
      expect(window.location.pathname).toBe('/app/44/edit')
    })
  })

  it('resumes a project from the landing list through the server resume endpoint and opens the returned screen', async () => {
    apiMock.listProjects.mockResolvedValue([{ id: 12, title: 'Door-to-balloon time', description: 'Reduce delays', status: 'draft' }])
    apiMock.resumeProject.mockResolvedValue(resumePayload({ id: 12, currentScreen: 'download' }))
    const user = userEvent.setup()

    render(<App />)

    await user.click(await screen.findByRole('button', { name: /resume/i }))

    expect(apiMock.resumeProject).toHaveBeenCalledWith(12)
    expect(await screen.findByRole('heading', { name: 'Screen download' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/app/12/download')
  })

  it('enables resumed wizard steps through review and keeps future steps disabled', async () => {
    window.localStorage.setItem('qiss:lastProjectId', '77')
    apiMock.resumeProject.mockResolvedValue(resumePayload({ id: 77, currentScreen: 'review' }))
    const user = userEvent.setup()

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Screen review' })).toBeInTheDocument()
    for (const label of ['Description', 'Intake', 'Upload', /Review/]) {
      expect(screen.getByRole('button', { name: label })).toBeEnabled()
    }
    expect(screen.getByRole('button', { name: /Results/ })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Upload' }))

    expect(await screen.findByRole('heading', { name: 'Screen upload' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/app/77/upload')
  })

  it('lets the landing project list recover from a load failure', async () => {
    apiMock.listProjects
      .mockRejectedValueOnce(Object.assign(new Error('Could not load projects'), { requestId: 'req-projects-2' }))
      .mockResolvedValueOnce([{ id: 21, title: 'Sepsis huddle follow-up', description: '', status: 'draft' }])
    const user = userEvent.setup()

    render(<App />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load projects (Request ID: req-projects-2)')
    await user.click(screen.getByRole('button', { name: 'Retry' }))

    expect(await screen.findByRole('heading', { name: 'Sepsis huddle follow-up' })).toBeInTheDocument()
    expect(apiMock.listProjects).toHaveBeenCalledTimes(2)
    expect(apiMock.listProjects).toHaveBeenLastCalledWith({ limit: 25, order: 'created_desc' })
  })
})
