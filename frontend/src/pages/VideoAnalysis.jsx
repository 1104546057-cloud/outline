import { useEffect, useRef, useState } from 'react'
import ThemedSelect from '../components/ThemedSelect'
import { authFetch } from '../utils/authFetch'
import '../styles/VideoAnalysis.css'

const IMAGE_BASE = '/video-analysis'

const tabs = [
  { key: 'overview', label: '实时识别看板' },
  { key: 'records', label: '识别记录' },
  { key: 'faces', label: '人员库' },
  { key: 'plates', label: '车牌库' },
]

const faceLibrary = [
  { id: 'EMP-23331148', name: '董祖豪', type: '教职工', department: '软件工程学院', phone: '138****1128', images: 6, updatedAt: '2026-06-20', image: `${IMAGE_BASE}/face-library-xie-tao.jpg` },
  { id: 'STU-20240218', name: '杨惠兰', type: '学生', department: '人工智能学院', phone: '136****2190', images: 4, updatedAt: '2026-06-18', image: `${IMAGE_BASE}/face-library-lin-yu.jpg` },
  { id: 'VIS-20260612', name: '访客 A-107', type: '访客', department: '访客中心', phone: '139****7710', images: 3, updatedAt: '2026-06-12', image: `${IMAGE_BASE}/face-library-visitor-a107.jpg` },
  { id: 'KEY-000028', name: '重点人员 028', type: '重点关注', department: '安保处', phone: '--', images: 8, updatedAt: '2026-06-10', image: `${IMAGE_BASE}/face-library-key-028.jpg` },
]

const plateLibrary = [
  { plate: '粤C·223E2', owner: '访客车辆', type: '临时授权', color: '白色', expireAt: '2026-06-30', status: '有效' },
  { plate: '粤C·1783H', owner: '后勤车辆', type: '校内车辆', color: '蓝色', expireAt: '2027-01-01', status: '有效' },
  { plate: '粤A·M12R0', owner: '工程车辆', type: '施工车辆', color: '黑色', expireAt: '2026-07-15', status: '有效' },
  { plate: '粤B·F806L', owner: '访客车辆', type: '临时授权', color: '银色', expireAt: '2026-06-25', status: '过期' },
]

function Icon({ name, size = 18 }) {
  const paths = {
    scan: <><path d="M4 7V4h3M17 4h3v3M20 17v3h-3M7 20H4v-3" /><path d="M7 12h10" /><path d="M10 9h4v6h-4z" /></>,
    face: <><circle cx="12" cy="9" r="4" /><path d="M5 21a7 7 0 0 1 14 0" /></>,
    plate: <><rect x="3" y="7" width="18" height="10" rx="2" /><path d="M7 11h2M12 11h5M7 14h10" /></>,
    route: <><circle cx="5" cy="6" r="2" /><circle cx="19" cy="18" r="2" /><path d="M7 6h4a3 3 0 0 1 0 6H9a3 3 0 0 0 0 6h8" /></>,
    database: <><ellipse cx="12" cy="5" rx="7" ry="3" /><path d="M5 5v7c0 1.7 3.1 3 7 3s7-1.3 7-3V5" /><path d="M5 12v7c0 1.7 3.1 3 7 3s7-1.3 7-3v-7" /></>,
    search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
    upload: <><path d="M12 16V4" /><path d="m7 9 5-5 5 5" /><path d="M5 20h14" /></>,
    camera: <><path d="M4 8h4l2-3h4l2 3h4v11H4z" /><circle cx="12" cy="13" r="3.5" /></>,
    link: <><path d="M10 13a5 5 0 0 0 7.1 0l2-2a5 5 0 0 0-7.1-7.1l-1.1 1.1" /><path d="M14 11a5 5 0 0 0-7.1 0l-2 2A5 5 0 0 0 12 20.1l1.1-1.1" /></>,
    alert: <><path d="M12 3 22 20H2L12 3Z" /><path d="M12 9v5M12 17h.01" /></>,
  }

  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {paths[name] || paths.scan}
    </svg>
  )
}

function StatusPill({ children, tone = 'normal' }) {
  return <span className={`va-pill ${tone}`}>{children}</span>
}

function MetricCard({ icon, label, value, unit, tone }) {
  return (
    <article className={`va-metric ${tone || ''}`}>
      <span className="va-metric-icon"><Icon name={icon} /></span>
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
        {unit ? <em>{unit}</em> : null}
      </div>
    </article>
  )
}

function confidencePct(value) {
  const number = Number(value) || 0
  return Math.round(number <= 1 ? number * 100 : number)
}

function DetectionOverlay({ detections, width, height, activeId, onSelect, stale }) {
  if (!detections?.length || !width || !height) return null
  return (
    <svg className={`va-detect-overlay ${stale ? 'stale' : ''}`} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet" aria-label={stale ? `历史识别 ${detections.length} 个目标` : `当前识别到 ${detections.length} 个目标`}>
      {detections.map((detection, index) => {
        const box = detection.bbox || {}
        const x = Math.max(0, Number(box.x) || 0)
        const y = Math.max(0, Number(box.y) || 0)
        const boxWidth = Math.max(0, Number(box.width) || 0)
        const boxHeight = Math.max(0, Number(box.height) || 0)
        const id = `${detection.label || 'target'}-${index}`
        const label = `${detection.label || '目标'} ${confidencePct(detection.confidence)}%`
        return (
          <g key={id} className={id === activeId ? 'active' : ''} onClick={() => onSelect(id)}>
            <rect className="va-detect-rect" x={x} y={y} width={boxWidth} height={boxHeight} />
            <rect className="va-detect-label-bg" x={x} y={Math.max(0, y - 28)} width={Math.max(120, label.length * 9)} height="26" />
            <text className="va-detect-label" x={x + 8} y={Math.max(18, y - 10)}>{label}</text>
          </g>
        )
      })}
    </svg>
  )
}

function isDeviceLive(device) {
  return device?.status === 'online' || device?.media_connected
}

function formatResultTime(value) {
  if (!value) return '--'
  const date = typeof value === 'number' ? new Date(value * (value < 1e12 ? 1000 : 1)) : new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  return date.toLocaleString('zh-CN', { hour12: false })
}

function inferenceLabel(inference, busy) {
  if (busy) return '处理中…'
  if (inference?.stopped || inference?.enabled === false) return '推理已停止'
  if (inference?.live || inference?.online) return '推理在线'
  if (inference?.enabled) return '推理启动中'
  return '推理离线'
}

function pickGunDeviceId(devices) {
  const withMedia = devices.find(device => device.media_connected)
  if (withMedia) return withMedia.id
  const online = devices.find(device => device.status === 'online')
  if (online) return online.id
  const preferred = devices.find(device => device.id === 2)
  return preferred?.id || devices[0]?.id || 2
}

function OverviewPane() {
  const [status, setStatus] = useState(null)
  const [detectionData, setDetectionData] = useState({ detections: [] })
  const [activeId, setActiveId] = useState('')
  const [error, setError] = useState('')
  const [previewUrl, setPreviewUrl] = useState('')
  const [previewSize, setPreviewSize] = useState({ width: 1280, height: 720 })
  const [gunCameraStatus, setGunCameraStatus] = useState('loading')
  const [inferenceBusy, setInferenceBusy] = useState(false)
  const [devices, setDevices] = useState([])
  const [gunDeviceId, setGunDeviceId] = useState(2)
  const [streamNonce, setStreamNonce] = useState(0)
  const fileRef = useRef(null)
  const pickedDeviceRef = useRef(false)

  const cameraConfigured = Boolean(status?.device?.configured || status?.camera?.configured)
  const detections = Array.isArray(detectionData?.detections) ? detectionData.detections : []
  const inference = status?.inference || {}
  const inferenceLive = Boolean(inference.enabled && (inference.live || inference.online) && !inference.stopped)
  const detectionsStale = Boolean(!inferenceLive && detections.length)
  const lastResultAt = status?.last_result?.updated_at || detectionData?.last_detection_time || detectionData?.updated_at
  const lastLatency = status?.last_result?.latency_ms || detectionData?.latency_ms || detectionData?.detector?.latency_ms
  const activeIndex = Math.max(0, detections.findIndex((item, index) => `${item.label || 'target'}-${index}` === activeId))
  const active = detections[activeIndex] || detections[0]
  const selectedDevice = devices.find(device => device.id === gunDeviceId)
  const selectedLive = isDeviceLive(selectedDevice)
  const streamUrl = previewUrl || (selectedLive || devices.length === 0
    ? `/api/devices/${gunDeviceId}/camera/stream?view=gun&retry=${streamNonce}`
    : '')

  const selectDevice = deviceId => {
    if (deviceId === gunDeviceId && !previewUrl) return
    pickedDeviceRef.current = true
    setGunDeviceId(deviceId)
    setGunCameraStatus('loading')
    setPreviewUrl('')
    setStreamNonce(value => value + 1)
  }

  useEffect(() => {
    let cancelled = false
    const refreshDevices = async () => {
      try {
        const response = await authFetch('/api/devices', { cache: 'no-store' })
        const payload = await response.json()
        if (!response.ok || !Array.isArray(payload) || cancelled) return
        setDevices(payload)
        setGunDeviceId(current => {
          if (pickedDeviceRef.current && payload.some(device => device.id === current)) return current
          const next = pickGunDeviceId(payload)
          pickedDeviceRef.current = true
          return next
        })
      } catch {
        /* keep last device list */
      }
    }
    refreshDevices()
    const timer = window.setInterval(refreshDevices, 10000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    let timer
    const refresh = async () => {
      try {
        const query = `device_id=${encodeURIComponent(gunDeviceId)}`
        const [statusRes, detectRes] = await Promise.all([
          authFetch(`/api/recognition/status?${query}`, { cache: 'no-store' }),
          authFetch(`/api/recognition/detections?${query}`, { cache: 'no-store' }),
        ])
        const [statusPayload, detectPayload] = await Promise.all([statusRes.json(), detectRes.json()])
        if (!statusRes.ok) throw new Error(statusPayload.detail || '识别状态读取失败')
        if (!detectRes.ok) throw new Error(detectPayload.detail || '识别结果读取失败')
        if (!cancelled) {
          setStatus(statusPayload)
          setDetectionData(detectPayload)
          setError('')
        }
      } catch (requestError) {
        if (!cancelled) setError(requestError.message)
      } finally {
        if (!cancelled) timer = window.setTimeout(refresh, 1500)
      }
    }
    refresh()
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [gunDeviceId])

  const handleTestImage = async event => {
    const file = event.target.files?.[0]
    if (!file) return
    const buffer = await file.arrayBuffer()
    const bytes = new Uint8Array(buffer)
    let binary = ''
    bytes.forEach(value => { binary += String.fromCharCode(value) })
    const imageB64 = btoa(binary)
    setPreviewUrl(URL.createObjectURL(file))
    const response = await authFetch('/api/recognition/detect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_b64: imageB64 }),
    })
    const payload = await response.json()
    if (!response.ok) {
      setError(payload.detail || '推理失败')
      return
    }
    setDetectionData(payload)
    setError('')
  }

  const handleInferenceToggle = async () => {
    if (!selectedDevice?.id || inferenceBusy) return
    const enabled = !inferenceLive && !inference.enabled
    setInferenceBusy(true)
    try {
      const response = await authFetch('/api/recognition/inference', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robotId: selectedDevice.id, enabled }),
      })
      const payload = await response.json()
      if (!response.ok) {
        const detail = typeof payload.detail === 'string' ? payload.detail : '推理开关操作失败'
        throw new Error(detail)
      }
      const nextInference = {
        ...(status?.inference || {}),
        ...(payload.response || {}),
        enabled: Boolean(payload.enabled),
        live: Boolean(payload.enabled),
        online: Boolean(payload.enabled && (payload.response?.gpu_ready || payload.response?.ready)),
        stale: !payload.enabled,
        stopped: !payload.enabled,
        message: payload.enabled ? '推理在线' : '推理已停止',
      }
      setStatus(current => ({
        ...current,
        inference: nextInference,
        last_result: {
          ...(current?.last_result || {}),
          live: Boolean(payload.enabled),
          stale: !payload.enabled,
        },
      }))
      if (!payload.enabled) {
        setDetectionData(current => ({ ...current, live: false, stale: true }))
      }
      setError('')
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setInferenceBusy(false)
    }
  }

  return (
    <div className="va-overview">
      <aside className="va-target-panel">
        <div className="va-panel-head">
          <div>
            <span>CAMERA SOURCES</span>
            <h2>设备画面</h2>
          </div>
          <StatusPill tone={devices.some(isDeviceLive) ? 'success' : 'warning'}>
            {devices.filter(isDeviceLive).length}/{devices.length || 0}
          </StatusPill>
        </div>
        <div className="va-device-list">
          {devices.length ? devices.map(device => {
            const live = isDeviceLive(device)
            return (
              <button
                type="button"
                key={device.id}
                className={`va-device-item ${device.id === gunDeviceId ? 'active' : ''} ${live ? 'live' : 'offline'}`}
                onClick={() => selectDevice(device.id)}
              >
                <span className={`va-live-dot ${live ? '' : 'off'}`} />
                <span className="va-target-main">
                  <strong>{device.name}</strong>
                  <small>{live ? (device.media_connected ? '枪机在线' : '设备在线') : '设备离线'}</small>
                </span>
                <span className={`va-device-tag ${live ? 'live' : ''}`}>{live ? 'LIVE' : 'OFF'}</span>
              </button>
            )
          }) : <p className="va-empty">正在读取设备列表…</p>}
        </div>
        <div className="va-panel-head va-panel-head-sub">
          <div>
            <span>TRACK TARGETS</span>
            <h2>目标列表</h2>
          </div>
          <StatusPill tone={detectionsStale ? 'warning' : detections.length ? 'success' : 'warning'}>
            {detectionsStale ? `历史 ${detections.length}` : `${detections.length} 个`}
          </StatusPill>
        </div>
        <div className="va-target-list">
          {detections.length ? detections.map((detection, index) => {
            const id = `${detection.label || 'target'}-${index}`
            return (
              <button type="button" key={id} className={`va-target-item ${id === (activeId || `${active?.label || 'target'}-0`) ? 'active' : ''}`} onClick={() => setActiveId(id)}>
                <span className="va-target-avatar"><Icon name="scan" size={20} /></span>
                <span className="va-target-main">
                  <strong>{detection.label || '目标'}</strong>
                  <small>{detectionsStale ? '历史结果 · dai' : 'YOLO · dai'}</small>
                </span>
                <span className="va-target-score">{confidencePct(detection.confidence)}%</span>
              </button>
            )
          }) : <p className="va-empty">等待检测结果。可先在上方选择在线车辆查看枪机，或上传照片测试推理。</p>}
        </div>
      </aside>

      <section className="va-monitor-panel">
        <div className="va-panel-head">
          <div>
            <span>LIVE RECOGNITION</span>
            <h2>视频目标识别</h2>
          </div>
          <div className="va-inference-actions">
            <StatusPill tone={selectedLive && gunCameraStatus === 'streaming' ? 'success' : selectedLive ? 'warning' : 'danger'}>
              {selectedLive && gunCameraStatus === 'streaming' ? '枪机在线' : selectedLive ? '枪机连接中' : '枪机离线'}
            </StatusPill>
            <StatusPill tone={inferenceLive ? 'success' : inference.enabled ? 'warning' : 'danger'}>
              {inferenceLabel(inference, inferenceBusy)}
            </StatusPill>
            <button
              type="button"
              className="va-inference-toggle"
              disabled={!selectedDevice || !selectedLive || inferenceBusy}
              onClick={handleInferenceToggle}
            >
              {inferenceBusy ? '处理中…' : inference.enabled || inferenceLive ? '停止推理' : '开始推理'}
            </button>
          </div>
        </div>
        <div className="va-video-stage">
          {streamUrl ? (
            <img
              key={streamUrl}
              src={streamUrl}
              alt={`${selectedDevice?.name || '巡检车'}枪式摄像头画面`}
              onLoad={event => {
                setGunCameraStatus('streaming')
                setPreviewSize({ width: event.target.naturalWidth || 1280, height: event.target.naturalHeight || 720 })
              }}
              onError={() => setGunCameraStatus('error')}
            />
          ) : (
            <div className="va-video-placeholder">
              <Icon name="camera" size={36} />
              <strong>{selectedDevice ? `${selectedDevice.name} 当前离线` : '请选择一台巡检车'}</strong>
              <small>左侧列表按车分别显示枪机画面，不会混到同一路。</small>
            </div>
          )}
          <DetectionOverlay
            detections={detections}
            width={previewSize.width}
            height={previewSize.height}
            activeId={activeId}
            onSelect={setActiveId}
            stale={detectionsStale}
          />
          <div className="va-video-topbar">
            <span>华为枪式摄像头 · {selectedDevice?.name || '未选择设备'}</span>
            <strong>{selectedLive ? '当前画面' : '等待上线'}</strong>
          </div>
          <div className="va-video-bottom">
            <span className={`va-live-dot ${selectedLive && gunCameraStatus === 'streaming' ? '' : 'off'}`} />
            <span>摄像头 {gunCameraStatus === 'streaming' ? '已连接' : gunCameraStatus === 'error' ? '连接失败' : selectedLive ? '连接中' : '未接入'}</span>
            <span>{detectionsStale ? '历史目标' : '目标'} {detections.length}</span>
            <span>{error || inference.message || inferenceLabel(inference, inferenceBusy)}</span>
          </div>
        </div>
        <div className="va-track-strip">
          <label className="va-test-upload">
            <Icon name="upload" size={16} />
            上传照片测试推理
            <input ref={fileRef} type="file" accept="image/jpeg,image/png" onChange={handleTestImage} />
          </label>
        </div>
      </section>

      <aside className="va-detail-panel">
        <div className="va-panel-head">
          <div>
            <span>TARGET DETAIL</span>
            <h2>目标详情</h2>
          </div>
          <StatusPill tone={gunCameraStatus === 'streaming' ? 'success' : 'warning'}>
            {gunCameraStatus === 'streaming' ? '枪机在线' : '枪机连接中'}
          </StatusPill>
        </div>
        <div className="va-person-card">
          <span className="va-person-avatar"><Icon name="scan" size={34} /></span>
          <div>
            <h3>{active?.label || '暂无目标'}</h3>
            <p>{status?.inference?.detection?.model_path?.split('/')?.pop() || 'YOLOv5'}</p>
          </div>
        </div>
        <dl className="va-detail-list">
        <div><dt>枪机状态</dt><dd>{selectedLive && gunCameraStatus === 'streaming' ? '在线' : selectedLive ? '连接中' : '离线'}</dd></div>
        <div><dt>推理服务</dt><dd>{inferenceLabel(inference, inferenceBusy)}</dd></div>
        <div><dt>最近识别</dt><dd>{active ? `${active.label || '目标'} ${confidencePct(active.confidence)}%${detectionsStale ? '（缓存）' : ''}` : '暂无'}</dd></div>
        <div><dt>结果时间</dt><dd>{formatResultTime(lastResultAt)}</dd></div>
        <div><dt>推理延迟</dt><dd>{lastLatency != null ? `${lastLatency} ms` : '--'}</dd></div>
        <div><dt>推理节点</dt><dd>dai / 10.139.91.78:9100</dd></div>
          <div><dt>ZeroTier</dt><dd>10.139.91.78 / 10.139.91.240</dd></div>
          <div><dt>检测框</dt><dd>{active?.bbox ? `${Math.round(active.bbox.x || 0)},${Math.round(active.bbox.y || 0)} ${Math.round(active.bbox.width || 0)}×${Math.round(active.bbox.height || 0)}` : '--'}</dd></div>
          <div><dt>画面来源</dt><dd>{detectionData?.source || (cameraConfigured ? 'camera' : '未接入')}</dd></div>
        </dl>
      </aside>

      <section className="va-flow-panel">
        {['专用摄像头', '抽帧/推流', 'dai YOLO 推理', '目标框回传', '事件入库', '预警联动'].map((step, index) => (
          <div key={step} className={index === 2 && inferenceLive ? 'ready' : index < 2 ? 'pending' : ''}>
            <span>{String(index + 1).padStart(2, '0')}</span>
            <strong>{step}</strong>
          </div>
        ))}
      </section>
    </div>
  )
}

function recordImageSrc(image) {
  if (!image) return ''
  if (image.startsWith('/') || image.startsWith('http')) return image
  return `/api/patrol-results/media/${image.split('/').map(encodeURIComponent).join('/')}`
}

function RecordRow({ record, selected, onSelect }) {
  const image = recordImageSrc(record.image)
  return (
    <button type="button" className={`va-record-row ${selected ? 'active' : ''}`} onClick={() => onSelect(record.id)}>
      <span>
        {image ? <img src={image} alt={record.title} /> : <span className="va-record-thumb"><Icon name="scan" /></span>}
        <span>
          <strong>{record.subject}</strong>
          <small>{record.title}</small>
        </span>
      </span>
      <em>{record.device}</em>
      <b>{record.confidence}%</b>
      <StatusPill tone={String(record.status || '').includes('待') ? 'warning' : 'success'}>{record.status}</StatusPill>
    </button>
  )
}

function RecordsPane() {
  const [records, setRecords] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [deviceId, setDeviceId] = useState('')
  const [since, setSince] = useState('')

  useEffect(() => {
    let cancelled = false
    const params = new URLSearchParams({ limit: '50' })
    if (deviceId.trim()) params.set('device_id', deviceId.trim())
    if (since.trim()) params.set('since', since.trim().replace('T', ' '))
    authFetch(`/api/recognition/results?${params}`, { cache: 'no-store' })
      .then(response => response.json())
      .then(payload => {
        if (cancelled) return
        const next = payload.results || []
        setRecords(next)
        setSelectedId(current => current || next[0]?.id || '')
      })
      .catch(() => {
        if (!cancelled) setRecords([])
      })
    return () => { cancelled = true }
  }, [deviceId, since])

  const selectedRecord = records.find(record => record.id === selectedId) || records[0]
  const selectedImage = recordImageSrc(selectedRecord?.image)

  return (
    <section className="va-records">
      <div className="va-filter-bar">
        <div className="va-filter-group">
          <ThemedSelect className="va-select" value="target" onChange={() => {}}>
            <option value="target">目标识别</option>
          </ThemedSelect>
          <input
            type="text"
            placeholder="设备ID"
            value={deviceId}
            onChange={event => setDeviceId(event.target.value)}
            aria-label="按设备ID查询"
          />
          <input
            type="datetime-local"
            value={since}
            onChange={event => setSince(event.target.value)}
            aria-label="按识别时间查询"
          />
        </div>
      </div>
      <div className="va-record-grid">
        <div className="va-record-table">
          <div className="va-table-head">
            <span>抓拍对象</span>
            <span>设备来源</span>
            <span>置信度</span>
            <span>状态</span>
          </div>
          <div className="va-record-list">
            {records.length ? records.map(record => (
              <RecordRow key={record.id} record={record} selected={selectedRecord?.id === record.id} onSelect={setSelectedId} />
            )) : <p className="va-empty">还没有识别记录。摄像头接入或上传测试图后会写到这里。</p>}
          </div>
        </div>
        {selectedRecord ? (
          <aside className="va-record-detail">
            <div className="va-panel-head">
              <div>
                <span>EVENT DETAIL</span>
                <h2>事件详情</h2>
              </div>
              <StatusPill tone="success">目标</StatusPill>
            </div>
            {selectedImage ? <img src={selectedImage} alt={selectedRecord.title} /> : null}
            <h3>{selectedRecord.subject}</h3>
            <dl>
              <div><dt>事件编号</dt><dd>{selectedRecord.id}</dd></div>
              <div><dt>识别类型</dt><dd>{selectedRecord.identity}</dd></div>
              <div><dt>采集时间</dt><dd>{selectedRecord.time}</dd></div>
              <div><dt>来源设备</dt><dd>{selectedRecord.device}</dd></div>
              <div><dt>设备ID</dt><dd>{selectedRecord.device_id || '--'}</dd></div>
              <div><dt>检测框</dt><dd>{selectedRecord.bbox ? JSON.stringify(selectedRecord.bbox) : '--'}</dd></div>
              <div><dt>推理延迟</dt><dd>{selectedRecord.latency_ms != null ? `${selectedRecord.latency_ms} ms` : '--'}</dd></div>
              <div><dt>摘要</dt><dd>{selectedRecord.detail}</dd></div>
            </dl>
          </aside>
        ) : null}
      </div>
    </section>
  )
}

function FacesPane() {
  const [mode, setMode] = useState('single')

  return (
    <section className="va-library va-face-library">
      <div className="va-library-main">
        <div className="va-filter-bar compact">
          <div className="va-filter-group">
            <ThemedSelect className="va-select" defaultValue="all">
              <option value="all">全部录入类型</option>
              <option value="staff">教职工</option>
              <option value="student">学生</option>
              <option value="visitor">访客</option>
              <option value="key">重点关注</option>
            </ThemedSelect>
            <input type="text" value="智慧校园公司" readOnly aria-label="公司" />
            <input type="text" placeholder="姓名 / 人员编号" aria-label="姓名或人员编号" />
          </div>
          <button type="button" className="va-primary-btn"><Icon name="search" />检索</button>
        </div>
        <div className="va-face-grid">
          {faceLibrary.map(person => (
            <article key={person.id} className={person.type === '重点关注' ? 'danger' : ''}>
              <img src={person.image} alt={person.name} />
              <div>
                <h3>{person.name}</h3>
                <p>{person.id}</p>
                <span>{person.type}</span>
              </div>
              <dl>
                <div><dt>部门</dt><dd>{person.department}</dd></div>
                <div><dt>样本</dt><dd>{person.images} 张</dd></div>
                <div><dt>更新</dt><dd>{person.updatedAt}</dd></div>
              </dl>
            </article>
          ))}
        </div>
      </div>
      <aside className="va-enroll-panel">
        <div className="va-panel-head">
          <div>
            <span>FACE ENROLLMENT</span>
            <h2>人脸录入</h2>
          </div>
        </div>
        <div className="va-mode-switch">
          <button type="button" className={mode === 'single' ? 'active' : ''} onClick={() => setMode('single')}>单张录入</button>
          <button type="button" className={mode === 'batch' ? 'active' : ''} onClick={() => setMode('batch')}>批量录入</button>
        </div>
        {mode === 'single' ? (
          <div className="va-enroll-form">
            <label><span>姓名</span><input type="text" value="新录入人员" readOnly /></label>
            <label><span>录入类型</span><input type="text" value="访客" readOnly /></label>
            <label><span>联系电话</span><input type="text" value="138****0000" readOnly /></label>
            <div className="va-upload-zone"><Icon name="camera" size={28} /><strong>拍照 / 上传图片</strong><small>最多 10 张人脸样本</small></div>
          </div>
        ) : (
          <div className="va-batch-box">
            <div><Icon name="upload" size={28} /><strong>上传 Excel</strong><small>人员信息表</small></div>
            <div><Icon name="upload" size={28} /><strong>上传 Zip</strong><small>人脸照片包</small></div>
          </div>
        )}
        <button type="button" className="va-primary-btn wide">保存到人员库</button>
      </aside>
    </section>
  )
}

function PlatesPane() {
  return (
    <section className="va-library va-plate-library">
      <div className="va-library-main">
        <div className="va-filter-bar compact">
          <div className="va-filter-group">
            <input type="text" placeholder="车牌号码" aria-label="车牌号码" />
            <ThemedSelect className="va-select" defaultValue="all">
              <option value="all">全部车辆类型</option>
              <option value="campus">校内车辆</option>
              <option value="visitor">访客车辆</option>
              <option value="contractor">施工车辆</option>
            </ThemedSelect>
            <input type="text" value="有效期 / 全部" readOnly aria-label="有效期" />
          </div>
          <button type="button" className="va-primary-btn"><Icon name="search" />查询</button>
        </div>
        <div className="va-plate-table">
          <div className="va-plate-head">
            <span>车牌号码</span><span>车主/用途</span><span>类型</span><span>颜色</span><span>有效期</span><span>状态</span>
          </div>
          {plateLibrary.map(row => (
            <div className="va-plate-row" key={row.plate}>
              <strong>{row.plate}</strong>
              <span>{row.owner}</span>
              <span>{row.type}</span>
              <span>{row.color}</span>
              <span>{row.expireAt}</span>
              <StatusPill tone={row.status === '有效' ? 'success' : 'danger'}>{row.status}</StatusPill>
            </div>
          ))}
        </div>
      </div>
      <aside className="va-enroll-panel">
        <div className="va-panel-head">
          <div>
            <span>PLATE ENROLLMENT</span>
            <h2>车牌录入</h2>
          </div>
        </div>
        <img className="va-plate-preview" src={`${IMAGE_BASE}/plate-capture.jpg`} alt="车牌抓拍样例" />
        <div className="va-enroll-form">
          <label><span>车牌号码</span><input type="text" value="粤C·223E2" readOnly /></label>
          <label><span>车辆类型</span><input type="text" value="访客车辆" readOnly /></label>
          <label><span>有效期</span><input type="text" value="2026-06-30" readOnly /></label>
        </div>
        <div className="va-batch-box single">
          <div><Icon name="upload" size={28} /><strong>批量导入模板</strong><small>Excel 车牌名单</small></div>
        </div>
        <button type="button" className="va-primary-btn wide">保存到车牌库</button>
      </aside>
    </section>
  )
}

export default function VideoAnalysis() {
  const [activeTab, setActiveTab] = useState('overview')
  const [summary, setSummary] = useState({ total: 0, pendingReview: 0, successRate: 0 })
  const [liveCount, setLiveCount] = useState(0)

  useEffect(() => {
    let cancelled = false
    const refresh = async () => {
      try {
        const [summaryRes, detectRes] = await Promise.all([
          authFetch('/api/recognition/summary', { cache: 'no-store' }),
          authFetch('/api/recognition/detections', { cache: 'no-store' }),
        ])
        const [summaryPayload, detectPayload] = await Promise.all([summaryRes.json(), detectRes.json()])
        if (cancelled) return
        if (summaryRes.ok) setSummary(summaryPayload)
        if (detectRes.ok) setLiveCount((detectPayload.detections || []).length)
      } catch {
        if (!cancelled) setLiveCount(0)
      }
    }
    refresh()
    const timer = window.setInterval(refresh, 4000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  const pending = summary.pendingReview || 0

  return (
    <div className="video-analysis-page">
      <header className="va-header">
        <div>
          <span className="va-kicker">VIDEO AI ANALYSIS</span>
          <h1>视频识别分析</h1>
          <p>专用识别摄像头 + dai YOLO 推理。车上深度相机不接入这一路。</p>
        </div>
        <div className="va-header-actions">
          <button type="button" onClick={() => setActiveTab('records')}><Icon name="search" />识别记录</button>
        </div>
      </header>

      <section className="va-metrics" aria-label="视频识别统计">
        <MetricCard icon="scan" label="当前目标" value={String(liveCount)} unit="个" tone="track" />
        <MetricCard icon="database" label="已入库事件" value={String(summary.total || 0)} unit="条" tone="face" />
        <MetricCard icon="route" label="识别成功率" value={String(summary.successRate || 0)} unit="%" tone="plate" />
        <MetricCard icon="alert" label="待复核事件" value={String(pending)} unit="条" tone="alert" />
      </section>

      <nav className="va-tabs" aria-label="视频识别分析子页面">
        {tabs.map(tab => (
          <button
            type="button"
            key={tab.key}
            className={activeTab === tab.key ? 'active' : ''}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {activeTab === 'overview' && <OverviewPane />}
      {activeTab === 'records' && <RecordsPane />}
      {activeTab === 'faces' && <FacesPane />}
      {activeTab === 'plates' && <PlatesPane />}
    </div>
  )
}
