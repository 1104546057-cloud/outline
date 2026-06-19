import { useState, useEffect, useCallback, useRef } from 'react'
import ThemedSelect from '../components/ThemedSelect'
import { authFetch } from '../utils/authFetch'
import '../styles/DeviceControl.css'

const rosSubscriberLabel = (response, prefix = '') => (
  Number.isFinite(response?.subscribers)
    ? `${prefix}ROS订阅者 ${response.subscribers}`
    : ''
)

/**
 * 真实无人车遥控页面
 * 
 * - 左侧：选中设备的实时摄像头画面
 * - 右侧：方向控制 + 自定义指令 + 日志
 * - 按住方向键持续发送 cmd_vel（每 180ms 一次）
 * - 松开/离开时发送 stop
 * - 支持速度滑块调节倍率
 */
export default function DeviceControl() {
  const [devices, setDevices] = useState([])
  const [selectedDeviceId, setSelectedDeviceId] = useState('')
  const [logs, setLogs] = useState([])
  const [controlConfig, setControlConfig] = useState({ maxLinear: 0.4, maxAngular: 1.2 })
  const [speedRatio, setSpeedRatio] = useState(0.5) // 速度倍率 0~1
  const [connectionStatus, setConnectionStatus] = useState('未检测') // 未检测 / 连接中 / 已连接 / 不可达
  const [activeDirection, setActiveDirection] = useState(null) // 当前按住的方向
  const [customCommand, setCustomCommand] = useState('{"type":"ping"}')
  const [cameraStatus, setCameraStatus] = useState('loading') // loading / streaming / error
  const [cameraError, setCameraError] = useState('')

  // 持续发送定时器
  const sendIntervalRef = useRef(null)
  // 标记组件是否已挂载
  const mountedRef = useRef(true)
  const imgRef = useRef(null)
  const retryTimerRef = useRef(null)
  const commandBusyRef = useRef(false)

  useEffect(() => {
    mountedRef.current = true
    fetchDevices()
    fetchControlConfig()
    // 定期刷新设备列表以获取最新遥测数据
    const timer = setInterval(fetchDevices, 5000)
    return () => {
      mountedRef.current = false
      stopSending()
      clearInterval(timer)
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
    }
  }, [])

  // 切换设备时停止、重置状态，并自动检测连接
  useEffect(() => {
    stopSending()
    setActiveDirection(null)
    setCameraStatus('loading')
    setCameraError('')
    if (selectedDeviceId) {
      handleTestConnection()
    } else {
      setConnectionStatus('未检测')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDeviceId])

  // 页面离开时发送 stop
  useEffect(() => {
    const handleBeforeUnload = () => {
      if (selectedDeviceId) {
        // 使用 sendBeacon 确保页面关闭时也能发送
        const body = JSON.stringify({ robotId: parseInt(selectedDeviceId) })
        navigator.sendBeacon('/api/robot-control/stop', new Blob([body], { type: 'application/json' }))
      }
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [selectedDeviceId])

  // 用 ref 跟踪 selectedDeviceId 最新值，避免 setInterval 闭包过期
  const selectedDeviceIdRef = useRef(selectedDeviceId)
  useEffect(() => {
    selectedDeviceIdRef.current = selectedDeviceId
  }, [selectedDeviceId])

  const fetchDevices = async () => {
    try {
      const res = await authFetch('/api/devices')
      if (res.ok) {
        const data = await res.json()
        setDevices(data)
        // 只有当尚未选择设备时，才自动选第一个在线设备
        if (data.length > 0 && !selectedDeviceIdRef.current) {
          const onlineDev = data.find(d => d.status === 'online') || data[0]
          setSelectedDeviceId(String(onlineDev.id))
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

  // ===== 连接检测 =====
  const handleTestConnection = async () => {
    if (!selectedDeviceId) {
      addLog('请先选择一个设备', 'error')
      return
    }
    setConnectionStatus('连接中')
    addLog('正在检测连接...')
    try {
      const res = await authFetch(`/api/robot-control/status?robotId=${selectedDeviceId}`)
      const data = await res.json()
      if (res.ok && data.ok) {
        setConnectionStatus('已连接')
        addLog(`✅ 连接成功 → Agent WebSocket（设备 ${data.target.deviceId}${rosSubscriberLabel(data.response, '，')}）`)
        // 刷新设备列表以获取更新后的在线状态
        fetchDevices()
      } else {
        setConnectionStatus('不可达')
        addLog(`❌ 连接失败: ${data.detail || '未知错误'}`, 'error')
      }
    } catch (e) {
      setConnectionStatus('不可达')
      addLog(`❌ 网络错误: ${e.message}`, 'error')
    }
  }

  // ===== 发送 cmd_vel =====
  const sendCmdVel = useCallback(async (linear, angular) => {
    if (!selectedDeviceId || commandBusyRef.current) return
    commandBusyRef.current = true
    try {
      const res = await authFetch('/api/robot-control/cmd_vel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          robotId: parseInt(selectedDeviceId),
          linear,
          angular,
        })
      })
      if (res.ok) {
        const data = await res.json()
        if (data.ok) {
          addLog(`📡 cmd_vel v=${data.linear.toFixed(3)} w=${data.angular.toFixed(3)}${rosSubscriberLabel(data.response, ' · ')}`)
        }
      } else {
        const err = await res.json()
        addLog(`❌ ${err.detail || '控制失败'}`, 'error')
        stopSending()
      }
    } catch (e) {
      addLog(`❌ 网络错误: ${e.message}`, 'error')
      stopSending()
    } finally {
      commandBusyRef.current = false
    }
  }, [selectedDeviceId, addLog])

  // ===== 发送 stop =====
  const sendStop = useCallback(async () => {
    if (!selectedDeviceId) return
    try {
      const res = await authFetch('/api/robot-control/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robotId: parseInt(selectedDeviceId) })
      })
      if (res.ok) {
        addLog('🛑 已发送停车指令')
      } else {
        const err = await res.json()
        addLog(`❌ 停车失败: ${err.detail || ''}`, 'error')
      }
    } catch (e) {
      addLog(`❌ 停车网络错误: ${e.message}`, 'error')
    }
  }, [selectedDeviceId, addLog])

  // ===== 停止持续发送 =====
  const stopSending = useCallback(() => {
    if (sendIntervalRef.current) {
      clearInterval(sendIntervalRef.current)
      sendIntervalRef.current = null
    }
    setActiveDirection(null)
  }, [])

  // ===== 方向控制：按下开始持续发送，松开发送 stop =====
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
    if (!selectedDeviceId || activeDirection === direction) return
    stopSending()
    setActiveDirection(direction)
    const { linear, angular } = getDirectionValues(direction)
    // 立即发送一次
    sendCmdVel(linear, angular)
    // 持续发送
    sendIntervalRef.current = setInterval(() => {
      const vals = getDirectionValues(direction)
      sendCmdVel(vals.linear, vals.angular)
    }, 180)
  }, [selectedDeviceId, activeDirection, stopSending, getDirectionValues, sendCmdVel])

  const stopDirection = useCallback(() => {
    if (sendIntervalRef.current) {
      stopSending()
      sendStop()
    }
  }, [stopSending, sendStop])

  // 急停
  const handleEmergencyStop = useCallback(() => {
    stopSending()
    sendStop()
    addLog('🚨 急停指令已发送', 'warning')
  }, [stopSending, sendStop, addLog])

  // ===== 发送自定义指令 =====
  const handleCustomSend = async (e) => {
    e.preventDefault()
    if (!selectedDeviceId || !customCommand.trim()) return
    addLog(`⇨ 发送: ${customCommand}`)
    try {
      const res = await authFetch('/api/robot-control/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robotId: parseInt(selectedDeviceId), command: customCommand })
      })
      const data = await res.json()
      if (res.ok && data.ok) {
        addLog(`✅ 响应: ${JSON.stringify(data.response)}`)
        fetchDevices()
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

  // ===== 摄像头画面控制 =====
  const streamUrl = selectedDeviceId ? `/api/devices/${selectedDeviceId}/camera/stream` : ''

  const handleCameraLoad = () => {
    setCameraStatus('streaming')
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current)
      retryTimerRef.current = null
    }
  }

  const handleCameraError = () => {
    setCameraStatus('error')
    setCameraError('无法连接到摄像头，请确认设备已开启摄像头服务')
    if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
    retryTimerRef.current = setTimeout(() => {
      retryCameraStream()
    }, 5000)
  }

  const retryCameraStream = () => {
    setCameraStatus('loading')
    setCameraError('')
    if (imgRef.current) {
      imgRef.current.src = `${streamUrl}?t=${Date.now()}`
    }
  }

  const captureSnapshot = async () => {
    if (!selectedDeviceId) return
    const device = devices.find(d => String(d.id) === selectedDeviceId)
    if (!device) return
    try {
      const res = await authFetch(`/api/devices/${selectedDeviceId}/camera/snapshot`)
      if (!res.ok) throw new Error('截图失败')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
      a.download = `${device.name}_${timestamp}.jpg`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      addLog('📷 截图已保存')
    } catch (err) {
      addLog(`❌ 截图失败: ${err.message}`, 'error')
    }
  }

  const selectedDevice = devices.find(d => String(d.id) === selectedDeviceId)

  const statusColorMap = {
    '未检测': '#6b7280',
    '连接中': '#f59e0b',
    '已连接': '#22c55e',
    '不可达': '#ef4444',
  }

  return (
    <div className="device-control-page">
      <div className="dc-header">
        <h1 className="page-title">🕹️ 远程遥控无人车</h1>
        <span className="page-subtitle">通过 Agent WebSocket 发送真实控制指令 · 按住方向键持续运动，松开停车</span>
      </div>

      {/* 设备选择 + 连接状态 */}
      <div className="dc-selector-card">
        <div className="dc-selector-row">
          <div className="dc-selector-left">
            <h2>目标设备</h2>
            <ThemedSelect
              className="dc-select"
              value={selectedDeviceId}
              onChange={(e) => setSelectedDeviceId(e.target.value)}
            >
              {devices.length === 0 && <option value="">暂无可用设备</option>}
              {devices.map(dev => (
                <option key={dev.id} value={dev.id}>
                  [{dev.status === 'online' ? '在线' : '离线'}] {dev.name} ({dev.type}) - Agent {dev.control_connected ? '已连接' : '未连接'}
                </option>
              ))}
            </ThemedSelect>
          </div>
          <div className="dc-selector-right">
            <button className="dc-btn-test" onClick={handleTestConnection} disabled={!selectedDeviceId}>
              检测连接
            </button>
            <span className="dc-connection-status" style={{ color: statusColorMap[connectionStatus] }}>
              ● {connectionStatus}
            </span>
          </div>
        </div>
        {selectedDevice && (
          <div className="dc-device-info">
            <span>🔋 {selectedDevice.battery != null ? `${selectedDevice.battery}%` : '--'}</span>
            <span>📶 {selectedDevice.signal != null ? `${selectedDevice.signal}%` : '--'}</span>
            <span>📍 {selectedDevice.lat && selectedDevice.lng ? `${selectedDevice.lat}, ${selectedDevice.lng}` : '无位置'}</span>
            <span>⏱️ {selectedDevice.last_seen ? new Date(selectedDevice.last_seen).toLocaleString('zh-CN') : '从未上报'}</span>
          </div>
        )}
      </div>

      {/* ===== 新布局：左侧摄像头画面 + 右侧控制面板 ===== */}
      <div className="dc-main-layout">
        {/* 左侧：实时摄像头画面 */}
        <div className="dc-camera-panel">
          <div className="dc-camera-card">
            <div className="dc-camera-header">
              <div className="dc-camera-title">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="23 7 16 12 23 17 23 7"></polygon>
                  <rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
                </svg>
                <span>设备实时画面</span>
                {cameraStatus === 'streaming' && (
                  <span className="dc-live-badge">
                    <span className="dc-live-dot"></span>
                    LIVE
                  </span>
                )}
              </div>
              <div className="dc-camera-actions">
                <button 
                  className="dc-camera-btn" 
                  onClick={captureSnapshot} 
                  disabled={cameraStatus !== 'streaming'}
                  title="截图保存"
                >
                  📷
                </button>
                <button 
                  className="dc-camera-btn" 
                  onClick={retryCameraStream}
                  title="重新连接"
                >
                  🔄
                </button>
              </div>
            </div>
            <div className="dc-camera-viewport">
              {selectedDeviceId ? (
                <>
                  <img
                    ref={imgRef}
                    className="dc-camera-stream"
                    src={streamUrl}
                    alt={`${selectedDevice?.name || '设备'} 摄像头`}
                    onLoad={handleCameraLoad}
                    onError={handleCameraError}
                    style={{ display: cameraStatus === 'streaming' ? 'block' : 'none' }}
                  />
                  {cameraStatus === 'loading' && (
                    <div className="dc-camera-overlay">
                      <div className="dc-camera-spinner"></div>
                      <div className="dc-camera-overlay-text">正在连接摄像头...</div>
                    </div>
                  )}
                  {cameraStatus === 'error' && (
                    <div className="dc-camera-overlay error">
                      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="10"></circle>
                        <line x1="15" y1="9" x2="9" y2="15"></line>
                        <line x1="9" y1="9" x2="15" y2="15"></line>
                      </svg>
                      <div className="dc-camera-overlay-text">{cameraError}</div>
                      <button className="dc-camera-retry-btn" onClick={retryCameraStream}>
                        重新连接
                      </button>
                    </div>
                  )}
                  {/* 底部信息条 */}
                  {cameraStatus === 'streaming' && (
                    <div className="dc-camera-info-bar">
                      <span>640×480</span>
                      <span>15 fps</span>
                    </div>
                  )}
                </>
              ) : (
                <div className="dc-camera-overlay">
                  <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{opacity: 0.4}}>
                    <polygon points="23 7 16 12 23 17 23 7"></polygon>
                    <rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
                  </svg>
                  <div className="dc-camera-overlay-text">请先选择一个设备</div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 右侧：控制面板 */}
        <div className="dc-control-panel">
          {/* 方向控制 */}
          <div className="dc-control-card">
            <h3>🕹️ 方向控制</h3>
            <p className="dc-control-desc">
              按住方向键持续发送运动指令，松开自动停车。支持键盘 WASD / 方向键 / 小键盘。
            </p>
            
            {/* 速度滑块 */}
            <div className="dc-speed-control">
              <label>速度倍率: <strong>{(speedRatio * 100).toFixed(0)}%</strong></label>
              <input 
                type="range" 
                min="0.05" max="1" step="0.05"
                value={speedRatio}
                onChange={e => setSpeedRatio(parseFloat(e.target.value))}
                className="dc-speed-slider"
              />
              <div className="dc-speed-info">
                <span>线速度上限: {(controlConfig.maxLinear * speedRatio).toFixed(2)} m/s</span>
                <span>角速度上限: {(controlConfig.maxAngular * speedRatio).toFixed(2)} rad/s</span>
              </div>
            </div>

            <div className="dc-numpad-container">
              <div className="dc-numpad">
                {/* Row 1: forward-left, forward, forward-right */}
                <button 
                  className={`dc-num-btn ${activeDirection === 'forward-left' ? 'active' : ''}`}
                  onPointerDown={() => startDirection('forward-left')}
                  onPointerUp={stopDirection}
                  onPointerLeave={stopDirection}
                  disabled={!selectedDeviceId}
                >
                  <span className="dc-num-icon">↖️</span>
                  <span className="dc-num-key">7</span>
                </button>
                <button 
                  className={`dc-num-btn ${activeDirection === 'forward' ? 'active' : ''}`}
                  onPointerDown={() => startDirection('forward')}
                  onPointerUp={stopDirection}
                  onPointerLeave={stopDirection}
                  disabled={!selectedDeviceId}
                >
                  <span className="dc-num-icon">⬆️</span>
                  <span className="dc-num-key">W / 8 前进</span>
                </button>
                <button 
                  className={`dc-num-btn ${activeDirection === 'forward-right' ? 'active' : ''}`}
                  onPointerDown={() => startDirection('forward-right')}
                  onPointerUp={stopDirection}
                  onPointerLeave={stopDirection}
                  disabled={!selectedDeviceId}
                >
                  <span className="dc-num-icon">↗️</span>
                  <span className="dc-num-key">9</span>
                </button>
                
                {/* Row 2: left, stop, right */}
                <button 
                  className={`dc-num-btn ${activeDirection === 'left' ? 'active' : ''}`}
                  onPointerDown={() => startDirection('left')}
                  onPointerUp={stopDirection}
                  onPointerLeave={stopDirection}
                  disabled={!selectedDeviceId}
                >
                  <span className="dc-num-icon">⬅️</span>
                  <span className="dc-num-key">A / 4 左转</span>
                </button>
                <button 
                  className="dc-num-btn stop"
                  onClick={handleEmergencyStop}
                  disabled={!selectedDeviceId}
                >
                  <span className="dc-num-icon">⏹️</span>
                  <span className="dc-num-key">空格 停止</span>
                </button>
                <button 
                  className={`dc-num-btn ${activeDirection === 'right' ? 'active' : ''}`}
                  onPointerDown={() => startDirection('right')}
                  onPointerUp={stopDirection}
                  onPointerLeave={stopDirection}
                  disabled={!selectedDeviceId}
                >
                  <span className="dc-num-icon">➡️</span>
                  <span className="dc-num-key">D / 6 右转</span>
                </button>
                
                {/* Row 3: backward-left, backward, backward-right */}
                <button 
                  className={`dc-num-btn ${activeDirection === 'backward-left' ? 'active' : ''}`}
                  onPointerDown={() => startDirection('backward-left')}
                  onPointerUp={stopDirection}
                  onPointerLeave={stopDirection}
                  disabled={!selectedDeviceId}
                >
                  <span className="dc-num-icon">↙️</span>
                  <span className="dc-num-key">1</span>
                </button>
                <button 
                  className={`dc-num-btn ${activeDirection === 'backward' ? 'active' : ''}`}
                  onPointerDown={() => startDirection('backward')}
                  onPointerUp={stopDirection}
                  onPointerLeave={stopDirection}
                  disabled={!selectedDeviceId}
                >
                  <span className="dc-num-icon">⬇️</span>
                  <span className="dc-num-key">S / 2 后退</span>
                </button>
                <button 
                  className={`dc-num-btn ${activeDirection === 'backward-right' ? 'active' : ''}`}
                  onPointerDown={() => startDirection('backward-right')}
                  onPointerUp={stopDirection}
                  onPointerLeave={stopDirection}
                  disabled={!selectedDeviceId}
                >
                  <span className="dc-num-icon">↘️</span>
                  <span className="dc-num-key">3</span>
                </button>
              </div>
            </div>

            {/* 急停按钮 */}
            <button className="dc-btn-emergency" onClick={handleEmergencyStop} disabled={!selectedDeviceId}>
              🚨 急停 (Emergency Stop)
            </button>
          </div>

          {/* 发送特定指令 */}
          <div className="dc-control-card">
            <h3>📝 发送特定指令</h3>
            <p className="dc-control-desc">直接输入 JSON 指令，通过 Agent WebSocket 发送到设备。</p>
            
            <form className="dc-custom-form" onSubmit={handleCustomSend}>
              <div className="dc-input-group">
                <label>指令代码 (JSON)</label>
                <input
                  type="text"
                  className="dc-input"
                  value={customCommand}
                  onChange={e => setCustomCommand(e.target.value)}
                  placeholder='{"type":"ping"}'
                  disabled={!selectedDeviceId}
                />
              </div>
              <button 
                type="submit" 
                className="dc-btn-send"
                disabled={!selectedDeviceId || !customCommand.trim()}
              >
                发送指令到设备
              </button>
            </form>

            <div className="dc-preset-commands">
              <label>快捷指令</label>
              <div className="dc-preset-list">
                {[
                  { label: 'Ping', cmd: '{"type":"ping"}' },
                  { label: 'Stop', cmd: '{"type":"stop"}' },
                  { label: '前进 0.1', cmd: '{"type":"cmd_vel","v":0.1,"w":0}' },
                ].map((preset, i) => (
                  <button 
                    key={i} 
                    className="dc-preset-btn"
                    type="button"
                    disabled={!selectedDeviceId}
                    onClick={() => {
                      setCustomCommand(preset.cmd)
                    }}
                  >{preset.label}</button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 终端日志（全宽） */}
      <div className="dc-log-container">
        <div className="dc-log-header">
          <h3>控制日志</h3>
          <button className="dc-btn-clear" onClick={() => setLogs([])}>清空日志</button>
        </div>
        <div className="dc-logs">
          {logs.length === 0 && <span style={{color: '#94a3b8'}}>暂无日志... 请先选择设备并检测连接</span>}
          {logs.map((log, idx) => (
            <div className="dc-log-item" key={idx}>
              <span className="dc-log-time">[{log.time}]</span>
              <span className={`dc-log-msg ${log.type}`}>{log.msg}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
