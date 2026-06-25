import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CameraFeed, CockpitPanel } from '../components/CockpitSensorFeed'
import ThemedSelect from '../components/ThemedSelect'
import { authFetch } from '../utils/authFetch'
import '../styles/Patrol.css'

const degToRad = value => (Number(value) * Math.PI) / 180

const formatNumber = value => (
  Number.isFinite(value) ? value.toFixed(3) : '--'
)

const formatMapDisplayName = name => String(name || '').replace(/\.yaml$/i, '')

function decodeGray8(base64) {
  const binary = atob(base64 || '')
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  return bytes
}

function previewToMap(preview, px, py) {
  const [originX = 0, originY = 0, originYaw = 0] = preview.origin || []
  const scale = preview.previewScale || 1
  const resolution = Number(preview.resolution || 0)
  const localX = px * scale * resolution
  const localY = (preview.height - py * scale) * resolution
  const cos = Math.cos(originYaw)
  const sin = Math.sin(originYaw)
  return {
    x: originX + localX * cos - localY * sin,
    y: originY + localX * sin + localY * cos,
  }
}

function mapToPreview(preview, x, y) {
  const [originX = 0, originY = 0, originYaw = 0] = preview.origin || []
  const scale = preview.previewScale || 1
  const resolution = Number(preview.resolution || 0)
  const dx = x - originX
  const dy = y - originY
  const cos = Math.cos(originYaw)
  const sin = Math.sin(originYaw)
  const localX = dx * cos + dy * sin
  const localY = -dx * sin + dy * cos
  return {
    px: localX / resolution / scale,
    py: (preview.height - localY / resolution) / scale,
  }
}

function drawArrow(ctx, px, py, yaw, fillStyle, radius = 18) {
  ctx.save()
  ctx.translate(px, py)
  ctx.rotate(yaw)
  ctx.fillStyle = fillStyle
  ctx.strokeStyle = '#fff'
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(radius, 0)
  ctx.lineTo(-radius * 0.55, -radius * 0.45)
  ctx.lineTo(-radius * 0.32, 0)
  ctx.lineTo(-radius * 0.55, radius * 0.45)
  ctx.closePath()
  ctx.fill()
  ctx.stroke()
  ctx.restore()
}

export default function PatrolNavigation() {
  const canvasRef = useRef(null)
  const [devices, setDevices] = useState([])
  const [selectedDeviceId, setSelectedDeviceId] = useState('')
  const [maps, setMaps] = useState([])
  const [selectedMap, setSelectedMap] = useState('')
  const [preview, setPreview] = useState(null)
  const [previewPixels, setPreviewPixels] = useState(null)
  const [target, setTarget] = useState(null)
  const [yawDeg, setYawDeg] = useState(0)
  const [navStatus, setNavStatus] = useState(null)
  const [loadingDevices, setLoadingDevices] = useState(true)
  const [loadingMaps, setLoadingMaps] = useState(false)
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [busyAction, setBusyAction] = useState('')
  const [message, setMessage] = useState('')

  const selectedDevice = useMemo(
    () => devices.find(device => String(device.id) === String(selectedDeviceId)),
    [devices, selectedDeviceId],
  )
  const robotPose = navStatus?.pose && Number.isFinite(navStatus.pose.x) && Number.isFinite(navStatus.pose.y)
    ? navStatus.pose
    : null

  const drawMap = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas || !preview || !previewPixels) return
    canvas.width = preview.previewWidth
    canvas.height = preview.previewHeight
    const ctx = canvas.getContext('2d')
    const imageData = ctx.createImageData(preview.previewWidth, preview.previewHeight)
    for (let i = 0; i < previewPixels.length; i += 1) {
      const value = previewPixels[i]
      const offset = i * 4
      imageData.data[offset] = value
      imageData.data[offset + 1] = value
      imageData.data[offset + 2] = value
      imageData.data[offset + 3] = 255
    }
    ctx.putImageData(imageData, 0, 0)
    if (robotPose) {
      const { px, py } = mapToPreview(preview, robotPose.x, robotPose.y)
      drawArrow(ctx, px, py, robotPose.yaw || 0, '#22c55e', 18)
      ctx.beginPath()
      ctx.arc(px, py, 5, 0, Math.PI * 2)
      ctx.fillStyle = '#dfffee'
      ctx.fill()
    }
    if (!target) return
    const { px, py } = mapToPreview(preview, target.x, target.y)
    drawArrow(ctx, px, py, degToRad(yawDeg), '#ff4f64', 16)
    ctx.beginPath()
    ctx.arc(px, py, 5, 0, Math.PI * 2)
    ctx.fillStyle = '#22d3ee'
    ctx.fill()
  }, [preview, previewPixels, robotPose, target, yawDeg])

  const loadDevices = useCallback(async () => {
    setLoadingDevices(true)
    try {
      const response = await authFetch('/api/devices')
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      setDevices(data)
      const preferred = data.find(device => device.control_connected) || data.find(device => device.status === 'online') || data[0]
      if (preferred) setSelectedDeviceId(current => current || String(preferred.id))
    } catch (error) {
      setMessage(`加载设备失败：${error.message}`)
    } finally {
      setLoadingDevices(false)
    }
  }, [])

  const loadStatus = useCallback(async () => {
    if (!selectedDeviceId) return
    try {
      const response = await authFetch(`/api/navigation/status?robotId=${selectedDeviceId}`)
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      setNavStatus(data.response)
    } catch (error) {
      setNavStatus(null)
    }
  }, [selectedDeviceId])

  const loadMaps = useCallback(async () => {
    if (!selectedDeviceId) return
    setLoadingMaps(true)
    setMaps([])
    setSelectedMap('')
    setPreview(null)
    setPreviewPixels(null)
    setTarget(null)
    try {
      const response = await authFetch(`/api/navigation/maps?robotId=${selectedDeviceId}`)
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      const nextMaps = data.maps || []
      setMaps(nextMaps)
      if (nextMaps[0]?.name) setSelectedMap(nextMaps[0].name)
      setMessage(nextMaps.length ? '' : '车端 slam_map 目录暂无地图')
    } catch (error) {
      setMessage(`加载地图失败：${error.message}`)
    } finally {
      setLoadingMaps(false)
    }
  }, [selectedDeviceId])

  const loadPreview = useCallback(async () => {
    if (!selectedDeviceId || !selectedMap) return
    setLoadingPreview(true)
    setPreview(null)
    setPreviewPixels(null)
    setTarget(null)
    try {
      const response = await authFetch('/api/navigation/map-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robotId: Number(selectedDeviceId), mapName: selectedMap }),
      })
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      setPreview(data.preview)
      setPreviewPixels(decodeGray8(data.preview.data))
      setMessage('')
    } catch (error) {
      setMessage(`加载地图预览失败：${error.message}`)
    } finally {
      setLoadingPreview(false)
    }
  }, [selectedDeviceId, selectedMap])

  useEffect(() => { loadDevices() }, [loadDevices])
  useEffect(() => { loadMaps(); loadStatus() }, [loadMaps, loadStatus])
  useEffect(() => { loadPreview() }, [loadPreview])
  useEffect(() => { drawMap() }, [drawMap])
  useEffect(() => {
    if (!selectedDeviceId) return undefined
    const timer = setInterval(loadStatus, 1500)
    return () => clearInterval(timer)
  }, [loadStatus, selectedDeviceId])

  const runAction = async (action, request) => {
    if (!selectedDeviceId) return
    setBusyAction(action)
    setMessage('')
    try {
      const response = await authFetch(`/api/navigation/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      })
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      if (data.response?.type === 'nav_status') setNavStatus(data.response)
      setMessage(action === 'goal' ? '目标点已发送' : '指令已下发')
      await loadStatus()
    } catch (error) {
      setMessage(`指令失败：${error.message}`)
    } finally {
      setBusyAction('')
    }
  }

  const startNavigation = () => runAction('start', {
    robotId: Number(selectedDeviceId),
    mapName: selectedMap,
  })

  const stopNavigation = () => runAction('stop', {
    robotId: Number(selectedDeviceId),
  })

  const sendGoal = () => {
    if (!target) return
    runAction('goal', {
      robotId: Number(selectedDeviceId),
      x: target.x,
      y: target.y,
      yaw: degToRad(yawDeg),
    })
  }

  const handleCanvasClick = event => {
    if (!preview) return
    const rect = event.currentTarget.getBoundingClientRect()
    const px = ((event.clientX - rect.left) / rect.width) * preview.previewWidth
    const py = ((event.clientY - rect.top) / rect.height) * preview.previewHeight
    const point = previewToMap(preview, px, py)
    setTarget(point)
  }

  return (
    <div className="patrol-page patrol-navigation-page">
      <div className="patrol-header">
        <div className="patrol-header-left">
          <h1>巡检导航</h1>
          <span className="patrol-subtitle">SLAM 地图目标点导航</span>
        </div>
        <div className="patrol-header-actions">
          <ThemedSelect
            className="patrol-header-select"
            value={selectedDeviceId}
            onChange={event => setSelectedDeviceId(event.target.value)}
            disabled={loadingDevices}
          >
            <option value="">选择设备</option>
            {devices.map(device => (
              <option key={device.id} value={device.id}>
                {device.name} · {device.control_connected ? '控制已连接' : device.status}
              </option>
            ))}
          </ThemedSelect>
          <button className="patrol-btn patrol-btn-secondary" onClick={loadDevices} disabled={loadingDevices}>刷新设备</button>
        </div>
      </div>

      <div className="patrol-body patrol-nav-layout">
        <aside className="patrol-sidebar patrol-nav-sidebar">
          <div className="patrol-sidebar-toolbar">
            <ThemedSelect
              className="patrol-header-select"
              value={selectedMap}
              onChange={event => setSelectedMap(event.target.value)}
              disabled={!selectedDeviceId || loadingMaps || maps.length === 0}
            >
              <option value="">选择地图</option>
              {maps.map(map => <option key={map.name} value={map.name}>{formatMapDisplayName(map.name)}</option>)}
            </ThemedSelect>
          </div>
          <div className="patrol-sidebar-list">
            <div className="patrol-card active">
              <div className="patrol-card-header">
                <span className="patrol-card-title">{selectedDevice?.name || '未选择设备'}</span>
              </div>
              <div className="patrol-card-meta">
                <span className="patrol-card-tag">{selectedDevice?.control_connected ? '控制已连接' : '控制未连接'}</span>
                <span className={`patrol-status-badge ${navStatus?.running ? 'patrol-status-running' : 'patrol-status-pending'}`}>
                  {navStatus?.running ? '导航运行中' : '导航未运行'}
                </span>
              </div>
              <div className="patrol-card-desc">
                地图：{formatMapDisplayName(navStatus?.mapName || selectedMap) || '--'}
              </div>
            </div>

            {preview && (
              <div className="patrol-nav-panel">
                <div className="patrol-nav-row"><span>分辨率</span><strong>{preview.resolution} m/px</strong></div>
                <div className="patrol-nav-row"><span>尺寸</span><strong>{preview.width} x {preview.height}</strong></div>
                <div className="patrol-nav-row"><span>原点</span><strong>{preview.origin?.slice(0, 2).map(formatNumber).join(', ')}</strong></div>
              </div>
            )}

            <div className="patrol-nav-panel">
              <label className="patrol-nav-label">当前车位</label>
              <div className="patrol-nav-coordinate">
                <span>X {formatNumber(robotPose?.x)}</span>
                <span>Y {formatNumber(robotPose?.y)}</span>
                <span>Yaw {robotPose ? Math.round((robotPose.yaw || 0) * 180 / Math.PI) : '--'}°</span>
              </div>
            </div>

            <div className="patrol-nav-panel patrol-nav-target-panel">
              <label className="patrol-nav-label">目标点</label>
              <div className="patrol-nav-coordinate">
                <span>X {formatNumber(target?.x)}</span>
                <span>Y {formatNumber(target?.y)}</span>
                <span>Yaw {yawDeg}°</span>
              </div>
              <input
                className="patrol-nav-range"
                type="range"
                min="-180"
                max="180"
                step="1"
                value={yawDeg}
                onChange={event => setYawDeg(Number(event.target.value))}
              />
              <div className="patrol-nav-heading-buttons">
                {[-180, -90, 0, 90, 180].map(value => (
                  <button key={value} className="patrol-btn patrol-btn-secondary patrol-btn-sm" onClick={() => setYawDeg(value)}>
                    {value}°
                  </button>
                ))}
              </div>
            </div>

            <div className="patrol-nav-actions">
              <button className="patrol-btn patrol-btn-primary" onClick={startNavigation} disabled={!selectedMap || busyAction === 'start'}>
                {busyAction === 'start' ? '启动中...' : '启动导航'}
              </button>
              <button className="patrol-btn patrol-btn-success" onClick={sendGoal} disabled={!target || busyAction === 'goal'}>
                {busyAction === 'goal' ? '发送中...' : '发送目标点'}
              </button>
              <button className="patrol-btn patrol-btn-warning" onClick={stopNavigation} disabled={busyAction === 'stop'}>
                停止导航
              </button>
            </div>

            {message && <div className="patrol-form-error">{message}</div>}
          </div>
        </aside>

        <section className="patrol-nav-map-section">
          <div className="patrol-map-container patrol-nav-map-container">
            {loadingPreview ? (
              <div className="patrol-loading"><div className="patrol-spinner" /><span>加载地图...</span></div>
            ) : preview ? (
              <canvas ref={canvasRef} className="patrol-nav-map-canvas" onClick={handleCanvasClick} />
            ) : (
              <div className="patrol-empty">
                <p>{selectedDeviceId ? '暂无可用地图' : '请选择设备'}</p>
              </div>
            )}

            {preview && (
              <div className="patrol-map-badge patrol-nav-map-info">
                <strong>SLAM 地图</strong>
                <span>分辨率：{preview.resolution} m/px</span>
                <span>尺寸：{preview.width} x {preview.height}</span>
                <span>原点：{preview.origin?.slice(0, 2).map(formatNumber).join(', ')}</span>
              </div>
            )}

            {target && (
              <div className="patrol-map-badge patrol-nav-target-badge">
                <strong>目标点</strong>
                <span>X：{formatNumber(target.x)} m</span>
                <span>Y：{formatNumber(target.y)} m</span>
                <span>Yaw：{yawDeg}°</span>
              </div>
            )}
            <div className="patrol-legend patrol-nav-legend">
              <div className="patrol-legend-item"><div className="patrol-legend-dot" style={{ background: '#22c55e' }} />当前车位</div>
              <div className="patrol-legend-item"><div className="patrol-legend-dot" style={{ background: '#ff4f64' }} />目标点</div>
            </div>
          </div>
        </section>

        <aside className="patrol-nav-sensors">
          <CockpitPanel title="彩色帧" code="COLOR" meta="01">
            <CameraFeed device={selectedDevice} label="彩色帧" view="color" />
          </CockpitPanel>
          <CockpitPanel title="深度图" code="DEPTH" meta="02">
            <CameraFeed device={selectedDevice} label="双目深度图" view="depth" />
          </CockpitPanel>
          <CockpitPanel title="激光雷达" code="LIDAR" meta="03">
            <CameraFeed device={selectedDevice} label="C16 16线点云" view="lidar" />
          </CockpitPanel>
        </aside>
      </div>
    </div>
  )
}
