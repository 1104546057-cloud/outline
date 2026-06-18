/* eslint-disable react/prop-types */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import CampusMap from '../components/CampusMap'
import DeviceStatusCard from '../components/DeviceStatusCard'
import { authFetch } from '../utils/authFetch'
import '../styles/Dashboard.css'

const STATUS_LABEL = {
  online: '在线', offline: '离线', warning: '告警',
  pending: '待开始', running: '巡检中', paused: '已暂停', completed: '已完成', cancelled: '已取消',
}

const alertItems = [
  { level: 'critical', time: '14:32:18', area: '东区实验楼', type: '人员闯入', status: '待处置' },
  { level: 'high', time: '14:18:42', area: '南门停车区', type: '车辆滞留', status: '处置中' },
  { level: 'medium', time: '13:57:09', area: '图书馆北侧', type: '设备低电量', status: '已派单' },
  { level: 'low', time: '13:41:33', area: '中心广场', type: '巡检偏航', status: '已恢复' },
]

const formatDistance = value => {
  if (value == null) return '--'
  return value >= 1000 ? `${(value / 1000).toFixed(2)} km` : `${Math.round(value)} m`
}

function Panel({ title, code, meta, className = '', children, onMetaClick }) {
  return (
    <section className={`command-panel ${className}`}>
      <div className="panel-corner top-left" /><div className="panel-corner top-right" />
      <div className="panel-heading">
        <div><span className="panel-title-mark" /><h2>{title}</h2><small>{code}</small></div>
        {meta && <span className={`panel-meta${onMetaClick ? ' panel-meta-clickable' : ''}`} onClick={onMetaClick}>{meta}</span>}
      </div>
      <div className="panel-content">{children}</div>
    </section>
  )
}

function DevicePanel({ devices, selectedDevice, onSelect, onOpenCockpit, onMetaClick }) {
  return (
    <Panel title="无人设备状态" code="DEVICE STATUS" meta={`${devices.length} 台`} className="device-panel" onMetaClick={onMetaClick}>
      <div className="device-scroll">
        {devices.length === 0 && <EmptyState text="暂无设备数据" />}
        {devices.map(device => (
          <DeviceStatusCard
            key={device.id}
            device={device}
            selected={selectedDevice?.id === device.id}
            onClick={() => onSelect(device)}
            onDoubleClick={() => onOpenCockpit(device)}
          />
        ))}
      </div>
    </Panel>
  )
}

function TaskPanel({ tasks, onView, onStart, onDelete, busyTask, onMetaClick }) {
  return (
    <Panel title="巡检任务" code="PATROL MISSIONS" meta={`${tasks.length} 项`} className="task-panel" onMetaClick={onMetaClick}>
      <div className="task-scroll">
        {tasks.length === 0 && <EmptyState text="暂无巡检任务" />}
        {tasks.map(task => {
          const canStart = ['pending', 'completed', 'cancelled', 'paused'].includes(task.status)
          return (
            <article className={`overview-task ${task.status}`} key={task.id}>
              <div className="task-head"><strong>{task.name}</strong><span className={`task-status ${task.status}`}>{STATUS_LABEL[task.status] || task.status}</span></div>
              <div className="task-data-grid">
                <span>所在区域<b>{task.area_name || '--'}</b></span>
                <span>巡检点位<b>{task.point_count ?? 0} 个</b></span>
                <span>线路名称<b>{task.route_name || '--'}</b></span>
                <span>线路长度<b>{formatDistance(task.route_distance)}</b></span>
                <span>GPS 轨迹<b>{task.gps_track?.length || 0} 个</b></span>
              </div>
              <div className="task-actions">
                <button onClick={() => onView(task)}>查看</button>
                <button className="primary" disabled={!canStart || busyTask === task.id} onClick={() => onStart(task)}>{task.status === 'paused' ? '继续' : '开始'}</button>
                <button className="danger" disabled={busyTask === task.id} onClick={() => onDelete(task)}>删除</button>
              </div>
            </article>
          )
        })}
      </div>
    </Panel>
  )
}

function VideoCard({ device, onClick }) {
  const [failed, setFailed] = useState(false)
  const online = device.status === 'online'
  return (
    <div className="overview-video-card" onClick={onClick}>
      <div className="video-card-head"><strong>{device.name}</strong><span className={online ? 'online' : 'offline'}>{online ? 'LIVE' : 'OFFLINE'}</span></div>
      <div className="video-frame">
        {online && !failed ? (
          <img src={`/api/devices/${device.id}/camera/stream`} alt={`${device.name}实时画面`} onError={() => setFailed(true)} />
        ) : (
          <div className="video-placeholder"><span className="camera-reticle" /><b>{failed ? '视频流连接失败' : '设备当前离线'}</b></div>
        )}
        <div className="video-scanline" />
      </div>
      <div className="video-card-foot"><span>{device.media_connected ? '媒体已连接' : '媒体未连接'}</span><span>640×480 · 15 FPS</span></div>
    </div>
  )
}

function VideoStrip({ devices, onVideoClick }) {
  const stripRef = useRef(null)

  const handleWheel = event => {
    const strip = stripRef.current
    if (!strip || strip.scrollWidth <= strip.clientWidth) return
    if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
      event.preventDefault()
      strip.scrollLeft += event.deltaY
    }
  }

  return (
    <div className="video-strip-wrap">
      <div className="video-strip" ref={stripRef} onWheel={handleWheel}>
        {devices.length === 0 ? <EmptyState text="暂无可用设备画面" /> : devices.map(device => <VideoCard device={device} key={device.id} onClick={() => onVideoClick(device)} />)}
      </div>
    </div>
  )
}

function SecuritySituation() {
  return (
    <Panel title="校园安防态势" code="SECURITY SITUATION" meta="实时" className="situation-panel">
      <div className="situation-content">
        <div className="risk-ring" style={{ '--risk': '78%' }}><div><strong>78</strong><span>安全指数</span></div></div>
        <div className="risk-summary"><span><i className="cyan" />今日事件<b>24</b></span><span><i className="orange" />处理中<b>6</b></span><span><i className="green" />已闭环<b>18</b></span></div>
        <div className="trend-chart" aria-label="近七日安全事件趋势">
          {[42, 58, 35, 70, 52, 82, 63].map((value, index) => <div key={index}><i style={{ height: `${value}%` }} /><span>{index + 8}日</span></div>)}
        </div>
        <div className="event-types"><span>异常闯入<b>38%</b></span><span>设备告警<b>29%</b></span><span>巡逻异常<b>21%</b></span><span>其他事件<b>12%</b></span></div>
      </div>
    </Panel>
  )
}

function WarningList() {
  return (
    <Panel title="安全预警信息" code="WARNING FEED" meta="4 条" className="warning-panel">
      <div className="warning-list">
        {alertItems.map((item, index) => (
          <div className={`warning-item ${item.level}`} key={`${item.time}-${index}`}>
            <span className="warning-level">{String(index + 1).padStart(2, '0')}</span>
            <div><strong>{item.type}</strong><small>{item.area} · {item.time}</small></div>
            <b>{item.status}</b>
          </div>
        ))}
      </div>
    </Panel>
  )
}

function EmptyState({ text }) {
  return <div className="overview-empty"><span>◇</span><p>{text}</p></div>
}

function Dashboard() {
  const navigate = useNavigate()
  const [devices, setDevices] = useState([])
  const [tasks, setTasks] = useState([])
  const [selectedDevice, setSelectedDevice] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [deleteTask, setDeleteTask] = useState(null)
  const [busyTask, setBusyTask] = useState(null)

  const fetchOverview = useCallback(async () => {
    try {
      const [deviceResponse, taskResponse] = await Promise.all([authFetch('/api/devices'), authFetch('/api/patrol/tasks')])
      if (!deviceResponse.ok || !taskResponse.ok) throw new Error('监控数据请求失败')
      const [deviceData, taskData] = await Promise.all([deviceResponse.json(), taskResponse.json()])
      setDevices(deviceData)
      setTasks(taskData)
      setSelectedDevice(current => current ? deviceData.find(item => item.id === current.id) || null : deviceData[0] || null)
      setError('')
    } catch (requestError) {
      console.error(requestError)
      setError('部分实时数据暂时无法获取')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchOverview()
    const timer = setInterval(fetchOverview, 5000)
    return () => clearInterval(timer)
  }, [fetchOverview])

  const onlineCount = useMemo(() => devices.filter(device => device.status === 'online').length, [devices])
  const warningCount = useMemo(() => devices.filter(device => device.status === 'warning').length, [devices])

  const viewTask = task => navigate(`/patrol/tasks?task=${task.id}`)

  const startTask = async task => {
    const action = task.status === 'paused' ? 'resume' : 'start'
    setBusyTask(task.id)
    try {
      const response = await authFetch(`/api/patrol/tasks/${task.id}/${action}`, { method: 'PUT' })
      if (!response.ok) throw new Error('任务操作失败')
      await fetchOverview()
    } catch (actionError) {
      console.error(actionError)
      setError('巡检任务操作失败，请稍后重试')
    } finally {
      setBusyTask(null)
    }
  }

  const confirmDelete = async () => {
    if (!deleteTask) return
    setBusyTask(deleteTask.id)
    try {
      const response = await authFetch(`/api/patrol/tasks/${deleteTask.id}`, { method: 'DELETE' })
      if (!response.ok) throw new Error('删除任务失败')
      setDeleteTask(null)
      await fetchOverview()
    } catch (deleteError) {
      console.error(deleteError)
      setError('删除巡检任务失败，请稍后重试')
    } finally {
      setBusyTask(null)
    }
  }

  return (
    <div className="command-dashboard" id="dashboard-page">
      <div className="dashboard-ambient" />
      <div className="overview-status-bar">
        <span><i className="online" />系统运行正常</span><span>设备在线 <b>{onlineCount}/{devices.length}</b></span><span>设备告警 <b className={warningCount ? 'warn' : ''}>{warningCount}</b></span><span>任务执行中 <b>{tasks.filter(task => task.status === 'running').length}</b></span>
        {loading && <span className="overview-sync">实时数据同步中...</span>}{error && <span className="overview-error">{error}</span>}
      </div>

      <div className="dashboard-grid">
        <div className="dashboard-column left-column">
          <DevicePanel
            devices={devices}
            selectedDevice={selectedDevice}
            onSelect={setSelectedDevice}
            onOpenCockpit={device => navigate(`/device-cockpit/${device.id}`)}
            onMetaClick={() => navigate('/devices')}
          />
          <TaskPanel tasks={tasks} onView={viewTask} onStart={startTask} onDelete={setDeleteTask} busyTask={busyTask} onMetaClick={() => navigate('/patrol/tasks')} />
        </div>

        <div className="dashboard-column center-column">
          <Panel title="校园无人设备态势地图" code="SATELLITE SITUATION MAP" meta={selectedDevice ? `当前：${selectedDevice.name}` : '卫星图'} className="satellite-panel">
            <CampusMap devices={devices} selectedDevice={selectedDevice} onSelectDevice={setSelectedDevice} mode="satellite" />
            <div className="map-legend"><span><i className="online" />在线</span><span><i className="warning" />告警</span><span><i className="offline" />离线</span></div>
          </Panel>
          <Panel title="无人设备实时画面" code="LIVE CAMERA STREAMS" meta="横向浏览" className="video-panel">
            <VideoStrip devices={devices} onVideoClick={device => navigate(`/live-video?deviceId=${device.id}`)} />
          </Panel>
        </div>

        <div className="dashboard-column right-column">
          <Panel title="校园设备分布" code="DEVICE DISTRIBUTION" meta="标准地图" className="distribution-panel">
            <CampusMap devices={devices} selectedDevice={selectedDevice} onSelectDevice={setSelectedDevice} mode="normal" />
          </Panel>
          <SecuritySituation />
          <WarningList />
        </div>
      </div>

      {deleteTask && (
        <div className="overview-modal-backdrop" onMouseDown={() => setDeleteTask(null)}>
          <div className="overview-confirm" onMouseDown={event => event.stopPropagation()}>
            <span className="confirm-icon">!</span><h2>删除巡检任务</h2><p>确定删除“{deleteTask.name}”吗？该操作不可撤销。</p>
            <div><button onClick={() => setDeleteTask(null)}>取消</button><button className="danger" disabled={busyTask === deleteTask.id} onClick={confirmDelete}>确认删除</button></div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Dashboard
