// Displays ranked flight results with AI explanations

import { RankedResult } from '../api/client'
import FlightCard from './FlightCard'

interface ResultsListProps {
  results: RankedResult[]
}

export default function ResultsList({ results }: ResultsListProps) {
  if (results.length === 0) {
    return (
      <div className="mt-6 p-8 text-center text-gray-500 bg-white rounded-xl border">
        <p className="text-lg">No flights found</p>
        <p className="mt-1 text-sm">Try adjusting your dates, destination, or cabin class</p>
      </div>
    )
  }

  return (
    <div className="mt-6 space-y-4">
      {results.map((result) => (
        <FlightCard key={result.flight.id} result={result} />
      ))}
    </div>
  )
}
