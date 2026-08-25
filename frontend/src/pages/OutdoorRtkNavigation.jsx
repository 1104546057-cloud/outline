import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import AMapLoader from '@amap/amap-jsapi-loader'
import ThemedSelect from '../components/ThemedSelect'
import { authFetch } from '../utils/authFetch'
import { gcj02ToWgs84, wgs84ToGcj02 } from '../utils/coordinates'
import '../styles/OutdoorRtkNavigation.css'

const AMAP_KEY = import.meta.env.VITE_AMAP_API_KEY
const AMAP_SECURITY_KEY = import.meta.env.VITE_AMAP_API_SECURE_KEY

const readError = async (response, fallback) => {
  try {
    const body = await response.json()
    return body.detail || body.response?.error || fallback
  } catch {
    return fallback
  }
}

const pointYaw = (point, nextPoint) => {
  if (!nextPoint) return 0
  const meanLatitude = ((point.lat + nextPoint.lat) / 2) * Math.PI / 180
  const east = (nextPoint.lng - point.lng) * Math.cos(meanLatitude)
  const north = nextPoint.lat - point.lat
  return Math.atan2(north, east)
}

const formatAge = value => Number.isFinite(value) ? `${value.toFixed(1)} s` : '--'

export default function OutdoorRtkNavigation() {
  const mapElementRef = useRef(null)
  const mapRef = useRef(null)
  const amapRef = useRef(null)
  const overlaysRef = useRef([])
  const [devices, setDevices] = useState([])
  const [areas, setAreas] = useState([])
  const [routes, setRoutes] = useState([])
  const [deviceId, setDeviceId] = useState('')
  const [areaId, setAreaId] = useState('')
  const [routeId, setRouteId] = useState('')
  const [nextPointIndex, setNextPointIndex] = useState(0)
  const [status, setStatus] = useState(null)
  const [mapReady, setMapReady] = useState(false)
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')

  const selectedDevice = useMemo(
    () => devices.find(device => device.id === Number(deviceId)),
    [devices, deviceId],
  )
  const selectedRoute = useMemo(
    () => routes.find(route => route.id === Number(routeId)),
    [routes, routeId],
  )
  const nextPoint = selectedRoute?.points?.[nextPointIndex]
  const rtk = status?.rtk || {}
  const positionLongitude = rtk.position?.longitude
  const positionLatitude = rtk.position?.latitude
  const canSendGoal = Boolean(
    status?.running && rtk.valid && selectedRoute?.points?.length && nextPoint && !status?.safety?.goalActive && !busy,
  )

  useEffect(() => {
    let cancelled = false
    Promise.all([authFetch('/api/devices'), authFetch('/api/patrol/areas')])
      .then(async ([deviceResponse, areaResponse]) => {
        const [deviceData, areaData] = await Promise.all([
          deviceResponse.ok ? deviceResponse.json() : [],
          areaResponse.ok ? areaResponse.json() : [],
        ])
        if (cancelled) return
        setDevices(deviceData)
        setAreas(areaData)
        const preferred = deviceData.find(device => device.control_connected) || deviceData[0]
        if (preferred) setDeviceId(String(preferred.id))
        if (areaData[0]) setAreaId(String(areaData[0].id))
      })
      .catch(error => !cancelled && setMessage(error.message))
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    setRouteId('')
    setNextPointIndex(0)
    if (!areaId) {
      setRoutes([])
      return
    }
    let cancelled = false
    authFetch(`/api/patrol/routes?area_id=${areaId}`)
      .then(response => response.ok ? response.json() : [])
      .then(data => {
        if (cancelled) return
        setRoutes(data)
        if (data[0]) setRouteId(String(data[0].id))
      })
      .catch(error => !cancelled && setMessage(error.message))
    return () => { cancelled = true }
  }, [areaId])

  const refreshStatus = useCallback(async (quiet = false) => {
    if (!deviceId) return
    try {
      const response = await authFetch(`/api/navigation/rtk/status?robotId=${deviceId}`)
      if (!response.ok) throw new Error(await readError(response, '读取 RTK 状态失败'))
      const body = await response.json()
      setStatus(body.response)
      if (!quiet) setMessage('状态已刷新')
    } catch (error) {
      if (!quiet) setMessage(error.message)
    }
  }, [deviceId])

  useEffect(() => {
    setStatus(null)
    if (!deviceId) return undefined
    refreshStatus(true)
    const timer = setInterval(() => refreshStatus(true), 2000)
    return () => clearInterval(timer)
  }, [deviceId, refreshStatus])

  useEffect(() => {
    if (!mapElementRef.current || mapRef.current) return undefined
    window._AMapSecurityConfig = { securityJsCode: AMAP_SECURITY_KEY }
    let disposed = false
    AMapLoader.load({
      key: AMAP_KEY,
      version: '2.0',
      plugins: ['AMap.Marker', 'AMap.Polyline'],
    }).then(AMap => {
      if (disposed) return
      amapRef.current = AMap
      mapRef.current = new AMap.Map(mapElementRef.current, {
        zoom: 18,
        center: [113.584101, 22.349278],
        layers: [new AMap.TileLayer.Satellite(), new AMap.TileLayer.RoadNet()],
      })
      setMapReady(true)
    }).catch(error => {
      if (!disposed) setMessage(`高德地图加载失败：${error.message}`)
    })
    return () => {
      disposed = true
      mapRef.current?.destroy()
      mapRef.current = null
    }
  }, [])

  useEffect(() => {
    const AMap = amapRef.current
    const map = mapRef.current
    if (!AMap || !map) return
    overlaysRef.current.forEach(item => map.remove(item))
    const overlays = []
    const routePoints = selectedRoute?.points || []
    if (routePoints.length) {
      const path = routePoints.map(point => [point.lng, point.lat])
      const line = new AMap.Polyline({ path, strokeColor: '#16a34a', strokeWeight: 5, strokeOpacity: 0.9 })
      overlays.push(line)
      routePoints.forEach((point, index) => {
        overlays.push(new AMap.Marker({
          position: [point.lng, point.lat],
          anchor: 'center',
          content: `<div class="rtk-map-point ${index === nextPointIndex ? 'active' : ''}">${index + 1}</div>`,
        }))
      })
    }
    if (Number.isFinite(positionLongitude) && Number.isFinite(positionLatitude)) {
      const vehiclePosition = wgs84ToGcj02([positionLongitude, positionLatitude])
      overlays.push(new AMap.Marker({
        position: vehiclePosition,
        anchor: 'center',
        content: '<div class="rtk-vehicle-marker"><span></span></div>',
        zIndex: 200,
      }))
    }
    if (overlays.length) {
      map.add(overlays)
      map.setFitView(overlays, false, [60, 60, 60, 60], 19)
    }
    overlaysRef.current = overlays
  }, [selectedRoute, nextPointIndex, positionLongitude, positionLatitude, mapReady])

  const postAction = async (name, url, body) => {
    setBusy(name)
    setMessage('')
    try {
      const response = await authFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!response.ok) throw new Error(await readError(response, `${name}失败`))
      const data = await response.json()
      if (!data.ok) throw new Error(data.response?.error || `${name}失败`)
      if (data.response?.type === 'rtk_nav_status') setStatus(data.response)
      setMessage(`${name}成功`)
      return true
    } catch (error) {
      setMessage(error.message)
      return false
    } finally {
      setBusy('')
    }
  }

  const startRtk = async () => {
    const ok = await postAction('启动 RTK 模式', '/api/navigation/rtk/start', { robotId: Number(deviceId) })
    if (ok) setNextPointIndex(0)
  }

  const stopRtk = () => postAction('停止导航', '/api/navigation/rtk/stop', { robotId: Number(deviceId) })

  const sendNextPoint = async () => {
    if (!nextPoint) return
    const [longitude, latitude] = gcj02ToWgs84([nextPoint.lng, nextPoint.lat])
    const following = selectedRoute.points[nextPointIndex + 1]
    const ok = await postAction('发送航点', '/api/navigation/rtk/goal', {
      robotId: Number(deviceId),
      longitude,
      latitude,
      yaw: pointYaw(nextPoint, following),
    })
    if (ok) {
      setNextPointIndex(index => Math.min(index + 1, selectedRoute.points.length))
      await refreshStatus(true)
    }
  }

  return (
    <div className="rtk-page">
      <header className="rtk-header">
        <div>
          <h1>厘米级 RTK 室外导航</h1>
          <p>高德地图规划 · WGS-84 下发 · 激光滚动避障 · 无需预扫静态地图</p>
        </div>
        <div className={`rtk-fixed-badge ${rtk.valid ? 'valid' : 'invalid'}`}>
          {rtk.valid ? 'RTK FIXED 可导航' : (rtk.qualityLabel || '等待 G70')}
        </div>
      </header>

      <section className="rtk-toolbar">
        <label>车辆<ThemedSelect value={deviceId} onChange={event => setDeviceId(event.target.value)}>
          <option value="">请选择车辆</option>
          {devices.map(device => <option key={device.id} value={device.id}>{device.name} · {device.control_connected ? 'Agent 已连接' : '未连接'}</option>)}
        </ThemedSelect></label>
        <label>区域<ThemedSelect value={areaId} onChange={event => setAreaId(event.target.value)}>
          <option value="">请选择区域</option>
          {areas.map(area => <option key={area.id} value={area.id}>{area.name}</option>)}
        </ThemedSelect></label>
        <label>线路<ThemedSelect value={routeId} onChange={event => { setRouteId(event.target.value); setNextPointIndex(0) }}>
          <option value="">请选择线路</option>
          {routes.map(route => <option key={route.id} value={route.id}>{route.name}（{route.point_count} 点）</option>)}
        </ThemedSelect></label>
      </section>

      <div className="rtk-workspace">
        <div className="rtk-map" ref={mapElementRef} />
        <aside className="rtk-panel">
          <section>
            <h2>定位与安全门</h2>
            <dl className="rtk-status-grid">
              <div><dt>导航进程</dt><dd>{status?.running ? '运行中' : '未启动'}</dd></div>
              <div><dt>GGA 质量</dt><dd>{rtk.quality ?? '--'} / {rtk.qualityLabel || '--'}</dd></div>
              <div><dt>定位时效</dt><dd>{formatAge(rtk.fixAge)}</dd></div>
              <div><dt>跳点检测</dt><dd>{rtk.jump?.active ? '已拦截' : '正常'}</dd></div>
              <div><dt>失锁停车</dt><dd>{status?.safety?.tripped ? '已触发' : '待命'}</dd></div>
              <div><dt>差分方式</dt><dd>{status?.provider?.correctionMode || '--'}</dd></div>
            </dl>
            {rtk.lastError && <div className="rtk-alert">{rtk.lastError}</div>}
            {status?.safety?.reason && <div className="rtk-alert danger">安全停车：{status.safety.reason}</div>}
          </section>

          <section>
            <h2>线路执行</h2>
            <p className="rtk-route-name">{selectedRoute?.name || '尚未选择线路'}</p>
            <p className="rtk-next-point">下一航点：{nextPoint ? `${nextPointIndex + 1}. ${nextPoint.name}` : '线路已发送完毕'}</p>
            <div className="rtk-actions">
              <button className="primary" disabled={!selectedDevice?.control_connected || Boolean(busy)} onClick={startRtk}>启动 RTK 模式</button>
              <button className="success" disabled={!canSendGoal} onClick={sendNextPoint}>发送下一航点</button>
              <button className="danger" disabled={!deviceId || Boolean(busy)} onClick={stopRtk}>停车并退出</button>
              <button disabled={!deviceId || Boolean(busy)} onClick={() => refreshStatus(false)}>刷新状态</button>
            </div>
            <small>航点不会自动连续下发；当前目标结束且 RTK 仍为 Fixed 后，人工确认再发送下一点。</small>
          </section>

          <section className="rtk-coordinate-note">
            <h2>坐标约定</h2>
            <p>高德显示与数据库点位：GCJ-02</p>
            <p>G70、FindCM 与车端目标：WGS-84</p>
            <p>账号密码只保存在车辆环境文件，不进入平台数据库。</p>
          </section>
          {message && <div className="rtk-message">{message}</div>}
        </aside>
      </div>
    </div>
  )
}
