import { useState, useEffect, useCallback } from 'react'
import '../styles/ClusterControl.css'

export default function ClusterControl() {
  const [clusters, setClusters] = useState([])
  const [selectedClusterId, setSelectedClusterId] = useState('')
  const [customCommand, setCustomCommand] = useState('')
  const [customParams, setCustomParams] = useState('')
  const [logs, setLogs] = useState([])
  
  // Track currently pressed key for visual feedback
  const [activeKey, setActiveKey] = useState(null)

  useEffect(() => {
    fetchClusters()
  }, [])

  const fetchClusters = async () => {
    try {
      const res = await fetch('/api/clusters', { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setClusters(data)
        if (data.length > 0 && !selectedClusterId) {
          setSelectedClusterId(data[0].id)
        }
      }
    } catch (e) {
      console.error(e)
    }
  }

  const addLog = (msg, type = 'success') => {
    const time = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    setLogs(prev => [{ time, msg, type }, ...prev].slice(0, 50))
  }

  const sendCommand = useCallback(async (command, params = null) => {
    if (!selectedClusterId) {
      addLog('请先选择一个集群', 'error')
      return
    }

    try {
      const res = await fetch(`/api/clusters/${selectedClusterId}/control`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ command, params: params ? JSON.parse(params) : null })
      })
      if (res.ok) {
        const data = await res.json()
        addLog(data.message, 'success')
      } else {
        const err = await res.json()
        addLog(`发送失败: ${err.detail || '未知错误'}`, 'error')
      }
    } catch (e) {
      addLog(`网络/参数解析错误: ${e.message}`, 'error')
    }
  }, [selectedClusterId])

  // Keyboard controls for 9-grid
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Ignore if typing in input
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return

      const keyMap = {
        '8': 'forward',
        'Numpad8': 'forward',
        '2': 'backward',
        'Numpad2': 'backward',
        '4': 'left',
        'Numpad4': 'left',
        '6': 'right',
        'Numpad6': 'right',
        '5': 'stop',
        'Numpad5': 'stop',
      }

      const cmd = keyMap[e.code] || keyMap[e.key]
      if (cmd && activeKey !== cmd) {
        setActiveKey(cmd)
        sendCommand(cmd)
      }
    }

    const handleKeyUp = (e) => {
      const keyMap = {
        '8': 'forward', 'Numpad8': 'forward',
        '2': 'backward', 'Numpad2': 'backward',
        '4': 'left', 'Numpad4': 'left',
        '6': 'right', 'Numpad6': 'right',
        '5': 'stop', 'Numpad5': 'stop',
      }
      const cmd = keyMap[e.code] || keyMap[e.key]
      if (cmd === activeKey) {
        setActiveKey(null)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('keyup', handleKeyUp)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('keyup', handleKeyUp)
    }
  }, [sendCommand, activeKey])

  const handleCustomSend = (e) => {
    e.preventDefault()
    if (!customCommand.trim()) return
    
    // Check if params is valid JSON if provided
    if (customParams.trim()) {
      try {
        JSON.parse(customParams)
      } catch (e) {
        addLog('参数必须是合法的 JSON 格式', 'error')
        return
      }
    }
    
    sendCommand(customCommand, customParams || null)
  }

  const handlePadClick = (cmd) => {
    sendCommand(cmd)
  }

  return (
    <div className="cluster-control-page">
      <div className="cc-header">
        <h1>集群控制</h1>
        <p>一键向集群内所有在线设备下发同步动作指令</p>
      </div>

      <div className="cc-selector-card">
        <h2>目标集群</h2>
        <select 
          className="cc-select"
          value={selectedClusterId}
          onChange={(e) => setSelectedClusterId(e.target.value)}
        >
          {clusters.length === 0 && <option value="">暂无可用集群</option>}
          {clusters.map(cluster => (
            <option key={cluster.id} value={cluster.id}>
              {cluster.name} (包含 {cluster.devices.length} 台设备)
            </option>
          ))}
        </select>
      </div>

      <div className="cc-content-grid">
        <div className="cc-control-card">
          <h3>🕹️ 九宫格遥控 (集群编队)</h3>
          <p className="cc-control-desc">支持鼠标点击，或使用键盘数字键 / 小键盘 (8, 2, 4, 6, 5) 进行快捷操控。将对集群内所有在线设备下发相同动作。</p>
          
          <div className="cc-numpad-container">
            <div className="cc-numpad">
              <div className="cc-num-btn invisible"></div>
              <button 
                className={`cc-num-btn ${activeKey === 'forward' ? 'active' : ''}`}
                onClick={() => handlePadClick('forward')}
                disabled={!selectedClusterId}
              >
                <span className="cc-num-icon">⬆️</span>
                <span className="cc-num-key">8 前进</span>
              </button>
              <div className="cc-num-btn invisible"></div>
              
              <button 
                className={`cc-num-btn ${activeKey === 'left' ? 'active' : ''}`}
                onClick={() => handlePadClick('left')}
                disabled={!selectedClusterId}
              >
                <span className="cc-num-icon">⬅️</span>
                <span className="cc-num-key">4 左转</span>
              </button>
              <button 
                className={`cc-num-btn stop ${activeKey === 'stop' ? 'active' : ''}`}
                onClick={() => handlePadClick('stop')}
                disabled={!selectedClusterId}
              >
                <span className="cc-num-icon">⏹️</span>
                <span className="cc-num-key">5 停止</span>
              </button>
              <button 
                className={`cc-num-btn ${activeKey === 'right' ? 'active' : ''}`}
                onClick={() => handlePadClick('right')}
                disabled={!selectedClusterId}
              >
                <span className="cc-num-icon">➡️</span>
                <span className="cc-num-key">6 右转</span>
              </button>
              
              <div className="cc-num-btn invisible"></div>
              <button 
                className={`cc-num-btn ${activeKey === 'backward' ? 'active' : ''}`}
                onClick={() => handlePadClick('backward')}
                disabled={!selectedClusterId}
              >
                <span className="cc-num-icon">⬇️</span>
                <span className="cc-num-key">2 后退</span>
              </button>
              <div className="cc-num-btn invisible"></div>
            </div>
          </div>
        </div>

        <div className="cc-control-card">
          <h3>📝 发送特定指令</h3>
          <p className="cc-control-desc">向集群下发特定的文本指令与自定义参数 (JSON格式)。</p>
          
          <form className="cc-custom-form" onSubmit={handleCustomSend}>
            <div className="cc-input-group">
              <label>指令代码 (Command)</label>
              <input 
                type="text" 
                className="cc-input" 
                placeholder="例如: take_photo, return_home..." 
                value={customCommand}
                onChange={e => setCustomCommand(e.target.value)}
                required
              />
            </div>
            <div className="cc-input-group">
              <label>附加参数 (JSON格式, 可选)</label>
              <input 
                type="text" 
                className="cc-input" 
                placeholder='例如: {"resolution": "1080p"}' 
                value={customParams}
                onChange={e => setCustomParams(e.target.value)}
              />
            </div>
            <button type="submit" className="cc-btn-send" disabled={!selectedClusterId || !customCommand.trim()}>
              广播指令到集群
            </button>
          </form>
        </div>
      </div>

      <div className="cc-log-container">
        <div className="cc-log-header">
          <h3>下发终端日志</h3>
          <button className="cc-btn-clear" onClick={() => setLogs([])}>清空日志</button>
        </div>
        <div className="cc-logs">
          {logs.length === 0 && <span style={{color: '#94a3b8'}}>暂无下发日志...</span>}
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
