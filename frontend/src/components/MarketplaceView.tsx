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
import { useCallback, useEffect, useReducer, useState } from 'react'
import type { InstalledSkill } from './SkillManagerView'
import { AdminReviewView } from './market/AdminReviewView'
import MarketHome from './market/MarketHome'
import SearchResults from './market/SearchResults'
import SkillDetailPage from './market/SkillDetailPage'
import PublishSkillView from './market/PublishSkillView'
import MySkillsView from './market/MySkillsView'
import { apiFetch } from '../api/client'

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
  status?: string
  review_note?: string
  visibility?: 'public' | 'private'
  owner_org_id?: number | null
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

type TopTab = 'market' | 'installed' | 'my-skills' | 'review'

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

  const fireToast = useCallback((msg: string) => {
    dispatch({ type: 'SET_TOAST', payload: msg })
    window.setTimeout(() => dispatch({ type: 'SET_TOAST', payload: '' }), 2400)
  }, [])

  // ── API functions ──
  const fetchMarketSkills = useCallback(async (params?: Record<string, string>) => {
    dispatch({ type: 'SET_LOADING', payload: true })
    dispatch({ type: 'SET_ERROR', payload: '' })
    try {
      const qs = params ? '?' + new URLSearchParams(params).toString() : ''
      const data = await apiFetch<{ skills?: MarketSkillV2[] }>(`${API_BASE}/skills${qs}`)
      dispatch({ type: 'SET_MARKET_SKILLS', payload: data.skills ?? [] })
    } catch (e) { dispatch({ type: 'SET_ERROR', payload: e instanceof Error ? e.message : String(e) }) }
    finally { dispatch({ type: 'SET_LOADING', payload: false }) }
  }, [])

  const fetchCategories = useCallback(async () => {
    try {
      const data = await apiFetch<{ categories?: Category[] }>(`${API_BASE}/categories`)
      dispatch({ type: 'SET_CATEGORIES', payload: data.categories ?? [] })
    } catch { /* silent */ }
  }, [])

  const fetchRankings = useCallback(async (period: 'week' | 'month' = 'week') => {
    try {
      const data = await apiFetch<{ skills?: MarketSkillV2[] }>(`${API_BASE}/rankings?period=${period}`)
      dispatch({
        type: 'SET_RANKINGS',
        payload: { ...state.rankings, [period]: data.skills ?? [] },
      })
    } catch { /* silent */ }
  }, [state.rankings])

  const fetchFeatured = useCallback(async () => {
    try {
      const data = await apiFetch<{ skills?: MarketSkillV2[] }>(`${API_BASE}/featured`)
      dispatch({ type: 'SET_FEATURED', payload: data.skills ?? [] })
    } catch { /* silent */ }
  }, [])

  const installSkill = useCallback(async (name: string) => {
    try {
      await apiFetch(`${API_BASE}/skills/${encodeURIComponent(name)}/install`, { method: 'POST' })
      fireToast('安装成功')
      return true
    } catch (e) { fireToast(`安装失败：${e instanceof Error ? e.message : String(e)}`); return false }
  }, [fireToast])

  const fetchSkillDetail = useCallback(async (name: string) => {
    try {
      return await apiFetch<MarketSkillV2>(`${API_BASE}/skills/${encodeURIComponent(name)}`)
    } catch { return null }
  }, [])

  const fetchReviews = useCallback(async (name: string, page = 1) => {
    try {
      const data = await apiFetch<{ reviews?: Review[] }>(`${API_BASE}/skills/${encodeURIComponent(name)}/reviews?page=${page}`)
      return (data.reviews ?? []) as Review[]
    } catch { return [] as Review[] }
  }, [])

  const submitReview = useCallback(async (name: string, rating: number, comment: string) => {
    try {
      await apiFetch(`${API_BASE}/skills/${encodeURIComponent(name)}/reviews`, {
        method: 'POST',
        json: { rating, comment },
      })
      fireToast('评价已提交')
      return true
    } catch (e) { fireToast(`提交失败：${e instanceof Error ? e.message : String(e)}`); return false }
  }, [fireToast])

  const publishSkill = useCallback(async (formData: FormData) => {
    dispatch({ type: 'SET_LOADING', payload: true })
    try {
      await apiFetch(`${API_BASE}/publish`, { method: 'POST', body: formData })
      fireToast('发布成功')
      return true
    } catch (e) { fireToast(`发布失败：${e instanceof Error ? e.message : String(e)}`); return false }
    finally { dispatch({ type: 'SET_LOADING', payload: false }) }
  }, [fireToast])

  const fetchMySkills = useCallback(async () => {
    try {
      const data = await apiFetch<{ skills?: MarketSkillV2[] }>(`${API_BASE}/my-skills`)
      return (data.skills ?? []) as MarketSkillV2[]
    } catch { return [] as MarketSkillV2[] }
  }, [])

  const fetchFavorites = useCallback(async () => {
    try {
      const data = await apiFetch<{ skills?: MarketSkillV2[] }>(`${API_BASE}/favorites`)
      return (data.skills ?? []) as MarketSkillV2[]
    } catch { return [] as MarketSkillV2[] }
  }, [])

  const toggleFavorite = useCallback(async (name: string, isFav: boolean) => {
    const method = isFav ? 'DELETE' : 'POST'
    try {
      await apiFetch(`${API_BASE}/favorites/${encodeURIComponent(name)}`, { method })
      fireToast(isFav ? '已取消收藏' : '已收藏')
      return true
    } catch { return false }
  }, [fireToast])

  const markReviewHelpful = useCallback(async (reviewId: string) => {
    try {
      await apiFetch(`${API_BASE}/reviews/${encodeURIComponent(reviewId)}/helpful`, { method: 'POST' })
      return true
    } catch { return false }
  }, [])

  const withdrawSkill = useCallback(async (name: string) => {
    try {
      await apiFetch(`${API_BASE}/skills/${encodeURIComponent(name)}`, { method: 'DELETE' })
      fireToast('已下架')
      return true
    } catch (e) { fireToast(`下架失败：${e instanceof Error ? e.message : String(e)}`); return false }
  }, [fireToast])

  const fetchInstalled = useCallback(async () => {
    try {
      const data = await apiFetch<{ skills?: InstalledSkill[] }>('/api/frontend/skills')
      dispatch({ type: 'SET_INSTALLED_SKILLS', payload: data.skills ?? [] })
    } catch { /* silent */ }
  }, [])

  // initial load
  useEffect(() => {
    fetchMarketSkills()
    fetchCategories()
    fetchFeatured()
    fetchRankings('week')
    fetchInstalled()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return {
    state, dispatch, fireToast,
    fetchMarketSkills, fetchCategories, fetchRankings, fetchFeatured, fetchInstalled,
    installSkill, fetchSkillDetail, fetchReviews, submitReview, markReviewHelpful,
    publishSkill, fetchMySkills, fetchFavorites, toggleFavorite, withdrawSkill,
  }
}

// ─── MarketplaceView Component ───────────────────────────────────────────
export function MarketplaceView({ authToken, isAdmin = false }: { authToken: string; isAdmin?: boolean }) {
  const {
    state, dispatch, fireToast,
    fetchMarketSkills, fetchRankings,
    installSkill, fetchSkillDetail, fetchReviews, markReviewHelpful,
    publishSkill, fetchMySkills, fetchFavorites, toggleFavorite,
    withdrawSkill, fetchInstalled,
  } = useMarketplace(authToken)
  const [topTab, setTopTab] = useState<TopTab>('market')
  const [pendingCount, setPendingCount] = useState(0)
  const [mySkills, setMySkills] = useState<MarketSkillV2[]>([])
  const [favorites, setFavorites] = useState<MarketSkillV2[]>([])
  const [favoriteNames, setFavoriteNames] = useState<Set<string>>(new Set())
  const [mySkillsTab, setMySkillsTab] = useState<'published' | 'favorites'>('published')
  const [mySkillsLoading, setMySkillsLoading] = useState(false)
  const [detailSkill, setDetailSkill] = useState<MarketSkillV2 | null>(null)
  const [detailReviews, setDetailReviews] = useState<Review[]>([])
  const [detailLoading, setDetailLoading] = useState(false)

  const navigateTo = useCallback((view: MarketView) => {
    dispatch({ type: 'SET_VIEW', payload: view })
  }, [dispatch])

  // Fetch pending count for the review tab badge (admins only)
  const refreshPendingCount = useCallback(async () => {
    if (!isAdmin) return
    try {
      const data = await apiFetch<{ total?: number; skills?: unknown[] }>(`${API_BASE}/admin/pending`)
      setPendingCount(typeof data.total === 'number' ? data.total : (data.skills ?? []).length)
    } catch { /* silent */ }
  }, [isAdmin])

  useEffect(() => {
    refreshPendingCount()
  }, [refreshPendingCount])

  const loadMySkills = useCallback(async () => {
    setMySkillsLoading(true)
    try {
      const [pub, favs] = await Promise.all([fetchMySkills(), fetchFavorites()])
      setMySkills(pub)
      setFavorites(favs)
      setFavoriteNames(new Set(favs.map((s) => s.name)))
    } finally {
      setMySkillsLoading(false)
    }
  }, [fetchMySkills, fetchFavorites])

  // Load favorites once so the favorite state is known across market/detail views.
  useEffect(() => {
    fetchFavorites().then((favs) => {
      setFavorites(favs)
      setFavoriteNames(new Set(favs.map((s) => s.name)))
    })
  }, [fetchFavorites])

  const openDetail = useCallback(async (name: string) => {
    navigateTo({ kind: 'detail', skillName: name })
    setDetailLoading(true)
    setDetailSkill(null)
    try {
      const [skill, reviews] = await Promise.all([fetchSkillDetail(name), fetchReviews(name)])
      setDetailSkill(skill)
      setDetailReviews(reviews)
    } finally {
      setDetailLoading(false)
    }
  }, [navigateTo, fetchSkillDetail, fetchReviews])

  const handleCategoryChange = useCallback((id: string | null) => {
    dispatch({ type: 'SET_FILTERS', payload: { category: id } })
    fetchMarketSkills(id ? { category: id } : undefined)
  }, [dispatch, fetchMarketSkills])

  const handleSearch = useCallback((query: string) => {
    dispatch({ type: 'SET_SEARCH_QUERY', payload: query })
    navigateTo({ kind: 'search', query, filters: state.activeFilters })
    fetchMarketSkills({ search: query })
  }, [dispatch, navigateTo, fetchMarketSkills, state.activeFilters])

  const handleFiltersChange = useCallback((filters: FilterState) => {
    dispatch({ type: 'SET_FILTERS', payload: filters })
    const params: Record<string, string> = {}
    if (state.searchQuery) params.search = state.searchQuery
    if (filters.category) params.category = filters.category
    if (filters.sortBy) params.sort = filters.sortBy
    fetchMarketSkills(params)
  }, [dispatch, fetchMarketSkills, state.searchQuery])

  const handleInstall = useCallback(async (name: string) => {
    const ok = await installSkill(name)
    if (ok) fetchInstalled()
  }, [installSkill, fetchInstalled])

  const handleToggleFavorite = useCallback(async (name: string) => {
    const isFav = favoriteNames.has(name)
    const ok = await toggleFavorite(name, isFav)
    if (ok) {
      setFavoriteNames((prev) => {
        const next = new Set(prev)
        if (isFav) next.delete(name)
        else next.add(name)
        return next
      })
    }
  }, [favoriteNames, toggleFavorite])

  const handlePublishSuccess = useCallback(() => {
    setTopTab('my-skills')
    setMySkillsTab('published')
    navigateTo({ kind: 'my-skills', tab: 'published' })
    loadMySkills()
  }, [navigateTo, loadMySkills])

  const handlePublish = useCallback(async (formData: FormData) => {
    const ok = await publishSkill(formData)
    if (ok) handlePublishSuccess()
  }, [publishSkill, handlePublishSuccess])

  // ── Render content by topTab + currentView ──
  const renderContent = () => {
    if (topTab === 'review') {
      return (
        <AdminReviewView
          authToken={authToken}
          onCountChange={setPendingCount}
          fireToast={fireToast}
        />
      )
    }

    if (state.error) {
      return (
        <div className="mb-4 p-3 rounded-lg bg-rose-50 border border-rose-100 text-[12.5px] text-rose-700">
          {state.error}
        </div>
      )
    }

    const view = state.currentView

    // Publish wizard is reachable from any tab.
    if (view.kind === 'publish') {
      return (
        <PublishSkillView
          authToken={authToken}
          categories={state.categories}
          onPublish={handlePublish}
          onSuccess={handlePublishSuccess}
          onCancel={() => navigateTo(topTab === 'my-skills' ? { kind: 'my-skills', tab: 'published' } : { kind: 'home' })}
          loading={state.loading}
        />
      )
    }

    // Skill detail is shared between market / my-skills contexts.
    if (view.kind === 'detail') {
      return (
        <SkillDetailPage
          skill={detailSkill}
          skillName={view.skillName}
          reviews={detailReviews}
          authToken={authToken}
          onBack={() => navigateTo(topTab === 'my-skills' ? { kind: 'my-skills', tab: mySkillsTab } : { kind: 'home' })}
          onInstall={handleInstall}
          onMarkHelpful={(id) => { markReviewHelpful(id) }}
          onToggleFavorite={handleToggleFavorite}
          isFavorite={favoriteNames.has(view.skillName)}
          loading={detailLoading}
        />
      )
    }

    if (topTab === 'installed') {
      return <InstalledSkillsList skills={state.installedSkills} />
    }

    if (topTab === 'my-skills') {
      return (
        <MySkillsView
          authToken={authToken}
          tab={mySkillsTab}
          onTabChange={(t) => { setMySkillsTab(t); navigateTo({ kind: 'my-skills', tab: t }) }}
          mySkills={mySkills}
          favorites={favorites}
          onSkillClick={openDetail}
          onWithdraw={async (n) => { const ok = await withdrawSkill(n); if (ok) loadMySkills() }}
          onRemoveFavorite={async (n) => { await handleToggleFavorite(n); loadMySkills() }}
          loading={mySkillsLoading}
        />
      )
    }

    // topTab === 'market'
    if (view.kind === 'search') {
      return (
        <SearchResults
          skills={state.marketSkills}
          query={view.query}
          filters={state.activeFilters}
          categories={state.categories}
          onFiltersChange={handleFiltersChange}
          onSkillClick={openDetail}
          onInstall={handleInstall}
          onBack={() => navigateTo({ kind: 'home' })}
          loading={state.loading}
          viewMode={state.viewMode}
          onViewModeChange={(m) => dispatch({ type: 'SET_VIEW_MODE', payload: m })}
        />
      )
    }
    return (
      <MarketHome
        featured={state.featured}
        categories={state.categories}
        rankings={state.rankings}
        skills={state.marketSkills}
        activeCategory={state.activeFilters.category}
        onCategoryChange={handleCategoryChange}
        onSkillClick={openDetail}
        onInstall={handleInstall}
        onSearch={handleSearch}
        loading={state.loading}
      />
    )
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
          <button
            onClick={() => navigateTo({ kind: 'publish' })}
            className="shrink-0 inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-[13px] font-medium text-white transition-colors"
            style={{ backgroundColor: 'var(--primary-500, #3B82F6)' }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            发布技能
          </button>
        </div>

        {/* Top Tabs */}
        <div className="mt-4 flex items-center gap-6 border-b border-transparent -mb-4">
          <TabBtn active={topTab === 'market'} onClick={() => { setTopTab('market'); navigateTo({ kind: 'home' }) }}>
            技能市场
          </TabBtn>
          <TabBtn active={topTab === 'installed'} onClick={() => { setTopTab('installed'); navigateTo({ kind: 'installed' }) }}>
            已安装 <span className="ml-0.5 font-normal" style={{ color: 'var(--text-secondary, #9ca3af)' }}>{state.installedSkills.length}</span>
          </TabBtn>
          <TabBtn active={topTab === 'my-skills'} onClick={() => { setTopTab('my-skills'); navigateTo({ kind: 'my-skills', tab: 'published' }); loadMySkills() }}>
            我的发布
          </TabBtn>
          {isAdmin && (
            <TabBtn active={topTab === 'review'} onClick={() => { setTopTab('review'); refreshPendingCount() }}>
              审核
              {pendingCount > 0 && (
                <span className="ml-1 inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full bg-rose-500 text-white text-[10px] font-medium align-middle">
                  {pendingCount}
                </span>
              )}
            </TabBtn>
          )}
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

function InstalledSkillsList({ skills }: { skills: InstalledSkill[] }) {
  if (skills.length === 0) {
    return (
      <div className="text-center py-20">
        <div className="text-[14px] font-medium" style={{ color: 'var(--text-primary, #374151)' }}>还没有已安装的技能</div>
        <div className="text-[12.5px] mt-1.5" style={{ color: 'var(--text-secondary, #6b7280)' }}>前往技能市场安装社区技能</div>
      </div>
    )
  }
  return (
    <div className="space-y-3">
      {skills.map((s) => (
        <div key={s.name} className="bg-white border border-gray-200 rounded-xl p-4">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[14px] font-medium text-gray-900">{s.name}</span>
            <span className="text-[11px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">v{s.version}</span>
            <span className="text-[11px] px-1.5 py-0.5 rounded bg-sky-50 text-sky-700">{s.source === 'builtin' ? '内置' : '用户'}</span>
            <span className="text-[11px] px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700">{s.type === 'task' ? '任务型' : '参考型'}</span>
            {!s.enabled && <span className="text-[11px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">已禁用</span>}
          </div>
          <p className="text-[12.5px] text-gray-600 mt-1.5 break-words">{s.description}</p>
        </div>
      ))}
    </div>
  )
}

export default MarketplaceView
