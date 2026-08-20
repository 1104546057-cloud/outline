/* eslint-disable react/prop-types */
import './ui.css'

/**
 * 状态标签
 *
 * 用法：
 * <StatusBadge status="online" label="在线" />
 * <StatusBadge status="warning" label="告警" />
 */
export default function StatusBadge({ status = 'default', label, children, size = 'sm' }) {
  return (
    <span className={`ui-status-badge ui-status-${status} ui-status-badge-${size}`}>
      <i className="ui-status-badge-dot" />
      {label || children}
    </span>
  )
}
