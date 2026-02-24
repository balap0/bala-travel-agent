// Conversational refinement input — appears below results

import { useState } from 'react'

interface RefineInputProps {
  onRefine: (message: string) => void
  loading: boolean
}

export default function RefineInput({ onRefine, loading }: RefineInputProps) {
  const [message, setMessage] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (message.trim() && !loading) {
      onRefine(message.trim())
      setMessage('')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-6">
      <div className="bg-white rounded-xl border p-4">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Refine your search
        </label>
        <div className="flex gap-3">
          <input
            type="text"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder='e.g., "What about a day later?" or "Show me economy options"'
            className="flex-1 px-4 py-2 rounded-lg border border-gray-300 focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none transition"
          />
          <button
            type="submit"
            disabled={loading || !message.trim()}
            className="px-5 py-2 bg-brand-600 hover:bg-brand-700 text-white font-medium rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? '...' : 'Refine'}
          </button>
        </div>
      </div>
    </form>
  )
}
