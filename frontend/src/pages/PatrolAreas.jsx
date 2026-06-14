import { useState, useEffect, useRef } from 'react'
import AMapLoader from '@amap/amap-jsapi-loader'
import { authFetch } from '../utils/authFetch'
import '../styles/Patrol.css'

const AMAP_KEY = import.meta.env.VITE_AMAP_API_KEY
const AMAP_SECURITY_KEY = import.meta.env.VITE_AMAP_API_SECURE_KEY

/** 计算多边形面积（m²）—— 球面公式 */
function calcPolygonArea(path) {
  if (!path || path.length < 3) return 0
  const EARTH_R = 6378137
  let area = 0
  const n = path.length
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n
    const [lng1, lat1] = path[i]
    const [lng2, lat2] = path[j]
    const rad1 = (lat1 * Math.PI) / 180
    const rad2 = (lat2 * Math.PI) / 180
    const dLng = ((lng2 - lng1) * Math.PI) / 180
    area += dLng * (Math.sin(rad1) + Math.sin(rad2))
  }
  return Math.abs((area * EARTH_R * EARTH_R) / 2)
}

/** 计算多边形中心点 */
function calcCenter(path) {
  if (!path || path.length === 0) return [0, 0]
  const lng = path.reduce((s, p) => s + p[0], 0) / path.length
  const lat = path.reduce((s, p) => s + p[1], 0) / path.length
  return [lng, lat]
}

export default function PatrolAreas() {
  const mapRef = useRef(null)
  const mapInstanceRef = useRef(null)
  const amapRef = useRef(null)
  const mouseToolRef = useRef(null)
  const overlaysRef = useRef({}) // area_id -> polygon overlay

  const [areas, setAreas] = useState([])
  const [selectedArea, setSelectedArea] = useState(null)
  const [loading, setLoading] = useState(true)
  const [drawing, setDrawing] = useState(false)

  // 弹窗状态
  const [showModal, setShowModal] = useState(false)
  const [editingArea, setEditingArea] = useState(null) // null=新建
  const [pendingBoundary, setPendingBoundary] = useState(null)
  const [pendingCenter, setPendingCenter] = useState(null)
  const [pendingArea, setPendingArea] = useState(null)
  const [formData, setFormData] = useState({ name: '', description: '', manager: '' })
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState(null)
  const [drawError, setDrawError] = useState(false)

  // 加载区域列表
  const fetchAreas = async () => {
    try {
      const res = await authFetch('/api/patrol/areas')
      if (res.ok) {
        const data = await res.json()
        setAreas(data)
      }
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  useEffect(() => { fetchAreas() }, [])

  // 初始化高德地图
  useEffect(() => {
    if (!mapRef.current) return
    window._AMapSecurityConfig = { securityJsCode: AMAP_SECURITY_KEY }
    AMapLoader.load({
      key: AMAP_KEY,
      version: '2.0',
      plugins: ['AMap.MouseTool', 'AMap.Polygon', 'AMap.Marker'],
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
    return () => {
      mouseToolRef.current?.close()
      mapInstanceRef.current?.destroy()
    }
  }, [])

  // 当 areas 或 map 准备好后，绘制所有区域
  useEffect(() => {
    const AMap = amapRef.current
    const map = mapInstanceRef.current
    if (!AMap || !map || areas.length === 0) return

    // 清除旧覆盖物
    Object.values(overlaysRef.current).forEach(o => map.remove(o))
    overlaysRef.current = {}

    areas.forEach(area => {
      if (!area.boundary || area.boundary.length < 3) return
      const path = area.boundary.map(([lng, lat]) => new AMap.LngLat(lng, lat))
      const poly = new AMap.Polygon({
        path,
        fillColor: area.id === selectedArea?.id ? '#4f6ef7' : '#4f6ef7',
        fillOpacity: area.id === selectedArea?.id ? 0.25 : 0.08,
        strokeColor: '#4f6ef7',
        strokeWeight: area.id === selectedArea?.id ? 2.5 : 1.5,
        strokeOpacity: area.id === selectedArea?.id ? 1 : 0.5,
        strokeStyle: 'solid',
      })
      poly.on('click', () => handleSelectArea(area))
      map.add(poly)
      overlaysRef.current[area.id] = poly

      // 中心标注
      if (area.center_lng && area.center_lat) {
        const marker = new AMap.Marker({
          position: [area.center_lng, area.center_lat],
          content: `<div style="
            background:#4f6ef7;color:#fff;
            padding:3px 8px;border-radius:100px;
            font-size:11px;font-weight:600;
            white-space:nowrap;box-shadow:0 2px 8px rgba(79,110,247,0.4);
            transform:translateX(-50%);
          ">${area.name}</div>`,
          anchor: 'bottom-center',
          offset: new AMap.Pixel(0, -5),
        })
        marker.on('click', () => handleSelectArea(area))
        map.add(marker)
      }
    })

    if (areas.length > 0 && !selectedArea) {
      const first = areas[0]
      if (first.center_lng && first.center_lat) {
        map.setCenter([first.center_lng, first.center_lat])
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [areas])

  const handleSelectArea = (area) => {
    setSelectedArea(area)
    const map = mapInstanceRef.current
    const AMap = amapRef.current
    if (map && AMap) {
      const poly = overlaysRef.current[area.id]
      if (poly) {
        // 自适应视野并放大，最大放大级别设为 18，四周留 60px padding
        map.setFitView([poly], false, [60, 60, 60, 60], 18)
      } else if (area.center_lng && area.center_lat) {
        map.setCenter([area.center_lng, area.center_lat])
        map.setZoom(18)
      }
    }
  }

  // 开始绘制
  const startDrawing = () => {
    const AMap = amapRef.current
    const map = mapInstanceRef.current
    if (!AMap || !map) return
    setDrawing(true)
    mouseToolRef.current?.close(true)
    const tool = new AMap.MouseTool(map)
    mouseToolRef.current = tool
    tool.polygon({
      fillColor: '#4f6ef7',
      fillOpacity: 0.15,
      strokeColor: '#4f6ef7',
      strokeWeight: 2,
      strokeStyle: 'dashed',
    })
    tool.on('draw', ({ obj }) => {
      const path = obj.getPath().map(p => [p.getLng(), p.getLat()])
      if (path.length < 3) {
        tool.close(true)
        tool.polygon({
          fillColor: '#4f6ef7',
          fillOpacity: 0.15,
          strokeColor: '#4f6ef7',
          strokeWeight: 2,
          strokeStyle: 'dashed',
        })
        setDrawError(true)
        setTimeout(() => setDrawError(false), 3000)
        return
      }
      tool.close(true)
      setDrawing(false)
      const area = calcPolygonArea(path)
      const [clng, clat] = calcCenter(path)
      setPendingBoundary(path)
      setPendingCenter([clng, clat])
      setPendingArea(area)
      setEditingArea(null)
      setFormData({ name: '', description: '', manager: '' })
      setFormError('')
      setShowModal(true)
    })
  }

  const stopDrawing = () => {
    mouseToolRef.current?.close(true)
    setDrawing(false)
  }

  // 编辑区域
  const handleEditArea = (area, e) => {
    e.stopPropagation()
    setEditingArea(area)
    setFormData({ name: area.name, description: area.description || '', manager: area.manager || '' })
    setFormError('')
    setShowModal(true)
  }

  // 提交保存
  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!formData.name.trim()) { setFormError('请填写区域名称'); return }
    if (!editingArea && !pendingBoundary) { setFormError('请先在地图上绘制区域范围'); return }
    setSubmitting(true)
    setFormError('')
    try {
      let res
      if (editingArea) {
        res = await authFetch(`/api/patrol/areas/${editingArea.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(formData),
        })
      } else {
        res = await authFetch('/api/patrol/areas', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ...formData,
            boundary: pendingBoundary,
            center_lng: pendingCenter?.[0],
            center_lat: pendingCenter?.[1],
            area_sqm: pendingArea,
          }),
        })
      }
      if (res.ok) {
        const saved = await res.json()
        setShowModal(false)
        setPendingBoundary(null)
        setPendingCenter(null)
        setPendingArea(null)
        await fetchAreas()
        setSelectedArea(saved)
      } else {
        const err = await res.json()
        setFormError(err.detail || '保存失败')
      }
    } catch (e) { setFormError('网络错误') }
    finally { setSubmitting(false) }
  }

  // 删除区域
  const handleDelete = async (id) => {
    try {
      const res = await authFetch(`/api/patrol/areas/${id}`, { method: 'DELETE' })
      if (res.ok) {
        setDeleteConfirm(null)
        if (selectedArea?.id === id) setSelectedArea(null)
        fetchAreas()
      }
    } catch (e) { console.error(e) }
  }

  const formatArea = (sqm) => {
    if (!sqm) return '--'
    if (sqm >= 1e6) return `${(sqm / 1e6).toFixed(2)} km²`
    if (sqm >= 1e4) return `${(sqm / 1e4).toFixed(2)} 公顷`
    return `${sqm.toFixed(0)} m²`
  }

  return (
    <div className="patrol-page">
      {/* 页头 */}
      <div className="patrol-header">
        <div className="patrol-header-left">
          <h1>巡检区域</h1>
          <span className="patrol-subtitle">在地图上框选区域范围，定义巡检边界</span>
        </div>
        <div className="patrol-header-actions">
          {drawing ? (
            <button className="patrol-btn patrol-btn-warning" onClick={stopDrawing}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
              取消绘制
            </button>
          ) : (
            <button className="patrol-btn patrol-btn-primary" onClick={startDrawing}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="3,3 21,12 3,21" /></svg>
              框选新区域
            </button>
          )}
        </div>
      </div>

      {/* 主体 */}
      <div className="patrol-body">
        {/* 左侧列表 */}
        <div className="patrol-sidebar">
          <div className="patrol-sidebar-list">
            {loading ? (
              <div className="patrol-loading"><div className="patrol-spinner" /><span>加载中...</span></div>
            ) : areas.length === 0 ? (
              <div className="patrol-empty">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" /><polyline points="9,22 9,12 15,12 15,22" /></svg>
                <p>暂无巡检区域<br />点击「框选新区域」开始创建</p>
              </div>
            ) : areas.map(area => (
              <div
                key={area.id}
                className={`patrol-card ${selectedArea?.id === area.id ? 'active' : ''}`}
                onClick={() => handleSelectArea(area)}
              >
                <div className="patrol-card-header">
                  <span className="patrol-card-title">🗺️ {area.name}</span>
                </div>
                <div className="patrol-card-meta">
                  <span className="patrol-card-tag">📍 {area.point_count} 个点位</span>
                  <span className="patrol-card-tag">🛤️ {area.route_count} 条线路</span>
                  <span className="patrol-card-tag">📐 {formatArea(area.area_sqm)}</span>
                </div>
                {area.manager && <div className="patrol-card-desc">👤 负责人：{area.manager}</div>}
                {area.description && <div className="patrol-card-desc">{area.description}</div>}
                <div className="patrol-card-actions">
                  <button className="patrol-btn patrol-btn-secondary patrol-btn-sm" onClick={(e) => handleEditArea(area, e)}>
                    ✏️ 编辑
                  </button>
                  <button className="patrol-btn patrol-btn-danger patrol-btn-sm" onClick={(e) => { e.stopPropagation(); setDeleteConfirm(area) }}>
                    🗑️ 删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 右侧地图 */}
        <div className="patrol-map-container">
          <div ref={mapRef} className="patrol-map-el" />
          {drawing && (
            <div className="patrol-draw-banner">
              ✏️ 在地图上单击绘制区域边界，双击完成绘制
            </div>
          )}
          {drawError && (
            <div className="patrol-draw-banner" style={{ background: 'rgba(239,68,68,0.9)' }}>
              ⚠️ 绘制的区域点数不足，请至少绘制3个点以构成多边形
            </div>
          )}
          {!drawing && areas.length === 0 && (
            <div className="patrol-map-hint">
              <h3>🗺️ 开始定义巡检区域</h3>
              <p>点击右上角「框选新区域」在地图上<br />绘制多边形范围</p>
            </div>
          )}
          {selectedArea && (
            <div className="patrol-map-badge">
              <strong>{selectedArea.name}</strong>
              <span>面积：{formatArea(selectedArea.area_sqm)}</span>
              {selectedArea.center_lng && (
                <span>中心：{selectedArea.center_lat?.toFixed(5)}, {selectedArea.center_lng?.toFixed(5)}</span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 新建/编辑弹窗 */}
      {showModal && (
        <div className="patrol-modal-overlay">
          <div className="patrol-modal" onClick={e => e.stopPropagation()}>
            <div className="patrol-modal-header">
              <h2>{editingArea ? '编辑巡检区域' : '新建巡检区域'}</h2>
              <button className="patrol-modal-close" onClick={() => !submitting && setShowModal(false)}>✕</button>
            </div>
            <form onSubmit={handleSubmit}>
              <div className="patrol-modal-body">
                {!editingArea && pendingArea && (
                  <div style={{ background: 'var(--color-primary-bg)', border: '1px solid var(--color-primary-border)', borderRadius: 'var(--radius-sm)', padding: '0.65rem 0.85rem', fontSize: '0.8rem', color: 'var(--color-primary-dark)' }}>
                    📐 已绘制区域：<strong>{formatArea(pendingArea)}</strong>，共 {pendingBoundary?.length} 个边界点
                  </div>
                )}
                <div className="patrol-form-group">
                  <label>区域名称 <span style={{ color: '#ef4444' }}>*</span></label>
                  <input type="text" value={formData.name} onChange={e => setFormData({ ...formData, name: e.target.value })} placeholder="例：中山大学珠海校区软件工程学院" required disabled={submitting} />
                </div>
                <div className="patrol-form-group">
                  <label>负责人</label>
                  <input type="text" value={formData.manager} onChange={e => setFormData({ ...formData, manager: e.target.value })} placeholder="例：董祖豪" disabled={submitting} />
                </div>
                <div className="patrol-form-group">
                  <label>描述</label>
                  <textarea value={formData.description} onChange={e => setFormData({ ...formData, description: e.target.value })} placeholder="例：无人车日常巡检区域" disabled={submitting} />
                </div>
                {formError && <div className="patrol-form-error">{formError}</div>}
              </div>
              <div className="patrol-modal-footer">
                <button type="button" className="patrol-btn patrol-btn-secondary" onClick={() => setShowModal(false)} disabled={submitting}>取消</button>
                <button type="submit" className="patrol-btn patrol-btn-primary" disabled={submitting}>
                  {submitting ? '保存中...' : '保存区域'}
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
                确定删除巡检区域 <strong>「{deleteConfirm.name}」</strong> 吗？<br />
                <span style={{ color: '#ef4444', fontSize: '0.82rem' }}>该操作将同时删除区域内所有点位和线路，且不可撤销。</span>
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
