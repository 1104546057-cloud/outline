/* eslint-disable react/prop-types */
import { useCallback, useEffect, useRef, useState } from 'react'
import RobotDirectionPad from './RobotDirectionPad'
import { getRobotDirectionValues, ROBOT_DIRECTION_KEY_MAP } from './robotDirectionPadConfig'
import { authFetch } from '../utils/authFetch'

const SEND_INTERVAL_MS = 180

const readError = async (response, fallback) => {
  try {
    const body = await response.json()
    return body.detail || fallback
  } catch {
    return fallback
  }
}

export default function RtkSurveyCockpit({ deviceId, device, onNotice }) {
  const [controlConfig, setControlConfig] = useState({ maxLinear: 0.4, maxAngular: 1.2 })
  const [speedRatio, setSpeedRatio] = useState(0.15)
  const [armed, setArmed] = useState(false)
  const [activeDirection, setActiveDirection] = useState(null)
  const [cameraStatus, setCameraStatus] = useState('loading')
  const [cameraNonce, setCameraNonce] = useState(0)
  const [controlError, setControlError] = useState('')
  const intervalRef = useRef(null)
  const commandBusyRef = useRef(false)
  const activeDirectionRef = useRef(null)
  const controlledRef = useRef(false)

  const numericDeviceId = Number(deviceId)
  const deviceConnected = Boolean(deviceId && device?.control_connected)
  const streamUrl = deviceId
    ? `/api/devices/${deviceId}/camera/stream${cameraNonce ? `?t=${cameraNonce}` : ''}`
    : ''

  useEffect(() => {
    let cancelled = false
    authFetch('/api/robot-control/config')
      .then(response => response.ok ? response.json() : null)
      .then(data => {
        if (!cancelled && data) setControlConfig(data)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  const stopRepeating = useCallback(() => {
    if (intervalRef.current) clearInterval(intervalRef.current)
    intervalRef.current = null
    activeDirectionRef.current = null
    setActiveDirection(null)
  }, [])

  const sendStop = useCallback(async (quiet = false) => {
    if (!Number.isInteger(numericDeviceId) || numericDeviceId <= 0) return
    try {
      const response = await authFetch('/api/robot-control/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robotId: numericDeviceId }),
      })
      if (!response.ok) throw new Error(await readError(response, '停车指令失败'))
      if (!quiet) onNotice?.('已发送停车指令')
    } catch (error) {
      if (!quiet) setControlError(error.message)
    }
  }, [numericDeviceId, onNotice])

  const sendCmdVel = useCallback(async (linear, angular) => {
    if (!armed || !deviceConnected || commandBusyRef.current) return
    commandBusyRef.current = true
    try {
      const response = await authFetch('/api/robot-control/cmd_vel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robotId: numericDeviceId, linear, angular }),
      })
      if (!response.ok) throw new Error(await readError(response, '车辆控制失败'))
      controlledRef.current = true
      setControlError('')
    } catch (error) {
      setControlError(error.message)
      stopRepeating()
    } finally {
      commandBusyRef.current = false
    }
  }, [armed, deviceConnected, numericDeviceId, stopRepeating])

  const directionValues = useCallback(direction => getRobotDirectionValues(
    direction,
    controlConfig.maxLinear * speedRatio,
    controlConfig.maxAngular * speedRatio,
  ), [controlConfig, speedRatio])

  const startDirection = useCallback(direction => {
    if (!armed || !deviceConnected || activeDirectionRef.current === direction) return
    stopRepeating()
    activeDirectionRef.current = direction
    setActiveDirection(direction)
    const values = directionValues(direction)
    sendCmdVel(values.linear, values.angular)
    intervalRef.current = setInterval(() => {
      const next = directionValues(direction)
      sendCmdVel(next.linear, next.angular)
    }, SEND_INTERVAL_MS)
  }, [armed, deviceConnected, directionValues, sendCmdVel, stopRepeating])

  const stopDirection = useCallback(() => {
    if (!activeDirectionRef.current) return
    stopRepeating()
    sendStop()
  }, [sendStop, stopRepeating])

  const emergencyStop = useCallback(() => {
    stopRepeating()
    setArmed(false)
    sendStop()
  }, [sendStop, stopRepeating])

  const toggleArmed = useCallback(() => {
    if (armed) {
      stopRepeating()
      sendStop()
      setArmed(false)
      return
    }
    setControlError('')
    setArmed(true)
    onNotice?.('遥控已解锁，请保持观察摄像头并按住方向键行驶')
  }, [armed, onNotice, sendStop, stopRepeating])

  const adjustSpeedRatio = useCallback(delta => {
    setSpeedRatio(current => Math.min(0.5, Math.max(0.05, Number((current + delta).toFixed(2)))))
  }, [])

  useEffect(() => {
    stopRepeating()
    setArmed(false)
    setCameraStatus(deviceId ? 'loading' : 'idle')
    setControlError('')
  }, [deviceId, stopRepeating])

  useEffect(() => () => {
    stopRepeating()
    if (controlledRef.current) sendStop(true)
  }, [sendStop, stopRepeating])

  useEffect(() => {
    const isTypingTarget = target => {
      const tag = target?.tagName
      return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target?.isContentEditable
    }

    const handleKeyDown = event => {
      const direction = ROBOT_DIRECTION_KEY_MAP[event.code]
      if (!direction) return
      if (isTypingTarget(event.target)) return
      event.preventDefault()
      if (direction === 'stop') {
        emergencyStop()
        return
      }
      startDirection(direction)
    }

    const handleKeyUp = event => {
      const direction = ROBOT_DIRECTION_KEY_MAP[event.code]
      if (direction && direction !== 'stop' && direction === activeDirectionRef.current) {
        stopDirection()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('keyup', handleKeyUp)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('keyup', handleKeyUp)
    }
  }, [emergencyStop, startDirection, stopDirection])

  const retryCamera = () => {
    setCameraStatus('loading')
    setCameraNonce(Date.now())
  }

  const captureSnapshot = async () => {
    if (!deviceId) return
    try {
      const response = await authFetch(`/api/devices/${deviceId}/camera/snapshot`)
      if (!response.ok) throw new Error(await readError(response, '摄像头截图失败'))
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${device?.name || 'rtk-survey'}_${new Date().toISOString().replace(/[:.]/g, '-')}.jpg`
      link.click()
      URL.revokeObjectURL(url)
      onNotice?.('摄像头截图已保存')
    } catch (error) {
      setControlError(error.message)
    }
  }

  return (
    <section className="rtk-survey-cockpit" aria-label="RTK采集驾驶舱">
      <div className="rtk-cockpit-heading">
        <div>
          <h2>采集驾驶舱</h2>
          <p>摄像头、人工遥控和地图轨迹同屏；遥控不改变车端采集状态。</p>
        </div>
        <span className={`rtk-control-lock ${armed ? 'armed' : ''}`}>{armed ? '遥控已解锁' : '遥控已锁定'}</span>
      </div>
      <div className="rtk-cockpit-grid">
        <div className="rtk-camera-card">
          <div className="rtk-camera-toolbar">
            <strong>实时前视画面</strong>
            <span className={`rtk-camera-state ${cameraStatus}`}>{cameraStatus === 'streaming' ? 'LIVE' : cameraStatus === 'error' ? '未连接' : '连接中'}</span>
            <button type="button" onClick={captureSnapshot} disabled={cameraStatus !== 'streaming'}>截图</button>
            <button type="button" onClick={retryCamera} disabled={!deviceId}>重连</button>
          </div>
          <div className="rtk-camera-stage">
            {streamUrl ? <img
              src={streamUrl}
              alt={`${device?.name || '车辆'}实时摄像头`}
              onLoad={() => setCameraStatus('streaming')}
              onError={() => setCameraStatus('error')}
            /> : null}
            {cameraStatus !== 'streaming' ? <div className="rtk-camera-placeholder">
              <span>◉</span>
              <strong>{deviceId ? '等待车端摄像头画面' : '请先选择车辆'}</strong>
              <small>地图轨迹与RTK采集仍可独立刷新</small>
            </div> : null}
          </div>
        </div>
        <div className="rtk-drive-card">
          <div className="rtk-drive-title">
            <div><strong>人工驾驶</strong><small>按住行驶，松手立即停车</small></div>
            <button type="button" className={armed ? 'lock' : 'unlock'} disabled={!deviceConnected} onClick={toggleArmed}>{armed ? '锁定遥控' : '解锁遥控'}</button>
          </div>
          <div className="rtk-speed-control">
            <span>速度倍率</span><strong>{Math.round(speedRatio * 100)}%</strong>
            <div className="rtk-speed-adjuster">
              <button type="button" onClick={() => adjustSpeedRatio(-0.05)} disabled={Boolean(activeDirection) || speedRatio <= 0.05}>−5%</button>
              <input
                aria-label="速度倍率"
                type="range"
                min="0.05"
                max="0.5"
                step="0.05"
                value={speedRatio}
                onChange={event => setSpeedRatio(Number(event.target.value))}
                disabled={Boolean(activeDirection)}
                title={activeDirection ? '请先松开方向键停车，再调整速度' : '调整人工驾驶速度倍率'}
              />
              <button type="button" onClick={() => adjustSpeedRatio(0.05)} disabled={Boolean(activeDirection) || speedRatio >= 0.5}>+5%</button>
            </div>
          </div>
          <RobotDirectionPad
            className="rtk-direction-pad"
            activeDirection={activeDirection}
            movementDisabled={!armed || !deviceConnected}
            stopDisabled={!deviceId}
            onStart={startDirection}
            onStop={stopDirection}
            onEmergencyStop={emergencyStop}
          />
          {!deviceConnected ? <div className="rtk-control-warning">Agent 未连接，遥控保持锁定</div> : null}
          {controlError ? <div className="rtk-control-warning danger">{controlError}</div> : null}
        </div>
      </div>
    </section>
  )
}
