/* eslint-disable react/prop-types */
import { useEffect, useRef, useState } from 'react'
import AMapLoader from '@amap/amap-jsapi-loader'

const AMAP_KEY = import.meta.env.VITE_AMAP_API_KEY
const AMAP_SECURITY_KEY = import.meta.env.VITE_AMAP_API_SECURE_KEY

const getDeviceType = (type = '') => {
  if (type.includes('机') || type.includes('drone')) return { icon: '▲', className: 'drone' }
  if (type.includes('船') || type.includes('ship')) return { icon: '◆', className: 'ship' }
  return { icon: '●', className: 'car' }
}

export default function CampusMap({ devices, selectedDevice, onSelectDevice, mode = 'normal' }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const amapRef = useRef(null)
  const markersRef = useRef([])
  const selectedDeviceId = selectedDevice?.id
  const selectedDeviceLat = selectedDevice?.lat
  const selectedDeviceLng = selectedDevice?.lng
  const [status, setStatus] = useState(AMAP_KEY ? 'loading' : 'missing-key')

  useEffect(() => {
    if (!containerRef.current || !AMAP_KEY) return undefined
    let mounted = true
    window._AMapSecurityConfig = { securityJsCode: AMAP_SECURITY_KEY }

    AMapLoader.load({ key: AMAP_KEY, version: '2.0', plugins: [] })
      .then(AMap => {
        if (!mounted || !containerRef.current) return
        amapRef.current = AMap
        const options = {
          zoom: 16.8,
          center: [113.584101, 22.349278],
          viewMode: '2D',
          mapStyle: mode === 'normal' ? 'amap://styles/darkblue' : undefined,
          showLabel: mode === 'normal',
        }
        if (mode === 'satellite') {
          options.layers = [new AMap.TileLayer.Satellite(), new AMap.TileLayer.RoadNet({ opacity: 0.45 })]
        }
        mapRef.current = new AMap.Map(containerRef.current, options)
        setStatus('ready')
      })
      .catch(error => {
        console.error('高德地图加载失败:', error)
        if (mounted) setStatus('error')
      })

    return () => {
      mounted = false
      mapRef.current?.destroy()
      mapRef.current = null
    }
  }, [mode])

  useEffect(() => {
    const map = mapRef.current
    const AMap = amapRef.current
    if (!map || !AMap || status !== 'ready') return

    markersRef.current.forEach(marker => map.remove(marker))
    markersRef.current = []

    devices.forEach(device => {
      const lat = Number.parseFloat(device.lat)
      const lng = Number.parseFloat(device.lng)
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return

      const type = getDeviceType(device.type)
      const markerNode = document.createElement('button')
      markerNode.type = 'button'
      markerNode.className = `campus-map-marker ${type.className} ${device.status || 'offline'} ${selectedDevice?.id === device.id ? 'selected' : ''}`
      markerNode.textContent = type.icon
      markerNode.title = device.name

      const marker = new AMap.Marker({
        position: [lng, lat],
        content: markerNode,
        offset: new AMap.Pixel(-17, -17),
        zIndex: selectedDevice?.id === device.id ? 150 : 100,
      })
      marker.on('click', () => onSelectDevice?.(device))
      map.add(marker)
      markersRef.current.push(marker)

      AMap.convertFrom([lng, lat], 'gps', (convertStatus, result) => {
        if (convertStatus === 'complete' && result?.info === 'ok' && result.locations?.[0]) {
          marker.setPosition(result.locations[0])
        }
      })
    })
  }, [devices, selectedDevice, onSelectDevice, status])

  useEffect(() => {
    const map = mapRef.current
    const AMap = amapRef.current
    if (!map || !AMap || !selectedDeviceLat || !selectedDeviceLng) return
    const lng = Number.parseFloat(selectedDeviceLng)
    const lat = Number.parseFloat(selectedDeviceLat)
    if (!Number.isFinite(lng) || !Number.isFinite(lat)) return
    AMap.convertFrom([lng, lat], 'gps', (convertStatus, result) => {
      if (convertStatus === 'complete' && result?.info === 'ok' && result.locations?.[0]) {
        map.setZoomAndCenter(18, result.locations[0], true)
      }
    })
  }, [selectedDeviceId, selectedDeviceLat, selectedDeviceLng])

  return (
    <div className={`campus-map ${mode}`} ref={containerRef}>
      {status !== 'ready' && (
        <div className="campus-map-state">
          <span className="map-state-radar" />
          <strong>{status === 'missing-key' ? '地图密钥未配置' : status === 'error' ? '地图加载失败' : '地图数据加载中'}</strong>
          <small>{status === 'missing-key' ? '请配置 VITE_AMAP_API_KEY' : '正在连接高德地图服务'}</small>
        </div>
      )}
    </div>
  )
}
