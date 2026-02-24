// Bala Travel Agent — Main application component
// Routes between login gate and search page

import { useState, useEffect } from 'react'
import AuthGate from './components/AuthGate'
import SearchPage from './components/SearchPage'

function App() {
  const [token, setToken] = useState<string | null>(null)

  useEffect(() => {
    // Check for existing session token
    const saved = localStorage.getItem('bta_token')
    if (saved) setToken(saved)
  }, [])

  const handleLogin = (newToken: string) => {
    localStorage.setItem('bta_token', newToken)
    setToken(newToken)
  }

  const handleLogout = () => {
    localStorage.removeItem('bta_token')
    setToken(null)
  }

  if (!token) {
    return <AuthGate onLogin={handleLogin} />
  }

  return <SearchPage token={token} onLogout={handleLogout} />
}

export default App
