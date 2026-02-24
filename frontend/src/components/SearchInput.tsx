// Natural language search input — the main interface for the app

import { useState } from 'react'

interface SearchInputProps {
  onSearch: (query: string) => void
  loading: boolean
}

export default function SearchInput({ onSearch, loading }: SearchInputProps) {
  const [query, setQuery] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (query.trim() && !loading) {
      onSearch(query.trim())
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <div className="bg-white rounded-xl shadow-sm border p-4">
        <label htmlFor="search" className="block text-sm font-medium text-gray-700 mb-2">
          Where do you want to fly?
        </label>
        <textarea
          id="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder='e.g., "I want a 1 or 2 stop flight from Bangalore to Libreville around Sep 4th. Business class if not too expensive. Minimize travel time."'
          rows={3}
          className="w-full px-4 py-3 rounded-lg border border-gray-300 focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none resize-none transition"
          autoFocus
        />
        <div className="flex items-center justify-between mt-3">
          <span className="text-xs text-gray-400">
            Enter to search, Shift+Enter for new line
          </span>
          <button
            type="submit"
            disabled={loading || !query.trim()}
            className="px-6 py-2 bg-brand-600 hover:bg-brand-700 text-white font-medium rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {loading ? (
              <>
                <span className="animate-spin">⏳</span>
                Searching...
              </>
            ) : (
              'Search'
            )}
          </button>
        </div>
      </div>
    </form>
  )
}
