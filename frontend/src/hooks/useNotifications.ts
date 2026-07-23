/**
 * useNotifications — 站内拉取式通知 hook。
 *
 * - 登录后每 60s 轮询未读数（对齐现有活动轮询节奏）
 * - 打开下拉时才拉取列表
 * - 标记单条/全部已读，乐观更新未读数
 * - 所有请求失败静默降级（未读数归零 / 空列表），不阻塞界面
 */
import { useCallback, useEffect, useRef, useState } from 'react'

const API_BASE = '/api/frontend/notifications'
const POLL_INTERVAL_MS = 60_000

export interface NotificationItem {
  id: number
  type: string
  title: string
  body: string
  payload: Record<string, unknown>
  read: boolean
  created_at: string
}

interface UseNotificationsResult {
  unreadCount: number
  notifications: NotificationItem[]
  loading: boolean
  refreshCount: () => Promise<void>
  loadList: () => Promise<void>
  markRead: (id: number) => Promise<void>
  markAllRead: () => Promise<void>
}

export function useNotifications(authToken: string): UseNotificationsResult {
  const [unreadCount, setUnreadCount] = useState(0)
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [loading, setLoading] = useState(false)

  const tokenRef = useRef(authToken)
  tokenRef.current = authToken

  // 保存最新列表快照，供 markRead 同步判断某条是否原本未读。
  const notificationsRef = useRef(notifications)
  notificationsRef.current = notifications

  const authHeaders = useCallback(
    (): Record<string, string> => ({ Authorization: `Bearer ${tokenRef.current}` }),
    [],
  )

  const refreshCount = useCallback(async () => {
    if (!tokenRef.current) return
    try {
      const res = await fetch(`${API_BASE}/unread-count`, { headers: authHeaders() })
      if (!res.ok) {
        setUnreadCount(0)
        return
      }
      const data = await res.json().catch(() => ({}))
      setUnreadCount(typeof data.count === 'number' ? data.count : 0)
    } catch {
      setUnreadCount(0)
    }
  }, [authHeaders])

  const loadList = useCallback(async () => {
    if (!tokenRef.current) return
    setLoading(true)
    try {
      const res = await fetch(API_BASE, { headers: authHeaders() })
      if (!res.ok) {
        setNotifications([])
        return
      }
      const data = await res.json().catch(() => ({}))
      setNotifications(Array.isArray(data.notifications) ? data.notifications : [])
    } catch {
      setNotifications([])
    } finally {
      setLoading(false)
    }
  }, [authHeaders])

  const markRead = useCallback(
    async (id: number) => {
      // 乐观更新：命中未读条目才递减角标。基于 ref 读取当前状态，
      // 避免依赖 setState 更新函数的副作用（其执行时机不确定）。
      const target = notificationsRef.current.find((n) => n.id === id)
      const wasUnread = !!target && !target.read
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, read: true } : n)),
      )
      if (wasUnread) setUnreadCount((c) => Math.max(0, c - 1))
      try {
        await fetch(`${API_BASE}/${id}/read`, { method: 'POST', headers: authHeaders() })
      } catch {
        /* 静默降级：乐观状态已更新，下次轮询会自愈 */
      }
    },
    [authHeaders],
  )

  const markAllRead = useCallback(async () => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })))
    setUnreadCount(0)
    try {
      await fetch(`${API_BASE}/read-all`, { method: 'POST', headers: authHeaders() })
    } catch {
      /* 静默降级 */
    }
  }, [authHeaders])

  // 登录后轮询未读数。
  useEffect(() => {
    if (!authToken) {
      setUnreadCount(0)
      return
    }
    refreshCount()
    const timer = setInterval(refreshCount, POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [authToken, refreshCount])

  return {
    unreadCount,
    notifications,
    loading,
    refreshCount,
    loadList,
    markRead,
    markAllRead,
  }
}
