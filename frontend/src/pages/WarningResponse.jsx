import { useCallback, useEffect, useMemo, useState } from 'react'
import { authFetch } from '../utils/authFetch'
import '../styles/WarningResponse.css'

const severityLabels = {
  low: '低',
  medium: '中',
  high: '高',
  critical: '紧急',
}

const statusLabels = {
  pending: '待处置',
  acknowledged: '处理中',
  closed: '已关闭',
}

const mockSources = {
  video: {
    alert_type: 'video_detection',
    severity: 'high',
    title: '视频识别发现可疑人员滞留',
    description: '来自视频识别分析 Mock 数据：人员在重点区域持续停留，请核查现场情况。',
    source_type: 'video_analysis_mock',
    media_path: '/video-analysis/face-record-alert.jpg',
  },
  patrol: {
    alert_type: 'patrol_exception',
    severity: 'medium',
    title: '巡检成果发现路线异常',
    description: '来自巡检成果 Mock 数据：巡检路线出现异常偏离，需要确认设备和现场状态。',
    source_type: 'patrol_result_mock',
    media_path: '/video-analysis/plate-event.jpg',
  },
}

function formatTime(value) {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function WarningResponse() {
  const [alerts, setAlerts] = useState([])
  const [devices, setDevices] = useState([])
  const [severity, setSeverity] = useState('')
  const [status, setStatus] = useState('')
  const [selectedAlert, setSelectedAlert] = useState(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const loadAlerts = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const parameters = new URLSearchParams()
      if (severity) parameters.set('severity', severity)
      if (status) parameters.set('status', status)
      const response = await authFetch(`/api/security-alerts?${parameters}`)
      if (!response.ok) throw new Error('告警数据加载失败')
      const nextAlerts = await response.json()
      setAlerts(nextAlerts)
      setSelectedAlert(current => nextAlerts.find(alert => alert.id === current?.id) || null)
    } catch (requestError) {
      setError(requestError.message || '告警数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [severity, status])

  const loadDevices = useCallback(async () => {
    try {
      const response = await authFetch('/api/devices')
      if (response.ok) setDevices(await response.json())
    } catch {
      setDevices([])
    }
  }, [])

  useEffect(() => {
    loadAlerts()
  }, [loadAlerts])

  useEffect(() => {
    loadDevices()
  }, [loadDevices])

  const summary = useMemo(() => ({
    pending: alerts.filter(alert => alert.status === 'pending').length,
    acknowledged: alerts.filter(alert => alert.status === 'acknowledged').length,
    critical: alerts.filter(alert => alert.severity === 'critical' || alert.severity === 'high').length,
  }), [alerts])

  async function createMockAlert(source) {
    const template = mockSources[source]
    setSubmitting(true)
    setError('')
    try {
      const response = await authFetch('/api/security-alerts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...template,
          device_id: devices[0]?.id ?? null,
          source_id: `${source}-mock-${Date.now()}`,
        }),
      })
      if (!response.ok) throw new Error((await response.json()).detail || 'Mock 告警创建失败')
      const created = await response.json()
      await loadAlerts()
      setSelectedAlert(created)
    } catch (requestError) {
      setError(requestError.message || 'Mock 告警创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  async function updateAlert(action, body = {}) {
    if (!selectedAlert) return
    setSubmitting(true)
    setError('')
    try {
      const response = await authFetch(`/api/security-alerts/${selectedAlert.id}/${action}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!response.ok) throw new Error((await response.json()).detail || '告警处置失败')
      const updated = await response.json()
      setSelectedAlert(updated)
      await loadAlerts()
    } catch (requestError) {
      setError(requestError.message || '告警处置失败')
    } finally {
      setSubmitting(false)
    }
  }

  function assignAlert() {
    const assignee = window.prompt('请输入处理人', selectedAlert?.assignee || '')
    if (assignee?.trim()) updateAlert('assign', { assignee: assignee.trim() })
  }

  function closeAlert() {
    const handlingNote = window.prompt('请输入处理备注（可留空）', selectedAlert?.handling_note || '')
    if (handlingNote !== null) updateAlert('close', { handling_note: handlingNote.trim() })
  }

  return (
    <section className="warning-response-page">
      <header className="wr-header">
        <div>
          <span>SAFETY INCIDENT CENTER</span>
          <h1>安全预警处置</h1>
          <p>集中确认、指派和闭环处置来自巡检成果与视频分析的安全告警。</p>
        </div>
        <div className="wr-mock-actions">
          <button disabled={submitting} onClick={() => createMockAlert('video')}>+ 视频分析 Mock 告警</button>
          <button disabled={submitting} onClick={() => createMockAlert('patrol')}>+ 巡检成果 Mock 告警</button>
        </div>
      </header>

      <div className="wr-summary">
        <article><span>待处置</span><strong>{summary.pending}</strong></article>
        <article><span>处理中</span><strong>{summary.acknowledged}</strong></article>
        <article><span>中高等级</span><strong>{summary.critical}</strong></article>
      </div>

      <div className="wr-toolbar">
        <label>等级<select value={severity} onChange={event => setSeverity(event.target.value)}><option value="">全部等级</option>{Object.entries(severityLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label>状态<select value={status} onChange={event => setStatus(event.target.value)}><option value="">全部状态</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <button className="wr-refresh" onClick={loadAlerts} disabled={loading}>刷新列表</button>
      </div>

      {error && <div className="wr-error">{error}</div>}
      <div className="wr-content">
        <div className="wr-list-panel">
          {loading ? <div className="wr-empty">正在加载告警…</div> : alerts.length === 0 ? <div className="wr-empty">暂无告警。可使用右上角按钮创建两类本地 Mock 告警。</div> : <div className="wr-list">{alerts.map(alert => (
            <button key={alert.id} className={`wr-alert-row ${selectedAlert?.id === alert.id ? 'selected' : ''}`} onClick={() => setSelectedAlert(alert)}>
              <span className={`wr-severity ${alert.severity}`}>{severityLabels[alert.severity] || alert.severity}</span>
              <span className="wr-alert-main"><strong>{alert.title}</strong><small>{alert.device_name || '未关联设备'} · {formatTime(alert.occurred_at)}</small></span>
              <span className={`wr-status ${alert.status}`}>{statusLabels[alert.status] || alert.status}</span>
            </button>
          ))}</div>}
        </div>

        <aside className="wr-drawer">
          {!selectedAlert ? <div className="wr-drawer-empty">选择一条告警查看详情与处置操作</div> : <>
            <div className="wr-drawer-heading"><div><span>ALERT #{selectedAlert.id}</span><h2>{selectedAlert.title}</h2></div><span className={`wr-status ${selectedAlert.status}`}>{statusLabels[selectedAlert.status]}</span></div>
            {selectedAlert.media_path && <img className="wr-media" src={selectedAlert.media_path} alt={selectedAlert.title} />}
            <dl>
              <div><dt>告警类型</dt><dd>{selectedAlert.alert_type}</dd></div>
              <div><dt>等级</dt><dd>{severityLabels[selectedAlert.severity]}</dd></div>
              <div><dt>来源</dt><dd>{selectedAlert.source_type} · {selectedAlert.source_id || '--'}</dd></div>
              <div><dt>来源设备</dt><dd>{selectedAlert.device_name || '未关联设备'}</dd></div>
              <div><dt>发生时间</dt><dd>{formatTime(selectedAlert.occurred_at)}</dd></div>
              <div><dt>处理人</dt><dd>{selectedAlert.assignee || '未指派'}</dd></div>
              <div><dt>处理备注</dt><dd>{selectedAlert.handling_note || '暂无'}</dd></div>
            </dl>
            <p className="wr-description">{selectedAlert.description || '暂无告警描述。'}</p>
            <div className="wr-actions">
              <button disabled={submitting || selectedAlert.status !== 'pending'} onClick={() => updateAlert('acknowledge')}>确认告警</button>
              <button disabled={submitting || selectedAlert.status === 'closed'} onClick={assignAlert}>指派处理</button>
              <button className="close" disabled={submitting || selectedAlert.status === 'closed'} onClick={closeAlert}>关闭告警</button>
            </div>
          </>}
        </aside>
      </div>
    </section>
  )
}

export default WarningResponse
