import { useState, useEffect, useRef } from 'react'
import AMapLoader from '@amap/amap-jsapi-loader'
import '../styles/Dashboard.css'

/**
 * 数据看板页面
 *
 * 展示设备总览信息、地图标注、设备统计和设备列表
 * 参考图片风格：左侧统计面板 + 中间地图 + 右侧设备列表
 */

// ===== 硬编码设备数据 =====
const mockDevices = [
  {
    id: 'UAV-001',
    name: '侦察无人机 Alpha',
    type: 'drone',
    typeLabel: '无人机',
    status: 'online',
    statusLabel: '在线',
    battery: 87,
    health: 95,
    signal: 92,
    speed: 12.5,
    lat: 22.349278,
    lng: 113.584101,
    location: '软工学院上空',
  },
  {
    id: 'UAV-002',
    name: '运输无人机 Beta',
    type: 'drone',
    typeLabel: '无人机',
    status: 'online',
    statusLabel: '在线',
    battery: 65,
    health: 88,
    signal: 85,
    speed: 8.3,
    lat: 22.348278,
    lng: 113.586101,
    location: '教学楼附近',
  },
  {
    id: 'UAV-003',
    name: '巡检无人机 Gamma',
    type: 'drone',
    typeLabel: '无人机',
    status: 'offline',
    statusLabel: '离线',
    battery: 12,
    health: 72,
    signal: 0,
    speed: 0,
    lat: 22.350278,
    lng: 113.582101,
    location: '操场区域',
  },
  {
    id: 'UGV-001',
    name: '巡逻无人车 Delta',
    type: 'car',
    typeLabel: '无人车',
    status: 'online',
    statusLabel: '在线',
    battery: 78,
    health: 91,
    signal: 88,
    speed: 5.2,
    lat: 22.347278,
    lng: 113.585101,
    location: '校区南门',
  },
  {
    id: 'UGV-002',
    name: '运输无人车 Echo',
    type: 'car',
    typeLabel: '无人车',
    status: 'warning',
    statusLabel: '告警',
    battery: 34,
    health: 65,
    signal: 72,
    speed: 3.1,
    lat: 22.351278,
    lng: 113.583101,
    location: '校区北门',
  },
  {
    id: 'USV-001',
    name: '监测无人船 Foxtrot',
    type: 'ship',
    typeLabel: '无人船',
    status: 'online',
    statusLabel: '在线',
    battery: 92,
    health: 98,
    signal: 95,
    speed: 6.7,
    lat: 22.352278,
    lng: 113.589101,
    location: '情侣北路海域',
  },
  {
    id: 'USV-002',
    name: '巡航无人船 Golf',
    type: 'ship',
    typeLabel: '无人船',
    status: 'online',
    statusLabel: '在线',
    battery: 73,
    health: 85,
    signal: 80,
    speed: 4.5,
    lat: 22.346278,
    lng: 113.590101,
    location: '唐家湾海域',
  },
  {
    id: 'UAV-004',
    name: '测绘无人机 Hotel',
    type: 'drone',
    typeLabel: '无人机',
    status: 'online',
    statusLabel: '在线',
    battery: 54,
    health: 82,
    signal: 78,
    speed: 15.0,
    lat: 22.345278,
    lng: 113.584101,
    location: '附属第一医院',
  },
]

// 设备类型图标映射
const deviceTypeIcons = {
  drone: '✈️',
  car: '🚗',
  ship: '🚢',
}

// 状态颜色映射
const statusColors = {
  online: '#22c55e',
  offline: '#9098b1',
  warning: '#f59e0b',
}

function Dashboard() {
  const [selectedDevice, setSelectedDevice] = useState(null)
  const [currentTime, setCurrentTime] = useState(new Date())
  const mapContainerRef = useRef(null)
  const mapInstanceRef = useRef(null)

  // 统计数据
  const totalDevices = mockDevices.length
  const onlineDevices = mockDevices.filter(d => d.status === 'online').length
  const offlineDevices = mockDevices.filter(d => d.status === 'offline').length
  const warningDevices = mockDevices.filter(d => d.status === 'warning').length

  const droneCount = mockDevices.filter(d => d.type === 'drone').length
  const carCount = mockDevices.filter(d => d.type === 'car').length
  const shipCount = mockDevices.filter(d => d.type === 'ship').length

  const droneOnline = mockDevices.filter(d => d.type === 'drone' && d.status === 'online').length
  const carOnline = mockDevices.filter(d => d.type === 'car' && d.status === 'online').length
  const shipOnline = mockDevices.filter(d => d.type === 'ship' && d.status === 'online').length

  // 实时时钟
  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  // 初始化高德地图
  useEffect(() => {
    window._AMapSecurityConfig = {
      securityJsCode: import.meta.env.VITE_AMAP_API_SECURE_KEY,
    };

    AMapLoader.load({
      key: import.meta.env.VITE_AMAP_API_KEY, // 申请好的Web端开发者Key，首次调用 load 时必填
      version: '2.0', // 指定要加载的 JSAPI 的版本，缺省时默认为 1.4.15
      plugins: [], //需要使用的的插件列表
    })
      .then((AMap) => {
        if (!mapContainerRef.current) return

        const map = new AMap.Map(mapContainerRef.current, {
          zoom: 15,
          center: [113.584101, 22.349278], // 中山大学珠海校区
          mapStyle: 'amap://styles/light',
          viewMode: '2D',
        })

        mapInstanceRef.current = map

        // 添加设备标记
        mockDevices.forEach((device) => {
          // 创建自定义标记内容
          const markerContent = document.createElement('div')
          markerContent.className = `map-marker marker-${device.type} marker-status-${device.status}`
          markerContent.innerHTML = `<span class="marker-icon">${deviceTypeIcons[device.type]}</span>`

          const marker = new AMap.Marker({
            position: [device.lng, device.lat],
            content: markerContent,
            offset: new AMap.Pixel(-16, -16),
            title: device.name,
          })

          marker.on('click', () => {
            setSelectedDevice(device)
          })

          map.add(marker)
        })
      })
      .catch((e) => {
        // 地图加载失败时显示备用内容
        console.error('高德地图加载失败:', e)
      })

    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.destroy()
      }
    }
  }, [])

  // 监听选中设备的变化，联动放大并定位地图
  useEffect(() => {
    if (selectedDevice && mapInstanceRef.current) {
      // 放大级别为 18，并在第三个参数传入 true 以启用动画过渡
      mapInstanceRef.current.setZoomAndCenter(18, [selectedDevice.lng, selectedDevice.lat], true)
    }
  }, [selectedDevice])

  // 获取电池图标颜色
  const getBatteryColor = (level) => {
    if (level >= 60) return '#22c55e'
    if (level >= 30) return '#f59e0b'
    return '#ef4444'
  }

  return (
    <div className="dashboard" id="dashboard-page">
      {/* ===== 顶部标题栏 ===== */}
      <div className="dashboard-header">
        <div className="header-left">
          <h1 className="page-title">数据看板</h1>
          <span className="page-subtitle">异构无人集群实时监控总览</span>
        </div>
        <div className="header-right">
          <div className="header-time">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"></circle>
              <polyline points="12 6 12 12 16 14"></polyline>
            </svg>
            <span>{currentTime.toLocaleString('zh-CN', { hour12: false })}</span>
          </div>
        </div>
      </div>

      {/* ===== 主体内容：三栏布局 ===== */}
      <div className="dashboard-body">
        {/* ===== 左侧统计面板 ===== */}
        <div className="dashboard-left">
          {/* 无人机监控 */}
          <div className="stat-card">
            <div className="stat-card-header">
              <span className="stat-card-icon drone-icon">✈️</span>
              <span className="stat-card-title">无人机监控</span>
            </div>
            <div className="stat-main">
              <span className="stat-label">在线总数量</span>
              <span className="stat-value">{droneOnline}<span className="stat-unit">架</span></span>
            </div>
            <div className="stat-row">
              <div className="stat-item">
                <span className="stat-item-label">执行中</span>
                <span className="stat-item-value accent-blue">{droneOnline}架</span>
              </div>
              <div className="stat-item">
                <span className="stat-item-label">空闲中</span>
                <span className="stat-item-value accent-green">{droneCount - droneOnline}架</span>
              </div>
            </div>
          </div>

          {/* 无人车监控 */}
          <div className="stat-card">
            <div className="stat-card-header">
              <span className="stat-card-icon car-icon">🚗</span>
              <span className="stat-card-title">无人车监控</span>
            </div>
            <div className="stat-main">
              <span className="stat-label">在线总数量</span>
              <span className="stat-value">{carOnline}<span className="stat-unit">辆</span></span>
            </div>
            <div className="stat-row">
              <div className="stat-item">
                <span className="stat-item-label">执行中</span>
                <span className="stat-item-value accent-blue">{carOnline}辆</span>
              </div>
              <div className="stat-item">
                <span className="stat-item-label">告警中</span>
                <span className="stat-item-value accent-orange">{warningDevices}辆</span>
              </div>
            </div>
          </div>

          {/* 无人船监控 */}
          <div className="stat-card">
            <div className="stat-card-header">
              <span className="stat-card-icon ship-icon">🚢</span>
              <span className="stat-card-title">无人船监控</span>
            </div>
            <div className="stat-main">
              <span className="stat-label">在线总数量</span>
              <span className="stat-value">{shipOnline}<span className="stat-unit">艘</span></span>
            </div>
            <div className="stat-row">
              <div className="stat-item">
                <span className="stat-item-label">执行中</span>
                <span className="stat-item-value accent-blue">{shipOnline}艘</span>
              </div>
              <div className="stat-item">
                <span className="stat-item-label">空闲中</span>
                <span className="stat-item-value accent-green">{shipCount - shipOnline}艘</span>
              </div>
            </div>
          </div>

          {/* 设备总览统计 */}
          <div className="stat-card summary-card">
            <div className="stat-card-header">
              <span className="stat-card-icon summary-icon">📊</span>
              <span className="stat-card-title">设备总览</span>
            </div>
            <div className="summary-grid">
              <div className="summary-item">
                <span className="summary-number">{totalDevices}</span>
                <span className="summary-label">设备总数</span>
              </div>
              <div className="summary-item">
                <span className="summary-number online">{onlineDevices}</span>
                <span className="summary-label">在线</span>
              </div>
              <div className="summary-item">
                <span className="summary-number offline">{offlineDevices}</span>
                <span className="summary-label">离线</span>
              </div>
              <div className="summary-item">
                <span className="summary-number warning">{warningDevices}</span>
                <span className="summary-label">告警</span>
              </div>
            </div>
          </div>
        </div>

        {/* ===== 中间地图区域 ===== */}
        <div className="dashboard-center">
          <div className="map-container" id="amap-container" ref={mapContainerRef}>
            {/* 高德地图将渲染到这里 */}
            <div className="map-fallback">
              <div className="map-fallback-content">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#b4bcd0" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
                  <circle cx="12" cy="10" r="3"></circle>
                </svg>
                <p>地图加载中...</p>
                <p className="map-fallback-hint">请配置高德地图 API Key</p>
              </div>
            </div>
          </div>
        </div>

        {/* ===== 右侧设备列表 ===== */}
        <div className="dashboard-right">
          <div className="device-list-header">
            <h3>设备信息</h3>
            <span className="device-count">{totalDevices} 台设备</span>
          </div>
          <div className="device-list">
            {mockDevices.map((device) => (
              <div
                key={device.id}
                className={`device-card ${selectedDevice?.id === device.id ? 'selected' : ''}`}
                onClick={() => setSelectedDevice(device)}
                id={`device-${device.id}`}
              >
                <div className="device-card-top">
                  <div className="device-type-badge">
                    <span className="device-type-icon">{deviceTypeIcons[device.type]}</span>
                    <span className="device-type-name">{device.typeLabel}</span>
                  </div>
                  <span
                    className="device-status-dot"
                    style={{ background: statusColors[device.status] }}
                    title={device.statusLabel}
                  ></span>
                </div>
                <div className="device-card-name">{device.name}</div>
                <div className="device-card-id">{device.id}</div>
                <div className="device-card-location">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
                    <circle cx="12" cy="10" r="3"></circle>
                  </svg>
                  <span>{device.location}</span>
                </div>
                <div className="device-card-coords" style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center', gap: '0.25rem', marginTop: '0.25rem' }}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="2" y1="12" x2="22" y2="12"></line>
                    <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
                  </svg>
                  <span style={{ fontFamily: 'monospace' }}>{device.lng.toFixed(6)},{device.lat.toFixed(6)}</span>
                </div>
                <div className="device-card-metrics">
                  <div className="metric" title="电量">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={getBatteryColor(device.battery)} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="1" y="6" width="18" height="12" rx="2" ry="2"></rect>
                      <line x1="23" y1="13" x2="23" y2="11"></line>
                    </svg>
                    <span style={{ color: getBatteryColor(device.battery) }}>{device.battery}%</span>
                  </div>
                  <div className="metric" title="信号">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M5 12.55a11 11 0 0 1 14.08 0"></path>
                      <path d="M1.42 9a16 16 0 0 1 21.16 0"></path>
                      <path d="M8.53 16.11a6 6 0 0 1 6.95 0"></path>
                      <line x1="12" y1="20" x2="12.01" y2="20"></line>
                    </svg>
                    <span>{device.signal}%</span>
                  </div>
                  <div className="metric" title="速度">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
                    </svg>
                    <span>{device.speed}m/s</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export default Dashboard
