/* eslint-disable react/prop-types */
import './ui.css'

/**
 * 加载状态
 *
 * 用法：
 * <LoadingState text="加载中…" />
 * <LoadingState inline />
 */
export default function LoadingState({ text = '加载中…', inline = false, className = '' }) {
  if (inline) {
    return (
      <div className={`ui-state-loading-inline ${className}`}>
        <span className="ui-spinner" aria-hidden="true" />
        <span>{text}</span>
      </div>
    )
  }
  return (
    <div className={`ui-state-loading ${className}`} role="status" aria-live="polite">
      <span className="ui-spinner ui-spinner-lg" aria-hidden="true" />
      <p>{text}</p>
    </div>
  )
}
