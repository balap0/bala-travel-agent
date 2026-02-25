// Preferences panel — slide-out panel for managing user preferences
// Preferences are injected into all Claude prompts to personalize results

import { useState, useEffect, useCallback } from 'react'
import { api, Preference } from '../api/client'

interface PreferencesPanelProps {
  token: string
  isOpen: boolean
  onClose: () => void
}

const CATEGORY_ICONS: Record<string, string> = {
  hard_constraint: '🚫',
  soft_preference: '⭐',
  context: '👤',
}

const CATEGORY_LABELS: Record<string, string> = {
  hard_constraint: 'Hard rule',
  soft_preference: 'Preference',
  context: 'Context',
}

export default function PreferencesPanel({ token, isOpen, onClose }: PreferencesPanelProps) {
  const [preferences, setPreferences] = useState<Preference[]>([])
  const [newContent, setNewContent] = useState('')
  const [newCategory, setNewCategory] = useState<string>('soft_preference')
  const [loading, setLoading] = useState(false)

  const fetchPreferences = useCallback(async () => {
    try {
      const data = await api.getPreferences(token)
      setPreferences(data.preferences || [])
    } catch {
      // silent — prefs are non-critical
    }
  }, [token])

  useEffect(() => {
    if (isOpen) fetchPreferences()
  }, [isOpen, fetchPreferences])

  const handleAdd = async () => {
    if (!newContent.trim()) return
    setLoading(true)
    try {
      await api.addPreference(newContent.trim(), newCategory, token)
      setNewContent('')
      await fetchPreferences()
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }

  const handleToggle = async (id: string) => {
    try {
      await api.togglePreference(id, token)
      await fetchPreferences()
    } catch {
      // silent
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await api.deletePreference(id, token)
      await fetchPreferences()
    } catch {
      // silent
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />

      {/* Panel */}
      <div className="relative w-full max-w-md bg-white shadow-xl flex flex-col">
        {/* Header */}
        <div className="px-5 py-4 border-b flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">My Preferences</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">
            &times;
          </button>
        </div>

        {/* Preferences list */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
          {preferences.length === 0 && (
            <p className="text-sm text-gray-400 text-center py-8">
              No preferences yet. Add one below, or type "Remember I prefer..." in the search refinement.
            </p>
          )}

          {preferences.map((pref) => (
            <div
              key={pref.id}
              className={`flex items-start gap-3 p-3 rounded-lg border transition ${
                pref.active ? 'bg-white border-gray-200' : 'bg-gray-50 border-gray-100 opacity-60'
              }`}
            >
              <span className="text-lg mt-0.5">{CATEGORY_ICONS[pref.category] || '⭐'}</span>
              <div className="flex-1 min-w-0">
                <p className={`text-sm ${pref.active ? 'text-gray-900' : 'text-gray-500 line-through'}`}>
                  {pref.content}
                </p>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-xs text-gray-400">
                    {CATEGORY_LABELS[pref.category] || pref.category}
                  </span>
                  <span className="text-xs text-gray-300">·</span>
                  <span className="text-xs text-gray-400">
                    {pref.source === 'inferred' ? 'Learned' : 'You added'}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => handleToggle(pref.id)}
                  className={`w-10 h-5 rounded-full transition relative ${
                    pref.active ? 'bg-brand-500' : 'bg-gray-300'
                  }`}
                  title={pref.active ? 'Disable' : 'Enable'}
                >
                  <span
                    className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
                      pref.active ? 'translate-x-5' : 'translate-x-0.5'
                    }`}
                  />
                </button>
                <button
                  onClick={() => handleDelete(pref.id)}
                  className="text-gray-300 hover:text-red-500 ml-1 text-sm"
                  title="Delete"
                >
                  ✕
                </button>
              </div>
            </div>
          ))}
        </div>

        {/* Add new preference */}
        <div className="border-t px-5 py-4 space-y-3">
          <div className="flex gap-2">
            <select
              value={newCategory}
              onChange={(e) => setNewCategory(e.target.value)}
              className="text-sm border border-gray-300 rounded-lg px-2 py-2 bg-white"
            >
              <option value="soft_preference">⭐ Preference</option>
              <option value="hard_constraint">🚫 Hard rule</option>
              <option value="context">👤 Context</option>
            </select>
            <input
              type="text"
              value={newContent}
              onChange={(e) => setNewContent(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
              placeholder="e.g., Prefer morning departures"
              className="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none"
            />
          </div>
          <button
            onClick={handleAdd}
            disabled={loading || !newContent.trim()}
            className="w-full py-2 bg-brand-600 hover:bg-brand-700 text-white text-sm font-medium rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? 'Saving...' : 'Add Preference'}
          </button>
        </div>
      </div>
    </div>
  )
}
