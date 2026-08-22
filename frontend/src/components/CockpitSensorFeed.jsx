/* eslint-disable react/prop-types */
import { useEffect, useRef, useState } from 'react'
import { authFetch } from '../utils/authFetch'
import '../styles/DeviceCockpit.css'

const JPEG_START = [0xff, 0xd8]
const JPEG_END = [0xff, 0xd9]

function findMarker(bytes, marker, from = 0) {
  for (let index = from; index < bytes.length - 1; index += 1) {
    if (bytes[index] === marker[0] && bytes[index + 1] === marker[1]) return index
  }
  return -1
}

function appendBytes(left, right) {
  const combined = new Uint8Array(left.length + right.length)
  combined.set(left)
  combined.set(right, left.length)
  return combined
}

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

export function CameraFeed({ device, label, view = null, unavailableText = '', simulated = false, large = false, refreshKey = 0, onStatusChange, lowLatency = false }) {
  const [status, setStatus] = useState('loading')
  const imageRef = useRef(null)
  const streamEnabled = Boolean(view)

  useEffect(() => {
    setStatus(streamEnabled && device?.status === 'online' ? 'loading' : 'offline')
  }, [device?.id, device?.status, refreshKey, streamEnabled])

  useEffect(() => {
    onStatusChange?.(status)
  }, [onStatusChange, status])

  const streamUrl = device && streamEnabled ? `/api/devices/${device.id}/camera/stream?view=${view}&retry=${refreshKey}` : ''

  useEffect(() => {
    if (!lowLatency || !streamUrl || device?.status !== 'online') return undefined

    const controller = new AbortController()
    const image = imageRef.current
    let buffer = new Uint8Array(0)
    let currentObjectUrl = ''
    let decodingObjectUrl = ''
    let pendingFrame = null
    let receivedFrame = false

    const renderPendingFrame = () => {
      if (!image || decodingObjectUrl || !pendingFrame) return
      const frame = pendingFrame
      pendingFrame = null
      decodingObjectUrl = URL.createObjectURL(new Blob([frame], { type: 'image/jpeg' }))
      image.onload = () => {
        const previousObjectUrl = currentObjectUrl
        currentObjectUrl = decodingObjectUrl
        decodingObjectUrl = ''
        if (previousObjectUrl) URL.revokeObjectURL(previousObjectUrl)
        if (!receivedFrame) {
          receivedFrame = true
          setStatus('streaming')
        }
        renderPendingFrame()
      }
      image.onerror = () => {
        URL.revokeObjectURL(decodingObjectUrl)
        decodingObjectUrl = ''
        renderPendingFrame()
      }
      image.src = decodingObjectUrl
    }

    const renderLatestFrame = frame => {
      pendingFrame = frame
      renderPendingFrame()
    }

    const consumeStream = async () => {
      try {
        const response = await authFetch(streamUrl, {
          cache: 'no-store',
          signal: controller.signal,
        })
        if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)
        const reader = response.body.getReader()

        while (!controller.signal.aborted) {
          const { value, done } = await reader.read()
          if (done) throw new Error('视频流已断开')
          buffer = appendBytes(buffer, value)

          let latestFrame = null
          let consumed = 0
          let searchFrom = 0
          while (true) {
            const start = findMarker(buffer, JPEG_START, searchFrom)
            if (start < 0) break
            const end = findMarker(buffer, JPEG_END, start + 2)
            if (end < 0) {
              if (start > 0) buffer = buffer.slice(start)
              consumed = 0
              break
            }
            consumed = end + 2
            latestFrame = buffer.slice(start, consumed)
            searchFrom = consumed
          }

          if (consumed > 0) buffer = buffer.slice(consumed)
          else if (!latestFrame && buffer.length > 5 * 1024 * 1024) buffer = buffer.slice(-1)
          if (latestFrame) renderLatestFrame(latestFrame)
        }
      } catch {
        if (!controller.signal.aborted) setStatus('error')
      }
    }

    consumeStream()
    return () => {
      controller.abort()
      if (image) {
        image.onload = null
        image.onerror = null
      }
      if (currentObjectUrl) URL.revokeObjectURL(currentObjectUrl)
      if (decodingObjectUrl) URL.revokeObjectURL(decodingObjectUrl)
    }
  }, [device?.status, lowLatency, streamUrl])

  return (
    <div className={`cockpit-camera ${large ? 'large' : ''} ${simulated ? 'simulated' : ''}`}>
      {streamEnabled && device?.status === 'online' && status !== 'error' ? (
        <img
          ref={imageRef}
          key={streamUrl}
          src={lowLatency ? undefined : streamUrl}
          alt={`${device.name}${label}`}
          onLoad={lowLatency ? undefined : () => setStatus('streaming')}
          onError={lowLatency ? undefined : () => setStatus('error')}
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
