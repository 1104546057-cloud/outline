/* eslint-disable react/prop-types */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import DeviceCockpitMap from '../components/DeviceCockpitMap'
import DeviceStatusCard from '../components/DeviceStatusCard'
import { authFetch } from '../utils/authFetch'
import '../styles/DeviceCockpit.css'

const DIRECTIONS = [
  { key: 'forward-left', icon: '↖', label: '左前' },
  { key: 'forward', icon: '↑', label: '前进' },
  { key: 'forward-right', icon: '↗', label: '右前' },
  { key: 'left', icon: '←', label: '左转' },
  { key: 'stop', icon: '■', label: '停止' },
  { key: 'right', icon: '→', label: '右转' },
  { key: 'backward-left', icon: '↙', label: '左后' },
  { key: 'backward', icon: '↓', label: '后退' },
  { key: 'backward-right', icon: '↘', label: '右后' },
]

function CockpitPanel({ title, code, meta, className = '', children }) {
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

function CameraFeed({ device, label, view = null, unavailableText = '', simulated = false, large = false, refreshKey = 0, onStatusChange }) {
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

export default function DeviceCockpit() {
  const { deviceId } = useParams()
  const navigate = useNavigate()
  const parsedDeviceId = Number(deviceId)
  const [device, setDevice] = useState(null)
  const [runningTask, setRunningTask] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [controlConfig, setControlConfig] = useState({ maxLinear: .4, maxAngular: 1.2 })
  const [speedRatio, setSpeedRatio] = useState(.65)
  const [connectionStatus, setConnectionStatus] = useState('未检测')
  const [controlMessage, setControlMessage] = useState('等待连接设备控制服务')
  const [activeDirection, setActiveDirection] = useState(null)
  const [mainCameraStatus, setMainCameraStatus] = useState('loading')
  const [cameraRefreshKey, setCameraRefreshKey] = useState(0)
  const sendIntervalRef = useRef(null)
  const activeDirectionRef = useRef(null)
  const commandBusyRef = useRef(false)
  const refreshBusyRef = useRef(false)
  const testedDeviceRef = useRef(null)

  const stopSending = useCallback(() => {
    if (sendIntervalRef.current) clearInterval(sendIntervalRef.current)
    sendIntervalRef.current = null
    activeDirectionRef.current = null
    setActiveDirection(null)
  }, [])

  const sendStop = useCallback(async (silent = false) => {
    if (!Number.isInteger(parsedDeviceId) || parsedDeviceId <= 0) return
    try {
      const response = await authFetch('/api/robot-control/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robotId: parsedDeviceId }),
      })
      if (!response.ok) throw new Error((await response.json()).detail || '停车失败')
      if (!silent) setControlMessage('停车指令已发送')
    } catch (error) {
      if (!silent) setControlMessage(`停车失败：${error.message}`)
    }
  }, [parsedDeviceId])

  const testConnection = useCallback(async () => {
    if (!device) return
    if (device.status !== 'online') {
      setConnectionStatus('不可达')
      setControlMessage('设备离线，运动控制已禁用')
      return
    }
    setConnectionStatus('连接中')
    setControlMessage('正在检测设备控制服务')
    try {
      const response = await authFetch(`/api/robot-control/status?robotId=${parsedDeviceId}`)
      const data = await response.json()
      if (response.ok && data.ok) {
        setConnectionStatus('已连接')
        setControlMessage(`控制服务已连接 ${data.target?.host || device.ip_address}:${data.target?.port || device.port || 9000}`)
      } else {
        setConnectionStatus('不可达')
        setControlMessage(data.detail || '设备控制服务不可达')
      }
    } catch (error) {
      setConnectionStatus('不可达')
      setControlMessage(`连接检测失败：${error.message}`)
    }
  }, [device, parsedDeviceId])

  const fetchCockpitData = useCallback(async () => {
    if (!Number.isInteger(parsedDeviceId) || parsedDeviceId <= 0) {
      setLoading(false)
      setLoadError('设备编号无效')
      return
    }
    if (refreshBusyRef.current) return
    refreshBusyRef.current = true
    try {
      const [deviceResponse, taskResponse] = await Promise.all([
        authFetch('/api/devices'),
        authFetch('/api/patrol/tasks'),
      ])
      if (!deviceResponse.ok || !taskResponse.ok) throw new Error('驾驶舱数据请求失败')
      const [devices, tasks] = await Promise.all([deviceResponse.json(), taskResponse.json()])
      const currentDevice = devices.find(item => item.id === parsedDeviceId)
      if (!currentDevice) {
        setDevice(null)
        setRunningTask(null)
        setLoadError('未找到指定设备，设备可能已被删除')
        return
      }
      setDevice(currentDevice)
      const taskSummary = tasks.find(task => task.device_id === parsedDeviceId && task.status === 'running')
      if (taskSummary) {
        const detailResponse = await authFetch(`/api/patrol/tasks/${taskSummary.id}`)
        setRunningTask(detailResponse.ok ? await detailResponse.json() : taskSummary)
      } else {
        setRunningTask(null)
      }
      setLoadError('')
    } catch (error) {
      console.error(error)
      setLoadError('驾驶舱实时数据暂时无法获取')
    } finally {
      refreshBusyRef.current = false
      setLoading(false)
    }
  }, [parsedDeviceId])

  useEffect(() => {
    fetchCockpitData()
    const timer = setInterval(fetchCockpitData, 5000)
    return () => clearInterval(timer)
  }, [fetchCockpitData])

  useEffect(() => {
    authFetch('/api/robot-control/config')
      .then(response => response.ok ? response.json() : null)
      .then(config => { if (config) setControlConfig(config) })
      .catch(console.error)
  }, [])

  useEffect(() => {
    const testKey = device ? `${device.id}:${device.status}` : null
    if (!device || testedDeviceRef.current === testKey) return
    testedDeviceRef.current = testKey
    testConnection()
  }, [device, testConnection])

  useEffect(() => {
    if (device?.status === 'online') return
    if (activeDirectionRef.current) {
      stopSending()
      sendStop(true)
    }
  }, [device?.status, sendStop, stopSending])

  useEffect(() => {
    const stopOnExit = () => {
      if (!Number.isInteger(parsedDeviceId) || parsedDeviceId <= 0) return
      const body = JSON.stringify({ robotId: parsedDeviceId })
      navigator.sendBeacon('/api/robot-control/stop', new Blob([body], { type: 'application/json' }))
    }
    window.addEventListener('beforeunload', stopOnExit)
    return () => {
      window.removeEventListener('beforeunload', stopOnExit)
      stopSending()
      if (Number.isInteger(parsedDeviceId) && parsedDeviceId > 0) {
        fetch('/api/robot-control/stop', {
          method: 'POST',
          credentials: 'include',
          keepalive: true,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ robotId: parsedDeviceId }),
        }).catch(() => { })
      }
    }
  }, [parsedDeviceId, stopSending])

  const movementEnabled = device?.status === 'online' && connectionStatus === '已连接'

  const getDirectionValues = useCallback(direction => {
    const maxLinear = controlConfig.maxLinear * speedRatio
    const maxAngular = controlConfig.maxAngular * speedRatio
    switch (direction) {
      case 'forward': return { linear: maxLinear, angular: 0 }
      case 'backward': return { linear: -maxLinear, angular: 0 }
      case 'left': return { linear: 0, angular: maxAngular }
      case 'right': return { linear: 0, angular: -maxAngular }
      case 'forward-left': return { linear: maxLinear, angular: maxAngular * .5 }
      case 'forward-right': return { linear: maxLinear, angular: -maxAngular * .5 }
      case 'backward-left': return { linear: -maxLinear, angular: maxAngular * .5 }
      case 'backward-right': return { linear: -maxLinear, angular: -maxAngular * .5 }
      default: return { linear: 0, angular: 0 }
    }
  }, [controlConfig, speedRatio])

  const sendCmdVel = useCallback(async (linear, angular) => {
    if (!movementEnabled || commandBusyRef.current) return
    commandBusyRef.current = true
    try {
      const response = await authFetch('/api/robot-control/cmd_vel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robotId: parsedDeviceId, linear, angular }),
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || '控制失败')
      }
      setControlMessage(`运动指令 v=${linear.toFixed(2)} m/s · w=${angular.toFixed(2)} rad/s`)
    } catch (error) {
      stopSending()
      setConnectionStatus('不可达')
      setControlMessage(`运动控制失败：${error.message}`)
    } finally {
      commandBusyRef.current = false
    }
  }, [movementEnabled, parsedDeviceId, stopSending])

  const startDirection = useCallback(direction => {
    if (!movementEnabled || direction === 'stop' || activeDirectionRef.current === direction) return
    stopSending()
    activeDirectionRef.current = direction
    setActiveDirection(direction)
    const values = getDirectionValues(direction)
    sendCmdVel(values.linear, values.angular)
    sendIntervalRef.current = setInterval(() => {
      const nextValues = getDirectionValues(direction)
      sendCmdVel(nextValues.linear, nextValues.angular)
    }, 180)
  }, [getDirectionValues, movementEnabled, sendCmdVel, stopSending])

  const stopDirection = useCallback(() => {
    if (!activeDirectionRef.current) return
    stopSending()
    sendStop()
  }, [sendStop, stopSending])

  const emergencyStop = useCallback(() => {
    stopSending()
    sendStop()
  }, [sendStop, stopSending])

  useEffect(() => {
    const keyMap = {
      ArrowUp: 'forward', KeyW: 'forward', Numpad8: 'forward',
      ArrowDown: 'backward', KeyS: 'backward', Numpad2: 'backward',
      ArrowLeft: 'left', KeyA: 'left', Numpad4: 'left',
      ArrowRight: 'right', KeyD: 'right', Numpad6: 'right',
      Numpad7: 'forward-left', Numpad9: 'forward-right',
      Numpad1: 'backward-left', Numpad3: 'backward-right',
      Space: 'stop', Numpad5: 'stop',
    }
    const handleKeyDown = event => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName)) return
      const direction = keyMap[event.code]
      if (!direction) return
      event.preventDefault()
      if (direction === 'stop') emergencyStop()
      else startDirection(direction)
    }
    const handleKeyUp = event => {
      if (keyMap[event.code] === activeDirectionRef.current) stopDirection()
    }
    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('keyup', handleKeyUp)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('keyup', handleKeyUp)
    }
  }, [emergencyStop, startDirection, stopDirection])

  const captureSnapshot = async () => {
    if (!device || mainCameraStatus !== 'streaming') return
    try {
      const response = await authFetch(`/api/devices/${device.id}/camera/snapshot`)
      if (!response.ok) throw new Error('截图接口返回失败')
      const url = URL.createObjectURL(await response.blob())
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${device.name}_${new Date().toISOString().replace(/[:.]/g, '-')}.jpg`
      anchor.click()
      URL.revokeObjectURL(url)
      setControlMessage('摄像头截图已保存')
    } catch (error) {
      setControlMessage(`截图失败：${error.message}`)
    }
  }

  const locationText = useMemo(() => {
    if (!device?.lng || !device?.lat) return '暂无定位'
    return `${Number(device.lng).toFixed(6)}, ${Number(device.lat).toFixed(6)}`
  }, [device])

  if (loading) {
    return <div className="cockpit-page-state"><span className="cockpit-radar" /><strong>正在建立设备驾驶舱</strong><small>同步设备、视频和巡逻数据</small></div>
  }

  if (!device) {
    return (
      <div className="cockpit-page-state error">
        <strong>{loadError || '设备不存在'}</strong>
        <small>无法打开该设备的专属驾驶舱</small>
        <button type="button" onClick={() => navigate('/dashboard')}>返回主界面</button>
      </div>
    )
  }

  return (
    <div className="device-cockpit-page">
      <div className="cockpit-status-line">
        <button type="button" onClick={() => navigate('/dashboard')}>← 返回主界面</button>
        <span><i className={device.status} />{device.name}</span>
        <span>坐标 <b>{locationText}</b></span>
        <span>巡逻任务 <b>{runningTask?.name || '当前无执行中任务'}</b></span>
        {loadError && <em>{loadError}</em>}
      </div>

      <div className="cockpit-layout">
        <aside className="cockpit-left-column">
          <CockpitPanel title="设备状态" code="DEVICE STATUS" meta={device.status === 'online' ? '实时' : '离线'} className="cockpit-device-panel">
            <DeviceStatusCard device={device} selected />
          </CockpitPanel>
          <CockpitPanel title="摄像头画面" code="CAMERA" meta="01">
            <CameraFeed device={device} label="可见光摄像头" view="color" refreshKey={cameraRefreshKey} />
          </CockpitPanel>
          <CockpitPanel title="双目深度图" code="DEPTH" meta="02">
            <CameraFeed device={device} label="双目深度图" view="depth" refreshKey={cameraRefreshKey} />
          </CockpitPanel>
          <CockpitPanel title="激光雷达" code="LIDAR" meta="03">
            <CameraFeed device={device} label="C16 16线点云" view="lidar" refreshKey={cameraRefreshKey} />
          </CockpitPanel>
          <CockpitPanel title="巡逻路线" code="PATROL ROUTE" meta={runningTask ? '执行中' : '实时定位'} className="cockpit-map-panel">
            <DeviceCockpitMap device={device} task={runningTask} />
            <div className="cockpit-map-legend">
              {runningTask && <><span><i className="route" />预设线路</span><span><i className="track" />实际轨迹</span></>}
              <span><i className="position" />当前位置</span>
            </div>
          </CockpitPanel>
        </aside>

        <section className="cockpit-right-column">
          <CockpitPanel title={`${device.name} 主摄像头`} code="PRIMARY CAMERA STREAM" meta={mainCameraStatus === 'streaming' ? 'LIVE' : 'MONITORING'} className="cockpit-main-video-panel">
            <CameraFeed device={device} label="主摄像头" view="color" large refreshKey={cameraRefreshKey} onStatusChange={setMainCameraStatus} />
            <div className="cockpit-video-tools">
              <button type="button" onClick={() => setCameraRefreshKey(key => key + 1)}>重新连接</button>
              <button type="button" onClick={captureSnapshot} disabled={mainCameraStatus !== 'streaming'}>截图保存</button>
            </div>
          </CockpitPanel>

          <CockpitPanel title="设备操作台" code="REMOTE CONTROL CONSOLE" meta={connectionStatus} className="cockpit-console-panel">
            <div className="cockpit-console">
              <div className="cockpit-drive-block">
                <div className="cockpit-block-title"><strong>行驶控制</strong><small>WASD / 方向键 / 数字键盘</small></div>
                <div className="cockpit-direction-grid">
                  {DIRECTIONS.map(direction => direction.key === 'stop' ? (
                    <button key={direction.key} type="button" className="stop" onClick={emergencyStop} disabled={!device} title={direction.label}>
                      <span>{direction.icon}</span><small>{direction.label}</small>
                    </button>
                  ) : (
                    <button
                      key={direction.key}
                      type="button"
                      className={activeDirection === direction.key ? 'active' : ''}
                      onPointerDown={() => startDirection(direction.key)}
                      onPointerUp={stopDirection}
                      onPointerCancel={stopDirection}
                      onPointerLeave={stopDirection}
                      disabled={!movementEnabled}
                      title={direction.label}
                    >
                      <span>{direction.icon}</span><small>{direction.label}</small>
                    </button>
                  ))}
                </div>
              </div>

              <div className="cockpit-speed-block">
                <div className="cockpit-block-title"><strong>动力与连接</strong><small>{controlMessage}</small></div>
                <div className="cockpit-connection-row">
                  <span className={`cockpit-connection ${connectionStatus}`}>{connectionStatus}</span>
                  <button type="button" onClick={testConnection} disabled={connectionStatus === '连接中'}>检测连接</button>
                </div>
                <label className="cockpit-speed-slider">
                  <span>速度倍率 <b>{Math.round(speedRatio * 100)}%</b></span>
                  <input type="range" min="0.1" max="1" step="0.05" value={speedRatio} onChange={event => setSpeedRatio(Number(event.target.value))} />
                </label>
                <div className="cockpit-speed-values">
                  <span>线速度<b>{(controlConfig.maxLinear * speedRatio).toFixed(2)} m/s</b></span>
                  <span>角速度<b>{(controlConfig.maxAngular * speedRatio).toFixed(2)} rad/s</b></span>
                </div>
                <button type="button" className="cockpit-emergency" onClick={emergencyStop}>急停 EMERGENCY STOP</button>
              </div>

              <div className="cockpit-aux-block">
                <div className="cockpit-block-title"><strong>辅助设备</strong><small>界面预留 · 功能待接入</small></div>
                <div className="cockpit-speaker-control">
                  <label>喊话器</label>
                  <textarea disabled placeholder="输入喊话内容" />
                  <div><button type="button" disabled>开始喊话</button><button type="button" disabled>停止喊话</button></div>
                </div>
                <div className="cockpit-light-control">
                  <div><label>探照灯</label><button type="button" disabled>关闭</button></div>
                  <input type="range" min="0" max="100" value="70" disabled readOnly />
                  <span>亮度 70% · 待接入</span>
                </div>
              </div>
            </div>
          </CockpitPanel>
        </section>
      </div>
    </div>
  )
}
