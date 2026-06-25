/* eslint-disable react/prop-types */
import { useEffect, useState } from 'react'
import '../styles/DeviceCockpit.css'

export function CockpitPanel({ title, code, meta, className = '', children }) {
  return (
    <section className={`cockpit-panel ${className}`}>
      <span className="cockpit-corner left" /><span className="cockpit-corner right" />
      <header className="cockpit-panel-head">
        <div><i /><strong>{title}</strong><small>{code}</small></div>
        {meta && <span>{meta}</span>}
      </header>
      <div className="cockpit-panel-body">{children}</div>
    </section>
  )
}

export function CameraFeed({ device, label, view = null, unavailableText = '', simulated = false, large = false, refreshKey = 0, onStatusChange }) {
  const [status, setStatus] = useState('loading')
  const streamEnabled = Boolean(view)

  useEffect(() => {
    setStatus(streamEnabled && device?.status === 'online' ? 'loading' : 'offline')
  }, [device?.id, device?.status, refreshKey, streamEnabled])

  useEffect(() => {
    onStatusChange?.(status)
  }, [onStatusChange, status])

  const streamUrl = device && streamEnabled ? `/api/devices/${device.id}/camera/stream?view=${view}&retry=${refreshKey}` : ''

  return (
    <div className={`cockpit-camera ${large ? 'large' : ''} ${simulated ? 'simulated' : ''}`}>
      {streamEnabled && device?.status === 'online' && status !== 'error' ? (
        <img
          key={streamUrl}
          src={streamUrl}
          alt={`${device.name}${label}`}
          onLoad={() => setStatus('streaming')}
          onError={() => setStatus('error')}
        />
      ) : (
        <div className="cockpit-camera-empty">
          <span className="cockpit-reticle" />
          <strong>{!streamEnabled ? unavailableText || '视频源待接入' : status === 'error' ? '视频流连接失败' : '设备当前离线'}</strong>
        </div>
      )}
      <div className="cockpit-camera-scan" />
      <div className="cockpit-camera-label">
        <span>{label}</span>
        <b className={status}>{!streamEnabled ? 'PENDING' : status === 'streaming' ? 'LIVE' : status === 'loading' ? 'CONNECTING' : status === 'error' ? 'ERROR' : 'OFFLINE'}</b>
      </div>
    </div>
  )
}
