import { useCallback, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'

// ── Copy button for code blocks ──────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* ignore */
    }
  }, [text])

  return (
    <button
      onClick={handleCopy}
      className="absolute top-2 right-2 px-2 py-1 rounded text-[11px] font-medium transition-all
        bg-gray-700/60 text-gray-300 hover:bg-gray-600 hover:text-white
        opacity-0 group-hover:opacity-100"
      title={copied ? '已复制' : '复制代码'}
    >
      {copied ? '✓ 已复制' : '复制'}
    </button>
  )
}

// ── Extract text content from React children ─────────────────────────

function extractText(children: React.ReactNode): string {
  if (typeof children === 'string') return children
  if (typeof children === 'number') return String(children)
  if (Array.isArray(children)) return children.map(extractText).join('')
  if (children && typeof children === 'object' && 'props' in children) {
    const el = children as { props?: { children?: React.ReactNode } }
    return extractText(el.props?.children)
  }
  return ''
}

// ── Language label from className ────────────────────────────────────

function getLangFromClassName(className?: string): string {
  if (!className) return ''
  const match = className.match(/language-(\w+)/)
  return match ? match[1] : ''
}

// ── Main Markdown Renderer ───────────────────────────────────────────

export function MarkdownRenderer({ content }: { content: string }) {
  return (
    <div className="md-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          // ── Code blocks ─────────────────────────────────────────
          pre({ children, ...props }) {
            const codeText = extractText(children)
            return (
              <div className="group relative my-3 rounded-xl overflow-hidden border border-gray-200 bg-[#1e1e2e]">
                <CopyButton text={codeText} />
                <pre
                  {...props}
                  className="px-4 py-3 overflow-x-auto text-[13px] leading-relaxed m-0"
                >
                  {children}
                </pre>
              </div>
            )
          },
          code({ className, children, ...props }) {
            const lang = getLangFromClassName(className)
            const isInline = !lang && !className
            if (isInline) {
              return (
                <code
                  className="px-1.5 py-0.5 rounded-md bg-gray-100 text-[#c7254e] text-[12.5px] font-mono"
                  {...props}
                >
                  {children}
                </code>
              )
            }
            return (
              <code className={className} {...props}>
                {children}
              </code>
            )
          },

          // ── Headings ────────────────────────────────────────────
          h1({ children, ...props }) {
            return (
              <h1 className="text-xl font-semibold text-gray-900 mt-5 mb-2 pb-1.5 border-b border-gray-200" {...props}>
                {children}
              </h1>
            )
          },
          h2({ children, ...props }) {
            return (
              <h2 className="text-lg font-semibold text-gray-800 mt-4 mb-2" {...props}>
                {children}
              </h2>
            )
          },
          h3({ children, ...props }) {
            return (
              <h3 className="text-base font-semibold text-gray-800 mt-3 mb-1.5" {...props}>
                {children}
              </h3>
            )
          },
          h4({ children, ...props }) {
            return (
              <h4 className="text-[14px] font-semibold text-gray-700 mt-2.5 mb-1" {...props}>
                {children}
              </h4>
            )
          },

          // ── Paragraph ───────────────────────────────────────────
          p({ children, ...props }) {
            return (
              <p className="mb-2.5 last:mb-0 leading-relaxed" {...props}>
                {children}
              </p>
            )
          },

          // ── Lists ───────────────────────────────────────────────
          ul({ children, ...props }) {
            return (
              <ul className="mb-2.5 pl-5 space-y-1 list-disc marker:text-gray-400" {...props}>
                {children}
              </ul>
            )
          },
          ol({ children, ...props }) {
            return (
              <ol className="mb-2.5 pl-5 space-y-1 list-decimal marker:text-gray-500 marker:font-medium" {...props}>
                {children}
              </ol>
            )
          },
          li({ children, ...props }) {
            return (
              <li className="leading-relaxed" {...props}>
                {children}
              </li>
            )
          },

          // ── Blockquote ──────────────────────────────────────────
          blockquote({ children, ...props }) {
            return (
              <blockquote
                className="my-3 pl-3.5 border-l-3 border-emerald-400 bg-emerald-50/50 py-2 pr-3 rounded-r-lg text-gray-600 italic"
                {...props}
              >
                {children}
              </blockquote>
            )
          },

          // ── Tables ──────────────────────────────────────────────
          table({ children, ...props }) {
            return (
              <div className="my-3 overflow-x-auto rounded-lg border border-gray-200">
                <table className="w-full text-[13px] border-collapse" {...props}>
                  {children}
                </table>
              </div>
            )
          },
          thead({ children, ...props }) {
            return (
              <thead className="bg-gray-50" {...props}>
                {children}
              </thead>
            )
          },
          th({ children, ...props }) {
            return (
              <th className="px-3 py-2 text-left font-semibold text-gray-700 border-b border-gray-200" {...props}>
                {children}
              </th>
            )
          },
          td({ children, ...props }) {
            return (
              <td className="px-3 py-2 border-b border-gray-100 text-gray-600" {...props}>
                {children}
              </td>
            )
          },

          // ── Links ───────────────────────────────────────────────
          a({ children, ...props }) {
            return (
              <a
                className="text-blue-600 hover:text-blue-800 underline decoration-blue-300 hover:decoration-blue-500 underline-offset-2 transition-colors"
                target="_blank"
                rel="noopener noreferrer"
                {...props}
              >
                {children}
              </a>
            )
          },

          // ── Horizontal rule ─────────────────────────────────────
          hr(props) {
            return <hr className="my-4 border-gray-200" {...props} />
          },

          // ── Strong / Em ─────────────────────────────────────────
          strong({ children, ...props }) {
            return (
              <strong className="font-semibold text-gray-900" {...props}>
                {children}
              </strong>
            )
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
