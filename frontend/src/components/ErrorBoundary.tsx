/**
 * 全局 React 错误边界
 *
 * 捕获渲染阶段抛出的异常，避免整棵组件树白屏崩溃，
 * 并复用 ErrorDisplay 给出统一的错误提示与「重新加载」入口。
 */

import { Component, type ErrorInfo, type ReactNode } from 'react'
import { ErrorDisplay } from './UXComponents'

interface ErrorBoundaryProps {
  children: ReactNode
  /** 自定义兜底 UI；不传则使用默认 ErrorDisplay。 */
  fallback?: (error: Error, reset: () => void) => ReactNode
}

interface ErrorBoundaryState {
  error: Error | null
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 保留控制台栈信息，便于开发排查；生产环境可接入上报。
    console.error('[ErrorBoundary] uncaught render error:', error, info.componentStack)
  }

  reset = (): void => {
    this.setState({ error: null })
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children

    if (this.props.fallback) {
      return this.props.fallback(error, this.reset)
    }

    return (
      <div className="min-h-screen flex items-center justify-center p-6 bg-gray-50">
        <div className="w-full max-w-lg">
          <ErrorDisplay
            errorType="unknown"
            customMessage="页面渲染时发生错误，请重新加载。若问题持续存在，请联系技术支持。"
            showDetails
            details={error.message}
            onRetry={() => window.location.reload()}
          />
        </div>
      </div>
    )
  }
}

export default ErrorBoundary
