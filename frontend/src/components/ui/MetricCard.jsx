/* eslint-disable react/prop-types */
import './ui.css'

/**
 * 指标卡
 *
 * 用法：
 * <MetricCard label="在线设备" value="23" suffix="台" status="success" />
 * <MetricCard label="告警" value="6" status="warning" onClick={...} />
 */
export default function MetricCard({ label, value, suffix, status = 'default', icon, onClick, loading, className = '' }) {
  const clickable = Boolean(onClick)
  const Tag = clickable ? 'button' : 'div'
  return (
    <Tag
      className={`ui-metric-card ui-status-${status} ${clickable ? 'ui-metric-card-clickable' : ''} ${className}`}
      onClick={onClick}
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      disabled={loading}
    >
      {icon && <span className="ui-metric-card-icon">{icon}</span>}
      <div className="ui-metric-card-body">
        <div className="ui-metric-card-value">
          {loading ? <span className="ui-metric-card-skeleton" /> : value}
          {suffix && !loading && <small>{suffix}</small>}
        </div>
        <div className="ui-metric-card-label">{label}</div>
      </div>
    </Tag>
  )
}
