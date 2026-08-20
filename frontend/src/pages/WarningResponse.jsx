import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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

const sourceLabels = {
  video: '视频分析成果',
  patrol: '巡检成果',
}

const DEFAULT_DEVICE = '__default__'
const UNASSOCIATED_DEVICE = '__unassociated__'

function getInitialAlertForm(source = 'video') {
  const template = mockSources[source]
  return {
    source,
    severity: template.severity,
    title: template.title,
    description: template.description,
    deviceId: DEFAULT_DEVICE,
  }
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
  const [alertForm, setAlertForm] = useState(() => getInitialAlertForm())
  const [severityTouched, setSeverityTouched] = useState(false)
  const [isCreateDrawerOpen, setIsCreateDrawerOpen] = useState(false)
  const latestAlertRequestRef = useRef(0)
  const pendingSelectedAlertIdRef = useRef(null)
  const createAlertTriggerRef = useRef(null)
  const createDrawerRef = useRef(null)
  const submittingRef = useRef(submitting)

  submittingRef.current = submitting

  const loadAlerts = useCallback(async ({ nextSeverity = severity, nextStatus = status, selectedAlertId } = {}) => {
    const requestId = latestAlertRequestRef.current + 1
    const targetAlertId = selectedAlertId ?? pendingSelectedAlertIdRef.current
    latestAlertRequestRef.current = requestId
    setLoading(true)
    setError('')
    try {
      const parameters = new URLSearchParams()
      if (nextSeverity) parameters.set('severity', nextSeverity)
      if (nextStatus) parameters.set('status', nextStatus)
      const response = await authFetch(`/api/security-alerts?${parameters}`)
      if (!response.ok) throw new Error('告警数据加载失败')
      const nextAlerts = await response.json()
      if (requestId !== latestAlertRequestRef.current) return
      setAlerts(nextAlerts)
      setSelectedAlert(current => nextAlerts.find(alert => alert.id === (targetAlertId ?? current?.id)) || null)
      if (targetAlertId !== null && pendingSelectedAlertIdRef.current === targetAlertId) {
        pendingSelectedAlertIdRef.current = null
      }
    } catch (requestError) {
      if (requestId !== latestAlertRequestRef.current) return
      if (targetAlertId !== null && pendingSelectedAlertIdRef.current === targetAlertId) {
        pendingSelectedAlertIdRef.current = null
      }
      setError(requestError.message || '告警数据加载失败')
    } finally {
      if (requestId === latestAlertRequestRef.current) setLoading(false)
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

  function handleAlertSourceChange(event) {
    const source = event.target.value
    const template = mockSources[source]
    setAlertForm(current => ({
      ...current,
      source,
      severity: severityTouched ? current.severity : template.severity,
      title: template.title,
      description: template.description,
    }))
  }

  function openCreateDrawer() {
    createAlertTriggerRef.current = document.activeElement
    setIsCreateDrawerOpen(true)
  }

  function closeCreateDrawer() {
    if (!submitting) setIsCreateDrawerOpen(false)
  }

  useEffect(() => {
    if (!isCreateDrawerOpen) return undefined

    const drawer = createDrawerRef.current
    const focusableSelector = 'a[href], area[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    const getFocusableElements = () => Array.from(drawer?.querySelectorAll(focusableSelector) || []).filter(element => !element.hasAttribute('hidden'))

    getFocusableElements()[0]?.focus()

    function handleDrawerKeyDown(event) {
      if (event.key === 'Escape') {
        if (!submittingRef.current) setIsCreateDrawerOpen(false)
        return
      }

      if (event.key !== 'Tab') return

      const focusableElements = getFocusableElements()
      if (focusableElements.length === 0) {
        event.preventDefault()
        return
      }

      const firstElement = focusableElements[0]
      const lastElement = focusableElements[focusableElements.length - 1]
      if (!drawer?.contains(document.activeElement)) {
        event.preventDefault()
        ;(event.shiftKey ? lastElement : firstElement).focus()
      } else if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault()
        lastElement.focus()
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault()
        firstElement.focus()
      }
    }

    document.addEventListener('keydown', handleDrawerKeyDown)
    return () => {
      document.removeEventListener('keydown', handleDrawerKeyDown)
      createAlertTriggerRef.current?.focus()
    }
  }, [isCreateDrawerOpen])

  async function showOperationResult(alertId) {
    pendingSelectedAlertIdRef.current = alertId
    setSeverity('')
    setStatus('')
    await loadAlerts({ nextSeverity: '', nextStatus: '', selectedAlertId: alertId })
  }

  async function createAlert(event) {
    event.preventDefault()
    const template = mockSources[alertForm.source]
    const title = alertForm.title.trim()
    const description = alertForm.description.trim()

    if (!template) {
      setError('请选择有效的告警信息。')
      return
    }
    if (!severityLabels[alertForm.severity]) {
      setError('请选择有效的告警等级。')
      return
    }
    if (!title) {
      setError('请填写告警标题。')
      return
    }

    const selectedDevice = devices.find(item => String(item.id) === alertForm.deviceId)
    const deviceId = alertForm.deviceId === UNASSOCIATED_DEVICE
      ? null
      : alertForm.deviceId === DEFAULT_DEVICE
        ? devices[0]?.id ?? null
        : selectedDevice?.id ?? null
    setSubmitting(true)
    setError('')
    try {
      const response = await authFetch('/api/security-alerts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          alert_type: template.alert_type,
          severity: alertForm.severity,
          title,
          description,
          device_id: deviceId,
          source_type: template.source_type,
          source_id: `${alertForm.source}-mock-${Date.now()}`,
          media_path: template.media_path,
        }),
      })
      if (!response.ok) throw new Error((await response.json()).detail || '告警创建失败')
      const created = await response.json()
      await showOperationResult(created.id)
      setAlertForm(getInitialAlertForm())
      setSeverityTouched(false)
      setIsCreateDrawerOpen(false)
    } catch (requestError) {
      setError(requestError.message || '告警创建失败')
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
      await showOperationResult(updated.id)
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
        <div className="wr-header-copy">
          <span className="wr-eyebrow">SAFETY INCIDENT CENTER</span>
          <h1>安全预警处置</h1>
          <p>聚焦待处置队列、告警详情与闭环操作，统一查看来自巡检成果和视频分析的安全事件。</p>
        </div>
        <div className="wr-header-actions">
          <button className="wr-secondary-button" type="button" onClick={loadAlerts} disabled={loading} aria-label="刷新告警列表">{loading ? '刷新中…' : '刷新列表'}</button>
          <button className="wr-primary-button" type="button" onClick={openCreateDrawer} aria-label="打开新增告警抽屉">新增告警</button>
        </div>
      </header>

      <div className="wr-summary" aria-label="告警态势概览">
        <article className="wr-summary-card pending"><span>待处置</span><strong>{summary.pending}</strong><small>需优先确认与分派</small></article>
        <article className="wr-summary-card processing"><span>处理中</span><strong>{summary.acknowledged}</strong><small>已确认，等待闭环</small></article>
        <article className="wr-summary-card elevated"><span>中高等级</span><strong>{summary.critical}</strong><small>高与紧急事件</small></article>
      </div>

      <div className="wr-toolbar" aria-label="告警筛选工具栏">
        <div className="wr-toolbar-filters">
          <label>等级<select value={severity} onChange={event => setSeverity(event.target.value)}><option value="">全部等级</option>{Object.entries(severityLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label>状态<select value={status} onChange={event => setStatus(event.target.value)}><option value="">全部状态</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        </div>
        <span className="wr-toolbar-note">筛选结果随条件自动更新</span>
      </div>

      {error && <div className="wr-error" role="alert">{error}</div>}

      <div className="wr-content">
        <section className="wr-list-panel" aria-label="告警队列">
          <div className="wr-panel-heading"><div><span className="wr-eyebrow">INCIDENT QUEUE</span><h2>告警队列</h2></div><strong>{alerts.length}<small> 条</small></strong></div>
          {loading ? <div className="wr-empty">正在加载告警…</div> : alerts.length === 0 ? <div className="wr-empty">暂无符合条件的告警。可通过右上角“新增告警”创建本地 Mock 告警。</div> : <div className="wr-list">{alerts.map(alert => (
            <button key={alert.id} type="button" className={`wr-alert-row ${selectedAlert?.id === alert.id ? 'selected' : ''}`} onClick={() => setSelectedAlert(alert)} aria-pressed={selectedAlert?.id === alert.id}>
              <span className={`wr-severity ${alert.severity}`}>{severityLabels[alert.severity] || alert.severity}</span>
              <span className="wr-alert-main"><strong>{alert.title}</strong><small>{alert.device_name || '未关联设备'}</small><time>{formatTime(alert.occurred_at)}</time></span>
              <span className={`wr-status ${alert.status}`}>{statusLabels[alert.status] || alert.status}</span>
            </button>
          ))}</div>}
        </section>

        <aside className="wr-detail-panel" aria-label="告警详情与处置">
          {!selectedAlert ? <div className="wr-drawer-empty">从左侧队列选择一条告警，查看完整信息并执行处置操作。</div> : <>
            <div className="wr-detail-heading"><div><span className="wr-eyebrow">ALERT #{selectedAlert.id}</span><h2>{selectedAlert.title}</h2></div><span className={`wr-status ${selectedAlert.status}`}>{statusLabels[selectedAlert.status] || selectedAlert.status}</span></div>
            <section className="wr-detail-section"><h3>事件摘要</h3><p className="wr-description">{selectedAlert.description || '暂无告警描述。'}</p></section>
            {selectedAlert.media_path && <section className="wr-detail-section"><h3>关联媒体</h3><img className="wr-media" src={selectedAlert.media_path} alt={selectedAlert.title} /></section>}
            <section className="wr-detail-section"><h3>事件属性</h3><dl><div><dt>告警类型</dt><dd>{selectedAlert.alert_type}</dd></div><div><dt>告警等级</dt><dd>{severityLabels[selectedAlert.severity] || selectedAlert.severity}</dd></div><div><dt>来源信息</dt><dd>{selectedAlert.source_type} · {selectedAlert.source_id || '--'}</dd></div><div><dt>来源设备</dt><dd>{selectedAlert.device_name || '未关联设备'}</dd></div><div><dt>发生时间</dt><dd>{formatTime(selectedAlert.occurred_at)}</dd></div></dl></section>
            <section className="wr-detail-section"><h3>处置记录</h3><dl><div><dt>当前状态</dt><dd>{statusLabels[selectedAlert.status] || selectedAlert.status}</dd></div><div><dt>处理人</dt><dd>{selectedAlert.assignee || '未指派'}</dd></div><div><dt>处理备注</dt><dd>{selectedAlert.handling_note || '暂无'}</dd></div></dl>{selectedAlert.status === 'closed' && <p className="wr-closed-note">该告警已完成闭环，不再提供可执行的处置操作。</p>}</section>
            {selectedAlert.status !== 'closed' && <section className="wr-detail-section wr-action-section"><h3>处置操作</h3><div className="wr-actions"><button type="button" disabled={submitting || selectedAlert.status !== 'pending'} onClick={() => updateAlert('acknowledge')}>确认告警</button><button type="button" disabled={submitting} onClick={assignAlert}>指派处理</button><button className="close" type="button" disabled={submitting} onClick={closeAlert}>关闭告警</button></div></section>}
          </>}
        </aside>
      </div>

      {isCreateDrawerOpen && <div className="wr-create-layer" role="presentation">
        <button className="wr-create-backdrop" type="button" onClick={closeCreateDrawer} disabled={submitting} aria-label="关闭新增告警抽屉" />
        <aside ref={createDrawerRef} className="wr-create-drawer" role="dialog" aria-modal="true" aria-label="新增告警">
          <div className="wr-create-heading"><div><span className="wr-eyebrow">CREATE INCIDENT</span><h2>新增告警</h2><p>创建本地 Mock 告警并立即加入当前队列。</p></div><button className="wr-icon-button" type="button" onClick={closeCreateDrawer} disabled={submitting} aria-label="关闭新增告警抽屉">×</button></div>
          <form className="wr-alert-form" onSubmit={createAlert}><div className="wr-form-fields">
            <label>告警来源<select value={alertForm.source} onChange={handleAlertSourceChange} disabled={submitting}>{Object.entries(sourceLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label>告警等级<select value={alertForm.severity} onChange={event => { setAlertForm(current => ({ ...current, severity: event.target.value })); setSeverityTouched(true) }} disabled={submitting}>{Object.entries(severityLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label>来源设备<select value={alertForm.deviceId} onChange={event => setAlertForm(current => ({ ...current, deviceId: event.target.value }))} disabled={submitting}><option value={DEFAULT_DEVICE}>默认设备（{devices[0]?.name || devices[0]?.device_name || '当前无设备'}）</option><option value={UNASSOCIATED_DEVICE}>未关联</option>{devices.map(device => <option key={device.id} value={device.id}>{device.name || device.device_name || `设备 #${device.id}`}</option>)}</select></label>
            <label className="wr-form-wide">告警标题<input value={alertForm.title} onChange={event => setAlertForm(current => ({ ...current, title: event.target.value }))} disabled={submitting} required /></label>
            <label className="wr-form-wide">告警描述<textarea value={alertForm.description} onChange={event => setAlertForm(current => ({ ...current, description: event.target.value }))} disabled={submitting} rows="4" /></label>
          </div><div className="wr-form-actions"><button className="wr-secondary-button" type="button" onClick={closeCreateDrawer} disabled={submitting}>取消</button><button className="wr-primary-button" type="submit" disabled={submitting}>{submitting ? '创建中…' : '创建告警'}</button></div></form>
        </aside>
      </div>}
    </section>
  )
}

export default WarningResponse
