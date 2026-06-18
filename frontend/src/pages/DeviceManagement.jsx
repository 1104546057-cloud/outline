import { useState, useEffect, useCallback } from 'react'
import ThemedSelect from '../components/ThemedSelect'
import { authFetch } from '../utils/authFetch'
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
  const defaultServerAddr = () => {
    // 优先使用缓存的地址，否则根据当前浏览器访问的主机推断
    try {
      const cached = localStorage.getItem('dwc_server_address')
      if (cached) return cached
    } catch (e) { /* ignore */ }
    const host = window.location.hostname
    return `http://${host}:8000`
  }
  const [addFormData, setAddFormData] = useState({ name: '', type: '无人车', ip_address: '', port: 9000, password: '123456', server_address: defaultServerAddr() })
  const [addSubmitting, setAddSubmitting] = useState(false)
  const [addError, setAddError] = useState('')

  // edit modal
  const [showEditModal, setShowEditModal] = useState(false)
  const [editingDevice, setEditingDevice] = useState(null)
  const [formData, setFormData] = useState({ name: '', type: '无人车', ip_address: '', port: 9000 })

  // token modal
  const [showTokenModal, setShowTokenModal] = useState(false)
  const [tokenDevice, setTokenDevice] = useState(null)
  const [tokens, setTokens] = useState([])
  
  // expanded device detail panel
  const [expandedDeviceIds, setExpandedDeviceIds] = useState(new Set())
  
  // API Fetch
  const fetchDevices = async () => {
    try {
      const res = await authFetch('/api/devices')
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
      const res = await authFetch(`/api/wifi/scan?subnet=${encodeURIComponent(targetSubnet)}`)
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

  const handleAddFromScan = (deviceInfo) => {
    // 关闭扫描弹窗，打开添加设备弹窗并自动填入扫描到的设备名称和IP
    setShowScanModal(false)
    setAddFormData({
      name: deviceInfo.ssid,
      type: deviceInfo.type,
      ip_address: deviceInfo.ip,
      port: 9000,
      password: '123456',
      server_address: defaultServerAddr(),
    })
    setAddError('')
    setShowAddModal(true)
  }

  const handleManualAdd = async (e) => {
    e.preventDefault()
    setAddError('')
    if (!addFormData.password.trim()) {
      setAddError('请输入设备连接密码')
      return
    }
    setAddSubmitting(true)
    try {
      const res = await authFetch('/api/devices', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(addFormData)
      })
      if (res.ok) {
        // 缓存成功使用的服务器地址
        try { localStorage.setItem('dwc_server_address', addFormData.server_address) } catch (e) { /* ignore */ }
        setShowAddModal(false)
        setAddFormData({ name: '', type: '无人车', ip_address: '', port: 9000, password: '123456', server_address: defaultServerAddr() })
        fetchDevices()
      } else {
        const err = await res.json()
        setAddError(err.detail || '添加失败')
      }
    } catch (e) {
      setAddError('网络错误')
    } finally {
      setAddSubmitting(false)
    }
  }

  const handleDelete = async (id) => {
    try {
      const res = await authFetch(`/api/devices/${id}`, { method: 'DELETE' })
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
      const res = await authFetch(`/api/devices/${editingDevice.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
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
    try {
      const res = await authFetch(`/api/devices/${device.id}/tokens`)
      if (res.ok) {
        const data = await res.json()
        setTokens(data)
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
    if (!lastSeen) return '等待上报'
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
      const temp = extra.cpu_temp_c
      const tempColor = temp > 70 ? '#ef4444' : temp > 55 ? '#f59e0b' : '#22c55e'
      items.push({ label: '🌡️ CPU', value: `${temp}°C`, color: tempColor })
    }
    if (extra.cpu && extra.cpu.total !== undefined) {
      items.push({ label: '⚙️ CPU', value: `${extra.cpu.total}%` })
    }
    if (extra.gpu && extra.gpu.load_percent !== undefined) {
      const gpuLoad = extra.gpu.load_percent
      const gpuColor = gpuLoad > 80 ? '#ef4444' : gpuLoad > 50 ? '#f59e0b' : '#10b981'
      items.push({ label: '🎮 GPU', value: `${gpuLoad}%`, color: gpuColor })
    }
    if (extra.memory && extra.memory.physical) {
      items.push({ label: '💾 内存', value: `${extra.memory.physical.percent}%` })
    }
    if (extra.system && extra.system.uptime) {
      items.push({ label: '⏱️ 运行', value: extra.system.uptime })
    }
    if (extra.power) {
      const pw = extra.power
      const pwColor = pw.percent > 50 ? '#22c55e' : pw.percent > 20 ? '#f59e0b' : '#ef4444'
      items.push({ label: '🔋 电源', value: `${Number(pw.voltage_V).toFixed(1)}V (${pw.percent}%)`, color: pwColor })
    }
    if (extra.ups) {
      items.push({ label: '🔌 UPS', value: `${Number(extra.ups.voltage_V).toFixed(1)}V / ${extra.ups.current_A}A` })
    }
    if (extra.gps) {
      const gpsStatus = extra.gps.status === 'fix' ? '已定位' : '未定位'
      items.push({ label: '📡 GPS', value: gpsStatus })
    }
    return items.length > 0 ? items : null
  }

  const formatBytes = useCallback((bytes) => {
    if (bytes === 0) return '0 B'
    const units = ['B', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(1024))
    return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`
  }, [])

  const toggleExpanded = (deviceId) => {
    setExpandedDeviceIds(prev => {
      const next = new Set(prev)
      if (next.has(deviceId)) {
        next.delete(deviceId)
      } else {
        next.add(deviceId)
      }
      return next
    })
  }

  const renderSystemPanel = (device) => {
    const extra = device.extra
    if (!extra) return null
    const sections = []

    // CPU 详情
    if (extra.cpu) {
      const cpu = extra.cpu
      sections.push(
        <div className="dm-sys-section" key="cpu">
          <div className="dm-sys-section-title">⚙️ CPU 监控</div>
          <div className="dm-sys-row">
            <span className="dm-sys-label">总使用率</span>
            <span className="dm-sys-value">{cpu.total}%</span>
          </div>
          <div className="dm-sys-bar-track">
            <div className="dm-sys-bar-fill" style={{ width: `${Math.min(100, cpu.total)}%`, background: cpu.total > 80 ? '#ef4444' : cpu.total > 50 ? '#f59e0b' : '#22c55e' }} />
          </div>
          {cpu.per_core && (
            <div className="dm-sys-cores">
              {cpu.per_core.map((val, i) => (
                <div className="dm-sys-core" key={i}>
                  <span className="dm-sys-core-label">核{i}</span>
                  <div className="dm-sys-core-bar-track">
                    <div className="dm-sys-core-bar-fill" style={{ width: `${Math.min(100, val)}%`, background: val > 80 ? '#ef4444' : val > 50 ? '#f59e0b' : '#3b82f6' }} />
                  </div>
                  <span className="dm-sys-core-pct">{val}%</span>
                </div>
              ))}
            </div>
          )}
          <div className="dm-sys-meta">
            {cpu.core_count && <span>核心数: {cpu.core_count}</span>}
            {cpu.freq_current_mhz && <span>频率: {cpu.freq_current_mhz} MHz</span>}
            {extra.cpu_temp_c !== undefined && <span>温度: {extra.cpu_temp_c}°C</span>}
          </div>
        </div>
      )
    }

    // GPU 监控
    if (extra.gpu) {
      const gpu = extra.gpu
      sections.push(
        <div className="dm-sys-section" key="gpu">
          <div className="dm-sys-section-title">🎮 GPU 监控</div>
          {gpu.load_percent !== undefined && (
            <>
              <div className="dm-sys-row">
                <span className="dm-sys-label">GPU 使用率</span>
                <span className="dm-sys-value">{gpu.load_percent}%</span>
              </div>
              <div className="dm-sys-bar-track">
                <div className="dm-sys-bar-fill" style={{ width: `${Math.min(100, gpu.load_percent)}%`, background: gpu.load_percent > 80 ? '#ef4444' : gpu.load_percent > 50 ? '#f59e0b' : '#10b981' }} />
              </div>
            </>
          )}
          <div className="dm-sys-meta">
            {gpu.freq_current_mhz !== undefined && <span>当前频率: {gpu.freq_current_mhz} MHz</span>}
            {gpu.freq_max_mhz !== undefined && <span>最大频率: {gpu.freq_max_mhz} MHz</span>}
            {gpu.temp_c !== undefined && <span>温度: {gpu.temp_c}°C</span>}
          </div>
        </div>
      )
    }

    // 内存详情
    if (extra.memory) {
      const mem = extra.memory
      sections.push(
        <div className="dm-sys-section" key="memory">
          <div className="dm-sys-section-title">💾 内存监控</div>
          {mem.physical && (
            <>
              <div className="dm-sys-row">
                <span className="dm-sys-label">物理内存</span>
                <span className="dm-sys-value">{mem.physical.used_gb} / {mem.physical.total_gb} GB ({mem.physical.percent}%)</span>
              </div>
              <div className="dm-sys-bar-track">
                <div className="dm-sys-bar-fill" style={{ width: `${Math.min(100, mem.physical.percent)}%`, background: mem.physical.percent > 85 ? '#ef4444' : mem.physical.percent > 60 ? '#f59e0b' : '#3b82f6' }} />
              </div>
            </>
          )}
          {mem.swap && mem.swap.total_gb > 0 && (
            <>
              <div className="dm-sys-row" style={{ marginTop: '0.5rem' }}>
                <span className="dm-sys-label">Swap</span>
                <span className="dm-sys-value">{mem.swap.used_gb} / {mem.swap.total_gb} GB ({mem.swap.percent}%)</span>
              </div>
              <div className="dm-sys-bar-track">
                <div className="dm-sys-bar-fill" style={{ width: `${Math.min(100, mem.swap.percent)}%`, background: '#a855f7' }} />
              </div>
            </>
          )}
        </div>
      )
    }

    // 磁盘详情
    if (extra.disk && extra.disk.length > 0) {
      sections.push(
        <div className="dm-sys-section" key="disk">
          <div className="dm-sys-section-title">💿 磁盘监控</div>
          {extra.disk.map((d, i) => (
            <div key={i} style={{ marginBottom: i < extra.disk.length - 1 ? '0.6rem' : 0 }}>
              <div className="dm-sys-row">
                <span className="dm-sys-label">{d.mountpoint}</span>
                <span className="dm-sys-value">{d.used_gb} / {d.total_gb} GB ({d.percent}%)</span>
              </div>
              <div className="dm-sys-bar-track">
                <div className="dm-sys-bar-fill" style={{ width: `${Math.min(100, d.percent)}%`, background: d.percent > 90 ? '#ef4444' : d.percent > 70 ? '#f59e0b' : '#06b6d4' }} />
              </div>
              <div className="dm-sys-meta">
                <span>{d.device}</span>
                <span>{d.fstype}</span>
                <span>可用: {d.free_gb} GB</span>
              </div>
            </div>
          ))}
        </div>
      )
    }

    // 网络详情
    if (extra.network) {
      sections.push(
        <div className="dm-sys-section" key="network">
          <div className="dm-sys-section-title">🌐 网络监控</div>
          {Object.entries(extra.network).map(([nic, stats]) => (
            <div key={nic} className="dm-sys-nic">
              <div className="dm-sys-row">
                <span className="dm-sys-label dm-sys-nic-name">
                  {nic}
                  {stats.is_up !== undefined && (
                    <span className={`dm-sys-nic-status ${stats.is_up ? 'up' : 'down'}`}>
                      {stats.is_up ? 'UP' : 'DOWN'}
                    </span>
                  )}
                </span>
                {stats.speed_mbps > 0 && <span className="dm-sys-value">{stats.speed_mbps} Mbps</span>}
              </div>
              <div className="dm-sys-nic-stats">
                <div className="dm-sys-nic-stat">
                  <span className="dm-sys-nic-arrow up">↑</span>
                  <span>{formatBytes(stats.bytes_sent)}</span>
                </div>
                <div className="dm-sys-nic-stat">
                  <span className="dm-sys-nic-arrow down">↓</span>
                  <span>{formatBytes(stats.bytes_recv)}</span>
                </div>
                {(stats.errin > 0 || stats.errout > 0) && (
                  <span className="dm-sys-nic-err">错误: {stats.errin + stats.errout}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )
    }

    // UPS 电源详情
    if (extra.ups) {
      const ups = extra.ups
      const pctColor = ups.percent > 60 ? '#22c55e' : ups.percent > 20 ? '#f59e0b' : '#ef4444'
      sections.push(
        <div className="dm-sys-section" key="ups">
          <div className="dm-sys-section-title">🔋 UPS 电源</div>
          <div className="dm-sys-row">
            <span className="dm-sys-label">电量</span>
            <span className="dm-sys-value" style={{ color: pctColor }}>{ups.percent}%</span>
          </div>
          <div className="dm-sys-bar-track">
            <div className="dm-sys-bar-fill" style={{ width: `${Math.min(100, ups.percent)}%`, background: pctColor }} />
          </div>
          <div className="dm-sys-info-grid" style={{ marginTop: '0.5rem' }}>
            <div className="dm-sys-info-item">
              <span className="dm-sys-info-label">电压</span>
              <span className="dm-sys-info-value">{Number(ups.voltage_V).toFixed(1)} V</span>
            </div>
            <div className="dm-sys-info-item">
              <span className="dm-sys-info-label">电流</span>
              <span className="dm-sys-info-value">{ups.current_A} A</span>
            </div>
            <div className="dm-sys-info-item">
              <span className="dm-sys-info-label">功率</span>
              <span className="dm-sys-info-value">{ups.power_W} W</span>
            </div>
          </div>
        </div>
      )
    }

    // ROS 电源详情
    if (extra.power) {
      const pw = extra.power
      const pctColor = pw.percent > 50 ? '#22c55e' : pw.percent > 20 ? '#f59e0b' : '#ef4444'
      sections.push(
        <div className="dm-sys-section" key="power">
          <div className="dm-sys-section-title">🔋 ROS 电源</div>
          <div className="dm-sys-row">
            <span className="dm-sys-label">电量</span>
            <span className="dm-sys-value" style={{ color: pctColor }}>{pw.percent}%</span>
          </div>
          <div className="dm-sys-bar-track">
            <div className="dm-sys-bar-fill" style={{ width: `${Math.min(100, pw.percent)}%`, background: pctColor }} />
          </div>
          <div className="dm-sys-info-grid" style={{ marginTop: '0.5rem' }}>
            <div className="dm-sys-info-item">
              <span className="dm-sys-info-label">电压</span>
              <span className="dm-sys-info-value">{Number(pw.voltage_V).toFixed(1)} V</span>
            </div>
            {pw.charging !== undefined && (
              <div className="dm-sys-info-item">
                <span className="dm-sys-info-label">充电状态</span>
                <span className="dm-sys-info-value" style={{ color: pw.charging ? '#22c55e' : '#94a3b8' }}>{pw.charging ? '充电中' : '未充电'}</span>
              </div>
            )}
            {pw.charging_current_A !== undefined && (
              <div className="dm-sys-info-item">
                <span className="dm-sys-info-label">充电电流</span>
                <span className="dm-sys-info-value">{pw.charging_current_A} A</span>
              </div>
            )}
          </div>
        </div>
      )
    }

    // 机器人诊断状态
    if (extra.robot_status) {
      const rs = extra.robot_status
      sections.push(
        <div className="dm-sys-section" key="robot_status">
          <div className="dm-sys-section-title">🛡️ 机器人安全与诊断</div>
          <div className="dm-sys-info-grid">
            {rs.chassis_security !== undefined && (
              <div className="dm-sys-info-item">
                <span className="dm-sys-info-label">底盘安全锁定</span>
                <span className="dm-sys-info-value" style={{ color: rs.chassis_security === 1 ? '#22c55e' : '#ef4444' }}>
                  {rs.chassis_security === 1 ? '解除锁定 (正常)' : `已锁定 (${rs.chassis_security})`}
                </span>
              </div>
            )}
            {rs.selfcheck !== undefined && (
              <div className="dm-sys-info-item">
                <span className="dm-sys-info-label">自检状态码</span>
                <span className="dm-sys-info-value" style={{ color: rs.selfcheck === 0 ? '#22c55e' : '#f59e0b' }}>
                  {rs.selfcheck === 0 ? '全系统正常 (0)' : `异常 (0x${rs.selfcheck.toString(16)})`}
                </span>
              </div>
            )}
            {rs.red_flag !== undefined && (
              <div className="dm-sys-info-item">
                <span className="dm-sys-info-label">急停状态</span>
                <span className="dm-sys-info-value" style={{ color: rs.red_flag === 1 ? '#ef4444' : '#22c55e' }}>
                  {rs.red_flag === 1 ? '急停拍下' : '正常'}
                </span>
              </div>
            )}
            {rs.recharge_flag !== undefined && (
              <div className="dm-sys-info-item">
                <span className="dm-sys-info-label">回充状态</span>
                <span className="dm-sys-info-value" style={{ color: rs.recharge_flag > 0 ? '#3b82f6' : '#94a3b8' }}>
                  {rs.recharge_flag > 0 ? `回充中 (${rs.recharge_flag})` : '未在回充'}
                </span>
              </div>
            )}
          </div>
        </div>
      )
    }

    // 运动状态
    if (extra.motion) {
      const mo = extra.motion
      sections.push(
        <div className="dm-sys-section" key="motion">
          <div className="dm-sys-section-title">🏎️ 底盘运动状态</div>
          <div className="dm-sys-info-grid">
            {mo.linear_x_mps !== undefined && (
              <div className="dm-sys-info-item">
                <span className="dm-sys-info-label">线速度</span>
                <span className="dm-sys-info-value">{mo.linear_x_mps.toFixed(2)} m/s</span>
              </div>
            )}
            {mo.angular_z_radps !== undefined && (
              <div className="dm-sys-info-item">
                <span className="dm-sys-info-label">角速度</span>
                <span className="dm-sys-info-value">{mo.angular_z_radps.toFixed(2)} rad/s</span>
              </div>
            )}
          </div>
          {mo.accel && (
            <div className="dm-sys-info-grid" style={{ marginTop: '0.5rem' }}>
              <div className="dm-sys-info-item">
                <span className="dm-sys-info-label">加速度 X</span>
                <span className="dm-sys-info-value">{mo.accel.x.toFixed(2)}</span>
              </div>
              <div className="dm-sys-info-item">
                <span className="dm-sys-info-label">加速度 Y</span>
                <span className="dm-sys-info-value">{mo.accel.y.toFixed(2)}</span>
              </div>
              <div className="dm-sys-info-item">
                <span className="dm-sys-info-label">加速度 Z</span>
                <span className="dm-sys-info-value">{mo.accel.z.toFixed(2)}</span>
              </div>
            </div>
          )}
        </div>
      )
    }

    // 硬件与外设详情
    if (extra.hardware || (extra.usb_devices && extra.usb_devices.length > 0)) {
      sections.push(
        <div className="dm-sys-section" key="hardware">
          <div className="dm-sys-section-title">🔌 硬件与外设</div>
          {extra.hardware && (
            <div className="dm-sys-info-grid" style={{ marginBottom: '0.75rem' }}>
              {Array.isArray(extra.hardware) 
                ? extra.hardware.map((item, index) => (
                    <div className="dm-sys-info-item" key={index}>
                      <span className="dm-sys-info-label">{item.label}</span>
                      <span className="dm-sys-info-value" style={{ fontSize: '0.72rem', wordBreak: 'break-all' }}>{item.value}</span>
                    </div>
                  ))
                : Object.entries(extra.hardware).map(([key, value]) => (
                    <div className="dm-sys-info-item" key={key}>
                      <span className="dm-sys-info-label">{key}</span>
                      <span className="dm-sys-info-value" style={{ fontSize: '0.72rem', wordBreak: 'break-all' }}>{value}</span>
                    </div>
                  ))
              }
            </div>
          )}
          {extra.hw_diagram && (
            <div>
              <div className="dm-sys-label" style={{ marginBottom: '0.4rem' }}>主板引脚结构图</div>
              <div className="dm-hardware-diagram">
                {extra.hw_diagram}
              </div>
            </div>
          )}
          {extra.usb_devices && extra.usb_devices.length > 0 && (
            <div>
              <div className="dm-sys-label" style={{ marginTop: '0.6rem', marginBottom: '0.4rem' }}>USB 外设列表</div>
              <ul className="dm-hardware-list">
                {extra.usb_devices.map((dev, i) => (
                  <li key={i} style={{ marginBottom: '0.2rem' }}>{dev}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )
    }

    // 系统信息
    if (extra.system) {
      const sys = extra.system
      sections.push(
        <div className="dm-sys-section" key="system">
          <div className="dm-sys-section-title">🖥️ 系统信息</div>
          <div className="dm-sys-info-grid">
            {sys.hostname && (
              <div className="dm-sys-info-item">
                <span className="dm-sys-info-label">主机名</span>
                <span className="dm-sys-info-value">{sys.hostname}</span>
              </div>
            )}
            {sys.uptime && (
              <div className="dm-sys-info-item">
                <span className="dm-sys-info-label">运行时长</span>
                <span className="dm-sys-info-value">{sys.uptime}</span>
              </div>
            )}
            {sys.boot_time && (
              <div className="dm-sys-info-item">
                <span className="dm-sys-info-label">启动时间</span>
                <span className="dm-sys-info-value">{new Date(sys.boot_time).toLocaleString('zh-CN')}</span>
              </div>
            )}
            {sys.load_avg && (
              <div className="dm-sys-info-item">
                <span className="dm-sys-info-label">系统负载</span>
                <span className="dm-sys-info-value">{sys.load_avg['1min']} / {sys.load_avg['5min']} / {sys.load_avg['15min']}</span>
              </div>
            )}
          </div>
        </div>
      )
    }

    return sections.length > 0 ? sections : null
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

            {/* 扩展遥测摘要信息 */}
            {getExtraInfo(dev) && (
              <div className="dm-device-extra">
                {getExtraInfo(dev).map((item, i) => (
                  <span key={i} className="dm-extra-tag" style={item.color ? { color: item.color, borderColor: item.color + '33' } : {}}>{item.label}: {item.value}</span>
                ))}
              </div>
            )}

            {/* 系统监控详情面板 */}
            {dev.extra && (dev.extra.cpu || dev.extra.gpu || dev.extra.memory || dev.extra.disk || dev.extra.network || dev.extra.system || dev.extra.hardware || dev.extra.usb_devices || dev.extra.ups || dev.extra.power || dev.extra.robot_status || dev.extra.motion) && (
              <>
                <button
                  className="dm-expand-btn"
                  onClick={() => toggleExpanded(dev.id)}
                >
                  {expandedDeviceIds.has(dev.id) ? '▲ 收起系统监控' : '▼ 展开系统监控'}
                </button>
                {expandedDeviceIds.has(dev.id) && (
                  <div className="dm-sys-panel">
                    {renderSystemPanel(dev)}
                  </div>
                )}
              </>
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

      {/* 添加设备弹窗（手动添加 / 扫描后添加共用） */}
      {showAddModal && (
        <div className="dm-modal-overlay">
          <div className="dm-modal" onClick={e => e.stopPropagation()}>
            <div className="dm-modal-header">
              <h2>添加新设备</h2>
              <button className="dm-modal-close" onClick={() => !addSubmitting && setShowAddModal(false)}>✕</button>
            </div>
            <form onSubmit={handleManualAdd}>
              <div className="dm-modal-body">
                <div className="dm-form-group">
                  <label>设备名称</label>
                  <input type="text" value={addFormData.name} onChange={e => setAddFormData({...addFormData, name: e.target.value})} placeholder="例：巡逻无人车 01" required disabled={addSubmitting} />
                </div>
                <div className="dm-form-group">
                  <label>设备类型</label>
                  <ThemedSelect value={addFormData.type} onChange={e => setAddFormData({...addFormData, type: e.target.value})} disabled={addSubmitting}>
                    <option value="无人车">无人车</option>
                    <option value="无人机">无人机</option>
                    <option value="无人船">无人船</option>
                    <option value="未知设备">未知设备</option>
                  </ThemedSelect>
                </div>
                <div className="dm-form-group">
                  <label>IP 地址</label>
                  <input type="text" value={addFormData.ip_address} onChange={e => setAddFormData({...addFormData, ip_address: e.target.value})} placeholder="例：192.168.31.200" required disabled={addSubmitting} />
                </div>
                <div className="dm-form-group">
                  <label>控制服务端口号</label>
                  <input type="number" value={addFormData.port} onChange={e => setAddFormData({...addFormData, port: parseInt(e.target.value) || 9000})} placeholder="缺省为 9000" min="1" max="65535" disabled={addSubmitting} />
                  <span className="dm-form-hint">树莓派控制服务默认监听 9000 端口</span>
                </div>
                <div className="dm-form-group">
                  <label>连接密码 <span style={{ color: '#ef4444', fontSize: '0.75rem' }}>*必填</span></label>
                  <input type="password" value={addFormData.password} onChange={e => setAddFormData({...addFormData, password: e.target.value})} placeholder="输入设备连接密码" required disabled={addSubmitting} autoComplete="off" />
                  <span className="dm-form-hint">设备端预设的连接密码，用于验证身份并获取通信令牌</span>
                </div>
                <div className="dm-form-group">
                  <label>上报服务器地址 <span style={{ color: '#ef4444', fontSize: '0.75rem' }}>*必填</span></label>
                  <input type="text" value={addFormData.server_address} onChange={e => setAddFormData({...addFormData, server_address: e.target.value})} placeholder="例：http://192.168.31.28:8000" required disabled={addSubmitting} />
                  <span className="dm-form-hint">设备将通过此地址上报遥测数据，请填写后端服务器的局域网 IP</span>
                </div>
                {addError && <p className="dm-form-error">{addError}</p>}
              </div>
              <div className="dm-modal-footer">
                <button type="button" className="dm-btn-cancel" onClick={() => setShowAddModal(false)} disabled={addSubmitting}>取消</button>
                <button type="submit" className="dm-btn-submit" disabled={addSubmitting}>
                  {addSubmitting ? '正在连接设备...' : '添加设备'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* WiFi 扫描弹窗 */}
      {showScanModal && (
        <div className="dm-modal-overlay">
          <div className="dm-modal dm-modal-wide" onClick={e => e.stopPropagation()}>
            <div className="dm-modal-header">
              <h2>扫描局域网设备</h2>
              <button className="dm-modal-close" onClick={() => setShowScanModal(false)}>✕</button>
            </div>
            <div className="dm-modal-body">
              <div className="dm-form-group" style={{ marginBottom: '1.5rem', display: 'flex', gap: '0.75rem', alignItems: 'flex-end' }}>
                <div style={{ flex: 1 }}>
                  <label className="dm-scan-label">扫描网段 (CIDR 格式)</label>
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
                <p className="dm-scan-cache" style={{ fontSize: '0.78rem', margin: '0 0 0.75rem', textAlign: 'right' }}>
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
                          <span className="dm-device-type-inline">{res.type}</span>
                          {res.vendor && res.vendor !== '未知' && (
                            <span className="dm-vendor-tag">{res.vendor}</span>
                          )}
                        </span>
                        <span className="dm-wifi-ip">{res.ip} | MAC: {res.mac}</span>
                      </div>
                      <span className="dm-wifi-item-action">添加设备</span>
                    </div>
                  )) : (
                    <p className="dm-inline-empty" style={{ textAlign: 'center', padding: '1rem 0' }}>未发现存活设备，您可以调整网段后重新扫描</p>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 编辑设备弹窗 */}
      {showEditModal && (
        <div className="dm-modal-overlay">
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
                  <ThemedSelect value={formData.type} onChange={e => setFormData({...formData, type: e.target.value})}>
                    <option value="无人车">无人车</option>
                    <option value="无人机">无人机</option>
                    <option value="无人船">无人船</option>
                    <option value="未知设备">未知设备</option>
                  </ThemedSelect>
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

      {/* Token 查看弹窗（只读） */}
      {showTokenModal && (
        <div className="dm-modal-overlay">
          <div className="dm-modal dm-modal-wide" onClick={e => e.stopPropagation()}>
            <div className="dm-modal-header">
              <h2>🔑 设备 Token - {tokenDevice?.name}</h2>
              <button className="dm-modal-close" onClick={() => setShowTokenModal(false)}>✕</button>
            </div>
            <div className="dm-modal-body">
              <p className="dm-token-desc">设备 Token 在添加设备时自动生成，用于设备 IoT 客户端向后端上报遥测数据的认证凭证。</p>
              <div className="dm-token-list">
                {tokens.length === 0 ? (
                  <p style={{ color: '#94a3b8' }}>暂无 Token，设备注册时将自动生成</p>
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
        <div className="dm-modal-overlay">
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
