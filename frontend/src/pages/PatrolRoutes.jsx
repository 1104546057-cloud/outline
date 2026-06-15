import { useState, useEffect, useRef, useCallback } from 'react'
import AMapLoader from '@amap/amap-jsapi-loader'
import ThemedSelect from '../components/ThemedSelect'
import { authFetch } from '../utils/authFetch'
import '../styles/Patrol.css'

const AMAP_KEY = import.meta.env.VITE_AMAP_API_KEY
const AMAP_SECURITY_KEY = import.meta.env.VITE_AMAP_API_SECURE_KEY

/** 球面两点间距（Haversine，返回米） */
function haversine(lat1, lng1, lat2, lng2) {
  const R = 6378137
  const dLat = ((lat2 - lat1) * Math.PI) / 180
  const dLng = ((lng2 - lng1) * Math.PI) / 180
  const a = Math.sin(dLat / 2) ** 2 + Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLng / 2) ** 2
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

/** 计算多段线路总距离（含首尾相连） */
function calcRouteDistance(points) {
  if (!points || points.length < 2) return 0
  let dist = 0
  for (let i = 0; i < points.length - 1; i++) {
    dist += haversine(points[i].lat, points[i].lng, points[i + 1].lat, points[i + 1].lng)
  }
  // 首尾相连
  if (points.length > 2) {
    dist += haversine(points[points.length - 1].lat, points[points.length - 1].lng, points[0].lat, points[0].lng)
  }
  return dist
}

const formatDist = (m) => {
  if (!m) return '--'
  if (m >= 1000) return `${(m / 1000).toFixed(2)} km`
  return `${Math.round(m)} m`
}

export default function PatrolRoutes() {
  const mapRef = useRef(null)
  const mapInstanceRef = useRef(null)
  const amapRef = useRef(null)
  const mapObjectsRef = useRef([]) // 当前地图上的所有覆盖物

  const [areas, setAreas] = useState([])
  const [selectedAreaId, setSelectedAreaId] = useState('')
  const [areaPoints, setAreaPoints] = useState([]) // 该区域的所有点位
  const [routes, setRoutes] = useState([])
  const [selectedRoute, setSelectedRoute] = useState(null)
  const [loading, setLoading] = useState(false)

  // 弹窗
  const [showModal, setShowModal] = useState(false)
  const [editingRoute, setEditingRoute] = useState(null)
  const [selectedPointIds, setSelectedPointIds] = useState([]) // 已选点位ID（有序）
  const [formData, setFormData] = useState({ name: '', description: '' })
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState(null)

  const currentArea = areas.find(a => a.id === Number(selectedAreaId))

  useEffect(() => {
    authFetch('/api/patrol/areas').then(r => r.ok ? r.json() : []).then(data => {
      setAreas(data)
      if (data.length > 0) setSelectedAreaId(String(data[0].id))
    }).catch(console.error)
  }, [])

  const fetchAreaPoints = useCallback(async (areaId) => {
    if (!areaId) { setAreaPoints([]); return }
    const res = await authFetch(`/api/patrol/points?area_id=${areaId}`)
    if (res.ok) setAreaPoints(await res.json())
  }, [])

  const fetchRoutes = useCallback(async (areaId) => {
    if (!areaId) { setRoutes([]); return }
    setLoading(true)
    try {
      const res = await authFetch(`/api/patrol/routes?area_id=${areaId}`)
      if (res.ok) setRoutes(await res.json())
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    fetchAreaPoints(selectedAreaId)
    fetchRoutes(selectedAreaId)
    setSelectedRoute(null)
  }, [selectedAreaId, fetchAreaPoints, fetchRoutes])

  // 初始化地图
  useEffect(() => {
    if (!mapRef.current) return
    window._AMapSecurityConfig = { securityJsCode: AMAP_SECURITY_KEY }
    AMapLoader.load({
      key: AMAP_KEY,
      version: '2.0',
      plugins: ['AMap.Polygon', 'AMap.Polyline', 'AMap.Marker'],
    }).then((AMap) => {
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
    }).catch(console.error)
    return () => { mapInstanceRef.current?.destroy() }
  }, [])

  // 渲染地图覆盖物
  const renderMap = useCallback(() => {
    const AMap = amapRef.current
    const map = mapInstanceRef.current
    if (!AMap || !map) return

    // 清除旧覆盖物
    mapObjectsRef.current.forEach(o => map.remove(o))
    mapObjectsRef.current = []

    // 绘制区域边界
    if (currentArea?.boundary && currentArea.boundary.length >= 3) {
      const path = currentArea.boundary.map(([lng, lat]) => new AMap.LngLat(lng, lat))
      const poly = new AMap.Polygon({
        path,
        fillColor: '#4f6ef7',
        fillOpacity: 0.05,
        strokeColor: '#4f6ef7',
        strokeWeight: 2,
        strokeStyle: 'solid',
        strokeOpacity: 0.5,
      })
      map.add(poly)
      mapObjectsRef.current.push(poly)
    }

    // 绘制所有点位
    areaPoints.forEach((pt, idx) => {
      let isInRoute = false;
      let isStart = false;
      let isEnd = false;
      if (selectedRoute && selectedRoute.points) {
        isInRoute = selectedRoute.points.some(p => p.id === pt.id);
        if (selectedRoute.points.length > 0) {
          if (selectedRoute.points[0].id === pt.id) isStart = true;
          if (selectedRoute.points[selectedRoute.points.length - 1].id === pt.id) isEnd = true;
        }
      }

      let bg = '#94a3b8';
      if (isInRoute) bg = '#4f6ef7';
      if (isEnd) bg = '#ef4444'; // 红
      if (isStart) bg = '#10b981'; // 绿

      let text = String(idx + 1);
      if (isStart) text = '起';
      else if (isEnd) text = '终';

      const marker = new AMap.Marker({
        position: [pt.lng, pt.lat],
        content: `<div style="
          width:26px;height:26px;
          background:${bg};
          border:2.5px solid #fff;
          border-radius:50%;
          box-shadow:0 2px 6px rgba(0,0,0,0.2);
          display:flex;align-items:center;justify-content:center;
          font-size:10px;font-weight:700;color:#fff;
          cursor:pointer;
        ">${text}</div>`,
        anchor: 'center',
      })
      map.add(marker)
      mapObjectsRef.current.push(marker)
    })

    // 绘制所有线路（非选中状态为灰色淡线）
    routes.forEach(route => {
      if (!route.points || route.points.length < 2) return
      const isSelected = selectedRoute?.id === route.id
      const path = route.points.map(p => new AMap.LngLat(p.lng, p.lat))
      // 环形：加上第一个点形成闭环
      if (route.points.length > 2) path.push(new AMap.LngLat(route.points[0].lng, route.points[0].lat))

      const line = new AMap.Polyline({
        path,
        strokeColor: isSelected ? '#22c55e' : '#94a3b8',
        strokeWeight: isSelected ? 4 : 2,
        strokeOpacity: isSelected ? 1 : 0.5,
        strokeStyle: 'solid',
        lineJoin: 'round',
        lineCap: 'round',
      })
      line.on('click', () => setSelectedRoute(route))
      map.add(line)
      mapObjectsRef.current.push(line)

      // 选中线路的方向箭头
      if (isSelected && route.points.length >= 2) {
        route.points.forEach((pt, i) => {
          const next = route.points[(i + 1) % route.points.length]
          const mid = new AMap.LngLat((pt.lng + next.lng) / 2, (pt.lat + next.lat) / 2)
          const arrowMarker = new AMap.Marker({
            position: mid,
            content: `<div style="color:#22c55e;font-size:16px;transform:rotate(${90 - Math.atan2(next.lat - pt.lat, next.lng - pt.lng) * 180 / Math.PI}deg)">▲</div>`,
            anchor: 'center',
          })
          map.add(arrowMarker)
          mapObjectsRef.current.push(arrowMarker)
        })
      }
    })

    // 自适应视野到区域边界
    if (currentArea?.boundary && currentArea.boundary.length >= 3) {
      const path = currentArea.boundary.map(([lng, lat]) => new AMap.LngLat(lng, lat))
      const fitPoly = new AMap.Polygon({ path, strokeOpacity: 0, fillOpacity: 0 })
      map.add(fitPoly)
      map.setFitView([fitPoly], false, [40, 40, 40, 40], 18)
      map.remove(fitPoly)
    }
  }, [currentArea, areaPoints, routes, selectedRoute])

  useEffect(() => { renderMap() }, [renderMap])

  // 打开新建弹窗
  const handleNewRoute = () => {
    setEditingRoute(null)
    setSelectedPointIds([])
    setFormData({ name: '', description: '' })
    setFormError('')
    setShowModal(true)
  }

  // 打开编辑弹窗
  const handleEditRoute = (route, e) => {
    e.stopPropagation()
    setEditingRoute(route)
    setSelectedPointIds(route.points.map(p => p.id))
    setFormData({ name: route.name, description: route.description || '' })
    setFormError('')
    setShowModal(true)
  }

  // 点位选择
  const togglePoint = (ptId) => {
    setSelectedPointIds(prev => {
      if (prev.includes(ptId)) return prev.filter(id => id !== ptId)
      return [...prev, ptId]
    })
  }

  const movePoint = (idx, dir) => {
    setSelectedPointIds(prev => {
      const arr = [...prev]
      const newIdx = idx + dir
      if (newIdx < 0 || newIdx >= arr.length) return arr
      ;[arr[idx], arr[newIdx]] = [arr[newIdx], arr[idx]]
      return arr
    })
  }

  const calcCurrentDist = () => {
    const pts = selectedPointIds.map(id => areaPoints.find(p => p.id === id)).filter(Boolean)
    return calcRouteDistance(pts)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!formData.name.trim()) { setFormError('请填写线路名称'); return }
    if (selectedPointIds.length < 2) { setFormError('至少需要选择 2 个点位'); return }
    setSubmitting(true)
    setFormError('')
    const dist = calcCurrentDist()
    try {
      let res
      if (editingRoute) {
        res = await authFetch(`/api/patrol/routes/${editingRoute.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...formData, point_ids: selectedPointIds, distance: dist }),
        })
      } else {
        res = await authFetch('/api/patrol/routes', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ area_id: Number(selectedAreaId), ...formData, point_ids: selectedPointIds, distance: dist }),
        })
      }
      if (res.ok) {
        const saved = await res.json()
        setShowModal(false)
        await fetchRoutes(selectedAreaId)
        setSelectedRoute(saved)
      } else {
        const err = await res.json()
        setFormError(err.detail || '保存失败')
      }
    } catch (e) { setFormError('网络错误') }
    finally { setSubmitting(false) }
  }

  const handleDelete = async (id) => {
    try {
      const res = await authFetch(`/api/patrol/routes/${id}`, { method: 'DELETE' })
      if (res.ok) {
        setDeleteConfirm(null)
        if (selectedRoute?.id === id) setSelectedRoute(null)
        fetchRoutes(selectedAreaId)
      }
    } catch (e) { console.error(e) }
  }

  return (
    <div className="patrol-page">
      <div className="patrol-header">
        <div className="patrol-header-left">
          <h1>巡检线路</h1>
          <span className="patrol-subtitle">串联多个点位规划巡检路径，首尾自动闭环</span>
        </div>
        <div className="patrol-header-actions">
          <ThemedSelect
            className="patrol-header-select"
            value={selectedAreaId}
            onChange={e => setSelectedAreaId(e.target.value)}
          >
            <option value="">-- 选择巡检区域 --</option>
            {areas.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
          </ThemedSelect>
          {selectedAreaId && (
            <button className="patrol-btn patrol-btn-primary" onClick={handleNewRoute} disabled={areaPoints.length < 2}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              新建线路
            </button>
          )}
        </div>
      </div>

      <div className="patrol-body">
        <div className="patrol-sidebar">
          <div className="patrol-sidebar-list">
            {!selectedAreaId ? (
              <div className="patrol-empty">
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2"><polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/></svg>
                <p>请先选择巡检区域</p>
              </div>
            ) : loading ? (
              <div className="patrol-loading"><div className="patrol-spinner"/><span>加载中...</span></div>
            ) : routes.length === 0 ? (
              <div className="patrol-empty">
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2"><polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/></svg>
                <p>暂无线路<br/>{areaPoints.length < 2 ? '请先添加至少2个点位' : '点击「新建线路」开始规划'}</p>
              </div>
            ) : routes.map(route => (
              <div
                key={route.id}
                className={`patrol-card ${selectedRoute?.id === route.id ? 'active' : ''}`}
                onClick={() => setSelectedRoute(route)}
              >
                <div className="patrol-card-header">
                  <span className="patrol-card-title">🛤️ {route.name}</span>
                </div>
                <div className="patrol-card-meta">
                  <span className="patrol-card-tag">📍 {route.point_count} 个点位</span>
                  <span className="patrol-card-tag">📏 {formatDist(route.distance)}</span>
                </div>
                {route.description && <div className="patrol-card-desc">{route.description}</div>}
                {selectedRoute?.id === route.id && route.points?.length > 0 && (
                  <div style={{ marginTop: '0.5rem', fontSize: '0.74rem', color: 'var(--color-primary)', lineHeight: '1.6' }}>
                    {route.points.map((p, i) => (
                      <span key={p.id}>
                        <span style={{ background: 'var(--color-primary)', color: '#fff', borderRadius: '50%', width: '14px', height: '14px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: '9px', marginRight: '3px' }}>{i + 1}</span>
                        {p.name}{i < route.points.length - 1 ? ' → ' : ' ↺'}
                      </span>
                    ))}
                  </div>
                )}
                <div className="patrol-card-actions">
                  <button className="patrol-btn patrol-btn-secondary patrol-btn-sm" onClick={(e) => handleEditRoute(route, e)}>✏️ 编辑</button>
                  <button className="patrol-btn patrol-btn-danger patrol-btn-sm" onClick={(e) => { e.stopPropagation(); setDeleteConfirm(route) }}>🗑️ 删除</button>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="patrol-map-container">
          <div ref={mapRef} className="patrol-map-el" />
          {/* 图例 */}
          <div style={{ position: 'absolute', bottom: '1rem', left: '1rem', zIndex: 100 }}>
            <div className="patrol-legend">
              <div className="patrol-legend-item">
                <div className="patrol-legend-dot" style={{ background: '#4f6ef7' }}/>
                <span>区域点位</span>
              </div>
              <div className="patrol-legend-item">
                <div className="patrol-legend-line" style={{ background: '#22c55e' }}/>
                <span>当前线路</span>
              </div>
              <div className="patrol-legend-item">
                <div className="patrol-legend-line" style={{ background: '#94a3b8' }}/>
                <span>其他线路</span>
              </div>
            </div>
          </div>
          {selectedRoute && (
            <div className="patrol-map-badge">
              <strong>🛤️ {selectedRoute.name}</strong>
              <span>距离：{formatDist(selectedRoute.distance)}</span>
              <span>点位：{selectedRoute.point_count} 个（首尾闭环）</span>
            </div>
          )}
        </div>
      </div>

      {/* 新建/编辑线路弹窗 */}
      {showModal && (
        <div className="patrol-modal-overlay">
          <div className="patrol-modal patrol-modal-wide" onClick={e => e.stopPropagation()}>
            <div className="patrol-modal-header">
              <h2>{editingRoute ? '编辑巡检线路' : '新建巡检线路'}</h2>
              <button className="patrol-modal-close" onClick={() => setShowModal(false)}>✕</button>
            </div>
            <form onSubmit={handleSubmit}>
              <div className="patrol-modal-body">
                <div className="patrol-form-row">
                  <div className="patrol-form-group">
                    <label>线路名称 <span style={{ color: '#ef4444' }}>*</span></label>
                    <input type="text" value={formData.name} onChange={e => setFormData({ ...formData, name: e.target.value })} placeholder="例：北侧围界线" required disabled={submitting} />
                  </div>
                  <div className="patrol-form-group">
                    <label>描述</label>
                    <input type="text" value={formData.description} onChange={e => setFormData({ ...formData, description: e.target.value })} placeholder="线路备注..." disabled={submitting} />
                  </div>
                </div>

                {/* 点位选择区域 */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                  {/* 左：可选点位 */}
                  <div className="patrol-form-group">
                    <label>可选点位（点击添加）</label>
                    <div className="patrol-point-picker">
                      {areaPoints.filter(p => !selectedPointIds.includes(p.id)).map((pt, idx) => (
                        <div key={pt.id} className="patrol-point-item" onClick={() => togglePoint(pt.id)}>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                          {pt.name}
                          {pt.address && <span style={{ color: 'var(--color-text-muted)', fontSize: '0.7rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{pt.address}</span>}
                        </div>
                      ))}
                      {areaPoints.filter(p => !selectedPointIds.includes(p.id)).length === 0 && (
                        <div style={{ color: 'var(--color-text-muted)', fontSize: '0.78rem', padding: '0.5rem', textAlign: 'center' }}>所有点位已添加</div>
                      )}
                    </div>
                  </div>

                  {/* 右：已选点位（可拖序） */}
                  <div className="patrol-form-group">
                    <label>
                      已选点位顺序
                      {selectedPointIds.length >= 2 && <span style={{ color: 'var(--color-primary)', marginLeft: '0.4rem', fontWeight: 400, fontSize: '0.76rem' }}>预估 {formatDist(calcCurrentDist())} ↺</span>}
                    </label>
                    <div className="patrol-point-picker">
                      {selectedPointIds.length === 0 && (
                        <div style={{ color: 'var(--color-text-muted)', fontSize: '0.78rem', padding: '0.5rem', textAlign: 'center' }}>从左侧选择点位</div>
                      )}
                      {selectedPointIds.map((id, idx) => {
                        const pt = areaPoints.find(p => p.id === id)
                        if (!pt) return null
                        return (
                          <div key={id} className="patrol-point-item selected" style={{ justifyContent: 'space-between' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flex: 1, overflow: 'hidden' }}>
                              <span className="point-order">{idx + 1}</span>
                              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{pt.name}</span>
                            </div>
                            <div style={{ display: 'flex', gap: '0.2rem', flexShrink: 0 }}>
                              <button type="button" className="patrol-btn-icon" onClick={() => movePoint(idx, -1)} disabled={idx === 0} title="上移">↑</button>
                              <button type="button" className="patrol-btn-icon" onClick={() => movePoint(idx, 1)} disabled={idx === selectedPointIds.length - 1} title="下移">↓</button>
                              <button type="button" className="patrol-btn-icon danger" onClick={() => togglePoint(id)} title="移除">✕</button>
                            </div>
                          </div>
                        )
                      })}
                      {selectedPointIds.length > 2 && (
                        <div style={{ padding: '0.3rem 0.5rem', fontSize: '0.72rem', color: 'var(--color-text-muted)', borderTop: '1px dashed var(--color-border)', marginTop: '0.2rem', textAlign: 'center' }}>↺ 路线闭环至起点</div>
                      )}
                    </div>
                  </div>
                </div>

                {formError && <div className="patrol-form-error">{formError}</div>}
              </div>
              <div className="patrol-modal-footer">
                <button type="button" className="patrol-btn patrol-btn-secondary" onClick={() => setShowModal(false)} disabled={submitting}>取消</button>
                <button type="submit" className="patrol-btn patrol-btn-primary" disabled={submitting || selectedPointIds.length < 2}>
                  {submitting ? '保存中...' : '保存线路'}
                </button>
              </div>
            </form>
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
                确定删除线路 <strong>「{deleteConfirm.name}」</strong> 吗？
              </p>
            </div>
            <div className="patrol-modal-footer">
              <button className="patrol-btn patrol-btn-secondary" onClick={() => setDeleteConfirm(null)}>取消</button>
              <button className="patrol-btn patrol-btn-danger" onClick={() => handleDelete(deleteConfirm.id)}>确认删除</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
