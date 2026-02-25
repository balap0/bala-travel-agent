// Unified input component — adapts based on conversation state
// Replaces SearchInput (initial query) + RefineInput (post-results refinement)

import { useState, useRef, useEffect } from 'react'

interface ConversationInputProps {
  agentState: 'idle' | 'thinking' | 'waiting_for_input' | 'ready'
  hasResults: boolean
  onSubmit: (message: string) => void
  loading: boolean
}

export default function ConversationInput({ agentState, hasResults, onSubmit, loading }: ConversationInputProps) {
  const [text, setText] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Determine placeholder based on context
  let placeholder = 'Where do you want to fly?'
  let label = 'Where do you want to fly?'

  if (hasResults) {
    placeholder = 'e.g., "Show me cheaper options" or "What about a day later?"'
    label = 'Refine your search'
  }
  if (agentState === 'idle' && !hasResults) {
    placeholder = 'e.g., "I want a 1 or 2 stop flight from Bangalore to Libreville around Sep 4th. Business class if not too expensive. Minimize travel time."'
  }

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`
    }
  }, [text])

  const handleSubmit = () => {
    if (!text.trim() || loading) return
    onSubmit(text.trim())
    setText('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  // Don't show when agent is waiting for input (question has its own reply box)
  if (agentState === 'waiting_for_input') return null

  const isDisabled = loading || agentState === 'thinking'

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
      <label className="block text-sm font-medium text-gray-700 mb-2">{label}</label>
      <textarea
        ref={textareaRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        rows={hasResults ? 1 : 3}
        disabled={isDisabled}
        className="w-full border border-gray-200 rounded-lg px-4 py-3 text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent resize-none disabled:opacity-50"
      />
      <div className="flex items-center justify-between mt-2">
        <span className="text-xs text-gray-400">
          Enter to {hasResults ? 'refine' : 'search'}, Shift+Enter for new line
        </span>
        <button
          onClick={handleSubmit}
          disabled={isDisabled || !text.trim()}
          className="px-5 py-2 bg-brand-500 text-white font-medium rounded-lg hover:bg-brand-600 disabled:opacity-50 disabled:cursor-not-allowed transition flex items-center gap-2"
        >
          {loading ? (
            <>
              <span className="animate-pulse">🔍</span>
              {hasResults ? 'Refining...' : 'Searching...'}
            </>
          ) : (
            hasResults ? 'Refine' : 'Search'
          )}
        </button>
      </div>
    </div>
  )
}
