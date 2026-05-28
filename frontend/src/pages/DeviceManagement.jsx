import { useState, useEffect } from 'react'
import '../styles/DeviceManagement.css'

export default function DeviceManagement() {
  const [devices, setDevices] = useState([])
  const [loading, setLoading] = useState(true)
  const [deleteConfirm, setDeleteConfirm] = useState(null)
  
  // scan modal
  const [showScanModal, setShowScanModal] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [scanResults, setScanResults] = useState([])
  const [scanSubnet, setScanSubnet] = useState('192.168.31.0/24')
  const [scanCacheTime, setScanCacheTime] = useState('')

  // localStorage 缓存辅助
  const SCAN_CACHE_KEY = 'dwc_scan_cache'

  const loadScanCache = (subnet) => {
    try {
      const raw = localStorage.getItem(SCAN_CACHE_KEY)
      if (!raw) return null
      const cache = JSON.parse(raw)
      if (cache.subnet === subnet && Array.isArray(cache.results)) {
        return cache
      }
    } catch (e) { /* ignore */ }
    return null
  }

  const saveScanCache = (subnet, results) => {
    try {
      localStorage.setItem(SCAN_CACHE_KEY, JSON.stringify({
        subnet,
        results,
        scannedAt: new Date().toISOString()
      }))
    } catch (e) { /* ignore */ }
  }
  
  // add device modal (手动添加)
  const [showAddModal, setShowAddModal] = useState(false)
  const [addFormData, setAddFormData] = useState({ name: '', type: '无人车', ip_address: '', port: 9000 })
  const [addError, setAddError] = useState('')

  // edit modal
  const [showEditModal, setShowEditModal] = useState(false)
  const [editingDevice, setEditingDevice] = useState(null)
  const [formData, setFormData] = useState({ name: '', type: '无人车', ip_address: '', port: 9000 })

  // token modal
  const [showTokenModal, setShowTokenModal] = useState(false)
  const [tokenDevice, setTokenDevice] = useState(null)
  const [tokens, setTokens] = useState([])
  const [newToken, setNewToken] = useState('')
  
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
    const timer = setInterval(fetchDevices, 5000)
    return () => clearInterval(timer)
  }, [])

  // 打开扫描弹窗：有缓存则直接展示，无缓存则自动发起扫描
  const handleOpenScanModal = () => {
    const cached = loadScanCache(scanSubnet)
    if (cached && cached.results.length > 0) {
      setScanResults(cached.results)
      setScanCacheTime(cached.scannedAt)
      setShowScanModal(true)
    } else {
      setScanCacheTime('')
      handleScan(scanSubnet)
    }
  }

  // 执行实际的 nmap 扫描并将结果缓存到 localStorage
  const handleScan = async (targetSubnet = scanSubnet) => {
    setShowScanModal(true)
    setScanning(true)
    setScanResults([])
    setScanCacheTime('')
    try {
      const res = await fetch(`/api/wifi/scan?subnet=${encodeURIComponent(targetSubnet)}`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setScanResults(data)
        saveScanCache(targetSubnet, data)
        setScanCacheTime(new Date().toISOString())
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
          ip_address: deviceInfo.ip,
          port: 9000,
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

  const handleManualAdd = async (e) => {
    e.preventDefault()
    setAddError('')
    try {
      const res = await fetch('/api/devices', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(addFormData)
      })
      if (res.ok) {
        setShowAddModal(false)
        setAddFormData({ name: '', type: '无人车', ip_address: '', port: 9000 })
        fetchDevices()
      } else {
        const err = await res.json()
        setAddError(err.detail || '添加失败')
      }
    } catch (e) {
      setAddError('网络错误')
    }
  }

  const handleDelete = async (id) => {
    try {
      const res = await fetch(`/api/devices/${id}`, { method: 'DELETE', credentials: 'include' })
      if (res.ok) {
        setDeleteConfirm(null)
        fetchDevices()
      }
    } catch (e) {
      console.error(e)
    }
  }

  const handleEdit = (device) => {
    setEditingDevice(device)
    setFormData({ name: device.name, type: device.type, ip_address: device.ip_address, port: device.port || 9000 })
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

  const handleShowTokens = async (device) => {
    setTokenDevice(device)
    setShowTokenModal(true)
    setNewToken('')
    try {
      const res = await fetch(`/api/devices/${device.id}/tokens`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setTokens(data)
      }
    } catch (e) {
      console.error(e)
    }
  }

  const handleCreateToken = async () => {
    try {
      const res = await fetch(`/api/devices/${tokenDevice.id}/tokens`, {
        method: 'POST',
        credentials: 'include',
      })
      if (res.ok) {
        const data = await res.json()
        setNewToken(data.token)
        // 刷新 token 列表
        const listRes = await fetch(`/api/devices/${tokenDevice.id}/tokens`, { credentials: 'include' })
        if (listRes.ok) {
          setTokens(await listRes.json())
        }
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

  const getStatusLabel = (status) => {
    if (status === 'online') return '在线'
    return '离线'
  }

  const formatLastSeen = (lastSeen) => {
    if (!lastSeen) return '从未上报'
    const date = new Date(lastSeen)
    const now = new Date()
    const diffSec = Math.floor((now - date) / 1000)
    if (diffSec < 60) return `${diffSec}秒前`
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}分钟前`
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}小时前`
    return date.toLocaleString('zh-CN')
  }

  const getExtraInfo = (device) => {
    const extra = device.extra
    if (!extra) return null
    const items = []
    if (extra.cpu_temp_c !== undefined) {
      items.push({ label: '🌡️ CPU', value: `${extra.cpu_temp_c}°C` })
    }
    if (extra.gps) {
      const gpsStatus = extra.gps.status === 'fix' ? '已定位' : '未定位'
      items.push({ label: '📡 GPS', value: gpsStatus })
    }
    if (extra.locationSource) {
      items.push({ label: '📍 定位源', value: extra.locationSource })
    }
    return items.length > 0 ? items : null
  }

  return (
    <div className="device-management">
      <div className="dm-header">
        <div className="dm-header-left">
          <h1 className="page-title">设备管理</h1>
          <span className="page-subtitle">管理您的无人集群设备 · 支持真实设备接入</span>
        </div>
        <div className="dm-header-actions">
          <button className="dm-btn-add" onClick={() => { setShowAddModal(true); setAddError('') }}>
            <span>➕</span> 手动添加设备
          </button>
          <button className="dm-btn-scan" onClick={handleOpenScanModal}>
            <span>📡</span> 扫描局域网
          </button>
        </div>
      </div>

      <div className="dm-device-grid">
        {devices.map(dev => (
          <div className="dm-device-card" key={dev.id}>
            <div className="dm-card-header">
              <div className="dm-device-title">
                <div className="dm-device-icon">{getDeviceIcon(dev.type)}</div>
                <div>
                  <h3 className="dm-device-name">{dev.name}</h3>
                  <p className="dm-device-ip">{dev.ip_address}:{dev.port || 9000}</p>
                </div>
              </div>
              <span className={`dm-device-status ${dev.status}`}>{getStatusLabel(dev.status)}</span>
            </div>

            <div className="dm-device-stats">
              <div className="dm-stat-item">
                <span className="dm-stat-label">🔋 电量</span>
                <span className="dm-stat-value">{dev.battery != null ? `${dev.battery}%` : '--'}</span>
                {dev.battery != null && (
                  <div className="dm-stat-bar-container">
                    <div className="dm-stat-bar" style={{ width: `${Math.max(0, Math.min(100, dev.battery))}%`, backgroundColor: dev.battery > 20 ? '#34d399' : '#f87171' }}></div>
                  </div>
                )}
              </div>
              <div className="dm-stat-item">
                <span className="dm-stat-label">📶 信号</span>
                <span className="dm-stat-value">{dev.signal != null ? `${dev.signal}%` : '--'}</span>
                {dev.signal != null && (
                  <div className="dm-stat-bar-container">
                    <div className="dm-stat-bar" style={{ width: `${Math.max(0, Math.min(100, dev.signal))}%`, backgroundColor: '#60a5fa' }}></div>
                  </div>
                )}
              </div>
              <div className="dm-stat-item">
                <span className="dm-stat-label">❤️ 健康度</span>
                <span className="dm-stat-value">{dev.health}%</span>
              </div>
              <div className="dm-stat-item">
                <span className="dm-stat-label">⏱️ 上报</span>
                <span className="dm-stat-value dm-stat-time">{formatLastSeen(dev.last_seen)}</span>
              </div>
            </div>

            {/* 扩展遥测信息（CPU温度、GPS状态等） */}
            {getExtraInfo(dev) && (
              <div className="dm-device-extra">
                {getExtraInfo(dev).map((item, i) => (
                  <span key={i} className="dm-extra-tag">{item.label}: {item.value}</span>
                ))}
              </div>
            )}

            <div className="dm-device-gps">
              <span>📍</span> {dev.lat && dev.lng ? `${dev.lat}, ${dev.lng}` : '暂无位置信息'}
            </div>

            <div className="dm-device-actions">
              <button className="dm-btn-icon token" onClick={() => handleShowTokens(dev)} title="管理设备Token">
                🔑 Token
              </button>
              <button className="dm-btn-icon edit" onClick={() => handleEdit(dev)}>
                ✏️ 编辑
              </button>
              <button className="dm-btn-icon delete" onClick={() => setDeleteConfirm(dev)}>
                🗑️ 删除
              </button>
            </div>
          </div>
        ))}
        {devices.length === 0 && !loading && (
           <p style={{ color: '#94a3b8', gridColumn: '1 / -1', textAlign: 'center', marginTop: '2rem' }}>暂无设备，请手动添加或扫描局域网</p>
        )}
      </div>

      {/* 手动添加设备弹窗 */}
      {showAddModal && (
        <div className="dm-modal-overlay" onClick={() => setShowAddModal(false)}>
          <div className="dm-modal" onClick={e => e.stopPropagation()}>
            <div className="dm-modal-header">
              <h2>添加新设备</h2>
              <button className="dm-modal-close" onClick={() => setShowAddModal(false)}>✕</button>
            </div>
            <form onSubmit={handleManualAdd}>
              <div className="dm-modal-body">
                <div className="dm-form-group">
                  <label>设备名称</label>
                  <input type="text" value={addFormData.name} onChange={e => setAddFormData({...addFormData, name: e.target.value})} placeholder="例：巡逻无人车 01" required />
                </div>
                <div className="dm-form-group">
                  <label>设备类型</label>
                  <select value={addFormData.type} onChange={e => setAddFormData({...addFormData, type: e.target.value})}>
                    <option value="无人车">无人车</option>
                    <option value="无人机">无人机</option>
                    <option value="无人船">无人船</option>
                    <option value="未知设备">未知设备</option>
                  </select>
                </div>
                <div className="dm-form-group">
                  <label>IP 地址</label>
                  <input type="text" value={addFormData.ip_address} onChange={e => setAddFormData({...addFormData, ip_address: e.target.value})} placeholder="例：192.168.31.200" required />
                </div>
                <div className="dm-form-group">
                  <label>控制服务端口号</label>
                  <input type="number" value={addFormData.port} onChange={e => setAddFormData({...addFormData, port: parseInt(e.target.value) || 9000})} placeholder="缺省为 9000" min="1" max="65535" />
                  <span className="dm-form-hint">树莓派控制服务默认监听 9000 端口</span>
                </div>
                {addError && <p className="dm-form-error">{addError}</p>}
              </div>
              <div className="dm-modal-footer">
                <button type="button" className="dm-btn-cancel" onClick={() => setShowAddModal(false)}>取消</button>
                <button type="submit" className="dm-btn-submit">添加设备</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* WiFi 扫描弹窗 */}
      {showScanModal && (
        <div className="dm-modal-overlay" onClick={() => setShowScanModal(false)}>
          <div className="dm-modal dm-modal-wide" onClick={e => e.stopPropagation()}>
            <div className="dm-modal-header">
              <h2>扫描局域网设备</h2>
              <button className="dm-modal-close" onClick={() => setShowScanModal(false)}>✕</button>
            </div>
            <div className="dm-modal-body">
              <div className="dm-form-group" style={{ marginBottom: '1.5rem', display: 'flex', gap: '0.75rem', alignItems: 'flex-end' }}>
                <div style={{ flex: 1 }}>
                  <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.88rem', color: '#475569', fontWeight: '500' }}>扫描网段 (CIDR 格式)</label>
                  <input 
                    type="text" 
                    value={scanSubnet} 
                    onChange={e => setScanSubnet(e.target.value)} 
                    placeholder="例如: 192.168.31.0/24" 
                    disabled={scanning}
                    style={{ margin: 0 }}
                  />
                </div>
                <button 
                  type="button" 
                  className="dm-btn-submit" 
                  onClick={() => handleScan(scanSubnet)} 
                  disabled={scanning}
                  style={{ height: '42px', display: 'flex', alignItems: 'center', gap: '0.25rem', whiteSpace: 'nowrap' }}
                >
                  {scanning ? '扫描中...' : '开始扫描'}
                </button>
              </div>

              {scanCacheTime && !scanning && (
                <p style={{ fontSize: '0.78rem', color: '#94a3b8', margin: '0 0 0.75rem', textAlign: 'right' }}>
                  缓存自 {new Date(scanCacheTime).toLocaleString('zh-CN')}
                </p>
              )}

              {scanning ? (
                <div className="dm-scan-status">
                  <div className="dm-scan-spinner"></div>
                  <p>正在使用 Nmap 扫描 {scanSubnet} 网段的设备...</p>
                </div>
              ) : (
                <div className="dm-wifi-list">
                  {scanResults.length > 0 ? scanResults.map((res, i) => (
                    <div className="dm-wifi-item" key={i} onClick={() => handleAddFromScan(res)}>
                      <div className="dm-wifi-item-info">
                        <span className="dm-wifi-ssid">
                          {res.ssid} 
                          <span style={{ fontSize: '0.8rem', color: '#3b82f6', marginLeft: '8px', fontWeight: '600' }}>{res.type}</span>
                          {res.vendor && res.vendor !== '未知' && (
                            <span style={{ fontSize: '0.75rem', color: '#64748b', marginLeft: '6px', background: '#f1f5f9', padding: '1px 5px', borderRadius: '4px' }}>{res.vendor}</span>
                          )}
                        </span>
                        <span className="dm-wifi-ip">{res.ip} | MAC: {res.mac}</span>
                      </div>
                      <span className="dm-wifi-item-action">添加设备</span>
                    </div>
                  )) : (
                    <p style={{ textAlign: 'center', color: '#94a3b8', padding: '1rem 0' }}>未发现存活设备，您可以调整网段后重新扫描</p>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 编辑设备弹窗 */}
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
                <div className="dm-form-group">
                  <label>控制服务端口号</label>
                  <input type="number" value={formData.port} onChange={e => setFormData({...formData, port: parseInt(e.target.value) || 9000})} min="1" max="65535" />
                  <span className="dm-form-hint">树莓派控制服务默认监听 9000 端口</span>
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

      {/* Token 管理弹窗 */}
      {showTokenModal && (
        <div className="dm-modal-overlay" onClick={() => setShowTokenModal(false)}>
          <div className="dm-modal dm-modal-wide" onClick={e => e.stopPropagation()}>
            <div className="dm-modal-header">
              <h2>🔑 设备 Token 管理 - {tokenDevice?.name}</h2>
              <button className="dm-modal-close" onClick={() => setShowTokenModal(false)}>✕</button>
            </div>
            <div className="dm-modal-body">
              <p className="dm-token-desc">设备 Token 用于树莓派 IoT 客户端向后端上报遥测数据的认证凭证。</p>
              <button className="dm-btn-submit" onClick={handleCreateToken} style={{ marginBottom: '1rem' }}>
                生成新 Token
              </button>
              {newToken && (
                <div className="dm-token-new">
                  <p>✅ 新 Token 已生成（请妥善保存，仅显示一次）：</p>
                  <code className="dm-token-code">{newToken}</code>
                </div>
              )}
              <div className="dm-token-list">
                {tokens.length === 0 ? (
                  <p style={{ color: '#94a3b8' }}>暂无 Token，请点击上方按钮生成</p>
                ) : tokens.map(t => (
                  <div className="dm-token-item" key={t.id}>
                    <code className="dm-token-value">{t.token}</code>
                    <div className="dm-token-meta">
                      <span className={`dm-token-status ${t.is_active ? 'active' : 'inactive'}`}>
                        {t.is_active ? '有效' : '已禁用'}
                      </span>
                      <span>{t.note}</span>
                      <span>{t.created_at ? new Date(t.created_at).toLocaleString('zh-CN') : ''}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 删除设备确认弹窗（统一风格） */}
      {deleteConfirm && (
        <div className="dm-modal-overlay" onClick={() => setDeleteConfirm(null)}>
          <div className="dm-modal dm-delete-modal" onClick={e => e.stopPropagation()}>
            <div className="dm-delete-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="15" y1="9" x2="9" y2="15"></line>
                <line x1="9" y1="9" x2="15" y2="15"></line>
              </svg>
            </div>
            <h3>确认删除</h3>
            <p>确定要删除设备 <strong>{deleteConfirm.name}</strong> 吗？此操作不可撤销。</p>
            <div className="dm-modal-footer" style={{ justifyContent: 'center', background: 'transparent', borderTop: 'none', padding: '0' }}>
              <button className="dm-btn-cancel" onClick={() => setDeleteConfirm(null)}>
                取消
              </button>
              <button className="dm-btn-delete" onClick={() => handleDelete(deleteConfirm.id)}>
                确认删除
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
