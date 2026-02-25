// Agent Thinking — progressive timeline showing the search pipeline's reasoning
// Replaces the simple ParsingIndicator with a multi-step conversational stream

import { RouteAnalysis } from '../api/client'

export interface ThinkingStep {
  type: 'thinking' | 'strategy' | 'clarify' | 'searching' | 'ranking' | 'error'
  message: string
  timestamp: number
}

interface AgentThinkingProps {
  steps: ThinkingStep[]
  isActive: boolean
  routeAnalysis?: RouteAnalysis
}

// Icon + color per step type
function stepStyle(type: ThinkingStep['type']) {
  switch (type) {
    case 'thinking':
      return { icon: '🧠', color: 'text-blue-700', bg: 'bg-blue-50', border: 'border-blue-200' }
    case 'strategy':
      return { icon: '🗺️', color: 'text-purple-700', bg: 'bg-purple-50', border: 'border-purple-200' }
    case 'clarify':
      return { icon: '❓', color: 'text-amber-700', bg: 'bg-amber-50', border: 'border-amber-200' }
    case 'searching':
      return { icon: '🔍', color: 'text-green-700', bg: 'bg-green-50', border: 'border-green-200' }
    case 'ranking':
      return { icon: '📊', color: 'text-indigo-700', bg: 'bg-indigo-50', border: 'border-indigo-200' }
    case 'error':
      return { icon: '⚠️', color: 'text-red-700', bg: 'bg-red-50', border: 'border-red-200' }
  }
}

export default function AgentThinking({ steps, isActive, routeAnalysis }: AgentThinkingProps) {
  if (steps.length === 0 && !isActive) return null

  return (
    <div className="mt-6 space-y-2">
      {/* Step timeline */}
      {steps.map((step, i) => {
        const style = stepStyle(step.type)
        const isLatest = i === steps.length - 1 && isActive

        return (
          <div
            key={i}
            className={`flex items-start gap-3 px-4 py-2.5 rounded-lg border ${style.bg} ${style.border} transition-all ${
              isLatest ? 'animate-pulse' : ''
            }`}
          >
            <span className="mt-0.5 text-base flex-shrink-0">{style.icon}</span>
            <span className={`text-sm ${style.color} leading-relaxed`}>
              {step.message}
            </span>
          </div>
        )
      })}

      {/* Active spinner when pipeline is still running */}
      {isActive && steps.length > 0 && (
        <div className="flex items-center gap-2 px-4 py-2 text-gray-400 text-sm">
          <span className="animate-spin">⏳</span>
          <span>Working...</span>
        </div>
      )}

      {/* Route analysis brief — shown as a card when available */}
      {routeAnalysis?.destination_brief && !isActive && (
        <div className="mt-3 px-4 py-3 bg-slate-50 border border-slate-200 rounded-lg">
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">Travel Context</p>
          <p className="text-sm text-slate-700 leading-relaxed">
            {routeAnalysis.destination_brief}
          </p>
          {routeAnalysis.recommended_airlines.length > 0 && (
            <p className="text-xs text-slate-500 mt-2">
              Airlines for this route: {routeAnalysis.recommended_airlines.join(', ')}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
