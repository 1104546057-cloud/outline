import { useState, useEffect, useRef, useCallback } from 'react'
import AMapLoader from '@amap/amap-jsapi-loader'
import ThemedSelect from '../components/ThemedSelect'
import { authFetch } from '../utils/authFetch'
import '../styles/Patrol.css'

const AMAP_KEY = import.meta.env.VITE_AMAP_API_KEY
const AMAP_SECURITY_KEY = import.meta.env.VITE_AMAP_API_SECURE_KEY

/** 判断点是否在多边形内（射线法） */
function isPointInPolygon(point, polygon) {
  if (!polygon || polygon.length < 3) return true // 无边界不限制
  const [x, y] = point
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i]
    const [xj, yj] = polygon[j]
    const intersect = ((yi > y) !== (yj > y)) && (x < ((xj - xi) * (y - yi)) / (yj - yi) + xi)
    if (intersect) inside = !inside
  }
  return inside
}

export default function PatrolPoints() {
  const mapRef = useRef(null)
  const mapInstanceRef = useRef(null)
  const amapRef = useRef(null)
  const areaPolygonRef = useRef(null)
  const markersRef = useRef({}) // point_id -> marker
  const currentAreaRef = useRef(null)

  const [areas, setAreas] = useState([])
  const [selectedAreaId, setSelectedAreaId] = useState('')
  const [points, setPoints] = useState([])
  const [selectedPoint, setSelectedPoint] = useState(null)
  const [loading, setLoading] = useState(false)
  const [placing, setPlacing] = useState(false) // 打点模式

  // 弹窗
  const [showModal, setShowModal] = useState(false)
  const [editingPoint, setEditingPoint] = useState(null)
  const [pendingLng, setPendingLng] = useState(null)
  const [pendingLat, setPendingLat] = useState(null)
  const [pendingAddr, setPendingAddr] = useState('')
  const [formData, setFormData] = useState({ name: '', description: '' })
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState(null)
  const [outOfBound, setOutOfBound] = useState(false)

  // 获取当前区域对象
  const currentArea = areas.find(a => a.id === Number(selectedAreaId))

  // 加载区域列表
  useEffect(() => {
    authFetch('/api/patrol/areas').then(r => r.ok ? r.json() : []).then(data => {
      setAreas(data)
      if (data.length > 0) setSelectedAreaId(String(data[0].id))
    }).catch(console.error)
  }, [])

  // 加载点位
  const fetchPoints = useCallback(async (areaId) => {
    if (!areaId) { setPoints([]); return }
    setLoading(true)
    try {
      const res = await authFetch(`/api/patrol/points?area_id=${areaId}`)
      if (res.ok) setPoints(await res.json())
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchPoints(selectedAreaId) }, [selectedAreaId, fetchPoints])

  // 初始化地图
  useEffect(() => {
    if (!mapRef.current) return
    window._AMapSecurityConfig = { securityJsCode: AMAP_SECURITY_KEY }
    AMapLoader.load({
      key: AMAP_KEY,
      version: '2.0',
      plugins: ['AMap.Geocoder', 'AMap.Polygon', 'AMap.Marker'],
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

  // 当选中区域变化时，绘制区域边界
  useEffect(() => {
    const AMap = amapRef.current
    const map = mapInstanceRef.current
    if (!AMap || !map) return

    // 移除旧区域边界
    if (areaPolygonRef.current) {
      map.remove(areaPolygonRef.current)
      areaPolygonRef.current = null
    }

    if (!currentArea || !currentArea.boundary) return
    const path = currentArea.boundary.map(([lng, lat]) => new AMap.LngLat(lng, lat))
    const poly = new AMap.Polygon({
      path,
      fillColor: '#4f6ef7',
      fillOpacity: 0.06,
      strokeColor: '#4f6ef7',
      strokeWeight: 2,
      strokeStyle: 'solid',
      strokeOpacity: 0.7,
      bubble: true,
    })
    map.add(poly)
    areaPolygonRef.current = poly
    map.setFitView([poly], false, [40, 40, 40, 40], 18)
  }, [currentArea])

  // 当 points 变化时更新标记
  useEffect(() => {
    const AMap = amapRef.current
    const map = mapInstanceRef.current
    if (!AMap || !map) return

    // 清除旧标记
    Object.values(markersRef.current).forEach(m => map.remove(m))
    markersRef.current = {}

    points.forEach((pt, idx) => {
      const marker = new AMap.Marker({
        position: [pt.lng, pt.lat],
        content: `<div style="
          width:28px;height:28px;
          background:${selectedPoint?.id === pt.id ? '#4f6ef7' : '#f59e0b'};
          border:3px solid #fff;
          border-radius:50% 50% 50% 0;
          transform:rotate(-45deg);
          box-shadow:0 2px 8px rgba(0,0,0,0.25);
          display:flex;align-items:center;justify-content:center;
        "><span style="transform:rotate(45deg);color:#fff;font-size:10px;font-weight:700">${idx + 1}</span></div>`,
        anchor: 'bottom-left',
        offset: new AMap.Pixel(-14, 14),
      })
      marker.on('click', () => {
        setSelectedPoint(pt)
      })
      map.add(marker)
      markersRef.current[pt.id] = marker
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points])

  // 逆地理编码
  const reverseGeocode = (AMap, lng, lat, callback) => {
    const geocoder = new AMap.Geocoder()
    geocoder.getAddress([lng, lat], (status, result) => {
      if (status === 'complete' && result.info === 'OK') {
        callback(result.regeocode.formattedAddress || '')
      } else {
        callback('')
      }
    })
  }

  // 地图点击事件（打点模式）
  const mapClickHandler = useRef(null)

  const enablePlacing = () => {
    const AMap = amapRef.current
    const map = mapInstanceRef.current
    if (!AMap || !map) return
    setPlacing(true)
    currentAreaRef.current = currentArea

    const handler = (e) => {
      const lng = e.lnglat.getLng()
      const lat = e.lnglat.getLat()
      // 检查是否在区域内
      const area = currentAreaRef.current
      if (area?.boundary) {
        const inside = isPointInPolygon([lng, lat], area.boundary)
        if (!inside) {
          setOutOfBound(true)
          setTimeout(() => setOutOfBound(false), 3000)
          return
        }
      }
      // 逆地理编码
      reverseGeocode(AMap, lng, lat, (addr) => {
        setPendingLng(lng)
        setPendingLat(lat)
        setPendingAddr(addr)
        setEditingPoint(null)
        setFormData({ name: '', description: '' })
        setFormError('')
        setShowModal(true)
      })
      map.off('click', mapClickHandler.current)
      setPlacing(false)
    }
    mapClickHandler.current = handler
    map.on('click', handler)
  }

  const disablePlacing = () => {
    const map = mapInstanceRef.current
    if (map && mapClickHandler.current) {
      map.off('click', mapClickHandler.current)
    }
    setPlacing(false)
  }

  const handleEditPoint = (pt, e) => {
    e.stopPropagation()
    setEditingPoint(pt)
    setFormData({ name: pt.name, description: pt.description || '' })
    setFormError('')
    setShowModal(true)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!formData.name.trim()) { setFormError('请填写点位名称'); return }
    if (!editingPoint && (pendingLng === null)) { setFormError('请先在地图上点击添加点位坐标'); return }
    setSubmitting(true)
    setFormError('')
    try {
      let res
      if (editingPoint) {
        res = await authFetch(`/api/patrol/points/${editingPoint.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(formData),
        })
      } else {
        res = await authFetch('/api/patrol/points', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            area_id: Number(selectedAreaId),
            name: formData.name,
            description: formData.description,
            lng: pendingLng,
            lat: pendingLat,
            address: pendingAddr,
          }),
        })
      }
      if (res.ok) {
        setShowModal(false)
        setPendingLng(null)
        setPendingLat(null)
        setPendingAddr('')
        fetchPoints(selectedAreaId)
      } else {
        const err = await res.json()
        setFormError(err.detail || '保存失败')
      }
    } catch (e) { setFormError('网络错误') }
    finally { setSubmitting(false) }
  }

  const handleDelete = async (id) => {
    try {
      const res = await authFetch(`/api/patrol/points/${id}`, { method: 'DELETE' })
      if (res.ok) {
        setDeleteConfirm(null)
        if (selectedPoint?.id === id) setSelectedPoint(null)
        fetchPoints(selectedAreaId)
      }
    } catch (e) { console.error(e) }
  }

  return (
    <div className="patrol-page">
      <div className="patrol-header">
        <div className="patrol-header-left">
          <h1>巡检点位</h1>
          <span className="patrol-subtitle">在区域内标记关键巡检位置</span>
        </div>
        <div className="patrol-header-actions">
          <ThemedSelect
            className="patrol-header-select"
            value={selectedAreaId}
            onChange={e => { setSelectedAreaId(e.target.value); setSelectedPoint(null) }}
          >
            <option value="">-- 选择巡检区域 --</option>
            {areas.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
          </ThemedSelect>
          {selectedAreaId && (
            placing ? (
              <button className="patrol-btn patrol-btn-warning" onClick={disablePlacing}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
                取消打点
              </button>
            ) : (
              <button className="patrol-btn patrol-btn-primary" onClick={enablePlacing}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="10" r="3" /><path d="M12 21.7C17.3 17 20 13 20 10a8 8 0 10-16 0c0 3 2.7 6.9 8 11.7z" /></svg>
                添加点位
              </button>
            )
          )}
        </div>
      </div>

      <div className="patrol-body">
        {/* 左侧列表 */}
        <div className="patrol-sidebar">
          <div className="patrol-sidebar-list">
            {!selectedAreaId ? (
              <div className="patrol-empty">
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2"><circle cx="12" cy="10" r="3" /><path d="M12 21.7C17.3 17 20 13 20 10a8 8 0 10-16 0c0 3 2.7 6.9 8 11.7z" /></svg>
                <p>请先在上方选择巡检区域</p>
              </div>
            ) : loading ? (
              <div className="patrol-loading"><div className="patrol-spinner" /><span>加载中...</span></div>
            ) : points.length === 0 ? (
              <div className="patrol-empty">
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2"><circle cx="12" cy="10" r="3" /><path d="M12 21.7C17.3 17 20 13 20 10a8 8 0 10-16 0c0 3 2.7 6.9 8 11.7z" /></svg>
                <p>暂无点位<br />点击「添加点位」在地图上标记</p>
              </div>
            ) : points.map((pt, idx) => (
              <div
                key={pt.id}
                className={`patrol-card ${selectedPoint?.id === pt.id ? 'active' : ''}`}
                onClick={() => {
                  setSelectedPoint(pt)
                  const map = mapInstanceRef.current
                  const AMap = amapRef.current
                  if (map && AMap) {
                    map.setCenter([pt.lng, pt.lat])
                    map.setZoom(17)
                  }
                }}
              >
                <div className="patrol-card-header">
                  <span className="patrol-card-title">
                    <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '1.5rem', height: '1.5rem', background: 'var(--color-primary)', borderRadius: '50%', color: '#fff', fontSize: '0.7rem', fontWeight: 700, marginRight: '0.4rem', flexShrink: 0 }}>{idx + 1}</span>
                    {pt.name}
                  </span>
                </div>
                <div className="patrol-card-meta">
                  <span className="patrol-card-tag">📍 {pt.lat?.toFixed(5)}, {pt.lng?.toFixed(5)}</span>
                </div>
                {pt.address && <div className="patrol-card-desc">🏠 {pt.address}</div>}
                {pt.description && <div className="patrol-card-desc">{pt.description}</div>}
                <div className="patrol-card-actions">
                  <button className="patrol-btn patrol-btn-secondary patrol-btn-sm" onClick={(e) => handleEditPoint(pt, e)}>✏️ 编辑</button>
                  <button className="patrol-btn patrol-btn-danger patrol-btn-sm" onClick={(e) => { e.stopPropagation(); setDeleteConfirm(pt) }}>🗑️ 删除</button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 地图 */}
        <div className="patrol-map-container">
          <div ref={mapRef} className="patrol-map-el" />
          {placing && (
            <div className="patrol-draw-banner">
              📍 点击地图添加巡检点位（需在区域范围内）
            </div>
          )}
          {outOfBound && (
            <div className="patrol-draw-banner" style={{ background: 'rgba(239,68,68,0.9)' }}>
              ⚠️ 该位置超出区域范围，请在区域内添加点位
            </div>
          )}
          {selectedPoint && (
            <div className="patrol-map-badge">
              <strong>📍 {selectedPoint.name}</strong>
              <span>经度：{selectedPoint.lng?.toFixed(6)}</span>
              <span>纬度：{selectedPoint.lat?.toFixed(6)}</span>
              {selectedPoint.address && <span>地址：{selectedPoint.address}</span>}
            </div>
          )}
        </div>
      </div>

      {/* 弹窗 */}
      {showModal && (
        <div className="patrol-modal-overlay">
          <div className="patrol-modal" onClick={e => e.stopPropagation()}>
            <div className="patrol-modal-header">
              <h2>{editingPoint ? '编辑巡检点位' : '新建巡检点位'}</h2>
              <button className="patrol-modal-close" onClick={() => !submitting && setShowModal(false)}>✕</button>
            </div>
            <form onSubmit={handleSubmit}>
              <div className="patrol-modal-body">
                {!editingPoint && pendingLng !== null && (
                  <div style={{ background: 'var(--color-primary-bg)', border: '1px solid var(--color-primary-border)', borderRadius: 'var(--radius-sm)', padding: '0.65rem 0.85rem', fontSize: '0.8rem', color: 'var(--color-primary-dark)' }}>
                    📍 坐标：{pendingLat?.toFixed(6)}, {pendingLng?.toFixed(6)}
                    {pendingAddr && <><br />🏠 地址：{pendingAddr}</>}
                  </div>
                )}
                <div className="patrol-form-group">
                  <label>点位名称 <span style={{ color: '#ef4444' }}>*</span></label>
                  <input type="text" value={formData.name} onChange={e => setFormData({ ...formData, name: e.target.value })} placeholder="例：实验室A102" required disabled={submitting} />
                </div>
                <div className="patrol-form-group">
                  <label>描述</label>
                  <textarea value={formData.description} onChange={e => setFormData({ ...formData, description: e.target.value })} placeholder="例：正门" disabled={submitting} />
                </div>
                {formError && <div className="patrol-form-error">{formError}</div>}
              </div>
              <div className="patrol-modal-footer">
                <button type="button" className="patrol-btn patrol-btn-secondary" onClick={() => setShowModal(false)} disabled={submitting}>取消</button>
                <button type="submit" className="patrol-btn patrol-btn-primary" disabled={submitting}>
                  {submitting ? '保存中...' : '保存点位'}
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
                确定删除点位 <strong>「{deleteConfirm.name}」</strong> 吗？
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
