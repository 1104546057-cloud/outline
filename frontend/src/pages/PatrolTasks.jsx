import { useState, useEffect, useRef, useCallback } from 'react'
import AMapLoader from '@amap/amap-jsapi-loader'
import { useSearchParams } from 'react-router-dom'
import ThemedSelect from '../components/ThemedSelect'
import { authFetch } from '../utils/authFetch'
import { wgs84CoordinatesToGcj02 } from '../utils/coordinates'
import '../styles/Patrol.css'

const AMAP_KEY = import.meta.env.VITE_AMAP_API_KEY
const AMAP_SECURITY_KEY = import.meta.env.VITE_AMAP_API_SECURE_KEY

const STATUS_LABEL = {
  pending: '待开始',
  running: '巡检中',
  paused: '已暂停',
  completed: '已完成',
  cancelled: '已取消',
}

const STATUS_CLASS = {
  pending: 'patrol-status-pending',
  running: 'patrol-status-running',
  paused: 'patrol-status-paused',
  completed: 'patrol-status-completed',
  cancelled: 'patrol-status-cancelled',
}

const formatDist = (m) => {
  if (!m) return '--'
  if (m >= 1000) return `${(m / 1000).toFixed(2)} km`
  return `${Math.round(m)} m`
}

const formatTime = (iso) => {
  if (!iso) return '--'
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

/** 任务详情地图组件 */
function TaskDetailMap({ task, device }) {
  const mapRef = useRef(null)
  const mapInstanceRef = useRef(null)
  const amapRef = useRef(null)
  const [mapReady, setMapReady] = useState(false)
  const objectsRef = useRef([])
  const hasFitViewRef = useRef(false)

  // 1. 初始化地图（只执行一次）
  useEffect(() => {
    if (!mapRef.current) return
    window._AMapSecurityConfig = { securityJsCode: AMAP_SECURITY_KEY }
    let isMounted = true
    AMapLoader.load({
      key: AMAP_KEY,
      version: '2.0',
      plugins: ['AMap.Polyline', 'AMap.Marker'],
    }).then((AMap) => {
      if (!isMounted) return
      amapRef.current = AMap
      const map = new AMap.Map(mapRef.current, {
        zoom: 16.8,
        center: [113.584101, 22.349278],
        layers: [
          new AMap.TileLayer.Satellite(),
          new AMap.TileLayer.RoadNet(),
        ],
      })
      mapInstanceRef.current = map
      setMapReady(true)
    }).catch(console.error)

    return () => { 
      isMounted = false
      mapInstanceRef.current?.destroy() 
      mapInstanceRef.current = null
    }
  }, [])

  // 2. 渲染数据（当 task, device, mapReady 变化时执行）
  useEffect(() => {
    const map = mapInstanceRef.current
    const AMap = amapRef.current
    if (!mapReady || !map || !AMap || !task) return

    // 清除旧覆盖物
    objectsRef.current.forEach(o => map.remove(o))
    objectsRef.current = []
    const objects = []

    // 绘制预设线路（蓝色）
    if (task.route?.points?.length >= 2) {
      const path = task.route.points.map(p => new AMap.LngLat(p.lng, p.lat))
      if (task.route.points.length > 2) path.push(new AMap.LngLat(task.route.points[0].lng, task.route.points[0].lat))
      const routeLine = new AMap.Polyline({
        path, strokeColor: '#4f6ef7', strokeWeight: 3, strokeOpacity: 0.85, strokeStyle: 'dashed', lineJoin: 'round',
      })
      map.add(routeLine)
      objects.push(routeLine)

      task.route.points.forEach((pt, i) => {
        let text = `${i + 1}`
        let bg = '#4f6ef7'
        if (i === 0) { text = '起'; bg = '#10b981' }
        else if (i === task.route.points.length - 1) { text = '终'; bg = '#ef4444' }
        const m = new AMap.Marker({
          position: [pt.lng, pt.lat],
          content: `<div style="width:22px;height:22px;background:${bg};border:2px solid #fff;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:#fff;box-shadow:0 2px 6px rgba(0,0,0,0.2)">${text}</div>`,
          anchor: 'center',
        })
        map.add(m)
        objects.push(m)
      })

      task.route.points.forEach((pt, i) => {
        const next = task.route.points[(i + 1) % task.route.points.length]
        const mid = new AMap.LngLat((pt.lng + next.lng) / 2, (pt.lat + next.lat) / 2)
        const arrowMarker = new AMap.Marker({
          position: mid,
          content: `<div style="color:#4f6ef7;font-size:16px;transform:rotate(${90 - Math.atan2(next.lat - pt.lat, next.lng - pt.lng) * 180 / Math.PI}deg)">▲</div>`,
          anchor: 'center',
        })
        map.add(arrowMarker)
        objects.push(arrowMarker)
      })
    }

    // 绘制 GPS 实际轨迹 + 当前位置，GPS 坐标为 WGS-84，需转换为 GCJ-02
    const gpsPoints = task.gps_track || []
    // 收集所有需要转换的 GPS 坐标（轨迹 + 设备当前位置）
    const rawCoords = gpsPoints.map(p => [p.lng, p.lat])
    if (rawCoords.length === 0 && device && device.lng && device.lat) {
      rawCoords.push([parseFloat(device.lng), parseFloat(device.lat)])
    }

    if (rawCoords.length > 0) {
      const locs = wgs84CoordinatesToGcj02(rawCoords)

      // 绘制 GPS 轨迹线（绿色）
      if (gpsPoints.length >= 2) {
        const gpsPath = locs.slice(0, gpsPoints.length).map(([lng, lat]) => new AMap.LngLat(lng, lat))
        const gpsLine = new AMap.Polyline({
          path: gpsPath, strokeColor: '#22c55e', strokeWeight: 4, strokeOpacity: 0.95, lineJoin: 'round', lineCap: 'round',
        })
        map.add(gpsLine)
        objects.push(gpsLine)
      }

      // 当前位置标记（取最后一个转换后的坐标）
      const lastLoc = locs[locs.length - 1]
      if (lastLoc) {
        const curMarker = new AMap.Marker({
          position: lastLoc,
          content: `<div style="width:18px;height:18px;background:#22c55e;border:3px solid #fff;border-radius:50%;box-shadow:0 0 0 4px rgba(34,197,94,0.3)"></div>`,
          anchor: 'center',
        })
        map.add(curMarker)
        objects.push(curMarker)
      }

      objectsRef.current = objects

      // 只在初次加载路线时自适应一次视野，避免刷新时乱跳
      if (objects.length > 0 && !hasFitViewRef.current) {
        map.setFitView(objects, false, [30, 30, 30, 30], 17)
        hasFitViewRef.current = true
      }
    } else {
      objectsRef.current = objects

      if (objects.length > 0 && !hasFitViewRef.current) {
        map.setFitView(objects, false, [30, 30, 30, 30], 17)
        hasFitViewRef.current = true
      }
    }
  }, [mapReady, task, device])

  return <div ref={mapRef} className="patrol-task-map-el" />
}

/** 摄像头实时画面 */
function TaskCamera({ deviceIp, devicePort }) {
  const [imgSrc, setImgSrc] = useState(null)
  const [camError, setCamError] = useState(false)

  useEffect(() => {
    if (!deviceIp) return
    const STREAM_PORT = 8080
    // 使用 action=stream 获取实时的 MJPEG 视频流，无需 interval 轮询
    setImgSrc(`http://${deviceIp}:${STREAM_PORT}/?action=stream`)
  }, [deviceIp])

  if (!deviceIp) {
    return (
      <div className="patrol-video-placeholder">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2"><polygon points="23,7 16,12 23,17 23,7" /><rect x="1" y="5" width="15" height="14" rx="2" /></svg>
        <span>未绑定设备</span>
      </div>
    )
  }

  return camError ? (
    <div className="patrol-video-placeholder">
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2"><polygon points="23,7 16,12 23,17 23,7" /><rect x="1" y="5" width="15" height="14" rx="2" /></svg>
      <span>摄像头连接失败</span>
    </div>
  ) : (
    <img
      className="patrol-video-frame"
      src={imgSrc}
      alt="实时画面"
      onError={() => setCamError(true)}
    />
  )
}

export default function PatrolTasks() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [tasks, setTasks] = useState([])
  const [routes, setRoutes] = useState([])
  const [devices, setDevices] = useState([])
  const [loading, setLoading] = useState(true)

  // 新建弹窗
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [createForm, setCreateForm] = useState({ name: '', route_id: '', device_id: '' })
  const [createError, setCreateError] = useState('')
  const [creating, setCreating] = useState(false)

  // 详情弹窗
  const [showDetailModal, setShowDetailModal] = useState(false)
  const [detailTask, setDetailTask] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const [deleteConfirm, setDeleteConfirm] = useState(null)
  const openedTaskIdRef = useRef(null)

  const fetchTasks = useCallback(async () => {
    try {
      const res = await authFetch('/api/patrol/tasks')
      if (res.ok) setTasks(await res.json())
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    fetchTasks()
    const t = setInterval(fetchTasks, 5000)
    return () => clearInterval(t)
  }, [fetchTasks])

  useEffect(() => {
    // 加载所有线路和设备
    authFetch('/api/patrol/routes').then(r => r.ok ? r.json() : []).then(setRoutes).catch(console.error)
    authFetch('/api/devices').then(r => r.ok ? r.json() : []).then(setDevices).catch(console.error)
  }, [])

  // 加载任务详情
  const loadDetail = async (task) => {
    setDetailLoading(true)
    setShowDetailModal(true)
    try {
      const res = await authFetch(`/api/patrol/tasks/${task.id}`)
      if (res.ok) setDetailTask(await res.json())
    } catch (e) { console.error(e) }
    finally { setDetailLoading(false) }
  }

  useEffect(() => {
    const taskId = Number(searchParams.get('task'))
    if (!Number.isInteger(taskId) || taskId <= 0 || openedTaskIdRef.current === taskId) return
    openedTaskIdRef.current = taskId
    loadDetail({ id: taskId })
  }, [searchParams])

  const closeDetail = () => {
    setShowDetailModal(false)
    setDetailTask(null)
    openedTaskIdRef.current = null
    if (searchParams.has('task')) setSearchParams({}, { replace: true })
  }

  // 刷新详情（任务运行或待开始时定期刷新轨迹/设备位置）
  useEffect(() => {
    if (!showDetailModal || !detailTask) return
    if (detailTask.status !== 'running' && detailTask.status !== 'pending') return
    const t = setInterval(async () => {
      const res = await authFetch(`/api/patrol/tasks/${detailTask.id}`)
      if (res.ok) setDetailTask(await res.json())
      const dRes = await authFetch('/api/devices')
      if (dRes.ok) setDevices(await dRes.json())
    }, 3000)
    return () => clearInterval(t)
  }, [showDetailModal, detailTask])

  // 任务状态操作
  const handleTaskAction = async (taskId, action) => {
    try {
      const res = await authFetch(`/api/patrol/tasks/${taskId}/${action}`, { method: 'PUT' })
      if (res.ok) {
        fetchTasks()
        if (detailTask?.id === taskId) {
          const r2 = await authFetch(`/api/patrol/tasks/${taskId}`)
          if (r2.ok) setDetailTask(await r2.json())
        }
      }
    } catch (e) { console.error(e) }
  }

  // GPS 轨迹采集已由后端在设备遥测上报时自动完成，前端只做状态操作
  const handleStart = (task) => handleTaskAction(task.id, 'start')
  const handleStop = (task) => handleTaskAction(task.id, 'stop')
  const handlePause = (task) => handleTaskAction(task.id, 'pause')
  const handleResume = (task) => handleTaskAction(task.id, 'resume')

  const handleCreate = async (e) => {
    e.preventDefault()
    if (!createForm.name.trim()) { setCreateError('请填写任务名称'); return }
    if (!createForm.route_id) { setCreateError('请选择巡检线路'); return }
    setCreating(true)
    setCreateError('')
    try {
      const res = await authFetch('/api/patrol/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: createForm.name,
          route_id: Number(createForm.route_id),
          device_id: createForm.device_id ? Number(createForm.device_id) : null,
        }),
      })
      if (res.ok) {
        setShowCreateModal(false)
        setCreateForm({ name: '', route_id: '', device_id: '' })
        fetchTasks()
      } else {
        const err = await res.json()
        setCreateError(err.detail || '创建失败')
      }
    } catch (e) { setCreateError('网络错误') }
    finally { setCreating(false) }
  }

  const trackLen = (task) => task.gps_track?.length || 0

  return (
    <div className="patrol-page">
      <div className="patrol-header">
        <div className="patrol-header-left">
          <h1>巡检任务</h1>
          <span className="patrol-subtitle">创建并监控无人设备的巡检执行任务</span>
        </div>
        <div className="patrol-header-actions">
          <button className="patrol-btn patrol-btn-primary" onClick={() => { setShowCreateModal(true); setCreateError('') }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
            新建任务
          </button>
        </div>
      </div>

      {/* 任务卡片网格 */}
      <div className="patrol-task-grid" style={{ flex: 1, overflow: 'auto' }}>
        {loading ? (
          <div className="patrol-loading" style={{ gridColumn: '1/-1' }}>
            <div className="patrol-spinner" /><span>加载中...</span>
          </div>
        ) : tasks.length === 0 ? (
          <div className="patrol-empty" style={{ gridColumn: '1/-1', paddingTop: '5rem' }}>
            <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2" /><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" /></svg>
            <p>暂无巡检任务<br />点击「新建任务」开始</p>
          </div>
        ) : tasks.map(task => (
          <div key={task.id} className={`patrol-task-card ${task.status === 'running' ? 'running' : ''}`}>
            <div className="patrol-task-card-header">
              <div className="patrol-task-title">{task.name}</div>
              <span className={`patrol-status-badge ${STATUS_CLASS[task.status]}`}>
                {task.status === 'running' && '● '}
                {STATUS_LABEL[task.status] || task.status}
              </span>
            </div>

            <div className="patrol-task-info">
              <div className="patrol-task-info-row">
                <span className="label">📋 线路</span>
                <span>{task.route_name || <em style={{ color: 'var(--color-text-muted)' }}>未关联</em>}</span>
              </div>
              <div className="patrol-task-info-row">
                <span className="label">🤖 设备</span>
                <span>{task.device_name || <em style={{ color: 'var(--color-text-muted)' }}>未绑定</em>}</span>
              </div>
              <div className="patrol-task-info-row">
                <span className="label">📡 轨迹</span>
                <span>{trackLen(task)} 个点</span>
              </div>
              <div className="patrol-task-info-row">
                <span className="label">⏱️ 开始</span>
                <span>{formatTime(task.started_at)}</span>
              </div>
            </div>

            <div className="patrol-task-actions">
              {/* 查看详情 */}
              <button className="patrol-btn patrol-btn-secondary patrol-btn-sm" onClick={() => loadDetail(task)}>
                🗺️ 查看
              </button>
              {/* 状态相关操作 */}
              {(task.status === 'pending' || task.status === 'completed' || task.status === 'cancelled') && (
                <button className="patrol-btn patrol-btn-success patrol-btn-sm" onClick={() => handleStart(task)}>
                  ▶ {task.status === 'pending' ? '开始' : '重新开始'}
                </button>
              )}
              {task.status === 'running' && (<>
                <button className="patrol-btn patrol-btn-warning patrol-btn-sm" onClick={() => handlePause(task)}>
                  ⏸ 暂停
                </button>
                <button className="patrol-btn patrol-btn-danger patrol-btn-sm" onClick={() => handleStop(task)}>
                  ⏹ 停止
                </button>
              </>)}
              {task.status === 'paused' && (<>
                <button className="patrol-btn patrol-btn-success patrol-btn-sm" onClick={() => handleResume(task)}>
                  ▶ 继续
                </button>
                <button className="patrol-btn patrol-btn-danger patrol-btn-sm" onClick={() => handleStop(task)}>
                  ⏹ 停止
                </button>
              </>)}
              {(task.status === 'completed' || task.status === 'cancelled') && (
                <button className="patrol-btn patrol-btn-danger patrol-btn-sm" onClick={() => setDeleteConfirm(task)}>
                  🗑️ 删除
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* 新建任务弹窗 */}
      {showCreateModal && (
        <div className="patrol-modal-overlay">
          <div className="patrol-modal" onClick={e => e.stopPropagation()}>
            <div className="patrol-modal-header">
              <h2>新建巡检任务</h2>
              <button className="patrol-modal-close" onClick={() => setShowCreateModal(false)}>✕</button>
            </div>
            <form onSubmit={handleCreate}>
              <div className="patrol-modal-body">
                <div className="patrol-form-group">
                  <label>任务名称 <span style={{ color: '#ef4444' }}>*</span></label>
                  <input type="text" value={createForm.name} onChange={e => setCreateForm({ ...createForm, name: e.target.value })} placeholder="例：2026-06-05 软院内部巡检" required disabled={creating} />
                </div>
                <div className="patrol-form-group">
                  <label>巡检线路 <span style={{ color: '#ef4444' }}>*</span></label>
                  <ThemedSelect value={createForm.route_id} onChange={e => setCreateForm({ ...createForm, route_id: e.target.value })} disabled={creating}>
                    <option value="">-- 选择线路 --</option>
                    {routes.map(r => <option key={r.id} value={r.id}>{r.name}（{r.point_count || 0} 点位）</option>)}
                  </ThemedSelect>
                </div>
                <div className="patrol-form-group">
                  <label>执行设备（可选）</label>
                  <ThemedSelect value={createForm.device_id} onChange={e => setCreateForm({ ...createForm, device_id: e.target.value })} disabled={creating}>
                    <option value="">-- 不绑定设备 --</option>
                    {devices.map(d => <option key={d.id} value={d.id}>{d.name}（{d.status === 'online' ? '🟢 在线' : '⚫ 离线'}）</option>)}
                  </ThemedSelect>
                  <span className="patrol-form-hint">绑定设备后，任务运行时将自动读取设备GPS位置记录轨迹</span>
                </div>
                {createError && <div className="patrol-form-error">{createError}</div>}
              </div>
              <div className="patrol-modal-footer">
                <button type="button" className="patrol-btn patrol-btn-secondary" onClick={() => setShowCreateModal(false)} disabled={creating}>取消</button>
                <button type="submit" className="patrol-btn patrol-btn-primary" disabled={creating}>
                  {creating ? '创建中...' : '创建任务'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 任务详情弹窗 */}
      {showDetailModal && (
        <div className="patrol-modal-overlay">
          <div className="patrol-modal patrol-modal-wide" style={{ maxWidth: 760 }} onClick={e => e.stopPropagation()}>
            <div className="patrol-modal-header">
              <h2>📋 {detailTask?.name || '任务详情'}</h2>
              <button
                className="patrol-modal-close"
                type="button"
                aria-label="关闭任务详情"
                title="关闭"
                onClick={closeDetail}
              >✕</button>
            </div>
            <div className="patrol-modal-body">
              {detailLoading ? (
                <div className="patrol-loading"><div className="patrol-spinner" /><span>加载中...</span></div>
              ) : detailTask ? (
                <div className="patrol-task-detail">
                  {/* 统计信息 */}
                  <div className="patrol-task-stats">
                    <div className="patrol-task-stat">
                      <span className="patrol-task-stat-label">状态</span>
                      <span className={`patrol-status-badge ${STATUS_CLASS[detailTask.status]}`} style={{ width: 'fit-content' }}>
                        {detailTask.status === 'running' && '● '}
                        {STATUS_LABEL[detailTask.status]}
                      </span>
                    </div>
                    <div className="patrol-task-stat">
                      <span className="patrol-task-stat-label">GPS轨迹</span>
                      <span className="patrol-task-stat-value">{detailTask.gps_track?.length || 0} 个点</span>
                    </div>
                    <div className="patrol-task-stat">
                      <span className="patrol-task-stat-label">线路距离</span>
                      <span className="patrol-task-stat-value">{formatDist(detailTask.route?.distance)}</span>
                    </div>
                  </div>

                  {/* 地图（预设线路 + GPS轨迹/设备当前位置） */}
                  <div className="patrol-task-map-container">
                    <TaskDetailMap key={detailTask.id} task={detailTask} device={devices.find(d => d.id === detailTask.device_id)} />
                  </div>

                  {/* 图例 */}
                  <div className="patrol-legend" style={{ justifyContent: 'center' }}>
                    <div className="patrol-legend-item">
                      <div className="patrol-legend-line" style={{ background: '#4f6ef7', borderTop: '2px dashed #4f6ef7', height: 0, width: 20 }} />
                      <span>预设线路</span>
                    </div>
                    <div className="patrol-legend-item">
                      <div className="patrol-legend-dot" style={{ background: '#4f6ef7' }} />
                      <span>预设点位</span>
                    </div>
                    <div className="patrol-legend-item">
                      <div className="patrol-legend-line" style={{ background: '#22c55e' }} />
                      <span>实际轨迹</span>
                    </div>
                    <div className="patrol-legend-item">
                      <div className="patrol-legend-dot" style={{ background: '#22c55e' }} />
                      <span>当前位置</span>
                    </div>
                  </div>

                  {/* 实时画面 */}
                  <div className="patrol-video-section">
                    <div className="patrol-video-header">
                      <span>📷 实时摄像头画面</span>
                      {detailTask.device_ip && (
                        <span className="patrol-video-live-dot">LIVE</span>
                      )}
                    </div>
                    <TaskCamera
                      deviceIp={detailTask.device_ip}
                      devicePort={detailTask.device_port}
                    />
                  </div>

                  {/* 任务信息 */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', fontSize: '0.82rem', color: 'var(--color-text-secondary)' }}>
                    <div>🤖 设备：{detailTask.device_name || '未绑定'}</div>
                    <div>📋 线路：{detailTask.route?.name || '--'}</div>
                    <div>⏱️ 开始：{formatTime(detailTask.started_at)}</div>
                    <div>🏁 结束：{formatTime(detailTask.ended_at)}</div>
                  </div>

                  {/* 操作按钮 */}
                  <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '0.5rem', borderTop: '1px solid var(--color-border)' }}>
                    {(detailTask.status === 'pending' || detailTask.status === 'completed' || detailTask.status === 'cancelled') && (
                      <button className="patrol-btn patrol-btn-success" onClick={() => handleStart(detailTask)}>
                        ▶ {detailTask.status === 'pending' ? '开始巡检' : '重新开始'}
                      </button>
                    )}
                    {detailTask.status === 'running' && (<>
                      <button className="patrol-btn patrol-btn-warning" onClick={() => handlePause(detailTask)}>⏸ 暂停</button>
                      <button className="patrol-btn patrol-btn-danger" onClick={() => handleStop(detailTask)}>⏹ 停止</button>
                    </>)}
                    {detailTask.status === 'paused' && (<>
                      <button className="patrol-btn patrol-btn-success" onClick={() => handleResume(detailTask)}>▶ 继续</button>
                      <button className="patrol-btn patrol-btn-danger" onClick={() => handleStop(detailTask)}>⏹ 停止</button>
                    </>)}
                  </div>
                </div>
              ) : <div style={{ textAlign: 'center', color: 'var(--color-text-muted)', padding: '2rem' }}>加载失败</div>}
            </div>
          </div>
        </div>
      )}

      {/* 删除确认 */}
      {deleteConfirm && (
        <div className="patrol-modal-overlay">
          <div className="patrol-modal" style={{ maxWidth: 400 }} onClick={e => e.stopPropagation()}>
            <div className="patrol-modal-header">
              <h2>确认删除</h2>
              <button className="patrol-modal-close" onClick={() => setDeleteConfirm(null)}>✕</button>
            </div>
            <div className="patrol-modal-body">
              <p style={{ fontSize: '0.9rem', color: 'var(--color-text-secondary)', margin: 0 }}>
                确定删除任务 <strong>「{deleteConfirm.name}」</strong> 吗？<br />
                <span style={{ fontSize: '0.82rem', color: '#ef4444' }}>GPS轨迹数据将一并删除。</span>
              </p>
            </div>
            <div className="patrol-modal-footer">
              <button className="patrol-btn patrol-btn-secondary" onClick={() => setDeleteConfirm(null)}>取消</button>
              <button className="patrol-btn patrol-btn-danger" onClick={async () => {
                try {
                  const res = await authFetch(`/api/patrol/tasks/${deleteConfirm.id}`, { method: 'DELETE' })
                  if (res.ok) { setDeleteConfirm(null); fetchTasks() }
                } catch (e) { console.error(e) }
              }}>确认删除</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
