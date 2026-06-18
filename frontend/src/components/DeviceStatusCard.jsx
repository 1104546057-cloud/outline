/* eslint-disable react/prop-types */
import '../styles/DeviceStatusCard.css'

const STATUS_LABEL = {
  online: '在线',
  offline: '离线',
  warning: '告警',
}

const getTypeInfo = (type = '') => {
  if (type.includes('机') || type.includes('drone')) return { label: '无人机', icon: '▲' }
  if (type.includes('船') || type.includes('ship')) return { label: '无人船', icon: '◆' }
  return { label: '无人车', icon: '●' }
}

const formatLastSeen = value => {
  if (!value) return '暂无上报'
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000))
  if (seconds < 60) return `${seconds} 秒前`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  return new Date(value).toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function MetricBar({ label, value, tone = 'cyan' }) {
  const safeValue = value == null ? 0 : Math.max(0, Math.min(100, Number(value)))
  return (
    <div className="metric-bar-row">
      <span>{label}</span>
      <div className="metric-bar-track"><i className={tone} style={{ width: `${safeValue}%` }} /></div>
      <strong>{value == null ? '--' : `${value}%`}</strong>
    </div>
  )
}

export default function DeviceStatusCard({ device, selected = false, onClick, onDoubleClick, className = '' }) {
  const info = getTypeInfo(device.type)
  return (
    <button
      type="button"
      className={`overview-device ${selected ? 'selected' : ''} ${className}`.trim()}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
    >
      <div className="overview-device-head">
        <span className={`device-symbol ${device.status}`}>{info.icon}</span>
        <div className="device-main">
          <strong>{device.name}</strong>
          <small>{info.label} · Agent {device.control_connected ? '控制已连接' : '等待连接'}</small>
        </div>
        <span className={`status-pill ${device.status}`}>{STATUS_LABEL[device.status] || '离线'}</span>
      </div>
      <div className="device-telemetry">
        <MetricBar label="电量" value={device.battery} tone={device.battery != null && device.battery < 25 ? 'red' : 'cyan'} />
        <MetricBar label="信号" value={device.signal} tone="blue" />
      </div>
      <div className="device-details">
        <span>健康度 <b>{device.health ?? '--'}%</b></span>
        <span>速度 <b>{device.speed || '0 m/s'}</b></span>
        <span>上报 <b>{formatLastSeen(device.last_seen)}</b></span>
      </div>
    </button>
  )
}
