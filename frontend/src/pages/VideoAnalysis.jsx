/* eslint-disable react/prop-types */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ThemedSelect from '../components/ThemedSelect'
import { authFetch } from '../utils/authFetch'
import '../styles/VideoAnalysis.css'

const IMAGE_BASE = '/video-analysis'
const POLL_INTERVAL = 10000

const tabs = [
  { key: 'overview', label: '实时识别看板' },
  { key: 'records', label: '识别记录' },
  { key: 'faces', label: '人员库' },
  { key: 'plates', label: '车牌库' },
]

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

const severityTone = {
  low: 'success',
  medium: 'warning',
  high: 'danger',
  critical: 'danger',
}

const statusTone = {
  pending: 'warning',
  acknowledged: 'danger',
  closed: 'success',
}

function isToday(iso) {
  if (!iso) return false
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return false
  const now = new Date()
  return d.getFullYear() === now.getFullYear()
    && d.getMonth() === now.getMonth()
    && d.getDate() === now.getDate()
}

function formatTime(iso) {
  if (!iso) return '--'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return '--'
  }
}

const trackedTargets = [
  {
    id: 'P-028',
    name: '目标人员 028',
    type: '陌生人员',
    status: '跟踪中',
    confidence: 91,
    risk: '高风险',
    camera: '无人车-01',
    lastSeen: '15:10:57',
    speed: '1.2 m/s',
    direction: '135°',
    age: '25-30',
    gender: '男',
    location: '行政楼东侧道路',
    bbox: { left: 58.4, top: 51.7, width: 7.6, height: 36.9 },
    path: ['北门入口', '主干道', '行政楼东侧', '停车场入口'],
  },
  {
    id: 'P-029',
    name: '目标人员 029',
    type: '校内人员',
    status: '稳定跟踪',
    confidence: 86,
    risk: '中风险',
    camera: '无人车-02',
    lastSeen: '15:10:48',
    speed: '0.8 m/s',
    direction: '92°',
    age: '20-25',
    gender: '女',
    location: '停车场入口',
    bbox: { left: 30.8, top: 51.9, width: 7.1, height: 35.3 },
    path: ['操场西侧', '树阵通道', '停车场入口'],
  },
  {
    id: 'P-026',
    name: '目标人员 026',
    type: '访客',
    status: '短时丢失',
    confidence: 78,
    risk: '中风险',
    camera: 'CAM-03',
    lastSeen: '15:09:36',
    speed: '0.5 m/s',
    direction: '61°',
    age: '30-40',
    gender: '男',
    location: '草坪边界',
    bbox: { left: 52.9, top: 36.0, width: 3.2, height: 18.3 },
    path: ['教学楼南侧', '草坪边界'],
  },
  {
    id: 'P-024',
    name: '目标人员 024',
    type: '陌生人员',
    status: '等待复核',
    confidence: 72,
    risk: '低风险',
    camera: 'CAM-02',
    lastSeen: '15:08:52',
    speed: '0.4 m/s',
    direction: '18°',
    age: '未知',
    gender: '未知',
    location: '北门外侧',
    bbox: { left: 77.6, top: 39.2, width: 5.4, height: 22.4 },
    path: ['北门外侧', '保安亭旁'],
  },
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

// 把后端实时 track 映射为与 mock 目标一致的结构，供列表/详情复用展示逻辑
function mapTrackToTarget(track) {
  const confidence = Math.round((track.confidence ?? 0) * 100)
  return {
    id: `T-${track.track_id}`,
    name: `${track.class_name} #${track.track_id}`,
    type: track.class_name,
    status: '跟踪中',
    confidence,
    risk: '低风险',
    camera: '当前设备',
    lastSeen: '实时',
    speed: '--',
    direction: '--',
    age: '--',
    gender: '--',
    location: '--',
    bbox: null,
    path: [],
  }
}

// 无实时目标时的兜底展示对象
const EMPTY_TARGET = {
  id: '--',
  name: '暂无目标',
  type: '--',
  status: '--',
  confidence: 0,
  risk: '低风险',
  camera: '--',
  lastSeen: '--',
  speed: '--',
  direction: '--',
  age: '--',
  gender: '--',
  location: '--',
  bbox: null,
  path: [],
}

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

function MetricCard({ icon, label, value, unit, tone, loading }) {
  return (
    <article className={`va-metric ${tone || ''}`}>
      <span className="va-metric-icon"><Icon name={icon} /></span>
      <div>
        <small>{label}</small>
        <strong>{loading ? '--' : value}</strong>
        <em>{unit}</em>
      </div>
    </article>
  )
}

function DemoBadge() {
  return <span className="va-pill" style={{ background: 'rgba(255,182,74,.16)', color: '#ffe1a4', borderColor: 'rgba(255,182,74,.38)' }}>演示数据</span>
}

function TargetList({ activeId, onSelect, targets, isLive }) {
  const [filter, setFilter] = useState('all')
  const filteredTargets = filter === 'all'
    ? targets
    : targets.filter(t => filter === 'high' ? t.risk.includes('高') : t.risk.includes('中') || t.risk.includes('低'))

  return (
    <aside className="va-target-panel">
      <div className="va-panel-head">
        <div>
          <span>TRACK TARGETS</span>
          <h2>目标列表</h2>
        </div>
        {isLive ? <StatusPill tone="success">实时</StatusPill> : <DemoBadge />}
      </div>
      <div className="va-target-tools">
        <button type="button" className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>全部</button>
        <button type="button" className={filter === 'medium' ? 'active' : ''} onClick={() => setFilter('medium')}>关注</button>
        <button type="button" className={filter === 'high' ? 'active' : ''} onClick={() => setFilter('high')}>告警</button>
      </div>
      <div className="va-target-list">
        {filteredTargets.map(target => (
          <button
            type="button"
            key={target.id}
            className={`va-target-item ${target.id === activeId ? 'active' : ''}`}
            onClick={() => onSelect(target.id)}
          >
            <span className={`va-target-avatar ${target.risk.includes('高') ? 'danger' : target.risk.includes('中') ? 'warning' : ''}`}>
              <Icon name="face" size={20} />
            </span>
            <span className="va-target-main">
              <strong>{target.id}</strong>
              <small>{target.type} · {target.camera}</small>
              <em>{target.location}</em>
            </span>
            <span className="va-target-score">{target.confidence}%</span>
          </button>
        ))}
        {!filteredTargets.length && (
          <div className="va-target-empty">当前筛选条件下暂无目标</div>
        )}
      </div>
    </aside>
  )
}

function TrackingStage({ activePerson, onSelect, devices, selectedDeviceId, onSelectDevice, targets, inferenceStatus }) {
  const onlineDevices = devices.filter(d => d.status === 'online')
  const currentDevice = devices.find(d => String(d.id) === String(selectedDeviceId))
  const cameraLabel = currentDevice ? currentDevice.name : '未选择设备'
  const isInference = Boolean(inferenceStatus?.running)
  const useAnnotated = isInference && Boolean(inferenceStatus?.annotate)
  const streamSrc = selectedDeviceId
    ? (useAnnotated
        ? `/api/inference/${selectedDeviceId}/annotated-stream`
        : `/api/devices/${selectedDeviceId}/camera/stream`)
    : `${IMAGE_BASE}/person-tracking.jpg`

  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  return (
    <section className="va-monitor-panel">
      <div className="va-panel-head">
        <div>
          <span>LIVE RECOGNITION</span>
          <h2>视频目标追踪</h2>
        </div>
        <div className="va-camera-tabs">
          {onlineDevices.length === 0 && (
            <span style={{ color: 'var(--va-muted)', fontSize: 11, padding: '0 8px' }}>暂无在线设备</span>
          )}
          {onlineDevices.slice(0, 4).map(device => (
            <button
              type="button"
              key={device.id}
              className={String(device.id) === String(selectedDeviceId) ? 'active' : ''}
              onClick={() => onSelectDevice(device.id)}
              title={device.name}
            >
              {device.name}
            </button>
          ))}
        </div>
      </div>
      <div className="va-video-stage">
        <img src={streamSrc} alt={selectedDeviceId ? `${cameraLabel} 实时画面` : '人员轨迹跟踪示例'} />
        <div className="va-video-topbar">
          <span>{selectedDeviceId ? `${useAnnotated ? '推理标注画面' : '实时画面'} · ${cameraLabel}` : `演示模式 · ${cameraLabel}`}</span>
          <strong>{now.toLocaleTimeString('zh-CN', { hour12: false })}</strong>
        </div>
        {!isInference && targets.map(target => (
          <button
            type="button"
            key={target.id}
            className={`va-detect-box ${target.id === activePerson.id ? 'active' : ''}`}
            style={{
              left: `${target.bbox.left}%`,
              top: `${target.bbox.top}%`,
              width: `${target.bbox.width}%`,
              height: `${target.bbox.height}%`,
            }}
            onClick={() => onSelect(target.id)}
            title={target.name}
          >
            <span>{target.id}</span>
          </button>
        ))}
        <div className="va-video-bottom">
          <span className="va-live-dot" />
          <span>{selectedDeviceId ? '视频流已接入' : '识别帧率 15 fps'}</span>
          <span>跟踪目标 {targets.length}</span>
          <span>识别状态 {isInference ? '推理进行中' : selectedDeviceId ? '视频流已接入，推理待上线' : '演示中'}</span>
        </div>
      </div>
      <div className="va-track-strip">
        <div className="va-track-route">
          {activePerson.path.map((point, index) => (
            <span key={point} className={index === activePerson.path.length - 1 ? 'current' : ''}>
              <i>{index + 1}</i>{point}
            </span>
          ))}
        </div>
        <div className="va-mini-panels">
          <article>
            <img src={`${IMAGE_BASE}/face-capture.jpg`} alt="人脸抓拍示例" />
            <div><strong>人脸抓拍</strong><small>{activePerson.confidence}% 相似度</small></div>
          </article>
          <article>
            <img src={`${IMAGE_BASE}/plate-capture.jpg`} alt="车牌抓拍示例" />
            <div><strong>车辆抓拍</strong><small>粤C·223E2</small></div>
          </article>
        </div>
      </div>
    </section>
  )
}

function TargetDetail({ activePerson }) {
  return (
    <aside className="va-detail-panel">
      <div className="va-panel-head">
        <div>
          <span>TARGET DETAIL</span>
          <h2>目标详情</h2>
        </div>
        <StatusPill tone={activePerson.risk.includes('高') ? 'danger' : 'warning'}>{activePerson.risk}</StatusPill>
      </div>
      <div className="va-person-card">
        <span className="va-person-avatar"><Icon name="face" size={34} /></span>
        <div>
          <h3>{activePerson.name}</h3>
          <p>{activePerson.status} · {activePerson.lastSeen}</p>
        </div>
      </div>
      <dl className="va-detail-list">
        <div><dt>ID</dt><dd>{activePerson.id}</dd></div>
        <div><dt>类型</dt><dd>{activePerson.type}</dd></div>
        <div><dt>性别</dt><dd>{activePerson.gender}</dd></div>
        <div><dt>年龄段</dt><dd>{activePerson.age}</dd></div>
        <div><dt>速度</dt><dd>{activePerson.speed}</dd></div>
        <div><dt>方向</dt><dd>{activePerson.direction}</dd></div>
        <div><dt>当前位置</dt><dd>{activePerson.location}</dd></div>
      </dl>
      <div className="va-confidence">
        <div><span>识别置信度</span><strong>{activePerson.confidence}%</strong></div>
        <i style={{ width: `${activePerson.confidence}%` }} />
      </div>
    </aside>
  )
}

function OverviewPane({ devices, selectedDeviceId, onSelectDevice, tracks, inferenceStatus }) {
  const isInference = Boolean(inferenceStatus?.running)
  const liveTargets = useMemo(() => (tracks || []).map(mapTrackToTarget), [tracks])
  const targets = isInference ? liveTargets : trackedTargets

  const [activePersonId, setActivePersonId] = useState(null)
  const activePerson = targets.find(target => target.id === activePersonId) || targets[0] || EMPTY_TARGET

  return (
    <div className="va-overview">
      <TargetList activeId={activePerson.id} onSelect={setActivePersonId} targets={targets} isLive={isInference} />
      <TrackingStage
        activePerson={activePerson}
        onSelect={setActivePersonId}
        devices={devices}
        selectedDeviceId={selectedDeviceId}
        onSelectDevice={onSelectDevice}
        targets={targets}
        inferenceStatus={inferenceStatus}
      />
      <TargetDetail activePerson={activePerson} />
      <section className="va-flow-panel">
        {['巡航成果', '视频抽帧', '人脸检测', '车牌检测', '事件入库', '预警联动'].map((step, index) => (
          <div key={step} className={index < 2 ? 'ready' : index < 4 ? 'pending' : ''}>
            <span>{String(index + 1).padStart(2, '0')}</span>
            <strong>{step}</strong>
          </div>
        ))}
      </section>
    </div>
  )
}

function RecordsPane({ alerts, loading, error }) {
  const [recordType, setRecordType] = useState('all')
  const [selectedId, setSelectedId] = useState(null)

  const videoAlerts = useMemo(() => {
    return alerts.filter(a => {
      const st = a.source_type || ''
      const at = a.alert_type || ''
      return st.startsWith('video_') || at.startsWith('video_') || st.startsWith('analytics_')
    })
  }, [alerts])

  const visibleRecords = useMemo(() => {
    if (recordType === 'all') return videoAlerts
    if (recordType === 'pending') return videoAlerts.filter(a => a.status === 'pending')
    if (recordType === 'high') return videoAlerts.filter(a => a.severity === 'high' || a.severity === 'critical')
    return videoAlerts
  }, [videoAlerts, recordType])

  const selectedRecord = visibleRecords.find(r => r.id === selectedId) || visibleRecords[0]

  return (
    <section className="va-records">
      <div className="va-filter-bar">
        <div className="va-filter-group">
          <ThemedSelect className="va-select" value={recordType} onChange={event => setRecordType(event.target.value)}>
            <option value="all">全部记录</option>
            <option value="pending">待处置</option>
            <option value="high">高危/紧急</option>
          </ThemedSelect>
          <input type="text" value="来源：视频识别 / 研判规则" readOnly aria-label="数据来源" />
          <input type="text" value="自动刷新（10 秒）" readOnly aria-label="刷新策略" />
        </div>
        <span className="va-pill" style={{ marginLeft: 'auto' }}>
          {loading ? '加载中...' : `${visibleRecords.length} 条记录`}
        </span>
      </div>

      {error && (
        <div style={{ padding: '12px 14px', color: 'var(--va-danger)', fontSize: 12, borderBottom: '1px solid var(--va-border-soft)' }}>
          加载失败：{error}
        </div>
      )}

      <div className="va-record-grid">
        <div className="va-record-table">
          <div className="va-table-head">
            <span>告警标题 / 类型</span>
            <span>来源设备</span>
            <span>等级</span>
            <span>状态</span>
          </div>
          <div className="va-record-list">
            {visibleRecords.length === 0 && !loading && (
              <div className="va-target-empty" style={{ padding: '40px 12px' }}>暂无视频识别记录</div>
            )}
            {visibleRecords.map(record => (
              <button
                type="button"
                key={record.id}
                className={`va-record-row ${selectedRecord && record.id === selectedRecord.id ? 'active' : ''}`}
                onClick={() => setSelectedId(record.id)}
              >
                <span>
                  <span>
                    <strong>{record.title}</strong>
                    <small>{record.alert_type} · {formatTime(record.occurred_at)}</small>
                  </span>
                </span>
                <em>{record.device_name || '--'}</em>
                <StatusPill tone={severityTone[record.severity] || 'normal'}>
                  {severityLabels[record.severity] || record.severity}
                </StatusPill>
                <StatusPill tone={statusTone[record.status] || 'normal'}>
                  {statusLabels[record.status] || record.status}
                </StatusPill>
              </button>
            ))}
          </div>
        </div>

        <aside className="va-record-detail">
          {selectedRecord ? (
            <>
              <div className="va-panel-head">
                <div>
                  <span>EVENT DETAIL</span>
                  <h2>事件详情</h2>
                </div>
                <StatusPill tone={severityTone[selectedRecord.severity] || 'normal'}>
                  {severityLabels[selectedRecord.severity] || selectedRecord.severity}
                </StatusPill>
              </div>
              <img src={selectedRecord.media_path ? `${IMAGE_BASE}/face-record-alert.jpg` : `${IMAGE_BASE}/face-record-stranger.jpg`} alt={selectedRecord.title} />
              <h3>{selectedRecord.title}</h3>
              <dl>
                <div><dt>事件编号</dt><dd>#{selectedRecord.id}</dd></div>
                <div><dt>告警类型</dt><dd>{selectedRecord.alert_type}</dd></div>
                <div><dt>发生时间</dt><dd>{formatTime(selectedRecord.occurred_at)}</dd></div>
                <div><dt>来源设备</dt><dd>{selectedRecord.device_name || '--'}</dd></div>
                <div><dt>来源类型</dt><dd>{selectedRecord.source_type}</dd></div>
                <div><dt>处置状态</dt><dd>{statusLabels[selectedRecord.status] || selectedRecord.status}</dd></div>
                <div><dt>描述</dt><dd>{selectedRecord.description || '--'}</dd></div>
              </dl>
              <div className="va-record-actions">
                <button type="button" onClick={() => window.open(`/warning-response`, '_blank')}>前往处置</button>
                <button type="button">复核</button>
                <button type="button">导出</button>
              </div>
            </>
          ) : (
            <div className="va-target-empty" style={{ padding: '60px 12px' }}>选择左侧记录查看详情</div>
          )}
        </aside>
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
          <DemoBadge />
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
            <label><span>姓名</span><input type="text" placeholder="待接入人员库后端" /></label>
            <label><span>录入类型</span><input type="text" placeholder="教职工 / 学生 / 访客" /></label>
            <label><span>联系电话</span><input type="text" placeholder="选填" /></label>
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
          <DemoBadge />
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
          <label><span>车牌号码</span><input type="text" placeholder="待接入车牌库后端" /></label>
          <label><span>车辆类型</span><input type="text" placeholder="访客车辆 / 校内车辆" /></label>
          <label><span>有效期</span><input type="text" placeholder="YYYY-MM-DD" /></label>
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
  const [devices, setDevices] = useState([])
  const [alerts, setAlerts] = useState([])
  const [alertsLoading, setAlertsLoading] = useState(true)
  const [alertsError, setAlertsError] = useState('')
  const [selectedDeviceId, setSelectedDeviceId] = useState(null)
  const [tracks, setTracks] = useState([])
  const [inferenceStatus, setInferenceStatus] = useState(null)
  const pollingRef = useRef(null)

  // 设备列表加载
  const fetchDevices = useCallback(async () => {
    try {
      const res = await authFetch('/api/devices')
      if (!res.ok) throw new Error('获取设备列表失败')
      const data = await res.json()
      setDevices(data)
      // 默认选第一个在线设备
      setSelectedDeviceId(prev => {
        if (prev !== null) return prev
        const firstOnline = data.find(d => d.status === 'online')
        return firstOnline ? firstOnline.id : null
      })
    } catch (err) {
      console.error('VideoAnalysis fetchDevices:', err)
    }
  }, [])

  // 告警列表加载（含视频类过滤）
  const fetchAlerts = useCallback(async () => {
    setAlertsLoading(true)
    setAlertsError('')
    try {
      const res = await authFetch('/api/security-alerts')
      if (!res.ok) throw new Error('获取告警列表失败')
      const data = await res.json()
      setAlerts(data)
    } catch (err) {
      setAlertsError(err.message || '获取告警列表失败')
    } finally {
      setAlertsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchDevices()
    fetchAlerts()
    pollingRef.current = setInterval(() => {
      fetchAlerts()
    }, POLL_INTERVAL)
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [fetchDevices, fetchAlerts])

  // 实时告警推送：收到 video_alert 时立即刷新告警列表（WS 断开后自动重连）
  useEffect(() => {
    let socket = null
    let reconnectTimer = null
    let disposed = false

    const connect = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      socket = new WebSocket(`${protocol}//${window.location.host}/api/ws/alerts`)
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data)
          if (message.type === 'video_alert') {
            fetchAlerts()
          }
        } catch {
          /* 忽略非 JSON 消息 */
        }
      }
      socket.onclose = () => {
        if (!disposed) reconnectTimer = setTimeout(connect, 5000)
      }
      socket.onerror = () => {
        socket?.close()
      }
    }

    connect()
    return () => {
      disposed = true
      clearTimeout(reconnectTimer)
      socket?.close()
    }
  }, [fetchAlerts])

  // 推理状态与实时目标轮询（2s）
  const fetchInference = useCallback(async () => {
    if (selectedDeviceId == null) {
      setTracks([])
      setInferenceStatus(null)
      return
    }
    try {
      const statusRes = await authFetch(`/api/inference/pipelines/${selectedDeviceId}/status`)
      if (statusRes.ok) setInferenceStatus(await statusRes.json())

      const tracksRes = await authFetch(`/api/inference/${selectedDeviceId}/tracks`)
      if (tracksRes.ok) {
        const data = await tracksRes.json()
        setTracks(data.tracks || [])
      } else {
        setTracks([])
      }
    } catch {
      setTracks([])
    }
  }, [selectedDeviceId])

  useEffect(() => {
    fetchInference()
    const timer = setInterval(fetchInference, 2000)
    return () => clearInterval(timer)
  }, [fetchInference])

  // 统计聚合
  const stats = useMemo(() => {
    const today = alerts.filter(a => isToday(a.occurred_at))
    const videoToday = today.filter(a => {
      const st = a.source_type || ''
      const at = a.alert_type || ''
      return st.startsWith('video_') || at.startsWith('video_') || st.startsWith('analytics_')
    })
    return {
      todayVideoAlerts: videoToday.length,
      pendingVideo: videoToday.filter(a => a.status === 'pending').length,
      highVideo: videoToday.filter(a => a.severity === 'high' || a.severity === 'critical').length,
      totalDevices: devices.filter(d => d.status === 'online').length,
    }
  }, [alerts, devices])

  return (
    <div className="video-analysis-page">
      <header className="va-header">
        <div>
          <span className="va-kicker">VIDEO AI ANALYSIS</span>
          <h1>视频识别分析</h1>
          <p>面向巡航成果与实时视频的人脸识别、车牌识别和目标轨迹工作台</p>
        </div>
        <div className="va-header-actions">
          <button type="button" onClick={() => setActiveTab('records')}><Icon name="search" />识别记录</button>
        </div>
      </header>

      <section className="va-metrics" aria-label="视频识别统计">
        <MetricCard icon="alert" label="今日视频类告警" value={stats.todayVideoAlerts} unit="条" tone="alert" loading={alertsLoading} />
        <MetricCard icon="alert" label="待处置" value={stats.pendingVideo} unit="条" tone="track" loading={alertsLoading} />
        <MetricCard icon="alert" label="高危/紧急" value={stats.highVideo} unit="条" tone="plate" loading={alertsLoading} />
        <MetricCard icon="route" label="在线设备" value={stats.totalDevices} unit="台" tone="face" loading={false} />
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

      {activeTab === 'overview' && (
        <OverviewPane
          devices={devices}
          selectedDeviceId={selectedDeviceId}
          onSelectDevice={setSelectedDeviceId}
          tracks={tracks}
          inferenceStatus={inferenceStatus}
        />
      )}
      {activeTab === 'records' && (
        <RecordsPane alerts={alerts} loading={alertsLoading} error={alertsError} />
      )}
      {activeTab === 'faces' && <FacesPane />}
      {activeTab === 'plates' && <PlatesPane />}
    </div>
  )
}
