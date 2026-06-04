import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'

// ── Theme mode ──────────────────────────────────────────────────────

export type ThemeMode = 'light' | 'dark' | 'system' | 'special'

// ── Special theme definitions ───────────────────────────────────────

export interface SpecialTheme {
  id: string
  name: string
  /** CSS class applied to <html> */
  cssClass: string
  /** Preview gradient for the theme card */
  preview: string
  /** Accent color for UI highlights */
  accent: string
}

export const SPECIAL_THEMES: SpecialTheme[] = [
  {
    id: 'cloud-dancer',
    name: '云朵舞者',
    cssClass: 'theme-cloud-dancer',
    preview: 'linear-gradient(135deg, #f5f0e8 0%, #e8ddd0 40%, #d4c5b0 100%)',
    accent: '#c4a882',
  },
  {
    id: 'clear-sky',
    name: '晴空碧海',
    cssClass: 'theme-clear-sky',
    preview: 'linear-gradient(135deg, #b8dff5 0%, #7ec8e3 35%, #4a9cc7 70%, #2d6fa0 100%)',
    accent: '#4a9cc7',
  },
  {
    id: 'forest-morning',
    name: '森息晨光',
    cssClass: 'theme-forest-morning',
    preview: 'linear-gradient(135deg, #c8e6c0 0%, #8cc88a 40%, #5a9e58 100%)',
    accent: '#5a9e58',
  },
  {
    id: 'sky-twilight',
    name: '苍穹暮色',
    cssClass: 'theme-sky-twilight',
    preview: 'linear-gradient(135deg, #1a1a3e 0%, #2d2b55 40%, #3f3d6e 70%, #1e1e40 100%)',
    accent: '#6b68b0',
  },
  {
    id: 'forest-night',
    name: '森息夜语',
    cssClass: 'theme-forest-night',
    preview: 'linear-gradient(135deg, #1a2e1a 0%, #2d4a2d 40%, #1e3a1e 70%, #0f280f 100%)',
    accent: '#4a7a4a',
  },
  {
    id: 'morandi-night',
    name: '莫兰迪夜',
    cssClass: 'theme-morandi-night',
    preview: 'linear-gradient(135deg, #3a3636 0%, #4a4444 40%, #5a5252 70%, #2e2a2a 100%)',
    accent: '#8a7e7e',
  },
]

// ── Markdown font sizes ─────────────────────────────────────────────

export type MdFontSize = 'small' | 'medium' | 'large'

export const MD_FONT_SIZES: Record<MdFontSize, string> = {
  small: '12.5px',
  medium: '13.5px',
  large: '15px',
}

// ── Context type ────────────────────────────────────────────────────

interface ThemeContextValue {
  mode: ThemeMode
  setMode: (m: ThemeMode) => void
  specialThemeId: string
  setSpecialTheme: (id: string) => void
  mdFontSize: MdFontSize
  setMdFontSize: (s: MdFontSize) => void
  /** Resolved effective theme: 'light' | 'dark' | special css class */
  resolvedTheme: string
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

// ── Helpers ─────────────────────────────────────────────────────────

const STORAGE_KEY = 'xuanji_theme'

interface StoredPrefs {
  mode: ThemeMode
  specialThemeId: string
  mdFontSize: MdFontSize
}

function loadPrefs(): StoredPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw)
  } catch { /* ignore */ }
  return { mode: 'light', specialThemeId: 'clear-sky', mdFontSize: 'medium' }
}

function savePrefs(p: StoredPrefs) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(p))
}

// ── Provider ────────────────────────────────────────────────────────

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [prefs, setPrefs] = useState<StoredPrefs>(loadPrefs)

  const update = useCallback((patch: Partial<StoredPrefs>) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch }
      savePrefs(next)
      return next
    })
  }, [])

  // Resolve system preference
  const [systemDark, setSystemDark] = useState(() =>
    typeof window !== 'undefined'
      ? window.matchMedia('(prefers-color-scheme: dark)').matches
      : false,
  )

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = (e: MediaQueryListEvent) => setSystemDark(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  // Apply theme class to <html>
  useEffect(() => {
    const root = document.documentElement
    // Remove all theme classes
    root.classList.remove('dark', ...SPECIAL_THEMES.map((t) => t.cssClass))

    let resolved = 'light'
    if (prefs.mode === 'dark') {
      root.classList.add('dark')
      resolved = 'dark'
    } else if (prefs.mode === 'system') {
      if (systemDark) {
        root.classList.add('dark')
        resolved = 'dark'
      } else {
        resolved = 'light'
      }
    } else if (prefs.mode === 'special') {
      const theme = SPECIAL_THEMES.find((t) => t.id === prefs.specialThemeId)
      if (theme) {
        root.classList.add(theme.cssClass)
        resolved = theme.cssClass
        // Special dark themes also get 'dark' class
        if (['sky-twilight', 'forest-night', 'morandi-night'].includes(theme.id)) {
          root.classList.add('dark')
        }
      }
    }

    // Apply markdown font size CSS variable
    root.style.setProperty('--md-font-size', MD_FONT_SIZES[prefs.mdFontSize])

    return () => {
      root.classList.remove('dark', ...SPECIAL_THEMES.map((t) => t.cssClass))
    }
  }, [prefs.mode, prefs.specialThemeId, prefs.mdFontSize, systemDark])

  const resolvedTheme = (() => {
    if (prefs.mode === 'dark') return 'dark'
    if (prefs.mode === 'system') return systemDark ? 'dark' : 'light'
    if (prefs.mode === 'special') {
      const t = SPECIAL_THEMES.find((t) => t.id === prefs.specialThemeId)
      return t?.cssClass || 'light'
    }
    return 'light'
  })()

  return (
    <ThemeContext.Provider
      value={{
        mode: prefs.mode,
        setMode: (m) => update({ mode: m }),
        specialThemeId: prefs.specialThemeId,
        setSpecialTheme: (id) => update({ specialThemeId: id, mode: 'special' }),
        mdFontSize: prefs.mdFontSize,
        setMdFontSize: (s) => update({ mdFontSize: s }),
        resolvedTheme,
      }}
    >
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
