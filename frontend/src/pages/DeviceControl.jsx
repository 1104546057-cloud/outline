import { useState, useEffect, useCallback } from 'react'
import '../styles/DeviceControl.css'

export default function DeviceControl() {
  const [devices, setDevices] = useState([])
  const [selectedDeviceId, setSelectedDeviceId] = useState('')
  const [customCommand, setCustomCommand] = useState('')
  const [customParams, setCustomParams] = useState('')
  const [logs, setLogs] = useState([])
  
  // Track currently pressed key for visual feedback
  const [activeKey, setActiveKey] = useState(null)

  useEffect(() => {
    fetchDevices()
  }, [])

  const fetchDevices = async () => {
    try {
      const res = await fetch('/api/devices', { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setDevices(data)
        if (data.length > 0 && !selectedDeviceId) {
          // Select first online device if possible
          const onlineDev = data.find(d => d.status === 'online') || data[0]
          setSelectedDeviceId(onlineDev.id)
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
    if (!selectedDeviceId) {
      addLog('请先选择一个设备', 'error')
      return
    }

    try {
      const res = await fetch(`/api/devices/${selectedDeviceId}/control`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ command, params: params ? JSON.parse(params) : null })
      })
      if (res.ok) {
        addLog(`成功发送指令: ${command}`)
      } else {
        const err = await res.json()
        addLog(`发送失败: ${err.detail || '未知错误'}`, 'error')
      }
    } catch (e) {
      addLog(`网络/参数解析错误: ${e.message}`, 'error')
    }
  }, [selectedDeviceId])

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
    <div className="device-control-page">
      <div className="dc-header">
        <h1>设备控制</h1>
        <p>远程下发控制指令与遥控驾驶</p>
      </div>

      <div className="dc-selector-card">
        <h2>目标设备</h2>
        <select 
          className="dc-select"
          value={selectedDeviceId}
          onChange={(e) => setSelectedDeviceId(e.target.value)}
        >
          {devices.length === 0 && <option value="">暂无可用设备</option>}
          {devices.map(dev => (
            <option key={dev.id} value={dev.id} disabled={dev.status !== 'online'}>
              [{dev.status === 'online' ? '在线' : '离线'}] {dev.name} ({dev.type}) - {dev.ip_address}
            </option>
          ))}
        </select>
      </div>

      <div className="dc-content-grid">
        <div className="dc-control-card">
          <h3>🕹️ 九宫格遥控 (无人车)</h3>
          <p className="dc-control-desc">支持鼠标点击，或使用键盘数字键 / 小键盘 (8, 2, 4, 6, 5) 进行快捷操控。</p>
          
          <div className="dc-numpad-container">
            <div className="dc-numpad">
              <div className="dc-num-btn invisible"></div>
              <button 
                className={`dc-num-btn ${activeKey === 'forward' ? 'active' : ''}`}
                onClick={() => handlePadClick('forward')}
                disabled={!selectedDeviceId}
              >
                <span className="dc-num-icon">⬆️</span>
                <span className="dc-num-key">8 前进</span>
              </button>
              <div className="dc-num-btn invisible"></div>
              
              <button 
                className={`dc-num-btn ${activeKey === 'left' ? 'active' : ''}`}
                onClick={() => handlePadClick('left')}
                disabled={!selectedDeviceId}
              >
                <span className="dc-num-icon">⬅️</span>
                <span className="dc-num-key">4 左转</span>
              </button>
              <button 
                className={`dc-num-btn stop ${activeKey === 'stop' ? 'active' : ''}`}
                onClick={() => handlePadClick('stop')}
                disabled={!selectedDeviceId}
              >
                <span className="dc-num-icon">⏹️</span>
                <span className="dc-num-key">5 停止</span>
              </button>
              <button 
                className={`dc-num-btn ${activeKey === 'right' ? 'active' : ''}`}
                onClick={() => handlePadClick('right')}
                disabled={!selectedDeviceId}
              >
                <span className="dc-num-icon">➡️</span>
                <span className="dc-num-key">6 右转</span>
              </button>
              
              <div className="dc-num-btn invisible"></div>
              <button 
                className={`dc-num-btn ${activeKey === 'backward' ? 'active' : ''}`}
                onClick={() => handlePadClick('backward')}
                disabled={!selectedDeviceId}
              >
                <span className="dc-num-icon">⬇️</span>
                <span className="dc-num-key">2 后退</span>
              </button>
              <div className="dc-num-btn invisible"></div>
            </div>
          </div>
        </div>

        <div className="dc-control-card">
          <h3>📝 发送特定指令</h3>
          <p className="dc-control-desc">向下位机发送特定的文本指令与自定义参数 (JSON格式)。</p>
          
          <form className="dc-custom-form" onSubmit={handleCustomSend}>
            <div className="dc-input-group">
              <label>指令代码 (Command)</label>
              <input 
                type="text" 
                className="dc-input" 
                placeholder="例如: take_photo, return_home..." 
                value={customCommand}
                onChange={e => setCustomCommand(e.target.value)}
                required
              />
            </div>
            <div className="dc-input-group">
              <label>附加参数 (JSON格式, 可选)</label>
              <input 
                type="text" 
                className="dc-input" 
                placeholder='例如: {"resolution": "1080p"}' 
                value={customParams}
                onChange={e => setCustomParams(e.target.value)}
              />
            </div>
            <button type="submit" className="dc-btn-send" disabled={!selectedDeviceId || !customCommand.trim()}>
              发送指令
            </button>
          </form>
        </div>
      </div>

      <div className="dc-log-container">
        <div className="dc-log-header">
          <h3>终端日志</h3>
          <button className="dc-btn-clear" onClick={() => setLogs([])}>清空日志</button>
        </div>
        <div className="dc-logs">
          {logs.length === 0 && <span style={{color: '#475569'}}>暂无日志...</span>}
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
