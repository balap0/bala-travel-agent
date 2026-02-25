// Main search page — SSE streaming with progressive agent thinking timeline

import { useState, useRef, useCallback } from 'react'
import { searchWithSSE, api, SearchResponse, RouteAnalysis } from '../api/client'
import SearchInput from './SearchInput'
import AgentThinking, { ThinkingStep } from './AgentThinking'
import ResultsList from './ResultsList'
import RefineInput from './RefineInput'
import PreferencesPanel from './PreferencesPanel'

interface SearchPageProps {
  token: string
  onLogout: () => void
}

type ViewState = 'idle' | 'searching' | 'results' | 'error'

export default function SearchPage({ token, onLogout }: SearchPageProps) {
  const [viewState, setViewState] = useState<ViewState>('idle')
  const [isRefining, setIsRefining] = useState(false)
  const [searchResponse, setSearchResponse] = useState<SearchResponse | null>(null)
  const [routeAnalysis, setRouteAnalysis] = useState<RouteAnalysis | undefined>()
  const [thinkingSteps, setThinkingSteps] = useState<ThinkingStep[]>([])
  const [error, setError] = useState('')
  const [prefsOpen, setPrefsOpen] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const addStep = useCallback((type: ThinkingStep['type'], message: string) => {
    setThinkingSteps(prev => [...prev, { type, message, timestamp: Date.now() }])
  }, [])

  const handleSearch = useCallback((query: string) => {
    // Abort any in-flight search
    abortRef.current?.abort()

    setError('')
    setViewState('searching')
    setThinkingSteps([])
    setSearchResponse(null)
    setRouteAnalysis(undefined)

    const controller = searchWithSSE(query, token, {
      onThinking: (msg) => addStep('thinking', msg),
      onStrategy: (msg) => addStep('strategy', msg),
      onClarify: (msg) => addStep('clarify', msg),
      onSearching: (msg) => addStep('searching', msg),
      onRanking: (msg) => addStep('ranking', msg),
      onResults: (response) => {
        setSearchResponse(response)
        if (response.route_analysis) {
          setRouteAnalysis(response.route_analysis)
        }
        setViewState('results')
      },
      onError: (err) => {
        if (err.includes('401')) {
          onLogout()
          return
        }
        setError(err)
        setViewState('error')
      },
    }, searchResponse?.session_id)

    abortRef.current = controller
  }, [token, searchResponse?.session_id, onLogout, addStep])

  const handleRefine = async (message: string) => {
    if (!searchResponse) return
    setIsRefining(true)

    try {
      const response = await api.refine(searchResponse.session_id, message, token)
      if (response.results) {
        setSearchResponse({
          ...searchResponse,
          results: response.results,
          parsed_query: response.updated_query || searchResponse.parsed_query,
        })
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Refinement failed')
      setViewState('error')
    } finally {
      setIsRefining(false)
    }
  }

  const handleInteraction = useCallback((action: string, flightRank: number, flightId: string) => {
    api.logInteraction({
      session_id: searchResponse?.session_id,
      action,
      flight_rank: flightRank,
      flight_id: flightId,
    }, token)
  }, [searchResponse?.session_id, token])

  const isSearching = viewState === 'searching'

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b px-4 py-3 flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900">Bala Travel Agent</h1>
        <div className="flex items-center gap-4">
          <button
            onClick={() => setPrefsOpen(true)}
            className="text-sm text-gray-500 hover:text-gray-700 transition flex items-center gap-1"
            title="My Preferences"
          >
            Preferences
          </button>
          <button
            onClick={onLogout}
            className="text-sm text-gray-500 hover:text-gray-700 transition"
          >
            Logout
          </button>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-3xl mx-auto px-4 py-8">
        {/* Search input — always visible */}
        <SearchInput
          onSearch={handleSearch}
          loading={isSearching || isRefining}
        />

        {/* Agent thinking timeline — visible during and after search */}
        <AgentThinking
          steps={thinkingSteps}
          isActive={isSearching}
          routeAnalysis={routeAnalysis}
        />

        {/* Error */}
        {error && (
          <div className="mt-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
            {error}
          </div>
        )}

        {/* Results */}
        {viewState === 'results' && searchResponse && (
          <>
            <div className="mt-6 text-sm text-gray-500">
              Found {searchResponse.total_options_found} options from{' '}
              {searchResponse.sources_used.join(' + ')} in{' '}
              {searchResponse.search_duration_seconds}s
            </div>

            {/* Parsed query summary */}
            {searchResponse.parsed_query && (
              <div className="mt-4 p-4 bg-gray-50 border border-gray-200 rounded-lg">
                <p className="text-sm font-medium text-gray-600 mb-2">Search parameters:</p>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div><span className="text-gray-500">From:</span> {searchResponse.parsed_query.origin}</div>
                  <div><span className="text-gray-500">To:</span> {searchResponse.parsed_query.destination}</div>
                  <div><span className="text-gray-500">Date:</span> {searchResponse.parsed_query.departure_date}</div>
                  <div><span className="text-gray-500">Class:</span> {searchResponse.parsed_query.cabin_class}</div>
                  <div><span className="text-gray-500">Max stops:</span> {searchResponse.parsed_query.max_stops}</div>
                  {searchResponse.parsed_query.preferences.length > 0 && (
                    <div className="col-span-2">
                      <span className="text-gray-500">Priorities:</span>{' '}
                      {searchResponse.parsed_query.preferences.map(p => p.replace('_', ' ')).join(', ')}
                    </div>
                  )}
                </div>
              </div>
            )}

            <ResultsList results={searchResponse.results} onInteraction={handleInteraction} />

            <RefineInput onRefine={handleRefine} loading={isRefining} />
          </>
        )}

        {/* Idle state */}
        {viewState === 'idle' && (
          <div className="mt-12 text-center text-gray-400">
            <p className="text-lg">Type your travel request above</p>
            <p className="mt-2 text-sm">
              Example: "I want a flight from Bangalore to Libreville around Sep 4th,
              business class, minimize travel time"
            </p>
          </div>
        )}
      </main>

      {/* Preferences panel */}
      <PreferencesPanel
        token={token}
        isOpen={prefsOpen}
        onClose={() => setPrefsOpen(false)}
      />
    </div>
  )
}
