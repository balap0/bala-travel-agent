// API client — fetch wrapper + SSE streaming for search pipeline

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

// SSE event callback types
export interface SSECallbacks {
  onThinking?: (message: string) => void
  onStrategy?: (message: string) => void
  onClarify?: (question: string) => void
  onSearching?: (message: string) => void
  onRanking?: (message: string) => void
  onResults?: (response: SearchResponse) => void
  onError?: (error: string) => void
}

// SSE-based search — streams progress events during the search pipeline
export function searchWithSSE(
  query: string,
  token: string,
  callbacks: SSECallbacks,
  sessionId?: string,
): AbortController {
  const controller = new AbortController()

  const body = JSON.stringify({ query, session_id: sessionId })

  fetch(`${BASE_URL}/search`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream',
      'Authorization': `Bearer ${token}`,
    },
    body,
    signal: controller.signal,
  }).then(async (response) => {
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: 'Search failed' }))
      callbacks.onError?.(err.detail || `HTTP ${response.status}`)
      return
    }

    const reader = response.body?.getReader()
    if (!reader) {
      callbacks.onError?.('No response stream')
      return
    }

    const decoder = new TextDecoder()
    let buffer = ''
    let pendingEvent = ''
    let pendingData = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // Parse SSE events from buffer
      const lines = buffer.split('\n')
      buffer = lines.pop() || '' // keep incomplete line in buffer

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          pendingEvent = line.slice(7).trim()
        } else if (line.startsWith('data: ')) {
          pendingData = line.slice(6)
        } else if (line === '' && pendingEvent) {
          // Empty line = event boundary, dispatch
          _dispatchSSEEvent(pendingEvent, pendingData, callbacks)
          pendingEvent = ''
          pendingData = ''
        }
      }
    }

    // Handle any remaining event after stream ends
    if (pendingEvent && pendingData) {
      _dispatchSSEEvent(pendingEvent, pendingData, callbacks)
    }
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      callbacks.onError?.(err instanceof Error ? err.message : 'Search failed')
    }
  })

  return controller
}

function _dispatchSSEEvent(event: string, rawData: string, callbacks: SSECallbacks) {
  try {
    const data = JSON.parse(rawData)

    switch (event) {
      case 'thinking':
        callbacks.onThinking?.(data)
        break
      case 'strategy':
        callbacks.onStrategy?.(data)
        break
      case 'clarify':
        callbacks.onClarify?.(data)
        break
      case 'searching':
        callbacks.onSearching?.(data)
        break
      case 'ranking':
        callbacks.onRanking?.(data)
        break
      case 'results':
        callbacks.onResults?.(data as SearchResponse)
        break
      case 'error':
        callbacks.onError?.(data)
        break
    }
  } catch {
    // If data isn't valid JSON, treat it as a plain string
    if (event === 'error') callbacks.onError?.(rawData)
  }
}

// Typed API methods
export const api = {
  login: (password: string) =>
    apiCall<{ token: string }>('/auth/login', {
      method: 'POST',
      body: { password },
    }),

  // Fallback non-streaming search (if SSE fails)
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

export interface RouteAnalysis {
  difficulty: string
  strategy: string
  connecting_hubs: string[]
  recommended_airlines: string[]
  destination_brief: string
  clarifying_questions: string[]
  reasoning: string
}

export interface SearchResponse {
  session_id: string
  parsed_query: ParsedQuery
  results: RankedResult[]
  sources_used: string[]
  search_duration_seconds: number
  total_options_found: number
  route_analysis?: RouteAnalysis
}

export interface RefineResponse {
  session_id: string
  message: string
  updated_query?: ParsedQuery
  results?: RankedResult[]
}
