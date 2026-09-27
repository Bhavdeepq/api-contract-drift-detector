import { useEffect, useState } from 'react'
import { checkBackendHealth } from './services/api'

export default function App() {
  const [status, setStatus] = useState('Checking backend…')

  useEffect(() => {
    checkBackendHealth()
      .then(() => setStatus('Connected to backend'))
      .catch(() => setStatus('Backend unavailable'))
  }, [])

  return (
    <main>
      <h1>API Contract Drift Detector</h1>
      <p>Foundation for finding drift between OpenAPI contracts and implementations.</p>
      <p aria-live="polite"><strong>Status:</strong> {status}</p>
    </main>
  )
}
