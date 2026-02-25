// Individual flight result card with route, price, and AI explanation

import { useState } from 'react'
import { RankedResult } from '../api/client'

interface FlightCardProps {
  result: RankedResult
  onInteraction?: (action: string, flightRank: number, flightId: string) => void
}

// Format minutes to "Xh Ym"
function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

export default function FlightCard({ result, onInteraction }: FlightCardProps) {
  const [expanded, setExpanded] = useState(result.rank === 1)
  const { flight, explanation, tags, rank } = result

  const isRecommended = tags.includes('recommended')

  return (
    <div className={`bg-white rounded-xl border p-5 transition ${
      isRecommended ? 'border-brand-500 ring-1 ring-brand-200' : 'border-gray-200'
    }`}>
      {/* Header: rank, airlines, tags */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <span className={`text-sm font-bold px-2 py-1 rounded ${
            isRecommended ? 'bg-brand-100 text-brand-700' : 'bg-gray-100 text-gray-600'
          }`}>
            #{rank}
          </span>
          <div>
            <p className="font-semibold text-gray-900">
              {flight.airline_names.join(' → ')}
            </p>
            <p className="text-sm text-gray-500">
              {flight.num_stops} stop{flight.num_stops !== 1 ? 's' : ''} · {flight.cabin_class}
            </p>
          </div>
        </div>
        <div className="text-right">
          <p className="text-xl font-bold text-gray-900">
            ${flight.price_usd.toLocaleString()}
          </p>
          <p className="text-sm text-gray-500">
            {formatDuration(flight.total_duration_minutes)}
          </p>
        </div>
      </div>

      {/* Route segments */}
      <div className="mt-3 flex items-center gap-2 text-sm text-gray-600">
        {flight.segments.map((seg, i) => (
          <span key={i} className="flex items-center gap-1">
            {i > 0 && <span className="text-gray-400 mx-1">→</span>}
            <span className="font-medium">{seg.departure_airport}</span>
            <span className="text-gray-400">({formatDuration(seg.duration_minutes)})</span>
          </span>
        ))}
        <span className="text-gray-400 mx-1">→</span>
        <span className="font-medium">
          {flight.segments[flight.segments.length - 1]?.arrival_airport}
        </span>
      </div>

      {/* Tags */}
      {tags.length > 0 && (
        <div className="mt-3 flex gap-2">
          {tags.map((tag) => (
            <span key={tag} className="text-xs px-2 py-1 rounded-full bg-gray-100 text-gray-600">
              {tag.replace('_', ' ')}
            </span>
          ))}
        </div>
      )}

      {/* AI Explanation */}
      <div className="mt-3">
        <button
          onClick={() => {
            const wasExpanded = expanded
            setExpanded(!wasExpanded)
            if (!wasExpanded) {
              onInteraction?.('expand_reasoning', rank, flight.id)
            }
          }}
          className="text-sm text-brand-600 hover:text-brand-700 font-medium"
        >
          {expanded ? '▼ Hide reasoning' : '▶ Show AI reasoning'}
        </button>
        {expanded && (
          <p className="mt-2 text-sm text-gray-700 leading-relaxed bg-gray-50 p-3 rounded-lg">
            {explanation}
          </p>
        )}
      </div>
    </div>
  )
}
