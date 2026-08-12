/**
 * OutdoorRouteAdmin.jsx — 校园室外巡检路线管理（阶段 B-7/B-8）
 * ====================================================================
 * 本页面与既有室内 Patrol* 页面严格分离，独立挂载在 /outdoor-patrol/routes。
 * 阶段 B 当前为 UI 骨架 + mock 数据，API 调用先占位，待后端 CRUD 接口
 * 落地后切换。
 *
 * 功能：
 *   1. 路线列表（含版本号、状态徽章、航点数、关联标定版本）
 *   2. 路线详情面板（航点序列、围栏摘要、速度限制）
 *   3. 标定版本下拉选择（驱动路线列表过滤）
 *   4. 新建路线按钮（阶段 B 后续接入编辑弹窗）
 *
 * 设计原则（对应需求 §5.1）：
 *   - 所有地理坐标一律保留 (lng, lat, coordinateType='wgs84')，
 *     展示层在前端再做 WGS84→GCJ-02 转换（交由高德组件处理）
 *   - 不与室内 PatrolRoutes.jsx 共享任何状态或组件
 */

import { useEffect, useState } from 'react'
import { authFetch } from '../utils/authFetch'
import { PageHeader, Panel, StatusBadge, Button, EmptyState, LoadingState } from '../components/ui'
import '../styles/OutdoorRouteAdmin.css'

const STATUS_LABEL = {
  draft: '草稿',
  published: '已发布',
  frozen: '已冻结',
  deprecated: '已弃用',
}

const STATUS_VARIANT = {
  draft: 'neutral',
  published: 'success',
  frozen: 'info',
  deprecated: 'warning',
}

// ── Mock 数据（阶段 B 占位；后端接口完成后替换为真实 fetch） ──
const MOCK_CALIBRATIONS = [
  { id: 1, name: '主校区标定', version: 'campus-main-v1', status: 'active' },
  { id: 2, name: '北区扩展', version: 'campus-north-v2', status: 'draft' },
]

const MOCK_ROUTES = [
  {
    id: 1,
    name: '图书馆环线',
    version: 1,
    calibration_id: 1,
    calibration_version: 'campus-main-v1',
    status: 'published',
    waypoint_count: 5,
    max_speed_ms: 0.8,
    fence_type: 'polygon',
    description: '环绕图书馆一周的试点路线',
    waypoints: [
      { seq_order: 1, name: '图书馆南门', geo_lng: 116.3074, geo_lat: 39.9847, arrival_radius_m: 0.5, dwell_seconds: 10 },
      { seq_order: 2, name: '图书馆东门', geo_lng: 116.3080, geo_lat: 39.9849, arrival_radius_m: 0.5, dwell_seconds: 10 },
      { seq_order: 3, name: '图书馆北门', geo_lng: 116.3081, geo_lat: 39.9853, arrival_radius_m: 0.5, dwell_seconds: 10 },
      { seq_order: 4, name: '图书馆西门', geo_lng: 116.3075, geo_lat: 39.9852, arrival_radius_m: 0.5, dwell_seconds: 10 },
      { seq_order: 5, name: '南门返回点', geo_lng: 116.3074, geo_lat: 39.9847, arrival_radius_m: 0.5, dwell_seconds: 0 },
    ],
  },
  {
    id: 2,
    name: '操场巡线',
    version: 2,
    calibration_id: 1,
    calibration_version: 'campus-main-v1',
    status: 'frozen',
    waypoint_count: 3,
    max_speed_ms: 0.6,
    fence_type: 'polygon',
    description: '操场周边 v2（路线已冻结，任务启动后会快照此版本）',
    waypoints: [
      { seq_order: 1, name: '操场东北角', geo_lng: 116.3090, geo_lat: 39.9860, arrival_radius_m: 0.6, dwell_seconds: 5 },
      { seq_order: 2, name: '操场西南角', geo_lng: 116.3085, geo_lat: 39.9855, arrival_radius_m: 0.6, dwell_seconds: 5 },
      { seq_order: 3, name: '操场中心', geo_lng: 116.3088, geo_lat: 39.9858, arrival_radius_m: 0.8, dwell_seconds: 0 },
    ],
  },
]

export default function OutdoorRouteAdmin() {
  const [calibrations, setCalibrations] = useState([])
  const [routes, setRoutes] = useState([])
  const [selectedCalibrationId, setSelectedCalibrationId] = useState(null)
  const [selectedRoute, setSelectedRoute] = useState(null)
  const [loading, setLoading] = useState(true)

  // 加载标定与路线列表
  const fetchCalibrations = async () => {
    try {
      const res = await authFetch('/api/outdoor-patrol/calibrations')
      if (res.ok) {
        const data = await res.json()
        if (Array.isArray(data) && data.length > 0) {
          setCalibrations(data)
          return
        }
      }
      // 后端无数据时降级到 mock
      setCalibrations(MOCK_CALIBRATIONS)
    } catch (e) {
      console.warn('fetchCalibrations failed, 使用 mock 数据:', e)
      setCalibrations(MOCK_CALIBRATIONS)
    }
  }

  const fetchRoutes = async (calibrationId = null) => {
    setLoading(true)
    try {
      const url = calibrationId
        ? `/api/outdoor-patrol/routes?calibration_id=${calibrationId}`
        : '/api/outdoor-patrol/routes'
      const res = await authFetch(url)
      if (res.ok) {
        const data = await res.json()
        if (Array.isArray(data) && data.length > 0) {
          setRoutes(data)
          setLoading(false)
          return
        }
      }
      // 降级到 mock
      const filtered = calibrationId
        ? MOCK_ROUTES.filter(r => r.calibration_id === calibrationId)
        : MOCK_ROUTES
      setRoutes(filtered)
    } catch (e) {
      console.warn('fetchRoutes failed, 使用 mock 数据:', e)
      const filtered = calibrationId
        ? MOCK_ROUTES.filter(r => r.calibration_id === calibrationId)
        : MOCK_ROUTES
      setRoutes(filtered)
    } finally {
      setLoading(false)
    }
  }

  const [showModal, setShowModal] = useState(false)
  const [editingRoute, setEditingRoute] = useState(null) // null=新建
  const [form, setForm] = useState(null)
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [actionMessage, setActionMessage] = useState('')

  useEffect(() => {
    fetchCalibrations()
  }, [])

  useEffect(() => {
    fetchRoutes(selectedCalibrationId)
    setSelectedRoute(null)
  }, [selectedCalibrationId])

  const emptyForm = () => ({
    name: '',
    description: '',
    calibration_id: selectedCalibrationId || (calibrations[0]?.id ?? null),
    fence_type: 'polygon',
    fence_buffer_m: 0.3,
    max_speed_ms: 0.8,
    applicable_device_types: ['无人车'],
    waypoints: [
      { seq_order: 1, name: '起点', geo_lng: '', geo_lat: '', yaw: '', arrival_radius_m: 0.5, dwell_seconds: 0, timeout_seconds: 120, is_enabled: true },
    ],
  })

  const handleNewRoute = () => {
    setEditingRoute(null)
    setForm(emptyForm())
    setFormError('')
    setShowModal(true)
  }

  const handleEditRoute = (route) => {
    // 拉 detail 取完整 waypoints
    const loadAndEdit = async () => {
      try {
        const res = await authFetch(`/api/outdoor-patrol/routes/${route.id}`)
        let detail = route
        if (res.ok) {
          const data = await res.json()
          if (data && data.waypoints) detail = data
        } else if (route.waypoints) {
          detail = route
        } else {
          // mock 路径下查找
          const m = MOCK_ROUTES.find(r => r.id === route.id)
          if (m) detail = m
        }
        setEditingRoute(detail)
        setForm({
          name: detail.name || '',
          description: detail.description || '',
          calibration_id: detail.calibration_id,
          fence_type: detail.fence_type || 'polygon',
          fence_buffer_m: detail.fence_buffer_m ?? 0.3,
          max_speed_ms: detail.max_speed_ms ?? 0.8,
          applicable_device_types: detail.applicable_device_types || ['无人车'],
          waypoints: (detail.waypoints || []).map(w => ({
            seq_order: w.seq_order,
            name: w.name || '',
            geo_lng: typeof w.geo_lng === 'number' ? w.geo_lng : '',
            geo_lat: typeof w.geo_lat === 'number' ? w.geo_lat : '',
            yaw: w.yaw ?? '',
            arrival_radius_m: w.arrival_radius_m ?? 0.5,
            dwell_seconds: w.dwell_seconds ?? 0,
            timeout_seconds: w.timeout_seconds ?? 120,
            is_enabled: w.is_enabled !== false,
          })),
        })
        setFormError('')
        setShowModal(true)
      } catch (e) {
        setActionMessage(`加载路线详情失败: ${e.message}`)
      }
    }
    loadAndEdit()
  }

  const addWaypoint = () => {
    if (!form) return
    const nextSeq = (form.waypoints.at(-1)?.seq_order || 0) + 1
    setForm({
      ...form,
      waypoints: [...form.waypoints, {
        seq_order: nextSeq, name: `航点${nextSeq}`, geo_lng: '', geo_lat: '',
        yaw: '', arrival_radius_m: 0.5, dwell_seconds: 0, timeout_seconds: 120, is_enabled: true,
      }],
    })
  }

  const removeWaypoint = (idx) => {
    if (!form) return
    const next = form.waypoints.filter((_, i) => i !== idx)
      .map((w, i) => ({ ...w, seq_order: i + 1 }))
    setForm({ ...form, waypoints: next })
  }

  const moveWaypoint = (idx, dir) => {
    if (!form) return
    const arr = [...form.waypoints]
    const target = idx + dir
    if (target < 0 || target >= arr.length) return
    ;[arr[idx], arr[target]] = [arr[target], arr[idx]]
    setForm({ ...form, waypoints: arr.map((w, i) => ({ ...w, seq_order: i + 1 })) })
  }

  const updateWaypoint = (idx, field, value) => {
    if (!form) return
    const next = [...form.waypoints]
    next[idx] = { ...next[idx], [field]: value }
    setForm({ ...form, waypoints: next })
  }

  const handleSaveRoute = async () => {
    setFormError('')
    if (!form.name.trim()) { setFormError('请填写路线名称'); return }
    if (!form.calibration_id) { setFormError('请选择标定版本'); return }
    if (form.waypoints.length === 0) { setFormError('至少需要一个航点'); return }
    for (let i = 0; i < form.waypoints.length; i++) {
      const w = form.waypoints[i]
      if (!w.name?.trim()) { setFormError(`航点 #${i + 1} 缺少名称`); return }
      if (w.geo_lng === '' || w.geo_lat === '') { setFormError(`航点 #${i + 1} 缺少经纬度`); return }
    }

    setSubmitting(true)
    try {
      const payload = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        calibration_id: form.calibration_id,
        fence_type: form.fence_type,
        fence_buffer_m: parseFloat(form.fence_buffer_m) || 0.3,
        max_speed_ms: parseFloat(form.max_speed_ms) || 0.8,
        applicable_device_types: form.applicable_device_types,
        waypoints: form.waypoints.map(w => ({
          seq_order: w.seq_order,
          name: w.name.trim(),
          geo_lng: parseFloat(w.geo_lng),
          geo_lat: parseFloat(w.geo_lat),
          yaw: w.yaw === '' ? null : parseFloat(w.yaw),
          arrival_radius_m: parseFloat(w.arrival_radius_m) || 0.5,
          dwell_seconds: parseInt(w.dwell_seconds) || 0,
          timeout_seconds: parseInt(w.timeout_seconds) || 120,
          is_enabled: w.is_enabled,
        })),
      }
      const url = editingRoute
        ? `/api/outdoor-patrol/routes/${editingRoute.id}`
        : '/api/outdoor-patrol/routes'
      const method = editingRoute ? 'PUT' : 'POST'
      const res = await authFetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (res.ok) {
        const data = await res.json().catch(() => ({}))
        setShowModal(false)
        setActionMessage(data.message || (editingRoute ? '路线已更新' : '路线已创建'))
        fetchRoutes(selectedCalibrationId)
      } else {
        const err = await res.json().catch(() => ({}))
        setFormError(err.detail || `保存失败 (${res.status})`)
      }
    } catch (e) {
      setFormError(`网络错误: ${e.message}`)
    } finally {
      setSubmitting(false)
    }
  }

  const handlePublish = async (route) => {
    setActionMessage('')
    try {
      const res = await authFetch(`/api/outdoor-patrol/routes/${route.id}/publish`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json().catch(() => ({}))
        setActionMessage(data.message || '已发布')
        fetchRoutes(selectedCalibrationId)
      } else {
        const err = await res.json().catch(() => ({}))
        setActionMessage(`发布失败: ${err.detail || res.status}`)
      }
    } catch (e) {
      setActionMessage(`网络错误: ${e.message}`)
    }
  }

  const handleFreeze = async (route) => {
    setActionMessage('')
    if (!confirm(`确认冻结路线 "${route.name}" v${route.version}？冻结后任务启动可锁定此版本，编辑会强制创建新版本。`)) return
    try {
      const res = await authFetch(`/api/outdoor-patrol/routes/${route.id}/freeze`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json().catch(() => ({}))
        setActionMessage(data.message || '已冻结')
        fetchRoutes(selectedCalibrationId)
      } else {
        const err = await res.json().catch(() => ({}))
        setActionMessage(`冻结失败: ${err.detail || res.status}`)
      }
    } catch (e) {
      setActionMessage(`网络错误: ${e.message}`)
    }
  }

  return (
    <div className="outdoor-route-admin">
      <PageHeader
        title="室外巡检路线管理"
        description="校园室外自主巡检路线的创建、版本管理与冻结操作。所有路线绑定坐标标定版本，编辑后生成新版本。"
      />

      {actionMessage && (
        <div className="outdoor-route-admin__msg">{actionMessage}</div>
      )}

      <div className="outdoor-route-admin__toolbar">
        <label className="outdoor-route-admin__filter-label">
          坐标标定版本：
          <select
            className="outdoor-route-admin__select"
            value={selectedCalibrationId || ''}
            onChange={e => setSelectedCalibrationId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">全部标定</option>
            {calibrations.map(c => (
              <option key={c.id} value={c.id}>
                {c.name} · {c.version} ({c.status})
              </option>
            ))}
          </select>
        </label>
        <Button variant="primary" onClick={handleNewRoute}>+ 新建路线</Button>
      </div>

      <div className="outdoor-route-admin__layout">
        <div className="outdoor-route-admin__list">
          <Panel title={`路线列表（${routes.length}）`}>
            {loading ? (
              <LoadingState text="加载路线..." />
            ) : routes.length === 0 ? (
              <EmptyState
                title="暂无路线"
                description={selectedCalibrationId ? '该标定下还没有路线，点击右上角新建。' : '请先选择标定版本或新建路线。'}
              />
            ) : (
              <ul className="outdoor-route-admin__route-items">
                {routes.map(r => (
                  <li
                    key={r.id}
                    className={`outdoor-route-admin__route-item ${selectedRoute?.id === r.id ? 'is-active' : ''}`}
                    onClick={() => setSelectedRoute(r)}
                  >
                    <div className="outdoor-route-admin__route-head">
                      <span className="outdoor-route-admin__route-name">{r.name}</span>
                      <StatusBadge variant={STATUS_VARIANT[r.status] || 'neutral'}>
                        {STATUS_LABEL[r.status] || r.status}
                      </StatusBadge>
                    </div>
                    <div className="outdoor-route-admin__route-meta">
                      <span>v{r.version}</span>
                      <span>·</span>
                      <span>{r.waypoint_count} 航点</span>
                      <span>·</span>
                      <span>{r.calibration_version || `cal#${r.calibration_id}`}</span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>

        <div className="outdoor-route-admin__detail">
          {selectedRoute ? (
            <Panel title={`路线详情：${selectedRoute.name}`}>
              <div className="outdoor-route-admin__detail-actions">
                {selectedRoute.status !== 'deprecated' && (
                  <Button variant="default" onClick={() => handleEditRoute(selectedRoute)}>
                    {selectedRoute.status === 'draft' ? '编辑' : '编辑（生成新版本）'}
                  </Button>
                )}
                {selectedRoute.status === 'draft' && (
                  <Button variant="primary" onClick={() => handlePublish(selectedRoute)}>
                    发布
                  </Button>
                )}
                {selectedRoute.status === 'published' && (
                  <Button variant="info" onClick={() => handleFreeze(selectedRoute)}>
                    冻结
                  </Button>
                )}
              </div>

              <div className="outdoor-route-admin__detail-grid">
                <div className="outdoor-route-admin__field">
                  <span className="outdoor-route-admin__field-label">版本</span>
                  <span className="outdoor-route-admin__field-value">v{selectedRoute.version}</span>
                </div>
                <div className="outdoor-route-admin__field">
                  <span className="outdoor-route-admin__field-label">状态</span>
                  <span className="outdoor-route-admin__field-value">
                    <StatusBadge variant={STATUS_VARIANT[selectedRoute.status] || 'neutral'}>
                      {STATUS_LABEL[selectedRoute.status] || selectedRoute.status}
                    </StatusBadge>
                  </span>
                </div>
                <div className="outdoor-route-admin__field">
                  <span className="outdoor-route-admin__field-label">最大速度</span>
                  <span className="outdoor-route-admin__field-value">
                    {selectedRoute.max_speed_ms ? `${selectedRoute.max_speed_ms} m/s` : '—'}
                  </span>
                </div>
                <div className="outdoor-route-admin__field">
                  <span className="outdoor-route-admin__field-label">围栏类型</span>
                  <span className="outdoor-route-admin__field-value">{selectedRoute.fence_type}</span>
                </div>
              </div>

              {selectedRoute.description && (
                <p className="outdoor-route-admin__desc">{selectedRoute.description}</p>
              )}

              <h3 className="outdoor-route-admin__section-title">航点序列</h3>
              <table className="outdoor-route-admin__waypoints">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>名称</th>
                    <th>WGS84 经度</th>
                    <th>WGS84 纬度</th>
                    <th>到达半径 (m)</th>
                    <th>停留 (s)</th>
                  </tr>
                </thead>
                <tbody>
                  {(selectedRoute.waypoints || []).map(w => (
                    <tr key={w.seq_order}>
                      <td>{w.seq_order}</td>
                      <td>{w.name}</td>
                      <td>{w.geo_lng.toFixed(7)}</td>
                      <td>{w.geo_lat.toFixed(7)}</td>
                      <td>{w.arrival_radius_m}</td>
                      <td>{w.dwell_seconds}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="outdoor-route-admin__hint">
                注：展示坐标为 WGS84，地图渲染时会自动转换为 GCJ-02。
                路线已冻结后不可编辑，需新建版本。
              </div>
            </Panel>
          ) : (
            <Panel title="路线详情">
              <EmptyState
                title="选择左侧路线查看详情"
                description="路线详情包含航点序列、围栏几何、速度限制与关联标定版本。"
              />
            </Panel>
          )}
        </div>
      </div>

      {showModal && form && (
        <div className="outdoor-route-admin__modal-overlay" onClick={() => setShowModal(false)}>
          <div className="outdoor-route-admin__modal" onClick={e => e.stopPropagation()}>
            <div className="outdoor-route-admin__modal-header">
              <h2>{editingRoute ? `编辑路线：${editingRoute.name} (v${editingRoute.version})` : '新建路线'}</h2>
              <button className="outdoor-route-admin__modal-close" onClick={() => setShowModal(false)}>×</button>
            </div>
            <div className="outdoor-route-admin__modal-body">
              {formError && (
                <div className="outdoor-route-admin__form-error">{formError}</div>
              )}
              {editingRoute && editingRoute.status !== 'draft' && (
                <div className="outdoor-route-admin__hint">
                  当前路线状态为 <b>{STATUS_LABEL[editingRoute.status]}</b>，
                  保存后将自动创建新版本（draft 状态），原版本保持不变。
                </div>
              )}

              <div className="outdoor-route-admin__form-row">
                <label>
                  路线名称<span className="outdoor-route-admin__required">*</span>
                  <input
                    type="text"
                    value={form.name}
                    onChange={e => setForm({ ...form, name: e.target.value })}
                    placeholder="如：图书馆环线"
                  />
                </label>
                <label>
                  绑定标定<span className="outdoor-route-admin__required">*</span>
                  <select
                    value={form.calibration_id || ''}
                    onChange={e => setForm({ ...form, calibration_id: Number(e.target.value) })}
                  >
                    <option value="">请选择</option>
                    {calibrations.map(c => (
                      <option key={c.id} value={c.id}>
                        {c.name} · {c.version}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <label className="outdoor-route-admin__form-full">
                描述
                <input
                  type="text"
                  value={form.description}
                  onChange={e => setForm({ ...form, description: e.target.value })}
                  placeholder="路线用途说明"
                />
              </label>

              <div className="outdoor-route-admin__form-row">
                <label>
                  围栏类型
                  <select
                    value={form.fence_type}
                    onChange={e => setForm({ ...form, fence_type: e.target.value })}
                  >
                    <option value="polygon">多边形</option>
                    <option value="corridor">走廊</option>
                  </select>
                </label>
                <label>
                  围栏缓冲 (m)
                  <input
                    type="number"
                    step="0.1"
                    value={form.fence_buffer_m}
                    onChange={e => setForm({ ...form, fence_buffer_m: e.target.value })}
                  />
                </label>
              </div>

              <div className="outdoor-route-admin__form-row">
                <label>
                  最大速度 (m/s)
                  <input
                    type="number"
                    step="0.1"
                    value={form.max_speed_ms}
                    onChange={e => setForm({ ...form, max_speed_ms: e.target.value })}
                  />
                </label>
                <label>
                  适用设备类型
                  <input
                    type="text"
                    value={Array.isArray(form.applicable_device_types) ? form.applicable_device_types.join(', ') : ''}
                    onChange={e => setForm({
                      ...form,
                      applicable_device_types: e.target.value.split(',').map(s => s.trim()).filter(Boolean),
                    })}
                    placeholder="逗号分隔，如：无人车, 无人机"
                  />
                </label>
              </div>

              <h3 className="outdoor-route-admin__section-title">
                航点序列（{form.waypoints.length}）
                <Button variant="default" onClick={addWaypoint}>+ 添加航点</Button>
              </h3>

              <div className="outdoor-route-admin__waypoint-editor">
                {form.waypoints.map((w, idx) => (
                  <div key={idx} className="outdoor-route-admin__waypoint-form">
                    <div className="outdoor-route-admin__waypoint-head">
                      <span>#{w.seq_order}</span>
                      <div className="outdoor-route-admin__waypoint-ops">
                        <button type="button" onClick={() => moveWaypoint(idx, -1)} disabled={idx === 0}>↑</button>
                        <button type="button" onClick={() => moveWaypoint(idx, 1)} disabled={idx === form.waypoints.length - 1}>↓</button>
                        <button type="button" onClick={() => removeWaypoint(idx)} className="outdoor-route-admin__waypoint-del">×</button>
                      </div>
                    </div>
                    <div className="outdoor-route-admin__form-row">
                      <label>
                        名称
                        <input
                          type="text"
                          value={w.name}
                          onChange={e => updateWaypoint(idx, 'name', e.target.value)}
                        />
                      </label>
                      <label>
                        期望朝向 (rad)
                        <input
                          type="number"
                          step="0.01"
                          value={w.yaw}
                          onChange={e => updateWaypoint(idx, 'yaw', e.target.value)}
                          placeholder="可选"
                        />
                      </label>
                    </div>
                    <div className="outdoor-route-admin__form-row">
                      <label>
                        WGS84 经度
                        <input
                          type="number"
                          step="0.0000001"
                          value={w.geo_lng}
                          onChange={e => updateWaypoint(idx, 'geo_lng', e.target.value)}
                        />
                      </label>
                      <label>
                        WGS84 纬度
                        <input
                          type="number"
                          step="0.0000001"
                          value={w.geo_lat}
                          onChange={e => updateWaypoint(idx, 'geo_lat', e.target.value)}
                        />
                      </label>
                    </div>
                    <div className="outdoor-route-admin__form-row">
                      <label>
                        到达半径 (m)
                        <input
                          type="number"
                          step="0.1"
                          value={w.arrival_radius_m}
                          onChange={e => updateWaypoint(idx, 'arrival_radius_m', e.target.value)}
                        />
                      </label>
                      <label>
                        停留 (s)
                        <input
                          type="number"
                          value={w.dwell_seconds}
                          onChange={e => updateWaypoint(idx, 'dwell_seconds', e.target.value)}
                        />
                      </label>
                      <label>
                        超时 (s)
                        <input
                          type="number"
                          value={w.timeout_seconds}
                          onChange={e => updateWaypoint(idx, 'timeout_seconds', e.target.value)}
                        />
                      </label>
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div className="outdoor-route-admin__modal-footer">
              <Button variant="default" onClick={() => setShowModal(false)}>取消</Button>
              <Button variant="primary" onClick={handleSaveRoute} disabled={submitting}>
                {submitting ? '保存中...' : (editingRoute ? '保存' : '创建路线')}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
