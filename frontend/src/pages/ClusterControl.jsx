import { useState, useEffect, useCallback, useRef } from 'react'
import ThemedSelect from '../components/ThemedSelect'
import { authFetch } from '../utils/authFetch'
import '../styles/ClusterControl.css'

/**
 * 集群控制页面
 * 
 * - 上方：集群内所有设备的实时画面（可自由拖动位置、可调整容器及子画面尺寸，子画面保持4:3比例）
 * - 下方：编队方向控制 + 广播指令 + 日志
 */

const ASPECT_RATIO = 4 / 3 // 子画面宽高比
const DEFAULT_CARD_WIDTH = 240 // 默认子画面宽度
const MIN_CARD_WIDTH = 120
const MAX_CARD_WIDTH = 600
const MIN_CONTAINER_HEIGHT = 200
const DEFAULT_CONTAINER_HEIGHT = 380

export default function ClusterControl() {
  const [clusters, setClusters] = useState([])
  const [selectedClusterId, setSelectedClusterId] = useState('')
  const [logs, setLogs] = useState([])
  const [controlConfig, setControlConfig] = useState({ maxLinear: 0.4, maxAngular: 1.2 })
  const [speedRatio, setSpeedRatio] = useState(1.0)
  const [activeDirection, setActiveDirection] = useState(null)
  const [customCommand, setCustomCommand] = useState('{"type":"ping"}')
  const [showCameras, setShowCameras] = useState(true)

  // 画面容器高度（宽度跟随父元素100%）
  const [containerHeight, setContainerHeight] = useState(DEFAULT_CONTAINER_HEIGHT)
  // 子画面统一宽度（高度 = width / ASPECT_RATIO）
  const [cardWidth, setCardWidth] = useState(DEFAULT_CARD_WIDTH)
  // 每个子画面的位置 { [deviceId]: { x, y } }
  const [cardPositions, setCardPositions] = useState({})

  // 持续发送定时器
  const sendIntervalRef = useRef(null)
  const mountedRef = useRef(true)
  const containerRef = useRef(null)

  // 拖拽相关 ref（避免 re-render）
  const dragRef = useRef({ active: false, deviceId: null, startX: 0, startY: 0, origX: 0, origY: 0 })
  // 容器调整高度相关 ref
  const resizeContainerRef = useRef({ active: false, startY: 0, origHeight: 0 })
  // 子画面调整大小相关 ref
  const resizeCardRef = useRef({ active: false, startX: 0, origWidth: 0 })

  useEffect(() => {
    mountedRef.current = true
    fetchClusters()
    fetchControlConfig()
    const timer = setInterval(fetchClusters, 5000)
    return () => {
      mountedRef.current = false
      stopSending()
      clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    stopSending()
    setActiveDirection(null)
    // 切换集群时重置子画面位置
    setCardPositions({})
  }, [selectedClusterId])

  // 页面离开时发送 stop
  useEffect(() => {
    const handleBeforeUnload = () => {
      if (selectedClusterId) {
        navigator.sendBeacon(`/api/clusters/${selectedClusterId}/stop`, new Blob([], { type: 'application/json' }))
      }
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [selectedClusterId])

  // 当设备列表变化时，为新设备分配初始位置（网格排列）
  const selectedCluster = clusters.find(c => String(c.id) === selectedClusterId)
  const clusterDevices = selectedCluster ? selectedCluster.devices : []

  useEffect(() => {
    if (clusterDevices.length === 0) return
    setCardPositions(prev => {
      const next = { ...prev }
      const gap = 12
      const cols = Math.max(1, Math.floor((containerRef.current?.clientWidth || 800) / (cardWidth + gap)))
      let needsUpdate = false
      const cardH = cardWidth / ASPECT_RATIO + 40 // +40 for header
      
      clusterDevices.forEach((dev, idx) => {
        if (next[dev.id] === undefined) {
          needsUpdate = true
          const col = idx % cols
          const row = Math.floor(idx / cols)
          next[dev.id] = {
            x: col * (cardWidth + gap) + gap,
            y: row * (cardH + gap) + gap,
          }
        }
      })

      // 自动适应初始容器高度，避免冗余
      const totalRows = Math.ceil(clusterDevices.length / cols)
      const neededHeight = totalRows * (cardH + gap) + gap
      setContainerHeight(Math.max(MIN_CONTAINER_HEIGHT, neededHeight))

      return needsUpdate ? next : prev
    })
  }, [clusterDevices.length, cardWidth])

  const fetchClusters = async () => {
    try {
      const res = await authFetch('/api/clusters')
      if (res.ok) {
        const data = await res.json()
        setClusters(data)
        if (data.length > 0 && !selectedClusterId) {
          setSelectedClusterId(String(data[0].id))
        }
      }
    } catch (e) {
      console.error(e)
    }
  }

  const fetchControlConfig = async () => {
    try {
      const res = await authFetch('/api/robot-control/config')
      if (res.ok) {
        const data = await res.json()
        setControlConfig(data)
      }
    } catch (e) {
      console.error(e)
    }
  }

  const addLog = useCallback((msg, type = 'success') => {
    const time = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    setLogs(prev => [{ time, msg, type }, ...prev].slice(0, 80))
  }, [])

  // ===== 发送 cmd_vel =====
  const sendCmdVel = useCallback(async (linear, angular) => {
    if (!selectedClusterId) return
    try {
      const res = await authFetch(`/api/clusters/${selectedClusterId}/cmd_vel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ linear, angular })
      })
      if (res.ok) {
        const data = await res.json()
        addLog(`📡 cmd_vel v=${linear.toFixed(3)} w=${angular.toFixed(3)} -> ${data.message}`)
      } else {
        const err = await res.json()
        addLog(`❌ 集群控制失败: ${err.detail || '未知错误'}`, 'error')
        stopSending()
      }
    } catch (e) {
      addLog(`❌ 网络错误: ${e.message}`, 'error')
      stopSending()
    }
  }, [selectedClusterId, addLog])

  // ===== 发送 stop =====
  const sendStop = useCallback(async () => {
    if (!selectedClusterId) return
    try {
      const res = await authFetch(`/api/clusters/${selectedClusterId}/stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      })
      if (res.ok) {
        const data = await res.json()
        addLog(`🛑 停车指令 -> ${data.message}`)
      } else {
        const err = await res.json()
        addLog(`❌ 停车失败: ${err.detail || ''}`, 'error')
      }
    } catch (e) {
      addLog(`❌ 停车网络错误: ${e.message}`, 'error')
    }
  }, [selectedClusterId, addLog])

  const stopSending = useCallback(() => {
    if (sendIntervalRef.current) {
      clearInterval(sendIntervalRef.current)
      sendIntervalRef.current = null
    }
    setActiveDirection(null)
  }, [])

  const getDirectionValues = useCallback((direction) => {
    const maxV = controlConfig.maxLinear * speedRatio
    const maxW = controlConfig.maxAngular * speedRatio
    switch (direction) {
      case 'forward': return { linear: maxV, angular: 0 }
      case 'backward': return { linear: -maxV, angular: 0 }
      case 'left': return { linear: 0, angular: maxW }
      case 'right': return { linear: 0, angular: -maxW }
      case 'forward-left': return { linear: maxV, angular: maxW * 0.5 }
      case 'forward-right': return { linear: maxV, angular: -maxW * 0.5 }
      case 'backward-left': return { linear: -maxV, angular: maxW * 0.5 }
      case 'backward-right': return { linear: -maxV, angular: -maxW * 0.5 }
      default: return { linear: 0, angular: 0 }
    }
  }, [controlConfig, speedRatio])

  const startDirection = useCallback((direction) => {
    if (!selectedClusterId || activeDirection === direction) return
    stopSending()
    setActiveDirection(direction)
    const { linear, angular } = getDirectionValues(direction)
    sendCmdVel(linear, angular)
    sendIntervalRef.current = setInterval(() => {
      const vals = getDirectionValues(direction)
      sendCmdVel(vals.linear, vals.angular)
    }, 180)
  }, [selectedClusterId, activeDirection, stopSending, getDirectionValues, sendCmdVel])

  const stopDirection = useCallback(() => {
    if (sendIntervalRef.current) {
      stopSending()
      sendStop()
    }
  }, [stopSending, sendStop])

  const handleEmergencyStop = useCallback(() => {
    stopSending()
    sendStop()
    addLog('🚨 集群急停指令已发送', 'warning')
  }, [stopSending, sendStop, addLog])

  // ===== 发送自定义指令 =====
  const handleCustomSend = async (e) => {
    e.preventDefault()
    if (!selectedClusterId || !customCommand.trim()) return
    addLog(`⇨ 广播发送: ${customCommand}`)
    try {
      const res = await authFetch(`/api/clusters/${selectedClusterId}/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: customCommand })
      })
      const data = await res.json()
      if (res.ok) {
        addLog(`✅ 广播响应: ${data.message}`)
        if (data.results && data.results.length > 0) {
          data.results.forEach(r => {
            const dev = selectedCluster?.devices?.find(d => d.id === r.device_id)
            const devName = dev ? dev.name : `设备 ${r.device_id}`
            if (r.ok) {
              addLog(`  -> ${devName}: ${JSON.stringify(r.response)}`)
            } else {
              addLog(`  -> ${devName}: 失败 (${r.error})`, 'error')
            }
          })
        }
      } else {
        addLog(`❌ ${data.detail || '发送失败'}`, 'error')
      }
    } catch (err) {
      addLog(`❌ 网络错误: ${err.message}`, 'error')
    }
  }

  // ===== 键盘控制 =====
  useEffect(() => {
    const keyMap = {
      'ArrowUp': 'forward', 'KeyW': 'forward', 'Numpad8': 'forward',
      'ArrowDown': 'backward', 'KeyS': 'backward', 'Numpad2': 'backward',
      'ArrowLeft': 'left', 'KeyA': 'left', 'Numpad4': 'left',
      'ArrowRight': 'right', 'KeyD': 'right', 'Numpad6': 'right',
      'Numpad7': 'forward-left', 'Numpad9': 'forward-right',
      'Numpad1': 'backward-left', 'Numpad3': 'backward-right',
      'Space': 'stop', 'Numpad5': 'stop',
    }

    const handleKeyDown = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return
      const direction = keyMap[e.code]
      if (!direction) return
      e.preventDefault()
      if (direction === 'stop') {
        handleEmergencyStop()
      } else {
        startDirection(direction)
      }
    }

    const handleKeyUp = (e) => {
      const direction = keyMap[e.code]
      if (direction && direction !== 'stop' && direction === activeDirection) {
        stopDirection()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('keyup', handleKeyUp)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('keyup', handleKeyUp)
    }
  }, [startDirection, stopDirection, handleEmergencyStop, activeDirection])

  // ===== 拖拽子画面 =====
  const handleCardDragStart = useCallback((e, deviceId) => {
    // 只响应标题栏的拖拽，忽略 resize handle
    if (e.target.closest('.cc-mini-resize-handle')) return
    e.preventDefault()
    const pos = cardPositions[deviceId] || { x: 0, y: 0 }
    dragRef.current = {
      active: true,
      deviceId,
      startX: e.clientX,
      startY: e.clientY,
      origX: pos.x,
      origY: pos.y,
    }
    document.addEventListener('pointermove', handleCardDragMove)
    document.addEventListener('pointerup', handleCardDragEnd)
  }, [cardPositions])

  const handleCardDragMove = useCallback((e) => {
    if (!dragRef.current.active) return
    const { deviceId, startX, startY, origX, origY } = dragRef.current
    const dx = e.clientX - startX
    const dy = e.clientY - startY
    setCardPositions(prev => ({
      ...prev,
      [deviceId]: {
        x: Math.max(0, origX + dx),
        y: Math.max(0, origY + dy),
      }
    }))
  }, [])

  const handleCardDragEnd = useCallback(() => {
    dragRef.current.active = false
    document.removeEventListener('pointermove', handleCardDragMove)
    document.removeEventListener('pointerup', handleCardDragEnd)
  }, [handleCardDragMove])

  // ===== 调整容器高度 =====
  const handleContainerResizeStart = useCallback((e) => {
    e.preventDefault()
    resizeContainerRef.current = {
      active: true,
      startY: e.clientY,
      origHeight: containerHeight,
    }
    document.addEventListener('pointermove', handleContainerResizeMove)
    document.addEventListener('pointerup', handleContainerResizeEnd)
  }, [containerHeight])

  const handleContainerResizeMove = useCallback((e) => {
    if (!resizeContainerRef.current.active) return
    const { startY, origHeight } = resizeContainerRef.current
    const dy = e.clientY - startY
    setContainerHeight(Math.max(MIN_CONTAINER_HEIGHT, origHeight + dy))
  }, [])

  const handleContainerResizeEnd = useCallback(() => {
    resizeContainerRef.current.active = false
    document.removeEventListener('pointermove', handleContainerResizeMove)
    document.removeEventListener('pointerup', handleContainerResizeEnd)
  }, [handleContainerResizeMove])

  // ===== 调整子画面宽度（统一宽度，保持4:3比例） =====
  const handleCardResizeStart = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    resizeCardRef.current = {
      active: true,
      startX: e.clientX,
      origWidth: cardWidth,
    }
    document.addEventListener('pointermove', handleCardResizeMove)
    document.addEventListener('pointerup', handleCardResizeEnd)
  }, [cardWidth])

  const handleCardResizeMove = useCallback((e) => {
    if (!resizeCardRef.current.active) return
    const { startX, origWidth } = resizeCardRef.current
    const dx = e.clientX - startX
    setCardWidth(Math.min(MAX_CARD_WIDTH, Math.max(MIN_CARD_WIDTH, origWidth + dx)))
  }, [])

  const handleCardResizeEnd = useCallback(() => {
    resizeCardRef.current.active = false
    document.removeEventListener('pointermove', handleCardResizeMove)
    document.removeEventListener('pointerup', handleCardResizeEnd)
  }, [handleCardResizeMove])

  // 自动排列按钮
  const autoArrangeCards = useCallback(() => {
    if (clusterDevices.length === 0) return
    const gap = 12
    const containerWidth = containerRef.current?.clientWidth || 800
    const cols = Math.max(1, Math.floor((containerWidth - gap) / (cardWidth + gap)))
    const cardH = cardWidth / ASPECT_RATIO + 40 // +40 for header height
    const newPositions = {}
    clusterDevices.forEach((dev, idx) => {
      const col = idx % cols
      const row = Math.floor(idx / cols)
      newPositions[dev.id] = {
        x: col * (cardWidth + gap) + gap,
        y: row * (cardH + gap) + gap,
      }
    })
    setCardPositions(newPositions)
    // 也适配容器高度
    const totalRows = Math.ceil(clusterDevices.length / cols)
    const neededHeight = totalRows * (cardH + gap) + gap
    setContainerHeight(Math.max(MIN_CONTAINER_HEIGHT, neededHeight))
  }, [clusterDevices, cardWidth])

  const onlineCount = clusterDevices.filter(d => d.status === 'online').length
  const cardHeight = cardWidth / ASPECT_RATIO

  return (
    <div className="cluster-control-page">
      <div className="cc-header">
        <h1 className="page-title">🚀 远程集群控制</h1>
        <span className="page-subtitle">通过 TCP 协议向集群内所有在线设备下发同步控制指令</span>
      </div>

      <div className="cc-selector-card">
        <div className="cc-selector-row">
          <div className="cc-selector-left">
            <h2>目标集群</h2>
            <ThemedSelect
              className="cc-select"
              value={selectedClusterId}
              onChange={(e) => setSelectedClusterId(e.target.value)}
            >
              {clusters.length === 0 && <option value="">暂无可用集群</option>}
              {clusters.map(cluster => {
                const onCount = cluster.devices.filter(d => d.status === 'online').length
                return (
                  <option key={cluster.id} value={cluster.id}>
                    {cluster.name} (在线 {onCount} / 总共 {cluster.devices.length} 台)
                  </option>
                )
              })}
            </ThemedSelect>
          </div>
          <div className="cc-selector-right">
            <button
              className={`cc-btn-toggle-cam ${showCameras ? 'active' : ''}`}
              onClick={() => setShowCameras(!showCameras)}
              title={showCameras ? '隐藏摄像头画面' : '显示摄像头画面'}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="23 7 16 12 23 17 23 7"></polygon>
                <rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
              </svg>
              {showCameras ? '隐藏画面' : '显示画面'}
            </button>
          </div>
        </div>
        {selectedCluster && (
          <p className="cc-cluster-info">
            当前集群共有 <strong>{onlineCount}</strong> 台设备在线，所有指令将广播至这 {onlineCount} 台设备。
          </p>
        )}
      </div>

      {/* ===== 集群设备实时画面区域 ===== */}
      {showCameras && clusterDevices.length > 0 && (
        <div className="cc-cameras-section">
          {/* 工具栏 */}
          <div className="cc-cameras-toolbar">
            <div className="cc-cameras-toolbar-left">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="23 7 16 12 23 17 23 7"></polygon>
                <rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
              </svg>
              <span className="cc-cameras-title">集群设备实时画面</span>
              <span className="cc-cameras-count">{clusterDevices.length} 台</span>
            </div>
            <div className="cc-cameras-toolbar-right">
              <div className="cc-cameras-size-control">
                <label>子画面宽度</label>
                <input
                  type="range"
                  min={MIN_CARD_WIDTH}
                  max={MAX_CARD_WIDTH}
                  step="10"
                  value={cardWidth}
                  onChange={e => setCardWidth(parseInt(e.target.value))}
                  className="cc-size-slider"
                />
                <span className="cc-size-value">{Math.round(cardWidth)}×{Math.round(cardHeight)}px</span>
              </div>
              <button className="cc-btn-arrange" onClick={autoArrangeCards} title="自动排列">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="3" width="7" height="7"></rect>
                  <rect x="14" y="3" width="7" height="7"></rect>
                  <rect x="14" y="14" width="7" height="7"></rect>
                  <rect x="3" y="14" width="7" height="7"></rect>
                </svg>
                自动排列
              </button>
            </div>
          </div>

          {/* 可拖拽画面容器 */}
          <div
            className="cc-cameras-canvas"
            ref={containerRef}
            style={{ height: `${containerHeight}px` }}
          >
            {clusterDevices.map(device => {
              const pos = cardPositions[device.id] || { x: 0, y: 0 }
              return (
                <MiniCameraCard
                  key={device.id}
                  device={device}
                  x={pos.x}
                  y={pos.y}
                  width={cardWidth}
                  height={cardHeight}
                  onDragStart={(e) => handleCardDragStart(e, device.id)}
                  onResizeStart={handleCardResizeStart}
                />
              )
            })}
          </div>

          {/* 容器高度调整手柄 */}
          <div
            className="cc-cameras-resize-bar"
            onPointerDown={handleContainerResizeStart}
            title="拖拽调整画面区域高度"
          >
            <div className="cc-cameras-resize-grip">
              <span></span><span></span><span></span>
            </div>
          </div>
        </div>
      )}

      {/* 两栏布局：左方向控制 / 右发送指令 */}
      <div className="cc-content-grid">
        {/* 左：方向控制面板 */}
        <div className="cc-control-card">
          <h3>🕹️ 编队方向控制</h3>
          <p className="cc-control-desc">
            按住方向键持续发送集群运动指令，松开自动停车。
          </p>

          <div className="cc-speed-control">
            <label>统一速度倍率: <strong>{(speedRatio * 100).toFixed(0)}%</strong></label>
            <input
              type="range"
              min="0.05" max="1" step="0.05"
              value={speedRatio}
              onChange={e => setSpeedRatio(parseFloat(e.target.value))}
              className="cc-speed-slider"
            />
          </div>

          <div className="cc-numpad-container">
            <div className="cc-numpad">
              {/* Row 1 */}
              <button
                className={`cc-num-btn ${activeDirection === 'forward-left' ? 'active' : ''}`}
                onPointerDown={() => startDirection('forward-left')}
                onPointerUp={stopDirection}
                onPointerLeave={stopDirection}
                disabled={!selectedClusterId}
              >
                <span className="cc-num-icon">↖️</span>
                <span className="cc-num-key">7</span>
              </button>
              <button
                className={`cc-num-btn ${activeDirection === 'forward' ? 'active' : ''}`}
                onPointerDown={() => startDirection('forward')}
                onPointerUp={stopDirection}
                onPointerLeave={stopDirection}
                disabled={!selectedClusterId}
              >
                <span className="cc-num-icon">⬆️</span>
                <span className="cc-num-key">W / 8 前进</span>
              </button>
              <button
                className={`cc-num-btn ${activeDirection === 'forward-right' ? 'active' : ''}`}
                onPointerDown={() => startDirection('forward-right')}
                onPointerUp={stopDirection}
                onPointerLeave={stopDirection}
                disabled={!selectedClusterId}
              >
                <span className="cc-num-icon">↗️</span>
                <span className="cc-num-key">9</span>
              </button>

              {/* Row 2 */}
              <button
                className={`cc-num-btn ${activeDirection === 'left' ? 'active' : ''}`}
                onPointerDown={() => startDirection('left')}
                onPointerUp={stopDirection}
                onPointerLeave={stopDirection}
                disabled={!selectedClusterId}
              >
                <span className="cc-num-icon">⬅️</span>
                <span className="cc-num-key">A / 4 左转</span>
              </button>
              <button
                className="cc-num-btn stop"
                onClick={handleEmergencyStop}
                disabled={!selectedClusterId}
              >
                <span className="cc-num-icon">⏹️</span>
                <span className="cc-num-key">空格 停止</span>
              </button>
              <button
                className={`cc-num-btn ${activeDirection === 'right' ? 'active' : ''}`}
                onPointerDown={() => startDirection('right')}
                onPointerUp={stopDirection}
                onPointerLeave={stopDirection}
                disabled={!selectedClusterId}
              >
                <span className="cc-num-icon">➡️</span>
                <span className="cc-num-key">D / 6 右转</span>
              </button>

              {/* Row 3 */}
              <button
                className={`cc-num-btn ${activeDirection === 'backward-left' ? 'active' : ''}`}
                onPointerDown={() => startDirection('backward-left')}
                onPointerUp={stopDirection}
                onPointerLeave={stopDirection}
                disabled={!selectedClusterId}
              >
                <span className="cc-num-icon">↙️</span>
                <span className="cc-num-key">1</span>
              </button>
              <button
                className={`cc-num-btn ${activeDirection === 'backward' ? 'active' : ''}`}
                onPointerDown={() => startDirection('backward')}
                onPointerUp={stopDirection}
                onPointerLeave={stopDirection}
                disabled={!selectedClusterId}
              >
                <span className="cc-num-icon">⬇️</span>
                <span className="cc-num-key">S / 2 后退</span>
              </button>
              <button
                className={`cc-num-btn ${activeDirection === 'backward-right' ? 'active' : ''}`}
                onPointerDown={() => startDirection('backward-right')}
                onPointerUp={stopDirection}
                onPointerLeave={stopDirection}
                disabled={!selectedClusterId}
              >
                <span className="cc-num-icon">↘️</span>
                <span className="cc-num-key">3</span>
              </button>
            </div>
          </div>

          <button className="cc-btn-emergency" onClick={handleEmergencyStop} disabled={!selectedClusterId}>
            🚨 集群急停 (Emergency Stop)
          </button>
        </div>

        {/* 右：发送特定指令 */}
        <div className="cc-control-card">
          <h3>📝 广播特定指令</h3>
          <p className="cc-control-desc">向集群内所有在线设备广播特定的 TCP JSON 指令。</p>

          <form className="cc-custom-form" onSubmit={handleCustomSend}>
            <div className="cc-input-group">
              <label>指令代码 (JSON)</label>
              <input
                type="text"
                className="cc-input"
                value={customCommand}
                onChange={e => setCustomCommand(e.target.value)}
                placeholder='{"type":"ping"}'
                disabled={!selectedClusterId}
              />
            </div>
            <button
              type="submit"
              className="cc-btn-send"
              disabled={!selectedClusterId || !customCommand.trim()}
            >
              广播指令到集群
            </button>
          </form>

          <div className="cc-preset-commands">
            <label>快捷广播</label>
            <div className="cc-preset-list">
              {[
                { label: 'Ping All', cmd: '{"type":"ping"}' },
                { label: 'Stop All', cmd: '{"type":"stop"}' },
                { label: '群体前进 0.1', cmd: '{"type":"cmd_vel","v":0.1,"w":0}' },
              ].map((preset, i) => (
                <button
                  key={i}
                  className="cc-preset-btn"
                  type="button"
                  disabled={!selectedClusterId}
                  onClick={() => {
                    setCustomCommand(preset.cmd)
                  }}
                >{preset.label}</button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* 终端日志（全宽） */}
      <div className="cc-log-container">
        <div className="cc-log-header">
          <h3>广播日志</h3>
          <button className="cc-btn-clear" onClick={() => setLogs([])}>清空日志</button>
        </div>
        <div className="cc-logs">
          {logs.length === 0 && <span style={{ color: '#94a3b8' }}>暂无日志...</span>}
          {logs.map((log, idx) => (
            <div className="cc-log-item" key={idx}>
              <span className="cc-log-time">[{log.time}]</span>
              <span className={`cc-log-msg ${log.type}`}>{log.msg}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}


/**
 * 紧凑型设备摄像头小卡片（可拖拽+可调整大小）
 */
function MiniCameraCard({ device, x, y, width, height, onDragStart, onResizeStart }) {
  const imgRef = useRef(null)
  const retryTimerRef = useRef(null)
  const [status, setStatus] = useState('loading')

  const streamUrl = `/api/devices/${device.id}/camera/stream`

  const handleLoad = () => {
    setStatus('streaming')
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current)
      retryTimerRef.current = null
    }
  }

  const handleError = () => {
    setStatus('error')
    if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
    retryTimerRef.current = setTimeout(() => {
      retryStream()
    }, 8000)
  }

  const retryStream = () => {
    setStatus('loading')
    if (imgRef.current) {
      imgRef.current.src = `${streamUrl}?t=${Date.now()}`
    }
  }

  useEffect(() => {
    return () => {
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
    }
  }, [])

  return (
    <div
      className="cc-mini-cam"
      style={{
        left: `${x}px`,
        top: `${y}px`,
        width: `${width}px`,
      }}
    >
      {/* 标题栏（拖拽手柄） */}
      <div
        className="cc-mini-cam-header"
        onPointerDown={onDragStart}
        style={{ cursor: 'grab' }}
      >
        <span className="cc-mini-cam-name">{device.name}</span>
        <div className="cc-mini-cam-status-area">
          {status === 'streaming' && (
            <span className="cc-mini-live">
              <span className="cc-mini-live-dot"></span>
              LIVE
            </span>
          )}
          <span className={`cc-mini-device-status ${device.status === 'online' ? 'online' : 'offline'}`}>
            {device.status === 'online' ? '在线' : '离线'}
          </span>
        </div>
      </div>
      {/* 画面 */}
      <div className="cc-mini-cam-viewport" style={{ height: `${height}px` }}>
        <img
          ref={imgRef}
          className="cc-mini-cam-stream"
          src={streamUrl}
          alt={`${device.name} 摄像头`}
          onLoad={handleLoad}
          onError={handleError}
          style={{ display: status === 'streaming' ? 'block' : 'none' }}
        />
        {status === 'loading' && (
          <div className="cc-mini-cam-overlay">
            <div className="cc-mini-cam-spinner"></div>
            <span>连接中...</span>
          </div>
        )}
        {status === 'error' && (
          <div className="cc-mini-cam-overlay error">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="15" y1="9" x2="9" y2="15"></line>
              <line x1="9" y1="9" x2="15" y2="15"></line>
            </svg>
            <span>连接失败</span>
            <button className="cc-mini-retry" onClick={retryStream}>重试</button>
          </div>
        )}
        {status === 'streaming' && (
          <div className="cc-mini-cam-info">
            <span>{device.ip_address}</span>
          </div>
        )}
      </div>
      {/* 子画面 resize handle（右下角三角） */}
      <div
        className="cc-mini-resize-handle"
        onPointerDown={onResizeStart}
        title="拖拽调整子画面大小"
      />
    </div>
  )
}
