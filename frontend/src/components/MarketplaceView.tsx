/**
 * MarketplaceView —— 技能市场社区平台主容器
 *
 * 布局结构：
 *   ┌─ 顶部 Tab 栏：技能市场 | 已安装 | 我的发布 ─┐
 *   ├─ 内容区域（按 currentView 路由）            ─┤
 *   │  home → 市场首页（placeholder）              ─┤
 *   │  search → 搜索结果（placeholder）            ─┤
 *   │  detail → 技能详情（placeholder）            ─┤
 *   ├─ Toast 通知                                ─┤
 *   └────────────────────────────────────────────┘
 */
import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import type { InstalledSkill } from './SkillManagerView'

// ─── API ─────────────────────────────────────────────────────────────────
const API_BASE = '/api/frontend/market/community'

// ─── Types ───────────────────────────────────────────────────────────────
type MarketView =
  | { kind: 'home' }
  | { kind: 'search'; query: string; filters: FilterState }
  | { kind: 'detail'; skillName: string }
  | { kind: 'publish' }
  | { kind: 'my-skills'; tab: 'published' | 'favorites' }
  | { kind: 'installed' }

export interface FilterState {
  category: string | null
  source: string[]
  minRating: number
  sortBy: 'popular' | 'newest' | 'rating' | 'name'
  tags: string[]
}

export interface MarketSkillV2 {
  name: string
  source_type: string
  category: string
  tags: string[]
  description: string
  author: string
  version: string
  rating_avg: number
  rating_count: number
  install_count: number
  icon_url?: string
  screenshots: string[]
  featured: boolean
  installed: boolean
  updated_at: string
  created_at: string
}

export interface Review {
  id: string
  user: { name: string; avatar?: string }
  rating: number
  comment: string
  created_at: string
  helpful_count: number
  version: string
}

export interface Category {
  id: string
  name: string
  icon: string
  sort_order: number
}

type TopTab = 'market' | 'installed' | 'my-skills'

// ─── Reducer ─────────────────────────────────────────────────────────────
interface MarketState {
  marketSkills: MarketSkillV2[]
  installedSkills: InstalledSkill[]
  categories: Category[]
  rankings: { week: MarketSkillV2[]; month: MarketSkillV2[] }
  featured: MarketSkillV2[]
  currentView: MarketView
  searchQuery: string
  activeFilters: FilterState
  viewMode: 'grid' | 'list'
  loading: boolean
  error: string
  toast: string
}

const defaultFilters: FilterState = {
  category: null,
  source: [],
  minRating: 0,
  sortBy: 'popular',
  tags: [],
}

const initialState: MarketState = {
  marketSkills: [],
  installedSkills: [],
  categories: [],
  rankings: { week: [], month: [] },
  featured: [],
  currentView: { kind: 'home' },
  searchQuery: '',
  activeFilters: defaultFilters,
  viewMode: 'grid',
  loading: false,
  error: '',
  toast: '',
}

type Action =
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_ERROR'; payload: string }
  | { type: 'SET_TOAST'; payload: string }
  | { type: 'SET_MARKET_SKILLS'; payload: MarketSkillV2[] }
  | { type: 'SET_INSTALLED_SKILLS'; payload: InstalledSkill[] }
  | { type: 'SET_CATEGORIES'; payload: Category[] }
  | { type: 'SET_RANKINGS'; payload: { week: MarketSkillV2[]; month: MarketSkillV2[] } }
  | { type: 'SET_FEATURED'; payload: MarketSkillV2[] }
  | { type: 'SET_VIEW'; payload: MarketView }
  | { type: 'SET_SEARCH_QUERY'; payload: string }
  | { type: 'SET_FILTERS'; payload: Partial<FilterState> }
  | { type: 'SET_VIEW_MODE'; payload: 'grid' | 'list' }

function reducer(state: MarketState, action: Action): MarketState {
  switch (action.type) {
    case 'SET_LOADING':         return { ...state, loading: action.payload }
    case 'SET_ERROR':           return { ...state, error: action.payload }
    case 'SET_TOAST':           return { ...state, toast: action.payload }
    case 'SET_MARKET_SKILLS':   return { ...state, marketSkills: action.payload }
    case 'SET_INSTALLED_SKILLS':return { ...state, installedSkills: action.payload }
    case 'SET_CATEGORIES':      return { ...state, categories: action.payload }
    case 'SET_RANKINGS':        return { ...state, rankings: action.payload }
    case 'SET_FEATURED':        return { ...state, featured: action.payload }
    case 'SET_VIEW':            return { ...state, currentView: action.payload }
    case 'SET_SEARCH_QUERY':    return { ...state, searchQuery: action.payload }
    case 'SET_FILTERS':         return { ...state, activeFilters: { ...state.activeFilters, ...action.payload } }
    case 'SET_VIEW_MODE':       return { ...state, viewMode: action.payload }
    default:                    return state
  }
}

// ─── useMarketplace Hook ─────────────────────────────────────────────────
export function useMarketplace(authToken: string) {
  const [state, dispatch] = useReducer(reducer, initialState)
  const headersRef = useRef<Record<string, string>>({})
  headersRef.current = { Authorization: `Bearer ${authToken}` }

  const fireToast = useCallback((msg: string) => {
    dispatch({ type: 'SET_TOAST', payload: msg })
    window.setTimeout(() => dispatch({ type: 'SET_TOAST', payload: '' }), 2400)
  }, [])

  // helper: authed fetch
  const authFetch = useCallback(async (url: string, init?: RequestInit) => {
    const res = await fetch(url, { ...init, headers: { ...headersRef.current, ...(init?.headers as Record<string, string> || {}) } })
    return res
  }, [])

  // ── API functions ──
  const fetchMarketSkills = useCallback(async (params?: Record<string, string>) => {
    dispatch({ type: 'SET_LOADING', payload: true })
    dispatch({ type: 'SET_ERROR', payload: '' })
    try {
      const qs = params ? '?' + new URLSearchParams(params).toString() : ''
      const res = await authFetch(`${API_BASE}/skills${qs}`)
      const data = await res.json().catch(() => ({}))
      if (res.ok) dispatch({ type: 'SET_MARKET_SKILLS', payload: data.skills ?? [] })
      else dispatch({ type: 'SET_ERROR', payload: data.error || `加载失败 (${res.status})` })
    } catch (e) { dispatch({ type: 'SET_ERROR', payload: e instanceof Error ? e.message : String(e) }) }
    finally { dispatch({ type: 'SET_LOADING', payload: false }) }
  }, [authFetch])

  const fetchCategories = useCallback(async () => {
    try {
      const res = await authFetch(`${API_BASE}/categories`)
      const data = await res.json().catch(() => ({}))
      if (res.ok) dispatch({ type: 'SET_CATEGORIES', payload: data.categories ?? [] })
    } catch { /* silent */ }
  }, [authFetch])

  const fetchRankings = useCallback(async (period: 'week' | 'month' = 'week') => {
    try {
      const res = await authFetch(`${API_BASE}/rankings?period=${period}`)
      const data = await res.json().catch(() => ({}))
      if (res.ok) {
        dispatch({
          type: 'SET_RANKINGS',
          payload: { ...state.rankings, [period]: data.skills ?? [] },
        })
      }
    } catch { /* silent */ }
  }, [authFetch, state.rankings])

  const fetchFeatured = useCallback(async () => {
    try {
      const res = await authFetch(`${API_BASE}/featured`)
      const data = await res.json().catch(() => ({}))
      if (res.ok) dispatch({ type: 'SET_FEATURED', payload: data.skills ?? [] })
    } catch { /* silent */ }
  }, [authFetch])

  const installSkill = useCallback(async (name: string) => {
    try {
      const res = await authFetch(`${API_BASE}/skills/${encodeURIComponent(name)}/install`, { method: 'POST' })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) { fireToast(`安装失败：${data.error || res.status}`); return false }
      fireToast('安装成功')
      return true
    } catch (e) { fireToast(`安装失败：${e instanceof Error ? e.message : String(e)}`); return false }
  }, [authFetch, fireToast])

  const fetchSkillDetail = useCallback(async (name: string) => {
    const res = await authFetch(`${API_BASE}/skills/${encodeURIComponent(name)}`)
    const data = await res.json().catch(() => ({}))
    return res.ok ? (data as MarketSkillV2) : null
  }, [authFetch])

  const fetchReviews = useCallback(async (name: string, page = 1) => {
    const res = await authFetch(`${API_BASE}/skills/${encodeURIComponent(name)}/reviews?page=${page}`)
    const data = await res.json().catch(() => ({}))
    return res.ok ? ((data.reviews ?? []) as Review[]) : []
  }, [authFetch])

  const submitReview = useCallback(async (name: string, rating: number, comment: string) => {
    const res = await authFetch(`${API_BASE}/skills/${encodeURIComponent(name)}/reviews`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating, comment }),
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) { fireToast(`提交失败：${data.error || res.status}`); return false }
    fireToast('评价已提交')
    return true
  }, [authFetch, fireToast])

  const publishSkill = useCallback(async (formData: FormData) => {
    dispatch({ type: 'SET_LOADING', payload: true })
    try {
      const res = await authFetch(`${API_BASE}/publish`, { method: 'POST', body: formData })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) { fireToast(`发布失败：${data.error || res.status}`); return false }
      fireToast('发布成功')
      return true
    } catch (e) { fireToast(`发布失败：${e instanceof Error ? e.message : String(e)}`); return false }
    finally { dispatch({ type: 'SET_LOADING', payload: false }) }
  }, [authFetch, fireToast])

  const fetchMySkills = useCallback(async () => {
    const res = await authFetch(`${API_BASE}/my-skills`)
    const data = await res.json().catch(() => ({}))
    return res.ok ? ((data.skills ?? []) as MarketSkillV2[]) : []
  }, [authFetch])

  const fetchFavorites = useCallback(async () => {
    const res = await authFetch(`${API_BASE}/favorites`)
    const data = await res.json().catch(() => ({}))
    return res.ok ? ((data.skills ?? []) as MarketSkillV2[]) : []
  }, [authFetch])

  const toggleFavorite = useCallback(async (name: string, isFav: boolean) => {
    const method = isFav ? 'DELETE' : 'POST'
    const res = await authFetch(`${API_BASE}/favorites/${encodeURIComponent(name)}`, { method })
    if (res.ok) fireToast(isFav ? '已取消收藏' : '已收藏')
    return res.ok
  }, [authFetch, fireToast])

  // initial load
  useEffect(() => {
    fetchMarketSkills()
    fetchCategories()
    fetchFeatured()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return {
    state, dispatch, fireToast,
    fetchMarketSkills, fetchCategories, fetchRankings, fetchFeatured,
    installSkill, fetchSkillDetail, fetchReviews, submitReview,
    publishSkill, fetchMySkills, fetchFavorites, toggleFavorite,
  }
}

// ─── MarketplaceView Component ───────────────────────────────────────────
export function MarketplaceView({ authToken }: { authToken: string }) {
  const { state, dispatch, fireToast: _ft } = useMarketplace(authToken)
  const [topTab, setTopTab] = useState<TopTab>('market')

  // Suppress unused warning — fireToast available for child components
  void _ft

  const navigateTo = useCallback((view: MarketView) => {
    dispatch({ type: 'SET_VIEW', payload: view })
  }, [dispatch])

  // ── Render content by topTab + currentView ──
  const renderContent = () => {
    if (state.loading) {
      return (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="bg-white border border-gray-200 rounded-xl p-4 animate-pulse min-h-[148px]">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-full bg-gray-100" />
                <div className="w-12 h-4 rounded bg-gray-100" />
              </div>
              <div className="h-4 bg-gray-100 rounded mt-3 w-1/2" />
              <div className="h-3 bg-gray-100 rounded mt-3 w-full" />
              <div className="h-3 bg-gray-100 rounded mt-1.5 w-4/5" />
            </div>
          ))}
        </div>
      )
    }

    if (state.error) {
      return (
        <div className="mb-4 p-3 rounded-lg bg-rose-50 border border-rose-100 text-[12.5px] text-rose-700">
          {state.error}
        </div>
      )
    }

    if (topTab === 'market') {
      const { kind } = state.currentView
      if (kind === 'search') {
        return <PlaceholderView title="搜索结果" hint={`关键词: "${state.currentView.query}" — 搜索功能即将上线`} />
      }
      if (kind === 'detail') {
        return <PlaceholderView title="技能详情" hint={`${state.currentView.skillName} — 详情页即将上线`} />
      }
      return <PlaceholderView title="市场首页" hint="精选推荐、排行榜、分类浏览 — 即将上线" />
    }

    if (topTab === 'installed') {
      return <PlaceholderView title="已安装技能" hint={`共 ${state.installedSkills.length} 个已安装技能 — 列表即将上线`} />
    }

    // my-skills
    return <PlaceholderView title="我的发布" hint="管理已发布的技能和收藏 — 即将上线" />
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-gray-50/40">
      {/* Header + Tabs */}
      <header className="shrink-0 px-6 lg:px-8 pt-6 pb-4 bg-white border-b border-gray-200/70">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="min-w-0">
            <h1 className="text-[22px] font-medium leading-tight" style={{ color: 'var(--text-primary, #111827)' }}>
              技能市场
            </h1>
            <p className="text-[13px] mt-1" style={{ color: 'var(--text-secondary, #6b7280)' }}>
              发现、安装和分享社区技能
            </p>
          </div>
        </div>

        {/* Top Tabs */}
        <div className="mt-4 flex items-center gap-6 border-b border-transparent -mb-4">
          <TabBtn active={topTab === 'market'} onClick={() => { setTopTab('market'); navigateTo({ kind: 'home' }) }}>
            技能市场
          </TabBtn>
          <TabBtn active={topTab === 'installed'} onClick={() => { setTopTab('installed'); navigateTo({ kind: 'installed' }) }}>
            已安装 <span className="ml-0.5 font-normal" style={{ color: 'var(--text-secondary, #9ca3af)' }}>{state.installedSkills.length}</span>
          </TabBtn>
          <TabBtn active={topTab === 'my-skills'} onClick={() => { setTopTab('my-skills'); navigateTo({ kind: 'my-skills', tab: 'published' }) }}>
            我的发布
          </TabBtn>
        </div>
      </header>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 lg:px-8 py-6">
        {renderContent()}
      </div>

      {/* Toast */}
      {state.toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[80] px-4 py-2 rounded-lg bg-gray-900 text-white text-[12.5px] shadow-lg">
          {state.toast}
        </div>
      )}
    </div>
  )
}

// ─── Small helpers ───────────────────────────────────────────────────────
function TabBtn({ active, children, onClick }: { active: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`relative pb-3 text-[13.5px] transition-colors ${
        active ? 'text-gray-900 font-medium' : 'text-gray-500 hover:text-gray-700'
      }`}
    >
      {children}
      {active && <span className="absolute bottom-0 left-0 right-0 h-[2px] bg-gray-900 rounded-full" />}
    </button>
  )
}

function PlaceholderView({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="text-center py-20">
      <div className="text-[14px] font-medium" style={{ color: 'var(--text-primary, #374151)' }}>{title}</div>
      <div className="text-[12.5px] mt-1.5" style={{ color: 'var(--text-secondary, #6b7280)' }}>{hint}</div>
    </div>
  )
}

export default MarketplaceView
