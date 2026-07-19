/**
 * XiaoPaw v2 前端 UX 优化组件库
 *
 * 包含以下组件：
 * 1. LoadingStates - 多种加载状态动画（骨架屏/脉冲/进度条）
 * 2. ErrorDisplay - 分类错误提示组件
 * 3. ProgressIndicator - 分步操作进度指示器
 * 4. useAsyncStatus - 自定义 Hook（管理异步操作状态）
 *
 * @version 1.0.0 (2026-07-01)
 * @description 提升用户体验，减少等待焦虑，提供清晰的操作反馈
 */

import React, { useState, useEffect, useCallback, ReactNode } from 'react';

// ══════════════════════════════════════════════════════════════
// 类型定义
// ══════════════════════════════════════════════════════════════

export type LoadingVariant = 'skeleton' | 'pulse' | 'spinner' | 'dots' | 'bars';

export type ErrorType =
  | 'network_timeout'
  | 'permission_denied'
  | 'quota_exceeded'
  | 'loop_detected'
  | 'server_error'
  | 'unknown';

export type StepId = string;

export interface Step {
  id: StepId;
  label: string;
  status: 'pending' | 'active' | 'completed' | 'error';
}

// ══════════════════════════════════════════════════════════════
// 错误信息配置映射
// ══════════════════════════════════════════════════════════════

export const ERROR_CONFIGS: Record<ErrorType, { title: string; message: string; icon: string; suggestion?: string }> = {
  network_timeout: {
    title: '连接超时',
    message: '网络请求超时，服务器响应时间过长。请检查网络连接后重试。',
    icon: '⏰',
    suggestion: '请检查：\n1. 网络连接是否正常\n2. 服务是否正常运行\n3. 防火墙是否阻止了请求',
  },
  permission_denied: {
    title: '权限不足',
    message: '您没有权限执行此操作。请联系管理员获取相应权限。',
    icon: '🔒',
    suggestion: '当前角色可能需要 admin/editor 权限才能执行此操作',
  },
  quota_exceeded: {
    title: '额度已用完',
    message: '今日 AI 调用额度已耗尽，明天将自动重置。感谢您的使用！',
    icon: '📊',
    suggestion: '升级账户可增加每日配额限制',
  },
  loop_detected: {
    title: '检测到重复回答模式',
    message: '系统检测到异常的重复回复模式，已自动终止本轮对话以避免资源浪费。',
    icon: '🔄',
    suggestion: '建议重新表述您的问题或换个角度提问',
  },
  server_error: {
    title: '服务器错误',
    message: '服务端发生内部错误，我们的技术团队已收到通知并正在处理中。',
    icon: '⚠️',
    suggestion: '请稍后再试，如问题持续存在请联系技术支持',
  },
  unknown: {
    title: '未知错误',
    message: '发生了未预期的错误，请重试或联系技术支持。',
    icon: '❓',
  },
};

// ══════════════════════════════════════════════════════════════
// 1. LoadingStates 组件
// ══════════════════════════════════════════════════════════════

interface LoadingStatesProps {
  variant?: LoadingVariant;
  text?: string;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
  fullscreen?: boolean;
}

/**
 * 多种加载状态动画组件
 *
 * @example
 * // 基础用法
 * <LoadingStates variant="spinner" text="加载中..." />
 *
 * // 全屏遮罩
 * <LoadingStates variant="pulse" text="正在处理..." fullscreen />
 */
export function LoadingStates({
  variant = 'skeleton',
  text = '加载中...',
  size = 'md',
  className = '',
  fullscreen = false,
}: LoadingStatesProps) {
  const [dotIndex, setDotIndex] = useState(0);

  // 动画点效果
  useEffect(() => {
    if (variant !== 'dots') return;
    const interval = setInterval(() => {
      setDotIndex((prev) => (prev + 1) % 4);
    }, 400);
    return () => clearInterval(interval);
  }, [variant]);

  const sizeClasses = {
    sm: 'w-4 h-4 text-sm',
    md: 'w-8 h-8 text-base',
    lg: 'w-12 h-12 text-lg',
  };

  const containerClass = fullscreen
    ? 'fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50'
    : `flex items-center justify-center ${className}`;

  const renderSpinner = () => (
    <div className={`${sizeClasses[size]} animate-spin rounded-full border-2 border-gray-200 border-t-blue-500`} />
  );

  const renderPulse = () => (
    <div className="space-y-2 w-full max-w-md">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-3 bg-gradient-to-r from-gray-200 via-gray-100 to-gray-200 rounded animate-pulse"
          style={{ animationDelay: `${i * 0.15}s`, width: `${80 - i * 15}%` }}
        />
      ))}
    </div>
  );

  const renderSkeleton = () => (
    <div className="space-y-3 w-full">
      {/* 模拟消息气泡 */}
      <div className="flex gap-3">
        <div className="w-8 h-8 rounded-full bg-gray-200 animate-pulse" />
        <div className="flex-1 space-y-2">
          <div className="h-4 bg-gray-200 rounded animate-pulse w-3/4" />
          <div className="h-4 bg-gray-200 rounded animate-pulse w-1/2" />
        </div>
      </div>
      {/* 模拟输入框 */}
      <div className="h-10 bg-gray-100 rounded-lg animate-pulse ml-11" />
    </div>
  );

  const renderDots = () => (
    <div className={`flex items-center gap-1 ${sizeClasses[size]}`}>
      {[0, 1, 2, 3].map((i) => (
        <span
          key={i}
          className={`inline-block w-2 h-2 rounded-full transition-all duration-300 ${
            i <= dotIndex ? 'bg-blue-500 scale-110' : 'bg-gray-300'
          }`}
        />
      ))}
    </div>
  );

  const renderBars = () => (
    <div className="flex items-end gap-1 h-6">
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className="w-1.5 bg-blue-500 rounded-full animate-bounce"
          style={{
            height: `${60 + Math.random() * 40}%`,
            animationDelay: `${i * 0.1}s`,
          }}
        />
      ))}
    </div>
  );

  const variantRenderers: Record<LoadingVariant, ReactNode> = {
    skeleton: renderSkeleton(),
    pulse: renderPulse(),
    spinner: renderSpinner(),
    dots: renderDots(),
    bars: renderBars(),
  };

  return (
    <div className={containerClass} role="status" aria-label={text}>
      <div className="flex flex-col items-center gap-3">
        {variantRenderers[variant]}
        {text && (
          <p className="text-gray-600 text-sm font-medium animate-pulse">
            {text}
            {variant === 'dots' && '.'.repeat(dotIndex + 1)}
          </p>
        )}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════
// 2. ErrorDisplay 组件
// ══════════════════════════════════════════════════════════════

interface ErrorDisplayProps {
  errorType: ErrorType;
  customMessage?: string;
  onRetry?: () => void;
  showDetails?: boolean;
  details?: ReactNode;
  className?: string;
}

/**
 * 分类错误展示组件
 *
 * 根据错误类型显示对应的图标、标题和建议信息。
 */
export function ErrorDisplay({
  errorType,
  customMessage,
  onRetry,
  showDetails = false,
  details,
  className = '',
}: ErrorDisplayProps) {
  const config = ERROR_CONFIGS[errorType];
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className={`rounded-xl border border-red-200 bg-red-50 p-5 ${className}`}
      role="alert"
    >
      {/* 头部：图标 + 标题 */}
      <div className="flex items-start gap-3 mb-3">
        <span className="text-2xl" role="img" aria-label={`${config.title} icon`}>
          {config.icon}
        </span>
        <div className="flex-1">
          <h3 className="font-semibold text-red-800">{config.title}</h3>
          <p className="mt-1 text-sm text-red-700">{customMessage || config.message}</p>
        </div>

        {/* 折叠按钮 */}
        {(showDetails || details || config.suggestion) && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-red-600 hover:text-red-800 text-sm font-medium underline"
            aria-expanded={expanded}
          >
            {expanded ? '收起详情' : '查看详情'}
          </button>
        )}
      </div>

      {/* 展开内容：建议和详细信息 */}
      {expanded && (
        <div className="mt-3 pt-3 border-t border-red-200 space-y-3">
          {config.suggestion && (
            <div className="bg-white/60 rounded-lg p-3">
              <p className="font-medium text-red-800 text-sm">💡 建议：</p>
              <p className="mt-1 text-sm text-red-700 whitespace-pre-line">{config.suggestion}</p>
            </div>
          )}

          {details && (
            <div className="bg-gray-900 text-green-400 rounded-lg p-3 font-mono text-xs overflow-x-auto">
              {details}
            </div>
          )}

          {/* 重试按钮 */}
          {onRetry && (
            <button
              onClick={onRetry}
              className="inline-flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg font-medium text-sm transition-colors"
            >
              🔄 重试
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════
// 3. ProgressIndicator 组件
// ══════════════════════════════════════════════════════════════

interface ProgressIndicatorProps {
  steps: Step[];
  currentStepId?: StepId;
  className?: string;
}

/**
 * 分步操作进度指示器
 *
 * 显示多步操作的执行状态（pending → active → completed/error）
 *
 * @example
 * const steps = [
 *   { id: 'understand', label: '理解需求', status: 'completed' },
 *   { id: 'skill', label: '调用 Skill', status: 'active' },
 *   { id: 'generate', label: '生成回复', status: 'pending' },
 * ];
 * <ProgressIndicator steps={steps} currentStepId="skill" />
 */
export function ProgressIndicator({ steps, currentStepId, className = '' }: ProgressIndicatorProps) {
  const currentIndex = steps.findIndex((s) => s.id === currentStepId);
  const activeCount = currentIndex >= 0 ? currentIndex : steps.findIndex((s) => s.status === 'active');

  return (
    <div className={`w-full ${className}`} role="progressbar" aria-valuenow={activeCount + 1} aria-valuemax={steps.length}>
      {/* 步骤列表 */}
      <div className="flex items-center justify-between mb-2">
        {steps.map((step, idx) => {
          const isCompleted = step.status === 'completed';
          const isActive = step.status === 'active';
          const isError = step.status === 'error';
          const isPending = step.status === 'pending';

          let icon = '';
          if (isCompleted) icon = '✅';
          else if (isError) icon = '❌';
          else if (isActive) icon = '⏳';
          else icon = '⏸️';

          return (
            <React.Fragment key={step.id}>
              {/* 步骤节点 */}
              <div className="flex flex-col items-center flex-1">
                <span className={`text-lg ${isActive ? 'animate-pulse' : ''}`}>{icon}</span>
                <span
                  className={`mt-1 text-xs font-medium text-center ${
                    isCompleted ? 'text-green-600' :
                    isError ? 'text-red-600' :
                    isActive ? 'text-blue-600 font-bold' :
                    'text-gray-400'
                  }`}
                >
                  {step.label}
                </span>
              </div>

              {/* 连接线 */}
              {idx < steps.length - 1 && (
                <div className={`flex-1 h-0.5 mx-2 rounded ${
                  isCompleted ? 'bg-green-500' :
                  isActive ? 'bg-blue-500' :
                  'bg-gray-200'
                }`} />
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* 文字说明 */}
      {currentStepId && (
        <p className="text-sm text-gray-500 text-center mt-2">
          正在{steps[activeCount]?.label ?? '处理中'}...
        </p>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════
// 4. useAsyncStatus 自定义 Hook
// ══════════════════════════════════════════════════════════════

interface AsyncStatus<T = any> {
  isLoading: boolean;
  data: T | null;
  error: Error | null;
  execute: (...args: any[]) => Promise<T>;
  reset: () => void;
}

/**
 * 异步操作状态管理 Hook
 *
 * 封装 loading/error/success 三种状态，
 * 自动追踪异步操作的完整生命周期。
 *
 * @example
 * const { isLoading, error, data, execute } = useAsyncStatus<string>();
 *
 * const handleClick = async () => {
 *   try {
 *     const result = await execute(fetchData, arg1, arg2);
 *     console.log(result); // 成功结果
 *   } catch (e) {
 *     console.error(e); // 已通过 error 状态捕获
 *   }
 * };
 */
export function useAsyncStatus<T = any>(): AsyncStatus<T> {
  const [isLoading, setIsLoading] = useState(false);
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const execute = useCallback(async (asyncFn: (...args: any[]) => Promise<T>, ...args: any[]): Promise<T> => {
    setIsLoading(true);
    setError(null);

    try {
      const result = await asyncFn(...args);
      setData(result);
      setIsLoading(false);
      return result;
    } catch (err) {
      const errorObj = err instanceof Error ? err : new Error(String(err));
      setError(errorObj);
      setIsLoading(false);
      throw errorObj; // 重新抛出以便调用者处理
    }
  }, []);

  const reset = useCallback(() => {
    setIsLoading(false);
    setData(null);
    setError(null);
  }, []);

  return { isLoading, data, error, execute, reset };
}

// ══════════════════════════════════════════════════════════════
// 导出所有组件
// ══════════════════════════════════════════════════════════════

export default {
  LoadingStates,
  ErrorDisplay,
  ProgressIndicator,
  useAsyncStatus,
};
