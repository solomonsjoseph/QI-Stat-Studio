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
    saveProjectEdit: vi.fn(),
    updateProject: vi.fn(),
  },
}))

vi.mock('./api', () => ({ api: apiMock }))
vi.mock('./screens/Auth', () => ({ default: () => <h1>Auth screen</h1> }))
vi.mock('./screens/ProjectIntake', () => ({ default: () => <h1>Screen description</h1> }))
vi.mock('./screens/ClarificationStage', () => ({ default: () => <h1>Screen clarify</h1> }))
vi.mock('./screens/DataReview', () => ({ default: () => <h1>Screen review</h1> }))
vi.mock('./screens/AnalysisPlanStage', () => ({ default: () => <h1>Screen analysis</h1> }))
vi.mock('./screens/Results', () => ({ default: () => <h1>Screen results</h1> }))
vi.mock('./screens/DownloadShare', () => ({ default: () => <h1>Screen download</h1> }))
vi.mock('./screens/Settings', () => ({ default: () => <h1>Screen settings</h1> }))
vi.mock('./screens/MentorView', () => ({ default: ({ token }) => <h1>Mentor {token}</h1> }))

function resumePayload({ id, currentScreen }) {
  return {
    project: { id, title: `Project ${id}`, description: 'A resident QI project' },
    latest_upload: { id: 20, col_types: { week: 'date' }, column_map: {}, quality_flags: [], acknowledged_flags: [] },
    latest_run: { id: 30, template: 'run_chart', parameters: { date_col: 'week' }, result: { result_summary: 'Improved.', interpretation: 'Server interpretation.' } },
    runs: [{ run_id: 30, template: 'run_chart', result_summary: 'Improved.', ai_interpretation: 'Server interpretation.', caption: '' }],
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
  apiMock.saveProjectEdit.mockReset().mockResolvedValue({})
  apiMock.updateProject.mockReset().mockResolvedValue({})
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
    for (const label of ['Project Intake', 'AI Clarification', /Review/]) {
      expect(screen.getByRole('button', { name: label })).toBeEnabled()
    }
    expect(screen.getByRole('button', { name: /Results/ })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'AI Clarification' }))

    expect(await screen.findByRole('heading', { name: 'Screen clarify' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/app/77/clarify')
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

  it('does not leak a prior project\'s locally-edited fields into a resumed project through applyResume', async () => {
    window.localStorage.setItem('qiss:lastProjectId', '44')
    apiMock.resumeProject
      .mockResolvedValueOnce(resumePayload({ id: 44, currentScreen: 'edit' }))
      .mockResolvedValueOnce(resumePayload({ id: 55, currentScreen: 'edit' }))
    apiMock.listProjects.mockResolvedValue([{ id: 55, title: 'Project 55', description: '', status: 'draft' }])
    const user = userEvent.setup()

    render(<App />)

    // Project 44 hydrates into Edit & Review with the server interpretation, then
    // the resident edits it locally (ctx.editedInterp), a field ctxFromResume never sets.
    expect(await screen.findByRole('heading', { name: 'Edit & Review' })).toBeInTheDocument()
    expect(screen.getByLabelText(/interpretation/i)).toHaveValue('Server interpretation.')
    await user.clear(screen.getByLabelText(/interpretation/i))
    await user.type(screen.getByLabelText(/interpretation/i), 'Project 44 local edit that must not leak.')
    await user.click(screen.getByRole('button', { name: /save & continue/i }))
    expect(await screen.findByRole('heading', { name: 'Screen download' })).toBeInTheDocument()

    // Navigate to landing and resume a different project (55) through applyResume.
    await user.click(screen.getByRole('button', { name: 'QI Stat Studio' }))
    await user.click(await screen.findByRole('button', { name: /resume/i }))

    // Project 55's Edit & Review must show its own server interpretation, not project
    // 44's leftover ctx.editedInterp: applyResume must fully replace ctx, not merge onto it.
    expect(await screen.findByRole('heading', { name: 'Edit & Review' })).toBeInTheDocument()
    const interpField = screen.getByLabelText(/interpretation/i)
    expect(interpField).toHaveValue('Server interpretation.')
    expect(interpField).not.toHaveValue('Project 44 local edit that must not leak.')
  })
})
