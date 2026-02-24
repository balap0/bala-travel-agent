// Main search page — contains search input, parsing indicator, results, and refinement

import { useState } from 'react'
import { api, SearchResponse } from '../api/client'
import SearchInput from './SearchInput'
import ParsingIndicator from './ParsingIndicator'
import ResultsList from './ResultsList'
import RefineInput from './RefineInput'

interface SearchPageProps {
  token: string
  onLogout: () => void
}

type ViewState = 'idle' | 'searching' | 'parsing' | 'results' | 'refining' | 'error'

export default function SearchPage({ token, onLogout }: SearchPageProps) {
  const [viewState, setViewState] = useState<ViewState>('idle')
  const [searchResponse, setSearchResponse] = useState<SearchResponse | null>(null)
  const [error, setError] = useState('')

  const handleSearch = async (query: string) => {
    setError('')
    setViewState('searching')

    try {
      const response = await api.search(query, token, searchResponse?.session_id)
      setSearchResponse(response)
      setViewState('results')
    } catch (err) {
      if (err instanceof Error && err.message.includes('401')) {
        onLogout()
        return
      }
      setError(err instanceof Error ? err.message : 'Search failed')
      setViewState('error')
    }
  }

  const handleRefine = async (message: string) => {
    if (!searchResponse) return
    setViewState('refining')

    try {
      const response = await api.refine(searchResponse.session_id, message, token)
      if (response.results) {
        setSearchResponse({
          ...searchResponse,
          results: response.results,
          parsed_query: response.updated_query || searchResponse.parsed_query,
        })
      }
      setViewState('results')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Refinement failed')
      setViewState('error')
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b px-4 py-3 flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900">✈️ Bala Travel Agent</h1>
        <button
          onClick={onLogout}
          className="text-sm text-gray-500 hover:text-gray-700 transition"
        >
          Logout
        </button>
      </header>

      {/* Main content */}
      <main className="max-w-3xl mx-auto px-4 py-8">
        {/* Search input — always visible */}
        <SearchInput
          onSearch={handleSearch}
          loading={viewState === 'searching' || viewState === 'refining'}
        />

        {/* Status messages */}
        {viewState === 'searching' && (
          <ParsingIndicator query="" />
        )}

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

            {searchResponse.parsed_query && (
              <ParsingIndicator
                query={searchResponse.parsed_query.raw_query}
                parsed={searchResponse.parsed_query}
              />
            )}

            <ResultsList results={searchResponse.results} />

            <RefineInput onRefine={handleRefine} loading={viewState === 'refining'} />
          </>
        )}

        {/* Idle state */}
        {viewState === 'idle' && (
          <div className="mt-12 text-center text-gray-400">
            <p className="text-lg">Type your travel request above</p>
            <p className="mt-2 text-sm">
              Example: "I want a flight from Bangalore to Nairobi around Sep 4th,
              business class, minimize travel time"
            </p>
          </div>
        )}
      </main>
    </div>
  )
}
