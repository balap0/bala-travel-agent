// API client — thin wrapper around fetch for backend communication

const BASE_URL = '/api'

interface ApiOptions {
  method?: string
  body?: unknown
  token?: string
}

export async function apiCall<T>(endpoint: string, options: ApiOptions = {}): Promise<T> {
  const { method = 'GET', body, token } = options

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const response = await fetch(`${BASE_URL}${endpoint}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Request failed' }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }

  return response.json()
}

// Typed API methods
export const api = {
  login: (password: string) =>
    apiCall<{ token: string }>('/auth/login', {
      method: 'POST',
      body: { password },
    }),

  search: (query: string, token: string, sessionId?: string) =>
    apiCall<SearchResponse>('/search', {
      method: 'POST',
      body: { query, session_id: sessionId },
      token,
    }),

  refine: (sessionId: string, message: string, token: string) =>
    apiCall<RefineResponse>(`/search/${sessionId}/refine`, {
      method: 'POST',
      body: { message },
      token,
    }),
}

// Response types matching backend schemas
export interface FlightSegment {
  airline: string
  airline_code: string
  flight_number: string
  departure_airport: string
  departure_time: string
  arrival_airport: string
  arrival_time: string
  duration_minutes: number
  aircraft?: string
  cabin_class: string
}

export interface FlightOption {
  id: string
  source: string
  segments: FlightSegment[]
  total_duration_minutes: number
  num_stops: number
  layovers: { airport: string; duration_minutes: number; overnight: boolean }[]
  price_usd: number
  cabin_class: string
  airline_names: string[]
  baggage_info?: Record<string, unknown>
  co2_emissions_kg?: number
  booking_links?: string[]
}

export interface RankedResult {
  rank: number
  flight: FlightOption
  explanation: string
  tags: string[]
}

export interface ParsedQuery {
  origin: string
  destination: string
  departure_date: string
  return_date?: string
  cabin_class: string
  max_stops: number
  preferences: string[]
  raw_query: string
  clarification_needed?: string
}

export interface SearchResponse {
  session_id: string
  parsed_query: ParsedQuery
  results: RankedResult[]
  sources_used: string[]
  search_duration_seconds: number
  total_options_found: number
}

export interface RefineResponse {
  session_id: string
  message: string
  updated_query?: ParsedQuery
  results?: RankedResult[]
}
