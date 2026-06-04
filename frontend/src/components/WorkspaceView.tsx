import { useState, useEffect, useCallback } from 'react'

// ── types ──────────────────────────────────────────────────────────────

interface TreeNode {
  name: string
  type: 'file' | 'dir'
  path: string
  size?: number
  mtime?: string
  children?: TreeNode[]
}

interface FileData {
  content?: string
  binary?: boolean
  path: string
  size: number
  error?: string
}

// ── constants ──────────────────────────────────────────────────────────

const API = '/api/frontend/workspace'

// ── component ──────────────────────────────────────────────────────────

export function WorkspaceView() {
  const [tree, setTree] = useState<TreeNode | null>(null)
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(
    () => new Set(['/']),
  )
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [fileData, setFileData] = useState<FileData | null>(null)
  const [editing, setEditing] = useState(false)
  const [editContent, setEditContent] = useState('')
  const [loading, setLoading] = useState(true)

  // ── load tree on mount ──────────────────────────────────────────────

  useEffect(() => {
    fetch(`${API}/tree`)
      .then((r) => r.json())
      .then((data) => {
        setTree(data)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  // ── directory expand / collapse ─────────────────────────────────────

  const toggleDir = useCallback((path: string) => {
    setExpandedPaths((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }, [])

  // ── file selection ──────────────────────────────────────────────────

  const selectFile = useCallback(async (path: string) => {
    setSelectedPath(path)
    setEditing(false)
    setFileData(null)
    try {
      const res = await fetch(`${API}/read?path=${encodeURIComponent(path)}`)
      const data: FileData = await res.json()
      setFileData(data)
    } catch {
      setFileData({ error: 'load failed', path, size: 0 })
    }
  }, [])

  // ── edit / save / cancel ────────────────────────────────────────────

  const startEdit = useCallback(() => {
    if (fileData?.content !== undefined) {
      setEditContent(fileData.content)
      setEditing(true)
    }
  }, [fileData])

  const saveFile = useCallback(async () => {
    if (!selectedPath) return
    try {
      const res = await fetch(
        `${API}/write?path=${encodeURIComponent(selectedPath)}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: editContent }),
        },
      )
      const data = await res.json()
      if (data.success) {
        setFileData((prev) =>
          prev ? { ...prev, content: editContent } : null,
        )
        setEditing(false)
      }
    } catch {
      /* silent */
    }
  }, [selectedPath, editContent])

  const cancelEdit = useCallback(() => {
    setEditing(false)
  }, [])

  // ── tree node renderer ──────────────────────────────────────────────

  const renderTreeNode = (node: TreeNode, depth: number) => {
    const isExpanded = expandedPaths.has(node.path)
    const isSelected = node.path === selectedPath
    const hasChildren = !!(node.children && node.children.length > 0)

    return (
      <div key={node.path}>
        <div
          className={`flex items-center gap-1 px-2 py-[3px] rounded cursor-pointer text-[12.5px] leading-tight ${
            isSelected
              ? 'bg-gray-100 text-gray-900'
              : 'text-gray-600 hover:bg-gray-50'
          }`}
          style={{ paddingLeft: 8 + depth * 14 }}
          onClick={() => {
            if (node.type === 'dir') {
              toggleDir(node.path)
            } else {
              selectFile(node.path)
            }
          }}
        >
          {node.type === 'dir' ? (
            <>
              <span className="text-gray-400 text-[9px] w-3 shrink-0 text-center">
                {isExpanded ? '▼' : '▶'}
              </span>
              <FolderIconSmall />
            </>
          ) : (
            <>
              <span className="w-3 shrink-0" />
              <FileIcon name={node.name} />
            </>
          )}
          <span className="truncate">{node.name}</span>
        </div>
        {node.type === 'dir' && isExpanded && hasChildren && (
          <div>
            {node.children!.map((child) => renderTreeNode(child, depth + 1))}
          </div>
        )}
      </div>
    )
  }

  // ── file content renderer ───────────────────────────────────────────

  const renderContent = () => {
    if (!selectedPath) {
      return (
        <div className="flex-1 flex items-center justify-center text-gray-400 text-[13px]">
          选择一个文件查看内容
        </div>
      )
    }

    if (!fileData) {
      return (
        <div className="flex-1 flex items-center justify-center text-gray-400 text-[13px]">
          加载中...
        </div>
      )
    }

    if (fileData.error) {
      return (
        <div className="flex-1 p-6 text-red-500 text-[13px]">
          {fileData.error}
        </div>
      )
    }

    // ── binary file ─────────────────────────────────────────────────
    if (fileData.binary) {
      const filename = selectedPath.split('/').pop() || ''
      const downloadUrl = `/api/frontend/files/download?path=${encodeURIComponent(selectedPath)}`
      return (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <div className="text-gray-400 text-[40px] mb-3 leading-none">
              <DocIcon />
            </div>
            <div className="text-[13px] font-medium text-gray-700 mb-1">
              {filename}
            </div>
            <div className="text-[11px] text-gray-400 mb-3">
              {(fileData.size / 1024).toFixed(1)} KB &middot; 二进制文件
            </div>
            <a
              href={downloadUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-900 text-white text-[12px] hover:bg-gray-800 transition-colors"
            >
              下载文件
            </a>
          </div>
        </div>
      )
    }

    // ── text file — editing mode ────────────────────────────────────
    if (editing) {
      return (
        <div className="flex-1 flex flex-col min-h-0">
          <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-200 bg-white shrink-0">
            <button
              onClick={saveFile}
              className="px-3 py-1 rounded bg-gray-900 text-white text-[12px] hover:bg-gray-800 transition-colors"
            >
              保存
            </button>
            <button
              onClick={cancelEdit}
              className="px-3 py-1 rounded border border-gray-200 text-gray-600 text-[12px] hover:bg-gray-50 transition-colors"
            >
              取消
            </button>
            <span className="text-[11px] text-gray-400 ml-auto">
              {selectedPath}
            </span>
          </div>
          <textarea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            className="flex-1 p-4 text-[13px] font-mono outline-none resize-none border-0"
            spellCheck={false}
          />
        </div>
      )
    }

    // ── text file — read mode ──────────────────────────────────────
    const isMd = selectedPath.toLowerCase().endsWith('.md')
    const isJson = selectedPath.toLowerCase().endsWith('.json')
    return (
      <div className="flex-1 flex flex-col min-h-0">
        {/* toolbar */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-white shrink-0">
          <span className="text-[11px] text-gray-400">
            {selectedPath} &middot; {(fileData.size! / 1024).toFixed(1)} KB
          </span>
          {isMd && (
            <button
              onClick={startEdit}
              className="px-3 py-1 rounded border border-gray-200 text-gray-600 text-[12px] hover:bg-gray-50 transition-colors"
            >
              编辑
            </button>
          )}
        </div>
        {/* content */}
        <pre className="flex-1 p-4 text-[13px] font-mono overflow-auto whitespace-pre-wrap text-gray-800 leading-relaxed">
          {isJson ? formatJson(fileData.content!) : fileData.content}
        </pre>
      </div>
    )
  }

  // ── render ───────────────────────────────────────────────────────────

  return (
    <div className="flex-1 flex min-h-0">
      {/* tree panel */}
      <div className="w-[240px] border-r border-gray-200 bg-[#fafafa] flex flex-col overflow-hidden shrink-0">
        <div className="px-3 py-2.5 text-[11px] text-gray-400 font-medium border-b border-gray-200/80 shrink-0">
          工作空间
        </div>
        <div className="flex-1 overflow-y-auto py-1">
          {loading ? (
            <div className="px-3 py-2 text-[12px] text-gray-400">
              加载中...
            </div>
          ) : tree ? (
            renderTreeNode(tree, 0)
          ) : (
            <div className="px-3 py-2 text-[12px] text-gray-400">
              加载失败
            </div>
          )}
        </div>
      </div>

      {/* preview / editor panel */}
      {renderContent()}
    </div>
  )
}

// ── small helpers ──────────────────────────────────────────────────────

function FolderIconSmall() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="#0284c7"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="shrink-0"
    >
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
    </svg>
  )
}

function FileIcon({ name }: { name: string }) {
  const ext = name.split('.').pop()?.toLowerCase()
  const color =
    ext === 'md'
      ? '#6366f1'
      : ext === 'json'
        ? '#f59e0b'
        : ext === 'js' || ext === 'ts' || ext === 'py'
          ? '#10b981'
          : ext === 'docx' || ext === 'pptx'
            ? '#3b82f6'
            : '#9ca3af'
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="shrink-0"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  )
}

function DocIcon() {
  return (
    <svg
      width="48"
      height="48"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    </svg>
  )
}

function formatJson(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return text
  }
}
