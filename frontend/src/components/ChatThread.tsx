// Conversational chat thread — renders the full agent-user dialogue
// Replaces the old AgentThinking + ResultsList + RefineInput with a unified conversation

import { useEffect, useRef, useState } from 'react'
import ResultsList from './ResultsList'
import { RankedResult, SearchResponse } from '../api/client'

export interface ConversationMessage {
  id: string
  role: 'user' | 'agent'
  type: 'text' | 'thinking' | 'question' | 'results' | 'strategy' | 'filter_notice' | 'searching' | 'ranking'
  content: string
  timestamp: number
  // For question type
  questionId?: string
  answered?: boolean
  answer?: string
  // For results type
  searchResponse?: SearchResponse
}

interface ChatThreadProps {
  messages: ConversationMessage[]
  agentState: 'idle' | 'thinking' | 'waiting_for_input' | 'ready'
  onReplyToQuestion: (answer: string) => void
  onInteraction?: (action: string, flightRank: number, flightId: string) => void
}

// Step type styling — maps message type to visual treatment
const stepStyles: Record<string, { icon: string; borderColor: string; textColor: string }> = {
  thinking: { icon: '🧠', borderColor: 'border-blue-200', textColor: 'text-blue-800' },
  strategy: { icon: '🏙️', borderColor: 'border-purple-200', textColor: 'text-purple-800' },
  searching: { icon: '🔍', borderColor: 'border-green-200', textColor: 'text-green-800' },
  ranking: { icon: '📊', borderColor: 'border-indigo-200', textColor: 'text-indigo-800' },
  question: { icon: '❓', borderColor: 'border-amber-300', textColor: 'text-amber-800' },
  filter_notice: { icon: '🚫', borderColor: 'border-red-200', textColor: 'text-red-700' },
  text: { icon: '💬', borderColor: 'border-gray-200', textColor: 'text-gray-700' },
  results: { icon: '✈️', borderColor: 'border-brand-200', textColor: 'text-brand-800' },
}

export default function ChatThread({ messages, agentState, onReplyToQuestion, onInteraction }: ChatThreadProps) {
  const bottomRef = useRef<HTMLDivElement>(null)
  // Per-question reply text — keyed by message ID so each input is independent
  const [replyTexts, setReplyTexts] = useState<Record<string, string>>({})

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (messages.length === 0) return null

  const getReplyText = (msgId: string) => replyTexts[msgId] || ''
  const setReplyText = (msgId: string, text: string) => {
    setReplyTexts(prev => ({ ...prev, [msgId]: text }))
  }

  const handleReply = (msgId: string) => {
    const text = getReplyText(msgId)
    if (!text.trim()) return
    onReplyToQuestion(text.trim())
    setReplyTexts(prev => ({ ...prev, [msgId]: '' }))
  }

  return (
    <div className="mt-6 space-y-3">
      {messages.map((msg) => {
        if (msg.role === 'user') {
          return (
            <div key={msg.id} className="flex justify-end">
              <div className="bg-brand-50 border border-brand-200 rounded-xl px-4 py-3 max-w-[85%]">
                <p className="text-sm text-gray-800">{msg.content}</p>
              </div>
            </div>
          )
        }

        // Agent messages
        if (msg.type === 'results' && msg.searchResponse) {
          return (
            <div key={msg.id}>
              <div className="text-sm text-gray-500 mb-2">
                Found {msg.searchResponse.total_options_found} options from{' '}
                {msg.searchResponse.sources_used.join(' + ')} in{' '}
                {msg.searchResponse.search_duration_seconds}s
              </div>

              {/* Search parameters summary */}
              {msg.searchResponse.parsed_query && (
                <div className="mb-4 p-3 bg-gray-50 border border-gray-200 rounded-lg text-sm">
                  <div className="grid grid-cols-2 gap-1">
                    <div><span className="text-gray-500">From:</span> {msg.searchResponse.parsed_query.origin}</div>
                    <div><span className="text-gray-500">To:</span> {msg.searchResponse.parsed_query.destination}</div>
                    <div><span className="text-gray-500">Depart:</span> {msg.searchResponse.parsed_query.departure_date}</div>
                    {msg.searchResponse.parsed_query.return_date && (
                      <div><span className="text-gray-500">Return:</span> {msg.searchResponse.parsed_query.return_date}</div>
                    )}
                    <div><span className="text-gray-500">Class:</span> {msg.searchResponse.parsed_query.cabin_class}</div>
                  </div>
                </div>
              )}

              <ResultsList results={msg.searchResponse.results} onInteraction={onInteraction} />
            </div>
          )
        }

        if (msg.type === 'question') {
          const style = stepStyles.question
          return (
            <div key={msg.id} className="space-y-2">
              <div className={`border-l-4 ${style.borderColor} bg-amber-50 rounded-lg p-4`}>
                <div className="flex items-start gap-2">
                  <span className="text-lg">{style.icon}</span>
                  <p className={`text-sm ${style.textColor} font-medium`}>{msg.content}</p>
                </div>
              </div>

              {msg.answered ? (
                // Show the user's answer
                <div className="flex justify-end">
                  <div className="bg-brand-50 border border-brand-200 rounded-xl px-4 py-2 max-w-[85%]">
                    <p className="text-sm text-gray-800">{msg.answer}</p>
                  </div>
                </div>
              ) : agentState === 'waiting_for_input' ? (
                // Show reply input — each question has its own independent text state
                <div className="ml-6 flex gap-2">
                  <input
                    type="text"
                    value={getReplyText(msg.id)}
                    onChange={(e) => setReplyText(msg.id, e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleReply(msg.id)}
                    placeholder="Type your answer..."
                    className="flex-1 border border-amber-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 focus:border-transparent"
                    autoFocus
                  />
                  <button
                    onClick={() => handleReply(msg.id)}
                    disabled={!getReplyText(msg.id).trim()}
                    className="px-4 py-2 bg-amber-500 text-white text-sm font-medium rounded-lg hover:bg-amber-600 disabled:opacity-50 disabled:cursor-not-allowed transition"
                  >
                    Reply
                  </button>
                </div>
              ) : null}
            </div>
          )
        }

        // Standard agent messages (thinking, strategy, searching, ranking, filter_notice)
        const style = stepStyles[msg.type] || stepStyles.text
        return (
          <div key={msg.id} className={`border-l-4 ${style.borderColor} rounded-r-lg px-4 py-2`}>
            <div className="flex items-start gap-2">
              <span className="text-sm mt-0.5">{style.icon}</span>
              <p className={`text-sm ${style.textColor}`}>{msg.content}</p>
            </div>
          </div>
        )
      })}

      {/* Thinking indicator */}
      {agentState === 'thinking' && (
        <div className="border-l-4 border-blue-200 rounded-r-lg px-4 py-2 animate-pulse">
          <div className="flex items-center gap-2">
            <span className="text-sm">🧠</span>
            <p className="text-sm text-blue-600">Thinking...</p>
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}
