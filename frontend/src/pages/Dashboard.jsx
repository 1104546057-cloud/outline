import { useState, useEffect, useRef } from 'react'
import AMapLoader from '@amap/amap-jsapi-loader'
import { authFetch } from '../utils/authFetch'
import '../styles/Dashboard.css'

/**
 * 数据看板页面
 *
 * 展示设备总览信息、地图标注、设备统计和设备列表
 * 从 /api/devices 获取真实设备数据
 */

// 设备类型图标映射
const deviceTypeIcons = {
  '无人机': '✈️',
  '无人车': '🚗',
  '无人船': '🚢',
  'drone': '✈️',
  'car': '🚗',
  'ship': '🚢',
}

// 状态颜色映射
const statusColors = {
  online: '#22c55e',
  offline: '#9098b1',
  warning: '#f59e0b',
}

// 获取设备类型图标
const getTypeIcon = (type) => {
  if (!type) return '🚗'
  for (const [key, icon] of Object.entries(deviceTypeIcons)) {
    if (type.includes(key)) return icon
  }
  return '🚗'
}

// 获取地图标记的背景色样式类
const getTypeClass = (type) => {
  if (!type) return 'marker-car'
  if (type.includes('机') || type.includes('drone')) return 'marker-drone'
  if (type.includes('船') || type.includes('ship')) return 'marker-ship'
  return 'marker-car' // 默认无人车
}

// 获取设备类型标签
const getTypeLabel = (type) => {
  if (!type) return '无人车'
  if (type.includes('机')) return '无人机'
  if (type.includes('船')) return '无人船'
  if (type.includes('车')) return '无人车'
  return '无人车' // 默认返回无人车
}

// 获取状态标签
const getStatusLabel = (status) => {
  if (status === 'online') return '在线'
  if (status === 'warning') return '告警'
  return '离线'
}

// 获取设备类型的量词
const getTypeUnit = (type) => {
  if (!type) return '辆'
  if (type.includes('机')) return '架'
  if (type.includes('船')) return '艘'
  if (type.includes('车')) return '辆'
  return '辆' // 默认量词
}

function Dashboard() {
  const [devices, setDevices] = useState([])
  const [selectedDevice, setSelectedDevice] = useState(null)
  const [currentTime, setCurrentTime] = useState(new Date())
  const [mapLoaded, setMapLoaded] = useState(false) // 新增：跟踪地图是否加载完成
  const mapContainerRef = useRef(null)
  const mapInstanceRef = useRef(null)
  const markersRef = useRef([])

  // 从 API 获取设备数据
  const fetchDevices = async () => {
    try {
      const res = await authFetch('/api/devices')
      if (res.ok) {
        const data = await res.json()
        setDevices(data)
      }
    } catch (e) {
      console.error('获取设备数据失败:', e)
    }
  }

  useEffect(() => {
    fetchDevices()
    const timer = setInterval(fetchDevices, 5000)
    return () => clearInterval(timer)
  }, [])

  // 统计数据（从真实数据计算）
  const totalDevices = devices.length
  const onlineDevices = devices.filter(d => d.status === 'online').length
  const offlineDevices = devices.filter(d => d.status === 'offline').length
  const warningDevices = devices.filter(d => d.status === 'warning').length

  const droneCount = devices.filter(d => d.type && d.type.includes('机')).length
  const carCount = devices.filter(d => d.type && d.type.includes('车')).length
  const shipCount = devices.filter(d => d.type && d.type.includes('船')).length

  const droneOnline = devices.filter(d => d.type && d.type.includes('机') && d.status === 'online').length
  const carOnline = devices.filter(d => d.type && d.type.includes('车') && d.status === 'online').length
  const shipOnline = devices.filter(d => d.type && d.type.includes('船') && d.status === 'online').length

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
      key: import.meta.env.VITE_AMAP_API_KEY,
      version: '2.0',
      plugins: [],
    })
      .then((AMap) => {
        if (!mapContainerRef.current) return

        const map = new AMap.Map(mapContainerRef.current, {
          zoom: 16.8,
          center: [113.584101, 22.349278],
          mapStyle: 'amap://styles/light',
          viewMode: '2D',
        })

        mapInstanceRef.current = map
        setMapLoaded(true) // 地图加载完成，触发渲染标记
      })
      .catch((e) => {
        console.error('高德地图加载失败:', e)
      })

    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.destroy()
      }
    }
  }, [])

  // 当设备数据变化时更新地图标记
  useEffect(() => {
    if (!mapInstanceRef.current) return
    const map = mapInstanceRef.current
    // 移除旧标记
    markersRef.current.forEach(m => map.remove(m))
    markersRef.current = []
    // 添加新标记
    const AMap = window.AMap
    if (!AMap) return
    devices.forEach((device) => {
      if (!device.lat || !device.lng) return
      const lat = parseFloat(device.lat)
      const lng = parseFloat(device.lng)
      if (isNaN(lat) || isNaN(lng)) return

      const markerContent = document.createElement('div')
      markerContent.className = `map-marker marker-status-${device.status} ${getTypeClass(device.type)}`
      markerContent.innerHTML = `<span class="marker-icon">${getTypeIcon(device.type)}</span>`

      const marker = new AMap.Marker({
        position: [lng, lat], // 初始暂存 WGS84，随后异步更新
        content: markerContent,
        offset: new AMap.Pixel(-16, -16),
        title: device.name,
      })

      // 调用高德 API 将 WGS84(gps) 转为 GCJ02(高德坐标)，解决几百米偏移问题
      AMap.convertFrom([lng, lat], 'gps', (status, result) => {
        if (result.info === 'ok') {
          marker.setPosition(result.locations[0])
        }
      })

      marker.on('click', () => {
        setSelectedDevice(device)
      })

      map.add(marker)
      markersRef.current.push(marker)
    })
  }, [devices, mapLoaded]) // 添加 mapLoaded 作为依赖

  // 监听选中设备的变化，联动放大并定位地图
  useEffect(() => {
    if (selectedDevice && mapInstanceRef.current && selectedDevice.lat && selectedDevice.lng) {
      const lat = parseFloat(selectedDevice.lat)
      const lng = parseFloat(selectedDevice.lng)
      if (!isNaN(lat) && !isNaN(lng)) {
        const AMap = window.AMap
        if (AMap) {
          AMap.convertFrom([lng, lat], 'gps', (status, result) => {
            if (result.info === 'ok') {
              mapInstanceRef.current.setZoomAndCenter(18, result.locations[0], true)
            }
          })
        }
      }
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
            {devices.length === 0 && (
              <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--color-text-muted)' }}>
                暂无设备数据
              </div>
            )}
            {devices.map((device) => (
              <div
                key={device.id}
                className={`device-card ${selectedDevice?.id === device.id ? 'selected' : ''}`}
                onClick={() => setSelectedDevice(device)}
                id={`device-${device.id}`}
              >
                <div className="device-card-top">
                  <div className="device-type-badge">
                    <span className="device-type-icon">{getTypeIcon(device.type)}</span>
                    <span className="device-type-name">{getTypeLabel(device.type)}</span>
                  </div>
                  <span
                    className="device-status-dot"
                    style={{ background: statusColors[device.status] || statusColors.offline }}
                    title={getStatusLabel(device.status)}
                  ></span>
                </div>
                <div className="device-card-name">{device.name}</div>
                <div className="device-card-id">{device.ip_address}:{device.port || 9000}</div>
                <div className="device-card-location">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
                    <circle cx="12" cy="10" r="3"></circle>
                  </svg>
                  <span>{device.lat && device.lng ? `${device.lat}, ${device.lng}` : '暂无位置信息'}</span>
                </div>
                <div className="device-card-metrics">
                  <div className="metric" title="电量">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={getBatteryColor(device.battery)} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="1" y="6" width="18" height="12" rx="2" ry="2"></rect>
                      <line x1="23" y1="13" x2="23" y2="11"></line>
                    </svg>
                    <span style={{ color: getBatteryColor(device.battery) }}>{device.battery != null ? `${device.battery}%` : '--'}</span>
                  </div>
                  <div className="metric" title="信号">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M5 12.55a11 11 0 0 1 14.08 0"></path>
                      <path d="M1.42 9a16 16 0 0 1 21.16 0"></path>
                      <path d="M8.53 16.11a6 6 0 0 1 6.95 0"></path>
                      <line x1="12" y1="20" x2="12.01" y2="20"></line>
                    </svg>
                    <span>{device.signal != null ? `${device.signal}%` : '--'}</span>
                  </div>
                  <div className="metric" title="速度">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
                    </svg>
                    <span>{device.speed || '0 m/s'}</span>
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
