import React from 'react'
import { useApp } from '../App'
import { api } from '../api'

export default function Landing() {
  const { update, next } = useApp()

  async function start() {
    const project = await api.createProject({ title: 'New QI Project', description: '' })
    update({ projectId: project.id })
    next()
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-6 p-8 text-center">
      <h1 className="text-4xl font-bold text-blue-800">QI Stat Studio</h1>
      <p className="text-gray-600 max-w-md text-lg">
        A guided statistical analysis tool for medical residents conducting quality
        improvement projects at Rutgers IM Clinic.
      </p>
      <button
        onClick={start}
        className="px-8 py-3 bg-blue-700 text-white rounded-lg text-lg font-medium hover:bg-blue-800"
      >
        Start New Project
      </button>
      <button
        onClick={() => api.listProjects().then(ps => ps.length && (update({ projectId: ps[0].id }), next()))}
        className="text-blue-600 underline text-sm"
      >
        Resume existing project
      </button>
    </div>
  )
}
