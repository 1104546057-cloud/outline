/* eslint-disable react/prop-types */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ThemedSelect from '../components/ThemedSelect'
import { authFetch } from '../utils/authFetch'
import '../styles/Patrol.css'

const CONTROL_INTERVAL_MS = 220
const MAP_COLORS = {
  background: [3, 16, 37],
  unknown: [22, 58, 79],
  free: [28, 143, 176],
  occupied: [1, 8, 18],
}

const formatMapName = name => String(name || '').replace(/\.yaml$/i, '')

const formatDuration = seconds => {
  const value = Math.max(0, Number(seconds) || 0)
  const minutes = Math.floor(value / 60)
  const remain = value % 60
  return `${String(minutes).padStart(2, '0')}:${String(remain).padStart(2, '0')}`
}

function decodeGray8(base64) {
  const binary = atob(base64 || '')
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  return bytes
}

function mapPixel(gray) {
  if (gray >= 245) return MAP_COLORS.free
  if (gray >= 185 && gray <= 225) return MAP_COLORS.unknown
  if (gray <= 70) return MAP_COLORS.occupied
  const ratio = Math.max(0, Math.min(1, gray / 255))
  return [Math.round(8 + ratio * 20), Math.round(28 + ratio * 95), Math.round(45 + ratio * 100)]
}

function MapPreviewCanvas({ preview, emptyText }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !preview?.data) return undefined
    const pixels = decodeGray8(preview.data)
    const source = document.createElement('canvas')
    source.width = preview.previewWidth
    source.height = preview.previewHeight
    const sourceContext = source.getContext('2d')
    const image = sourceContext.createImageData(source.width, source.height)
    for (let index = 0; index < pixels.length; index += 1) {
      const [red, green, blue] = mapPixel(pixels[index])
      const offset = index * 4
      image.data[offset] = red
      image.data[offset + 1] = green
      image.data[offset + 2] = blue
      image.data[offset + 3] = 255
    }
    sourceContext.putImageData(image, 0, 0)

    const draw = () => {
      const rect = canvas.getBoundingClientRect()
      const ratio = window.devicePixelRatio || 1
      canvas.width = Math.max(1, Math.round(rect.width * ratio))
      canvas.height = Math.max(1, Math.round(rect.height * ratio))
      const context = canvas.getContext('2d')
      context.setTransform(ratio, 0, 0, ratio, 0, 0)
      context.fillStyle = `rgb(${MAP_COLORS.background.join(',')})`
      context.fillRect(0, 0, rect.width, rect.height)
      const scale = Math.min(rect.width / source.width, rect.height / source.height) * 0.94
      const width = source.width * scale
      const height = source.height * scale
      context.imageSmoothingEnabled = false
      context.drawImage(source, (rect.width - width) / 2, (rect.height - height) / 2, width, height)
    }
    draw()
    const observer = new ResizeObserver(draw)
    observer.observe(canvas)
    return () => observer.disconnect()
  }, [preview])

  return preview?.data
    ? <canvas ref={canvasRef} className="indoor-map-canvas" aria-label="地图预览" />
    : <div className="indoor-map-empty"><span>◇</span><p>{emptyText}</p></div>
}

function IndoorMapManagement() {
  const navigate = useNavigate()
  const [devices, setDevices] = useState([])
  const [selectedDeviceId, setSelectedDeviceId] = useState('')
  const [maps, setMaps] = useState([])
  const [selectedMap, setSelectedMap] = useState('')
  const [savedPreview, setSavedPreview] = useState(null)
  const [livePreview, setLivePreview] = useState(null)
  const [mappingStatus, setMappingStatus] = useState(null)
  const [mapName, setMapName] = useState('')
  const [busyAction, setBusyAction] = useState('')
  const [message, setMessage] = useState('')
  const [messageType, setMessageType] = useState('info')
  const controlTimerRef = useRef(null)
  const controlActiveRef = useRef(false)

  const selectedDevice = useMemo(
    () => devices.find(device => String(device.id) === selectedDeviceId),
    [devices, selectedDeviceId],
  )
  const mappingRunning = Boolean(mappingStatus?.running)
  const canDrive = mappingRunning && selectedDevice?.control_connected && !busyAction

  const notify = (text, type = 'info') => {
    setMessage(text)
    setMessageType(type)
  }

  const loadDevices = useCallback(async () => {
    try {
      const response = await authFetch('/api/devices')
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      setDevices(data)
      const preferred = data.find(device => device.control_connected) || data.find(device => device.status === 'online') || data[0]
      if (preferred) setSelectedDeviceId(current => current || String(preferred.id))
    } catch (error) {
      notify(`加载设备失败：${error.message}`, 'error')
    }
  }, [])

  const loadMaps = useCallback(async () => {
    if (!selectedDeviceId) return
    try {
      const response = await authFetch(`/api/navigation/maps?robotId=${selectedDeviceId}`)
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      const nextMaps = data.maps || []
      setMaps(nextMaps)
      setSelectedMap(current => nextMaps.some(map => map.name === current) ? current : (nextMaps[0]?.name || ''))
    } catch (error) {
      notify(`加载地图列表失败：${error.message}`, 'error')
    }
  }, [selectedDeviceId])

  const loadMappingStatus = useCallback(async () => {
    if (!selectedDeviceId) return
    try {
      const response = await authFetch(`/api/navigation/mapping/status?robotId=${selectedDeviceId}`)
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      setMappingStatus(data.response)
    } catch {
      setMappingStatus(null)
    }
  }, [selectedDeviceId])

  const loadSavedPreview = useCallback(async () => {
    if (!selectedDeviceId || !selectedMap) {
      setSavedPreview(null)
      return
    }
    try {
      const response = await authFetch('/api/navigation/map-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robotId: Number(selectedDeviceId), mapName: selectedMap }),
      })
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      if (!data.preview?.ok) throw new Error(data.preview?.error || '地图预览不可用')
      setSavedPreview(data.preview)
    } catch (error) {
      setSavedPreview(null)
      notify(`加载地图预览失败：${error.message}`, 'error')
    }
  }, [selectedDeviceId, selectedMap])

  const loadLivePreview = useCallback(async () => {
    if (!selectedDeviceId || !mappingStatus?.running) return
    try {
      const response = await authFetch(`/api/navigation/mapping/live-preview?robotId=${selectedDeviceId}`)
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      if (data.preview?.ok) setLivePreview(data.preview)
    } catch {
      // Mapper may need several seconds before publishing its first /map frame.
    }
  }, [mappingStatus?.running, selectedDeviceId])

  useEffect(() => { loadDevices() }, [loadDevices])
  useEffect(() => {
    setMaps([])
    setSelectedMap('')
    setSavedPreview(null)
    setLivePreview(null)
    setMappingStatus(null)
    loadMaps()
    loadMappingStatus()
  }, [loadMaps, loadMappingStatus])
  useEffect(() => { loadSavedPreview() }, [loadSavedPreview])
  useEffect(() => {
    if (!selectedDeviceId) return undefined
    const timer = window.setInterval(loadMappingStatus, 1500)
    return () => window.clearInterval(timer)
  }, [loadMappingStatus, selectedDeviceId])
  useEffect(() => {
    if (!mappingStatus?.running) return undefined
    loadLivePreview()
    const timer = window.setInterval(loadLivePreview, 1800)
    return () => window.clearInterval(timer)
  }, [loadLivePreview, mappingStatus?.running])

  const runMappingAction = async (action, body = {}) => {
    if (!selectedDeviceId) return null
    setBusyAction(action)
    try {
      const response = await authFetch(`/api/navigation/mapping/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robotId: Number(selectedDeviceId), ...body }),
      })
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      if (!data.ok) throw new Error(data.response?.error || '车端拒绝了操作')
      if (data.response?.type === 'map_status') setMappingStatus(data.response)
      return data
    } catch (error) {
      notify(`操作失败：${error.message}`, 'error')
      return null
    } finally {
      setBusyAction('')
    }
  }

  const startMapping = async () => {
    if (!window.confirm('开始建图会停止当前导航。请确认车辆周围安全、底盘和雷达工作正常，并由现场人员看护。')) return
    setLivePreview(null)
    const result = await runMappingAction('start')
    if (result) notify('建图已启动，请使用低速控制覆盖室内区域', 'success')
  }

  const pauseMapping = async () => {
    const result = await runMappingAction('pause')
    if (result) notify('车辆已停车，当前地图仍保留，可继续控制或保存', 'success')
  }

  const discardMapping = async () => {
    if (!window.confirm('确定放弃本次建图？尚未保存的地图数据将丢失。')) return
    const result = await runMappingAction('discard')
    if (result) {
      setLivePreview(null)
      notify('本次建图已放弃，车辆保持停车', 'success')
    }
  }

  const saveMapping = async () => {
    const cleanName = mapName.trim()
    if (!cleanName) {
      notify('请先填写地图名称', 'error')
      return
    }
    const result = await runMappingAction('save', { mapName: cleanName })
    if (result) {
      setMapName('')
      setLivePreview(null)
      await loadMaps()
      notify(`地图“${cleanName}”已保存到车端`, 'success')
    }
  }

  const deleteMap = async () => {
    if (!selectedMap || !window.confirm(`确定删除地图“${formatMapName(selectedMap)}”？此操作不能撤销。`)) return
    setBusyAction('delete')
    try {
      const response = await authFetch('/api/navigation/maps/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robotId: Number(selectedDeviceId), mapName: selectedMap }),
      })
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      if (!data.ok) throw new Error(data.response?.error || '车端拒绝删除地图')
      setSavedPreview(null)
      await loadMaps()
      notify('地图已删除', 'success')
    } catch (error) {
      notify(`删除失败：${error.message}`, 'error')
    } finally {
      setBusyAction('')
    }
  }

  const sendVelocity = useCallback(async (linear, angular) => {
    if (!selectedDeviceId) return
    try {
      await authFetch('/api/robot-control/cmd_vel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robotId: Number(selectedDeviceId), linear, angular }),
      })
    } catch (error) {
      notify(`低速控制失败：${error.message}`, 'error')
    }
  }, [selectedDeviceId])

  const releaseControl = useCallback(async (force = false) => {
    if (controlTimerRef.current) window.clearInterval(controlTimerRef.current)
    controlTimerRef.current = null
    if ((!controlActiveRef.current && !force) || !selectedDeviceId) return
    controlActiveRef.current = false
    try {
      await authFetch('/api/robot-control/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robotId: Number(selectedDeviceId) }),
      })
    } catch {
      // The vehicle-side watchdog also stops motion when commands cease.
    }
  }, [selectedDeviceId])

  const holdControl = (linear, angular) => {
    if (!canDrive) return
    releaseControl()
    controlActiveRef.current = true
    sendVelocity(linear, angular)
    controlTimerRef.current = window.setInterval(() => sendVelocity(linear, angular), CONTROL_INTERVAL_MS)
  }

  useEffect(() => {
    const stop = () => releaseControl()
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', stop)
    window.addEventListener('blur', stop)
    return () => {
      window.removeEventListener('pointerup', stop)
      window.removeEventListener('pointercancel', stop)
      window.removeEventListener('blur', stop)
      if (controlTimerRef.current) window.clearInterval(controlTimerRef.current)
    }
  }, [releaseControl])

  const lidarAge = mappingStatus?.sensors?.lidar
  const odomAge = mappingStatus?.sensors?.odom

  return (
    <div className="patrol-page indoor-map-page">
      <div className="patrol-header">
        <div className="patrol-header-left">
          <h1>室内地图管理</h1>
          <span className="patrol-subtitle">Cartographer 低速遥控建图、实时预览与地图文件管理</span>
        </div>
        <div className="patrol-header-actions">
          <ThemedSelect value={selectedDeviceId} onChange={event => setSelectedDeviceId(event.target.value)}>
            <option value="">选择设备</option>
            {devices.map(device => (
              <option key={device.id} value={device.id}>{device.name} · {device.control_connected ? '控制已连接' : device.status}</option>
            ))}
          </ThemedSelect>
          <button className="patrol-btn patrol-btn-secondary" onClick={loadDevices}>刷新设备</button>
        </div>
      </div>

      {message && <div className={`indoor-map-message ${messageType}`}>{message}</div>}

      <div className="indoor-map-grid">
        <section className="indoor-map-panel indoor-map-live-panel">
          <div className="indoor-map-panel-header">
            <div><h2>实时建图</h2><p>网页不会自动驾驶，需现场人员低速遥控车辆完成扫描</p></div>
            <span className={`indoor-map-state ${mappingRunning ? 'running' : ''}`}>
              {mappingRunning ? (mappingStatus?.paused ? '已停车 · 可保存' : '建图中') : '未开始'}
            </span>
          </div>
          <div className="indoor-map-preview-wrap">
            <MapPreviewCanvas preview={livePreview} emptyText={mappingRunning ? '正在等待第一帧地图…' : '开始建图后显示实时地图'} />
            <div className="indoor-map-overlay">
              <span>算法 {mappingStatus?.algorithm || 'karto'}</span>
              <span>时长 {formatDuration(mappingStatus?.elapsed)}</span>
              <span>里程计 {odomAge >= 0 ? `${odomAge.toFixed(1)}s` : '--'}</span>
              <span>雷达 {lidarAge >= 0 ? `${lidarAge.toFixed(1)}s` : '--'}</span>
            </div>
          </div>
          <div className="indoor-map-actions">
            <button className="patrol-btn patrol-btn-success" onClick={startMapping} disabled={!selectedDeviceId || mappingRunning || busyAction}>开始建图</button>
            <button className="patrol-btn patrol-btn-warning" onClick={pauseMapping} disabled={!mappingRunning || busyAction}>停车并保留</button>
            <button className="patrol-btn patrol-btn-danger" onClick={discardMapping} disabled={!mappingRunning || busyAction}>放弃本次</button>
          </div>
          <div className="indoor-map-save-row">
            <input value={mapName} onChange={event => setMapName(event.target.value)} maxLength={64} placeholder="输入地图名称，如：实验室一层" disabled={!mappingRunning || busyAction} />
            <button className="patrol-btn patrol-btn-primary" onClick={saveMapping} disabled={!mappingRunning || !mapName.trim() || busyAction}>保存地图</button>
          </div>
        </section>

        <aside className="indoor-map-panel indoor-map-control-panel">
          <div className="indoor-map-panel-header"><div><h2>建图低速控制</h2><p>按住移动，松开立即停车</p></div></div>
          <div className="indoor-drive-pad">
            <button className="forward" disabled={!canDrive} onPointerDown={() => holdControl(0.10, 0)}>↑<small>前进 0.10 m/s</small></button>
            <button className="left" disabled={!canDrive} onPointerDown={() => holdControl(0, 0.25)}>←<small>左转</small></button>
            <button className="stop" disabled={!mappingRunning} onClick={() => releaseControl(true)}>■<small>停车</small></button>
            <button className="right" disabled={!canDrive} onPointerDown={() => holdControl(0, -0.25)}>→<small>右转</small></button>
            <button className="backward" disabled={!canDrive} onPointerDown={() => holdControl(-0.08, 0)}>↓<small>后退 0.08 m/s</small></button>
          </div>
          <div className="indoor-map-safety-note">
            <strong>建图安全约束</strong>
            <p>启动前检查车旁无人和障碍；始终由现场人员看护；网络异常时车端 0.5 秒看门狗会自动停车。</p>
          </div>
        </aside>

        <section className="indoor-map-panel indoor-map-library-panel">
          <div className="indoor-map-panel-header">
            <div><h2>地图文件库</h2><p>与“室内实时导航”共用车端 slam_map 目录</p></div>
            <span>{maps.length} 张</span>
          </div>
          <div className="indoor-map-library-body">
            <div className="indoor-map-list">
              {maps.length ? maps.map(map => (
                <button key={map.name} className={selectedMap === map.name ? 'active' : ''} onClick={() => setSelectedMap(map.name)}>
                  <strong>{formatMapName(map.name)}</strong>
                  <small>{map.resolution ? `${map.resolution} m/px` : '分辨率未知'} · {map.imageExists ? '文件完整' : '缺少图像'}</small>
                </button>
              )) : <div className="indoor-map-list-empty">暂无已保存地图</div>}
            </div>
            <div className="indoor-map-saved-preview">
              <MapPreviewCanvas preview={savedPreview} emptyText="选择地图查看预览" />
            </div>
          </div>
          <div className="indoor-map-library-actions">
            <button className="patrol-btn patrol-btn-primary" onClick={() => navigate('/patrol/indoor/navigation')} disabled={!selectedMap}>前往室内实时导航</button>
            <button className="patrol-btn patrol-btn-danger" onClick={deleteMap} disabled={!selectedMap || busyAction}>删除地图</button>
            <button className="patrol-btn patrol-btn-secondary" onClick={loadMaps} disabled={!selectedDeviceId}>刷新地图</button>
          </div>
        </section>
      </div>
    </div>
  )
}

export default IndoorMapManagement
