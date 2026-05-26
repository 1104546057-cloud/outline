import { useState, useEffect } from 'react'
import '../styles/DeviceManagement.css'

export default function DeviceManagement() {
  const [devices, setDevices] = useState([])
  const [loading, setLoading] = useState(true)
  
  // scan modal
  const [showScanModal, setShowScanModal] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [scanResults, setScanResults] = useState([])
  
  // edit modal
  const [showEditModal, setShowEditModal] = useState(false)
  const [editingDevice, setEditingDevice] = useState(null)
  const [formData, setFormData] = useState({ name: '', type: '无人车', ip_address: '' })
  
  // API Fetch
  const fetchDevices = async () => {
    try {
      const res = await fetch('/api/devices', { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setDevices(data)
      }
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDevices()
    const timer = setInterval(fetchDevices, 5000) // poll every 5s for updates
    return () => clearInterval(timer)
  }, [])

  const handleScan = async () => {
    setShowScanModal(true)
    setScanning(true)
    setScanResults([])
    try {
      const res = await fetch('/api/wifi/scan', { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setScanResults(data)
      }
    } catch (e) {
      console.error(e)
    } finally {
      setScanning(false)
    }
  }

  const handleAddFromScan = async (deviceInfo) => {
    try {
      const res = await fetch('/api/devices', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          name: deviceInfo.ssid,
          type: deviceInfo.type,
          ip_address: deviceInfo.ip
        })
      })
      if (res.ok) {
        setShowScanModal(false)
        fetchDevices()
      } else {
        const err = await res.json()
        alert(err.detail || '添加失败或设备已存在')
      }
    } catch (e) {
      console.error(e)
      alert('网络错误')
    }
  }

  const handleDelete = async (id) => {
    if (!confirm('确定删除该设备吗？')) return
    try {
      const res = await fetch(`/api/devices/${id}`, { method: 'DELETE', credentials: 'include' })
      if (res.ok) {
        fetchDevices()
      }
    } catch (e) {
      console.error(e)
    }
  }

  const handleEdit = (device) => {
    setEditingDevice(device)
    setFormData({ name: device.name, type: device.type, ip_address: device.ip_address })
    setShowEditModal(true)
  }

  const handleSaveEdit = async (e) => {
    e.preventDefault()
    try {
      const res = await fetch(`/api/devices/${editingDevice.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(formData)
      })
      if (res.ok) {
        setShowEditModal(false)
        fetchDevices()
      }
    } catch (e) {
      console.error(e)
    }
  }

  const getDeviceIcon = (type) => {
    if (!type) return '🤖'
    if (type.includes('车') || type.includes('Rover')) return '🚗'
    if (type.includes('机') || type.includes('Drone')) return '🚁'
    if (type.includes('船') || type.includes('Boat')) return '🚤'
    return '🤖'
  }

  return (
    <div className="device-management">
      <div className="dm-header">
        <div>
          <h1>设备管理</h1>
          <p>实时监控与管理您的无人集群设备</p>
        </div>
        <button className="dm-btn-scan" onClick={handleScan}>
          <span>📡</span> 扫描 Wi-Fi 添加设备
        </button>
      </div>

      <div className="dm-device-grid">
        {devices.map(dev => (
          <div className="dm-device-card" key={dev.id}>
            <div className="dm-card-header">
              <div className="dm-device-title">
                <div className="dm-device-icon">{getDeviceIcon(dev.type)}</div>
                <div>
                  <h3 className="dm-device-name">{dev.name}</h3>
                  <p className="dm-device-ip">{dev.ip_address}</p>
                </div>
              </div>
              <span className={`dm-device-status ${dev.status}`}>{dev.status}</span>
            </div>

            <div className="dm-device-stats">
              <div className="dm-stat-item">
                <span className="dm-stat-label">🔋 电量</span>
                <span className="dm-stat-value">{dev.battery}%</span>
                <div className="dm-stat-bar-container">
                  <div className="dm-stat-bar" style={{ width: `${Math.max(0, Math.min(100, dev.battery))}%`, backgroundColor: dev.battery > 20 ? '#34d399' : '#f87171' }}></div>
                </div>
              </div>
              <div className="dm-stat-item">
                <span className="dm-stat-label">📶 信号</span>
                <span className="dm-stat-value">{dev.signal}%</span>
                <div className="dm-stat-bar-container">
                  <div className="dm-stat-bar" style={{ width: `${Math.max(0, Math.min(100, dev.signal))}%`, backgroundColor: '#60a5fa' }}></div>
                </div>
              </div>
              <div className="dm-stat-item">
                <span className="dm-stat-label">❤️ 健康度</span>
                <span className="dm-stat-value">{dev.health}%</span>
              </div>
              <div className="dm-stat-item">
                <span className="dm-stat-label">⚡ 速度</span>
                <span className="dm-stat-value">{dev.speed}</span>
              </div>
            </div>

            <div className="dm-device-gps">
              <span>📍</span> 纬度: {dev.lat} | 经度: {dev.lng}
            </div>

            <div className="dm-device-actions">
              <button className="dm-btn-icon edit" onClick={() => handleEdit(dev)}>
                ✏️ 编辑
              </button>
              <button className="dm-btn-icon delete" onClick={() => handleDelete(dev.id)}>
                🗑️ 删除
              </button>
            </div>
          </div>
        ))}
        {devices.length === 0 && !loading && (
           <p style={{ color: '#94a3b8', gridColumn: '1 / -1', textAlign: 'center', marginTop: '2rem' }}>暂无设备，请扫描 Wi-Fi 添加</p>
        )}
      </div>

      {showScanModal && (
        <div className="dm-modal-overlay" onClick={() => setShowScanModal(false)}>
          <div className="dm-modal" onClick={e => e.stopPropagation()}>
            <div className="dm-modal-header">
              <h2>扫描局域网设备</h2>
              <button className="dm-modal-close" onClick={() => setShowScanModal(false)}>✕</button>
            </div>
            <div className="dm-modal-body">
              {scanning ? (
                <div className="dm-scan-status">
                  <div className="dm-scan-spinner"></div>
                  <p>正在扫描附近通过 Wi-Fi 连接的无人设备...</p>
                </div>
              ) : (
                <div className="dm-wifi-list">
                  {scanResults.length > 0 ? scanResults.map((res, i) => (
                    <div className="dm-wifi-item" key={i} onClick={() => handleAddFromScan(res)}>
                      <div className="dm-wifi-item-info">
                        <span className="dm-wifi-ssid">{res.ssid} <span style={{fontSize:'0.8rem', color:'#60a5fa', marginLeft:'5px'}}>{res.type}</span></span>
                        <span className="dm-wifi-ip">{res.ip} | MAC: {res.mac}</span>
                      </div>
                      <span className="dm-wifi-item-action">添加设备</span>
                    </div>
                  )) : (
                    <p style={{textAlign: 'center', color: '#94a3b8'}}>未发现新设备</p>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {showEditModal && (
        <div className="dm-modal-overlay" onClick={() => setShowEditModal(false)}>
          <div className="dm-modal" onClick={e => e.stopPropagation()}>
            <div className="dm-modal-header">
              <h2>编辑设备信息</h2>
              <button className="dm-modal-close" onClick={() => setShowEditModal(false)}>✕</button>
            </div>
            <form onSubmit={handleSaveEdit}>
              <div className="dm-modal-body">
                <div className="dm-form-group">
                  <label>设备名称</label>
                  <input type="text" value={formData.name} onChange={e => setFormData({...formData, name: e.target.value})} required />
                </div>
                <div className="dm-form-group">
                  <label>设备类型</label>
                  <select value={formData.type} onChange={e => setFormData({...formData, type: e.target.value})}>
                    <option value="无人车">无人车</option>
                    <option value="无人机">无人机</option>
                    <option value="无人船">无人船</option>
                    <option value="未知设备">未知设备</option>
                  </select>
                </div>
                <div className="dm-form-group">
                  <label>IP 地址</label>
                  <input type="text" value={formData.ip_address} onChange={e => setFormData({...formData, ip_address: e.target.value})} required />
                </div>
              </div>
              <div className="dm-modal-footer">
                <button type="button" className="dm-btn-cancel" onClick={() => setShowEditModal(false)}>取消</button>
                <button type="submit" className="dm-btn-submit">保存修改</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
