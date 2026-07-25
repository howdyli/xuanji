/**
 * CitationBadge —— 引用角标
 *
 * 渲染一个 `[n]` 角标；点击弹出对应引用片段（来源文档、定位、摘要）。
 * P0 用于知识库调试检索结果展示；后续可复用到聊天消息内联引用（P1）。
 */
import { useState } from 'react'
import type { Citation } from '../api/knowledge'

export function CitationBadge({
  citation,
  onOpenDocument,
}: {
  citation: Citation
  onOpenDocument?: (documentId: string) => void
}) {
  const [open, setOpen] = useState(false)

  return (
    <span className="relative inline-block align-baseline">
      <button
        type="button"
        aria-label={`引用 ${citation.n}`}
        onClick={() => setOpen(v => !v)}
        className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 mx-0.5 rounded
          bg-sky-50 text-sky-600 text-[11px] font-semibold align-super
          hover:bg-sky-100 transition-colors cursor-pointer"
      >
        {citation.n}
      </button>

      {open && (
        <>
          {/* 点击遮罩关闭 */}
          <span
            className="fixed inset-0 z-40"
            aria-hidden="true"
            onClick={() => setOpen(false)}
          />
          <span
            role="dialog"
            aria-label={`引用 ${citation.n} 详情`}
            className="absolute z-50 left-0 top-6 w-72 p-3 rounded-xl border border-gray-200
              bg-white shadow-lg text-left"
          >
            <span className="block text-[12.5px] font-semibold text-gray-800 truncate">
              [{citation.n}] {citation.title || '未命名文档'}
            </span>
            {citation.locator && (
              <span className="block text-[11px] text-gray-400 mt-0.5">{citation.locator}</span>
            )}
            <span className="block text-[12px] text-gray-600 mt-1.5 leading-relaxed max-h-32 overflow-y-auto">
              {citation.snippet}
            </span>
            {onOpenDocument && (
              <button
                type="button"
                onClick={() => { setOpen(false); onOpenDocument(citation.document_id) }}
                className="mt-2 text-[12px] text-sky-600 hover:text-sky-700 font-medium"
              >
                查看原文 →
              </button>
            )}
          </span>
        </>
      )}
    </span>
  )
}
