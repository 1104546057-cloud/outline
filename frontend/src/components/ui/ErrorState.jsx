/* eslint-disable react/prop-types */
import './ui.css'

/**
 * 错误状态
 *
 * 用法：
 * <ErrorState message="请求失败" onRetry={handleRetry} />
 */
export default function ErrorState({ message = '加载失败', description, onRetry, className = '' }) {
  return (
    <div className={`ui-state-error ${className}`} role="alert">
      <span className="ui-state-error-icon" aria-hidden="true">!</span>
      <p className="ui-state-error-message">{message}</p>
      {description && <p className="ui-state-error-desc">{description}</p>}
      {onRetry && (
        <button className="ui-btn ui-btn-secondary ui-btn-sm" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  )
}
