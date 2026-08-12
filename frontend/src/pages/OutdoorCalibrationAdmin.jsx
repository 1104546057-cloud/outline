/**
 * OutdoorCalibrationAdmin.jsx — 校园室外巡检 · 坐标标定管理（阶段 B）
 * ====================================================================
 * 管理校园坐标标定版本（OutdoorCalibration）。
 * 状态机：draft → verified → active → deprecated
 *
 * 功能：
 *   1. 标定列表（版本号、状态徽章、原点经纬度、yaw、验证状态）
 *   2. 新建标定弹窗（版本号、名称、WGS84 原点经纬度、原点高度、yaw）
 *   3. 标定操作按钮：提交对点验证、转 active、deprecate
 *
 * 设计原则（对应需求 §FR-02）：
 *   - 版本号唯一，一经创建不可修改
 *   - 原点修改仅 draft 状态允许
 *   - 转 active 必须先提交对点验证数据；自动降级原 active
 */

import { useEffect, useState } from 'react'
import { authFetch } from '../utils/authFetch'
import { PageHeader, Panel, StatusBadge, Button, EmptyState, LoadingState } from '../components/ui'
import '../styles/OutdoorCalibrationAdmin.css'

const STATUS_LABEL = {
  draft: '草稿',
  verified: '已验证',
  active: '启用中',
  deprecated: '已弃用',
}

const STATUS_VARIANT = {
  draft: 'neutral',
  verified: 'info',
  active: 'success',
  deprecated: 'warning',
}

// ── Mock 数据（后端无数据时降级） ──
const MOCK_CALIBRATIONS = [
  {
    id: 1,
    name: '主校区标定',
    version: 'campus-main-v1',
    description: '主校区原点，图书馆南门',
    origin_lng: 116.3074,
    origin_lat: 39.9847,
    origin_alt: 50.0,
    origin_yaw: 0.0,
    status: 'active',
    verified_by: '张工',
    verified_at: '2026-08-01T10:00:00',
    created_at: '2026-07-28T14:30:00',
  },
  {
    id: 2,
    name: '北区扩展（草案）',
    version: 'campus-north-v2',
    description: '北区操场原点，待现场对点验证',
    origin_lng: 116.3090,
    origin_lat: 39.9860,
    origin_alt: 51.0,
    origin_yaw: 0.0,
    status: 'draft',
    verified_by: null,
    verified_at: null,
    created_at: '2026-08-10T09:15:00',
  },
]

const EMPTY_FORM = {
  name: '',
  version: '',
  description: '',
  origin_lng: '',
  origin_lat: '',
  origin_alt: '',
  origin_yaw: '0',
}

export default function OutdoorCalibrationAdmin() {
  const [calibrations, setCalibrations] = useState([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [actionMessage, setActionMessage] = useState('')

  const fetchCalibrations = async () => {
    setLoading(true)
    try {
      const res = await authFetch('/api/outdoor-patrol/calibrations')
      if (res.ok) {
        const data = await res.json()
        if (Array.isArray(data) && data.length > 0) {
          setCalibrations(data)
          return
        }
      }
      setCalibrations(MOCK_CALIBRATIONS)
    } catch (e) {
      console.warn('fetchCalibrations 失败，使用 mock:', e)
      setCalibrations(MOCK_CALIBRATIONS)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchCalibrations() }, [])

  const openModal = () => {
    setForm(EMPTY_FORM)
    setFormError('')
    setShowModal(true)
  }

  const handleCreate = async () => {
    setFormError('')
    if (!form.name.trim()) { setFormError('请填写名称'); return }
    if (!form.version.trim()) { setFormError('请填写版本号'); return }
    if (!form.origin_lng || !form.origin_lat) { setFormError('请填写原点经纬度'); return }
    const lng = parseFloat(form.origin_lng)
    const lat = parseFloat(form.origin_lat)
    if (lat < -90 || lat > 90) { setFormError('纬度需在 [-90, 90]'); return }
    if (lng < -180 || lng > 180) { setFormError('经度需在 [-180, 180]'); return }

    setSubmitting(true)
    try {
      const payload = {
        name: form.name.trim(),
        version: form.version.trim(),
        description: form.description.trim() || null,
        origin_lng: lng,
        origin_lat: lat,
        origin_alt: form.origin_alt ? parseFloat(form.origin_alt) : null,
        origin_yaw: parseFloat(form.origin_yaw) || 0.0,
      }
      const res = await authFetch('/api/outdoor-patrol/calibrations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (res.ok) {
        setShowModal(false)
        setActionMessage('标定已创建为 draft，完成对点验证后可转 active')
        fetchCalibrations()
      } else {
        const err = await res.json().catch(() => ({}))
        setFormError(err.detail || `创建失败 (${res.status})`)
      }
    } catch (e) {
      setFormError(`网络错误: ${e.message}`)
    } finally {
      setSubmitting(false)
    }
  }

  const handleAction = async (cal, action) => {
    setActionMessage('')
    let endpoint = ''
    let payload = {}
    if (action === 'verify') {
      // 实际项目应弹窗输入对点验证数据，这里用占位
      payload = {
        status: 'verified',
        verification_geojson: {
          type: 'FeatureCollection',
          features: [{
            type: 'Feature',
            properties: { note: '现场对点验证占位' },
            geometry: { type: 'Point', coordinates: [cal.origin_lng, cal.origin_lat] },
          }],
        },
        verified_by: '当前用户',
      }
      endpoint = `/api/outdoor-patrol/calibrations/${cal.id}`
    } else if (action === 'activate') {
      payload = { status: 'active' }
      endpoint = `/api/outdoor-patrol/calibrations/${cal.id}`
    } else if (action === 'deprecate') {
      if (!confirm(`确认弃用标定 ${cal.version}？引用此标定的路线将无法启动新任务。`)) return
      endpoint = `/api/outdoor-patrol/calibrations/${cal.id}`
      payload = { status: 'deprecated' }
    }

    try {
      const res = await authFetch(endpoint, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (res.ok) {
        const data = await res.json().catch(() => ({}))
        setActionMessage(data.message || '操作成功')
        fetchCalibrations()
      } else {
        const err = await res.json().catch(() => ({}))
        setActionMessage(`操作失败: ${err.detail || res.status}`)
      }
    } catch (e) {
      setActionMessage(`网络错误: ${e.message}`)
    }
  }

  return (
    <div className="outdoor-cal-admin">
      <PageHeader
        title="室外坐标标定管理"
        description="校园坐标标定版本管理。每个标定定义 WGS84 原点与 ENU→map 偏航角，路线与任务必须绑定标定版本。"
      />

      {actionMessage && (
        <div className="outdoor-cal-admin__msg">{actionMessage}</div>
      )}

      <div className="outdoor-cal-admin__toolbar">
        <Button variant="primary" onClick={openModal}>+ 新建标定</Button>
      </div>

      {loading ? (
        <LoadingState text="加载标定列表..." />
      ) : calibrations.length === 0 ? (
        <EmptyState title="暂无标定" description="点击右上角新建第一个校园坐标标定。" />
      ) : (
        <Panel title={`标定列表（${calibrations.length}）`}>
          <table className="outdoor-cal-admin__table">
            <thead>
              <tr>
                <th>名称</th>
                <th>版本</th>
                <th>状态</th>
                <th>原点经度</th>
                <th>原点纬度</th>
                <th>偏航角 (rad)</th>
                <th>验证</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {calibrations.map(c => (
                <tr key={c.id}>
                  <td>
                    <div className="outdoor-cal-admin__name">{c.name}</div>
                    {c.description && (
                      <div className="outdoor-cal-admin__desc">{c.description}</div>
                    )}
                  </td>
                  <td><code>{c.version}</code></td>
                  <td>
                    <StatusBadge variant={STATUS_VARIANT[c.status] || 'neutral'}>
                      {STATUS_LABEL[c.status] || c.status}
                    </StatusBadge>
                  </td>
                  <td>{typeof c.origin_lng === 'number' ? c.origin_lng.toFixed(7) : c.origin_lng}</td>
                  <td>{typeof c.origin_lat === 'number' ? c.origin_lat.toFixed(7) : c.origin_lat}</td>
                  <td>{c.origin_yaw?.toFixed(4) ?? '—'}</td>
                  <td>
                    {c.verified_at ? (
                      <span className="outdoor-cal-admin__verified">
                        ✓ {c.verified_by || '已验证'}
                      </span>
                    ) : (
                      <span className="outdoor-cal-admin__unverified">未验证</span>
                    )}
                  </td>
                  <td>
                    <div className="outdoor-cal-admin__actions">
                      {c.status === 'draft' && (
                        <Button
                          variant="default"
                          onClick={() => handleAction(c, 'verify')}
                        >
                          提交验证
                        </Button>
                      )}
                      {c.status === 'verified' && (
                        <Button
                          variant="primary"
                          onClick={() => handleAction(c, 'activate')}
                        >
                          启用为 active
                        </Button>
                      )}
                      {c.status === 'active' && (
                        <Button
                          variant="warning"
                          onClick={() => handleAction(c, 'deprecate')}
                        >
                          弃用
                        </Button>
                      )}
                      {c.status === 'deprecated' && (
                        <span className="outdoor-cal-admin__deprecated-tag">已弃用</span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}

      {showModal && (
        <div className="outdoor-cal-admin__modal-overlay" onClick={() => setShowModal(false)}>
          <div className="outdoor-cal-admin__modal" onClick={e => e.stopPropagation()}>
            <div className="outdoor-cal-admin__modal-header">
              <h2>新建坐标标定</h2>
              <button className="outdoor-cal-admin__modal-close" onClick={() => setShowModal(false)}>×</button>
            </div>
            <div className="outdoor-cal-admin__modal-body">
              {formError && (
                <div className="outdoor-cal-admin__form-error">{formError}</div>
              )}
              <div className="outdoor-cal-admin__form-row">
                <label>
                  名称<span className="outdoor-cal-admin__required">*</span>
                  <input
                    type="text"
                    value={form.name}
                    onChange={e => setForm({ ...form, name: e.target.value })}
                    placeholder="如：主校区标定"
                  />
                </label>
                <label>
                  版本号<span className="outdoor-cal-admin__required">*</span>
                  <input
                    type="text"
                    value={form.version}
                    onChange={e => setForm({ ...form, version: e.target.value })}
                    placeholder="如：campus-main-v1（唯一，不可修改）"
                  />
                </label>
              </div>
              <label className="outdoor-cal-admin__form-full">
                描述
                <input
                  type="text"
                  value={form.description}
                  onChange={e => setForm({ ...form, description: e.target.value })}
                  placeholder="标定位置说明，如：图书馆南门"
                />
              </label>
              <div className="outdoor-cal-admin__form-row">
                <label>
                  原点经度 (WGS84)<span className="outdoor-cal-admin__required">*</span>
                  <input
                    type="number"
                    step="0.0000001"
                    value={form.origin_lng}
                    onChange={e => setForm({ ...form, origin_lng: e.target.value })}
                    placeholder="116.3074"
                  />
                </label>
                <label>
                  原点纬度 (WGS84)<span className="outdoor-cal-admin__required">*</span>
                  <input
                    type="number"
                    step="0.0000001"
                    value={form.origin_lat}
                    onChange={e => setForm({ ...form, origin_lat: e.target.value })}
                    placeholder="39.9847"
                  />
                </label>
              </div>
              <div className="outdoor-cal-admin__form-row">
                <label>
                  原点椭球高 (m)
                  <input
                    type="number"
                    step="0.1"
                    value={form.origin_alt}
                    onChange={e => setForm({ ...form, origin_alt: e.target.value })}
                    placeholder="可选"
                  />
                </label>
                <label>
                  ENU→map 偏航角 (rad)
                  <input
                    type="number"
                    step="0.001"
                    value={form.origin_yaw}
                    onChange={e => setForm({ ...form, origin_yaw: e.target.value })}
                    placeholder="默认 0（map 与 ENU 重合）"
                  />
                </label>
              </div>
              <div className="outdoor-cal-admin__hint">
                新建后状态为 <b>draft</b>。完成现场对点验证后可转为 <b>verified</b>，
                再由管理员启用为 <b>active</b>。同一时刻仅允许一个 active 标定。
              </div>
            </div>
            <div className="outdoor-cal-admin__modal-footer">
              <Button variant="default" onClick={() => setShowModal(false)}>取消</Button>
              <Button variant="primary" onClick={handleCreate} disabled={submitting}>
                {submitting ? '提交中...' : '创建标定'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
