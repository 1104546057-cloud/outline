/* eslint-disable react/prop-types */
import './ui.css'

/**
 * 空状态
 *
 * 用法：
 * <EmptyState text="暂无设备" icon="◇" />
 */
export default function EmptyState({ text = '暂无数据', icon = '◇', description, action, className = '' }) {
  return (
    <div className={`ui-state-empty ${className}`}>
      <span className="ui-state-empty-icon" aria-hidden="true">{icon}</span>
      <p className="ui-state-empty-text">{text}</p>
      {description && <p className="ui-state-empty-desc">{description}</p>}
      {action && <div className="ui-state-empty-action">{action}</div>}
    </div>
  )
}
