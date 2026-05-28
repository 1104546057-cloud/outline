import { useState, useEffect, useRef, useCallback } from 'react'
import '../styles/LiveVideo.css'

/**
 * 实时画面页面
 *
 * 从无人设备获取 MJPEG 摄像头视频流，通过后端代理转发。
 * 支持多画面网格布局、截图、全屏等功能。
 */

const CAMERA_PORT = 8080

function LiveVideo() {
  const [devices, setDevices] = useState([])
  const [loading, setLoading] = useState(true)
  const [layout, setLayout] = useState(4) // 1, 4, 6, 9
  const [activeStreams, setActiveStreams] = useState([]) // [{deviceId, device, status}]
  const [fullscreenIndex, setFullscreenIndex] = useState(null) // 全屏的画面索引
  const [toast, setToast] = useState(null)
  const initializedRef = useRef(false) // 标记是否已自动初始化过

  // 获取设备列表
  const fetchDevices = useCallback(async () => {
    try {
      const res = await fetch('/api/devices', { credentials: 'include' })
      if (res.status === 401) {
        window.location.href = '/login'
        return
      }
      if (!res.ok) throw new Error('获取设备列表失败')
      const data = await res.json()
      setDevices(data)
    } catch (err) {
      console.error('获取设备列表失败:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchDevices()
    // 每30秒刷新设备列表
    const timer = setInterval(fetchDevices, 30000)
    return () => clearInterval(timer)
  }, [fetchDevices])

  // 设备列表加载完成后，自动打开所有设备画面（在线排前面）
  useEffect(() => {
    if (initializedRef.current || devices.length === 0) return
    initializedRef.current = true

    // 排序：在线设备排前面，离线设备排后面
    const sorted = [...devices].sort((a, b) => {
      if (a.status === 'online' && b.status !== 'online') return -1
      if (a.status !== 'online' && b.status === 'online') return 1
      return a.id - b.id
    })

    // 自动选择合适布局
    const count = sorted.length
    let autoLayout = 1
    if (count >= 9) autoLayout = 9
    else if (count >= 5) autoLayout = 6
    else if (count >= 2) autoLayout = 4
    else autoLayout = 1
    setLayout(autoLayout)

    // 将全部设备添加到画面
    setActiveStreams(sorted.map(device => ({
      deviceId: device.id,
      device,
      status: 'loading',
      errorMsg: '',
    })))
  }, [devices])

  // 添加视频流画面
  const addStream = (deviceId) => {
    if (!deviceId) return
    const device = devices.find(d => d.id === parseInt(deviceId))
    if (!device) return

    // 检查是否已存在
    if (activeStreams.some(s => s.deviceId === device.id)) {
      showToast('该设备已在画面中', 'error')
      return
    }

    setActiveStreams(prev => [...prev, {
      deviceId: device.id,
      device,
      status: 'loading', // loading, streaming, error
      errorMsg: '',
    }])
  }

  // 移除视频流画面
  const removeStream = (deviceId) => {
    setActiveStreams(prev => prev.filter(s => s.deviceId !== deviceId))
    if (fullscreenIndex !== null) {
      setFullscreenIndex(null)
    }
  }

  // 更新流状态
  const updateStreamStatus = (deviceId, status, errorMsg = '') => {
    setActiveStreams(prev => prev.map(s =>
      s.deviceId === deviceId ? { ...s, status, errorMsg } : s
    ))
  }

  // 添加全部在线设备
  const addAllOnlineDevices = () => {
    const onlineDevices = devices.filter(d => d.status === 'online')
    if (onlineDevices.length === 0) {
      showToast('没有在线的设备', 'error')
      return
    }

    const maxSlots = layout
    const existing = activeStreams.map(s => s.deviceId)
    const toAdd = onlineDevices
      .filter(d => !existing.includes(d.id))
      .slice(0, maxSlots - activeStreams.length)

    if (toAdd.length === 0) {
      showToast('所有在线设备已在画面中', 'error')
      return
    }

    setActiveStreams(prev => [
      ...prev,
      ...toAdd.map(device => ({
        deviceId: device.id,
        device,
        status: 'loading',
        errorMsg: '',
      }))
    ])
  }

  // 清除所有画面
  const clearAllStreams = () => {
    setActiveStreams([])
    setFullscreenIndex(null)
  }

  // 切换布局
  const changeLayout = (newLayout) => {
    setLayout(newLayout)
    // 如果当前画面超出布局限制，不裁剪，只是变更布局
  }

  // 截图功能
  const captureSnapshot = async (deviceId) => {
    const device = devices.find(d => d.id === deviceId)
    if (!device) return

    try {
      const res = await fetch(`/api/devices/${deviceId}/camera/snapshot`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error('截图失败')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
      a.download = `${device.name}_${timestamp}.jpg`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      showToast('截图已保存', 'success')
    } catch (err) {
      showToast('截图失败: ' + err.message, 'error')
    }
  }

  // 全屏切换
  const toggleFullscreen = (index) => {
    setFullscreenIndex(fullscreenIndex === index ? null : index)
  }

  // Toast 消息
  const showToast = (msg, type = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }

  // ESC 退出全屏
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && fullscreenIndex !== null) {
        setFullscreenIndex(null)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [fullscreenIndex])

  // 可用设备（还未添加到画面中的）
  const availableDevices = devices.filter(
    d => !activeStreams.some(s => s.deviceId === d.id)
  )

  return (
    <div className="live-video-page" id="live-video-page">
      {/* 页头 */}
      <div className="lv-header">
        <h1>📹 实时画面</h1>
        <p>查看无人设备摄像头实时视频流</p>
      </div>

      {/* 工具栏 */}
      <div className="lv-toolbar" id="lv-toolbar">
        <div className="lv-toolbar-left">
          {/* 设备选择 */}
          <select
            className="lv-device-select"
            id="lv-device-select"
            defaultValue=""
            onChange={(e) => {
              addStream(e.target.value)
              e.target.value = ''
            }}
          >
            <option value="" disabled>选择设备添加到画面...</option>
            {availableDevices.map(d => (
              <option key={d.id} value={d.id}>
                {d.name} ({d.ip_address}) - {d.status === 'online' ? '在线' : '离线'}
              </option>
            ))}
          </select>

          {/* 添加全部在线设备 */}
          <button
            className="lv-btn lv-btn-primary"
            onClick={addAllOnlineDevices}
            disabled={loading}
            id="lv-add-all-btn"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="7" height="7"></rect>
              <rect x="14" y="3" width="7" height="7"></rect>
              <rect x="14" y="14" width="7" height="7"></rect>
              <rect x="3" y="14" width="7" height="7"></rect>
            </svg>
            添加全部在线
          </button>

          {activeStreams.length > 0 && (
            <button
              className="lv-btn lv-btn-danger"
              onClick={clearAllStreams}
              id="lv-clear-all-btn"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
              清空画面
            </button>
          )}
        </div>

        <div className="lv-toolbar-right">
          {/* 布局切换 */}
          <div className="lv-layout-btns">
            {[1, 4, 6, 9].map(n => (
              <button
                key={n}
                className={`lv-layout-btn ${layout === n ? 'active' : ''}`}
                onClick={() => changeLayout(n)}
                title={`${n} 宫格`}
              >
                {n === 1 ? '单画面' : `${n}宫格`}
              </button>
            ))}
          </div>

          {/* 刷新设备 */}
          <button
            className="lv-btn"
            onClick={fetchDevices}
            title="刷新设备列表"
            id="lv-refresh-btn"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="23 4 23 10 17 10"></polyline>
              <polyline points="1 20 1 14 7 14"></polyline>
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
            </svg>
          </button>
        </div>
      </div>

      {/* 视频网格 或 空状态 */}
      {activeStreams.length === 0 ? (
        <div className="lv-empty-state" id="lv-empty-state">
          <div className="lv-empty-icon">
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <polygon points="23 7 16 12 23 17 23 7"></polygon>
              <rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
            </svg>
          </div>
          <div className="lv-empty-title">暂无实时画面</div>
          <div className="lv-empty-desc">
            从上方工具栏选择设备，或点击"添加全部在线"按钮开始查看摄像头画面
          </div>
        </div>
      ) : (
        <div className={`lv-video-grid layout-${layout}`} id="lv-video-grid">
          {activeStreams.map((stream, idx) => (
            <VideoCard
              key={stream.deviceId}
              stream={stream}
              index={idx}
              isFullscreen={fullscreenIndex === idx}
              onRemove={() => removeStream(stream.deviceId)}
              onCapture={() => captureSnapshot(stream.deviceId)}
              onToggleFullscreen={() => toggleFullscreen(idx)}
              onStatusChange={(status, err) => updateStreamStatus(stream.deviceId, status, err)}
            />
          ))}

          {/* 空槽位 */}
          {Array.from({ length: Math.max(0, layout - activeStreams.length) }, (_, i) => (
            <div key={`empty-${i}`} className="lv-video-card">
              <div className="lv-video-placeholder">
                <div className="lv-placeholder-icon">
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="12" y1="5" x2="12" y2="19"></line>
                    <line x1="5" y1="12" x2="19" y2="12"></line>
                  </svg>
                </div>
                <div className="lv-placeholder-text">空闲画面位</div>
                <div className="lv-placeholder-hint">从工具栏选择设备添加</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div className={`lv-toast ${toast.type}`}>
          {toast.type === 'success' ? '✓' : '✕'} {toast.msg}
        </div>
      )}
    </div>
  )
}


/**
 * 视频卡片组件
 * 单个设备的视频流展示
 */
function VideoCard({ stream, index, isFullscreen, onRemove, onCapture, onToggleFullscreen, onStatusChange }) {
  const { device, status, errorMsg } = stream
  const imgRef = useRef(null)
  const retryTimerRef = useRef(null)

  // 构建流 URL（通过后端代理）
  const streamUrl = `/api/devices/${device.id}/camera/stream`

  // 处理图片加载成功
  const handleLoad = () => {
    onStatusChange('streaming')
    // 清除重试定时器
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current)
      retryTimerRef.current = null
    }
  }

  // 处理图片加载失败
  const handleError = () => {
    onStatusChange('error', '无法连接到摄像头，请确认设备已开启摄像头服务')
    // 5秒后自动重试
    if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
    retryTimerRef.current = setTimeout(() => {
      retryStream()
    }, 5000)
  }

  // 重试连接
  const retryStream = () => {
    onStatusChange('loading')
    if (imgRef.current) {
      // 追加时间戳破缓存
      imgRef.current.src = `${streamUrl}?t=${Date.now()}`
    }
  }

  // 清理
  useEffect(() => {
    return () => {
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
    }
  }, [])

  const statusLabel = {
    loading: '连接中...',
    streaming: '直播中',
    error: '连接失败',
  }[status] || ''

  const statusDotClass = {
    loading: 'loading',
    streaming: 'online',
    error: 'error',
  }[status] || 'offline'

  return (
    <div className={`lv-video-card ${isFullscreen ? 'fullscreen' : ''}`} id={`lv-video-card-${device.id}`}>
      {/* 卡片头 */}
      <div className="lv-video-card-header">
        <div className="lv-video-card-info">
          <span className="lv-video-card-name">{device.name}</span>
          <span className="lv-video-card-ip">{device.ip_address}</span>
          <div className="lv-video-card-status">
            <span className={`lv-status-dot ${statusDotClass}`}></span>
            <span>{statusLabel}</span>
          </div>
        </div>

        <div className="lv-video-card-actions">
          {/* 截图 */}
          <button
            className="lv-card-btn"
            onClick={onCapture}
            title="截图保存"
            disabled={status !== 'streaming'}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path>
              <circle cx="12" cy="13" r="4"></circle>
            </svg>
          </button>

          {/* 全屏 */}
          <button
            className="lv-card-btn"
            onClick={onToggleFullscreen}
            title={isFullscreen ? '退出全屏' : '全屏'}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              {isFullscreen ? (
                <>
                  <polyline points="4 14 10 14 10 20"></polyline>
                  <polyline points="20 10 14 10 14 4"></polyline>
                  <line x1="14" y1="10" x2="21" y2="3"></line>
                  <line x1="3" y1="21" x2="10" y2="14"></line>
                </>
              ) : (
                <>
                  <polyline points="15 3 21 3 21 9"></polyline>
                  <polyline points="9 21 3 21 3 15"></polyline>
                  <line x1="21" y1="3" x2="14" y2="10"></line>
                  <line x1="3" y1="21" x2="10" y2="14"></line>
                </>
              )}
            </svg>
          </button>

          {/* 关闭 */}
          <button
            className="lv-card-btn"
            onClick={onRemove}
            title="关闭画面"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
      </div>

      {/* 视频容器 */}
      <div className="lv-video-container">
        {/* LIVE 标识 */}
        {status === 'streaming' && (
          <div className="lv-live-badge">
            <span className="lv-live-dot"></span>
            LIVE
          </div>
        )}

        {/* MJPEG 图片流 */}
        <img
          ref={imgRef}
          className="lv-video-stream"
          src={streamUrl}
          alt={`${device.name} 摄像头`}
          onLoad={handleLoad}
          onError={handleError}
          style={{ display: status === 'streaming' ? 'block' : 'none' }}
        />

        {/* 加载中覆盖层 */}
        {status === 'loading' && (
          <div className="lv-loading-overlay">
            <div className="lv-spinner"></div>
            <div className="lv-loading-text">正在连接摄像头...</div>
          </div>
        )}

        {/* 错误覆盖层 */}
        {status === 'error' && (
          <div className="lv-error-overlay">
            <div className="lv-error-icon">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="15" y1="9" x2="9" y2="15"></line>
                <line x1="9" y1="9" x2="15" y2="15"></line>
              </svg>
            </div>
            <div className="lv-error-text">{errorMsg}</div>
            <button className="lv-error-retry" onClick={retryStream}>
              重新连接
            </button>
          </div>
        )}

        {/* 底部信息条 */}
        {status === 'streaming' && (
          <div className="lv-video-overlay-info">
            <span className="lv-video-resolution">640×480</span>
            <span className="lv-video-fps">15 fps</span>
          </div>
        )}
      </div>
    </div>
  )
}


export default LiveVideo
