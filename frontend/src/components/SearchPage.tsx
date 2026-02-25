// Main search page — conversational interface with SSE streaming
// The agent and user communicate through a chat thread with embedded flight results

import { useState, useRef, useCallback } from 'react'
import { searchWithSSE, replyToAgentSSE, refineWithSSE, api, SearchResponse, SSECallbacks } from '../api/client'
import ChatThread, { ConversationMessage } from './ChatThread'
import ConversationInput from './ConversationInput'
import PreferencesPanel from './PreferencesPanel'

interface SearchPageProps {
  token: string
  onLogout: () => void
}

const APP_VERSION = '3.0.0'

type AgentState = 'idle' | 'thinking' | 'waiting_for_input' | 'ready'

let msgCounter = 0
function nextMsgId() { return `msg_${++msgCounter}_${Date.now()}` }

export default function SearchPage({ token, onLogout }: SearchPageProps) {
  const [messages, setMessages] = useState<ConversationMessage[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [agentState, setAgentState] = useState<AgentState>('idle')
  const [latestResults, setLatestResults] = useState<SearchResponse | null>(null)
  const [error, setError] = useState('')
  const [prefsOpen, setPrefsOpen] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  // Helper to append a message to the conversation
  const addMessage = useCallback((msg: Omit<ConversationMessage, 'id' | 'timestamp'>) => {
    setMessages(prev => [...prev, { ...msg, id: nextMsgId(), timestamp: Date.now() }])
  }, [])

  // Mark the last question as answered
  const markQuestionAnswered = useCallback((answer: string) => {
    setMessages(prev => prev.map(m =>
      m.type === 'question' && !m.answered
        ? { ...m, answered: true, answer }
        : m
    ))
  }, [])

  // Build SSE callbacks that feed into the conversation
  const makeCallbacks = useCallback((): SSECallbacks => ({
    onThinking: (msg) => addMessage({ role: 'agent', type: 'thinking', content: msg }),
    onStrategy: (msg) => addMessage({ role: 'agent', type: 'strategy', content: msg }),
    onClarify: (question) => addMessage({
      role: 'agent', type: 'question', content: question,
      questionId: `q_${Date.now()}`,
    }),
    onSearching: (msg) => addMessage({ role: 'agent', type: 'searching', content: msg }),
    onRanking: (msg) => addMessage({ role: 'agent', type: 'ranking', content: msg }),
    onResults: (response) => {
      addMessage({
        role: 'agent', type: 'results',
        content: `Found ${response.total_options_found} options`,
        searchResponse: response,
      })
      setLatestResults(response)
      setSessionId(response.session_id)
      setAgentState('ready')
    },
    onWaitingForInput: (data) => {
      setSessionId(data.session_id)
      setAgentState('waiting_for_input')
    },
    onError: (err) => {
      if (err.includes('401')) {
        onLogout()
        return
      }
      // Friendly error messages for common issues
      if (err.includes('529') || err.includes('overloaded')) {
        setError('The AI service is temporarily overloaded. Please try again in a moment.')
      } else if (err.includes('timeout') || err.includes('Timeout')) {
        setError('The search timed out. Please try again.')
      } else {
        setError(err)
      }
      setAgentState('ready')
    },
  }), [addMessage, onLogout])

  // Initial search — clears previous conversation if starting fresh
  const handleSearch = useCallback((query: string) => {
    abortRef.current?.abort()
    setError('')
    setAgentState('thinking')
    setLatestResults(null)

    // If no session or previous error, start fresh conversation
    if (!sessionId || error) {
      setMessages([])
      setSessionId(null)
    }

    // Add user message to conversation
    addMessage({ role: 'user', type: 'text', content: query })

    const controller = searchWithSSE(query, token, makeCallbacks(), sessionId || undefined)
    abortRef.current = controller
  }, [token, sessionId, error, addMessage, makeCallbacks])

  // Reply to agent question (resumes paused pipeline)
  const handleReplyToQuestion = useCallback((answer: string) => {
    if (!sessionId) return

    markQuestionAnswered(answer)
    setAgentState('thinking')

    const controller = replyToAgentSSE(sessionId, answer, token, makeCallbacks())
    abortRef.current = controller
  }, [sessionId, token, markQuestionAnswered, makeCallbacks])

  // Refine search (post-results follow-up)
  const handleRefine = useCallback((message: string) => {
    if (!sessionId) return

    addMessage({ role: 'user', type: 'text', content: message })
    setAgentState('thinking')

    const controller = refineWithSSE(sessionId, message, token, makeCallbacks())
    abortRef.current = controller
  }, [sessionId, token, addMessage, makeCallbacks])

  // Unified submit handler — routes based on state
  const handleSubmit = useCallback((message: string) => {
    if (latestResults && sessionId && !error) {
      handleRefine(message)
    } else {
      handleSearch(message)
    }
  }, [latestResults, sessionId, error, handleRefine, handleSearch])

  // Interaction logging for flight card clicks
  const handleInteraction = useCallback((action: string, flightRank: number, flightId: string) => {
    api.logInteraction({
      session_id: sessionId || undefined,
      action,
      flight_rank: flightRank,
      flight_id: flightId,
    }, token)
  }, [sessionId, token])

  const isLoading = agentState === 'thinking'

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b px-4 py-3 flex items-center justify-between sticky top-0 z-10">
        <h1 className="text-xl font-bold text-gray-900">
          Bala Travel Agent <span className="text-xs font-normal text-gray-400">v{APP_VERSION}</span>
        </h1>
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
      <main className="max-w-3xl mx-auto px-4 py-6 pb-48">
        {/* Show search input at top when no messages yet */}
        {messages.length === 0 && (
          <ConversationInput
            agentState={agentState}
            hasResults={false}
            onSubmit={handleSearch}
            loading={isLoading}
          />
        )}

        {/* Idle state */}
        {messages.length === 0 && agentState === 'idle' && (
          <div className="mt-12 text-center text-gray-400">
            <p className="text-lg">Type your travel request above</p>
            <p className="mt-2 text-sm">
              Example: &quot;I want a flight from Bangalore to Libreville around Sep 4th,
              business class, returning Sep 15th. No Air India.&quot;
            </p>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="mt-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
            {error}
          </div>
        )}

        {/* Conversation thread */}
        <ChatThread
          messages={messages}
          agentState={agentState}
          onReplyToQuestion={handleReplyToQuestion}
          onInteraction={handleInteraction}
        />

        {/* Bottom input — shows after first search, acts as refinement input */}
        {messages.length > 0 && agentState !== 'waiting_for_input' && (
          <div className="mt-6">
            <ConversationInput
              agentState={agentState}
              hasResults={!!latestResults}
              onSubmit={handleSubmit}
              loading={isLoading}
            />
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
