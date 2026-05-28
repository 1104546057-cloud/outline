import { useState, useEffect, useCallback, useRef } from 'react'
import '../styles/ClusterControl.css'

export default function ClusterControl() {
  const [clusters, setClusters] = useState([])
  const [selectedClusterId, setSelectedClusterId] = useState('')
  const [logs, setLogs] = useState([])
  const [controlConfig, setControlConfig] = useState({ maxLinear: 0.4, maxAngular: 1.2 })
  const [speedRatio, setSpeedRatio] = useState(0.3) // 速度倍率 0~1
  const [activeDirection, setActiveDirection] = useState(null) // 当前按住的方向
  const [customCommand, setCustomCommand] = useState('{"type":"ping"}')

  // 持续发送定时器
  const sendIntervalRef = useRef(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    fetchClusters()
    fetchControlConfig()
    return () => {
      mountedRef.current = false
      stopSending()
    }
  }, [])

  useEffect(() => {
    stopSending()
    setActiveDirection(null)
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

  const fetchClusters = async () => {
    try {
      const res = await fetch('/api/clusters', { credentials: 'include' })
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
      const res = await fetch('/api/robot-control/config', { credentials: 'include' })
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
      const res = await fetch(`/api/clusters/${selectedClusterId}/cmd_vel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
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
      const res = await fetch(`/api/clusters/${selectedClusterId}/stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
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
      const res = await fetch(`/api/clusters/${selectedClusterId}/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
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

  const selectedCluster = clusters.find(c => String(c.id) === selectedClusterId)
  const onlineCount = selectedCluster ? selectedCluster.devices.filter(d => d.status === 'online').length : 0

  return (
    <div className="cluster-control-page">
      <div className="cc-header">
        <h1 className="page-title">🚀 远程集群控制</h1>
        <span className="page-subtitle">通过 TCP 协议向集群内所有在线设备下发同步控制指令</span>
      </div>

      <div className="cc-selector-card">
        <h2>目标集群</h2>
        <select
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
        </select>
        {selectedCluster && (
          <p style={{ marginTop: '0.8rem', fontSize: '0.85rem', color: '#64748b' }}>
            当前集群共有 <strong>{onlineCount}</strong> 台设备在线，所有指令将广播至这 {onlineCount} 台设备。
          </p>
        )}
      </div>

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
