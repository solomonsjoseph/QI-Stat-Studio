import React, { createContext, useContext, useState, useEffect } from 'react'
import Landing from './screens/Landing'
import ProjectDescription from './screens/ProjectDescription'
import IntakeQuestions from './screens/IntakeQuestions'
import Upload from './screens/Upload'
import DataReview from './screens/DataReview'
import AnalysisSelection from './screens/AnalysisSelection'
import ParameterSelection from './screens/ParameterSelection'
import Results from './screens/Results'
import EditReview from './screens/EditReview'
import DownloadShare from './screens/DownloadShare'
import Settings from './screens/Settings'
import MentorView from './screens/MentorView'

export const AppCtx = createContext(null)
export const useApp = () => useContext(AppCtx)

const SCREENS = [
  'landing', 'description', 'intake', 'upload', 'review',
  'analysis', 'params', 'results', 'edit', 'download',
]

const COMPONENTS = {
  landing: Landing,
  description: ProjectDescription,
  intake: IntakeQuestions,
  upload: Upload,
  review: DataReview,
  analysis: AnalysisSelection,
  params: ParameterSelection,
  results: Results,
  edit: EditReview,
  download: DownloadShare,
  settings: Settings,
}

export default function App() {
  const [screen, setScreen] = useState('landing')
  const [ctx, setCtx] = useState({})

  // Mentor URL detection: /mentor/<token>
  const path = window.location.pathname
  if (path.startsWith('/mentor/')) {
    const token = path.split('/mentor/')[1]
    return <MentorView token={token} />
  }

  const update = (patch) => setCtx(c => ({ ...c, ...patch }))
  const next = () => {
    const idx = SCREENS.indexOf(screen)
    if (idx < SCREENS.length - 1) setScreen(SCREENS[idx + 1])
  }
  const goTo = (s) => setScreen(s)

  const Screen = COMPONENTS[screen] || Landing

  return (
    <AppCtx.Provider value={{ ctx, update, next, goTo, screen }}>
      <div className="min-h-screen bg-gray-50">
        {/* Gear icon — visible on all screens except landing */}
        {screen !== 'landing' && (
          <button
            onClick={() => goTo('settings')}
            className="fixed top-3 right-4 text-gray-400 hover:text-gray-700 text-xl"
            title="Settings"
          >
            ⚙
          </button>
        )}
        <Screen />
      </div>
    </AppCtx.Provider>
  )
}
