// Shows what Claude understood from the natural language query

import { ParsedQuery } from '../api/client'

interface ParsingIndicatorProps {
  query: string
  parsed?: ParsedQuery
}

export default function ParsingIndicator({ query, parsed }: ParsingIndicatorProps) {
  if (!parsed) {
    return (
      <div className="mt-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
        <div className="flex items-center gap-2 text-blue-700">
          <span className="animate-pulse">🧠</span>
          <span className="font-medium">Understanding your request...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="mt-4 p-4 bg-gray-50 border border-gray-200 rounded-lg">
      <p className="text-sm font-medium text-gray-600 mb-2">Understood:</p>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <div><span className="text-gray-500">From:</span> {parsed.origin}</div>
        <div><span className="text-gray-500">To:</span> {parsed.destination}</div>
        <div><span className="text-gray-500">Date:</span> {parsed.departure_date}</div>
        <div><span className="text-gray-500">Class:</span> {parsed.cabin_class}</div>
        <div><span className="text-gray-500">Max stops:</span> {parsed.max_stops}</div>
        {parsed.preferences.length > 0 && (
          <div className="col-span-2">
            <span className="text-gray-500">Priorities:</span>{' '}
            {parsed.preferences.map(p => p.replace('_', ' ')).join(', ')}
          </div>
        )}
      </div>
    </div>
  )
}
