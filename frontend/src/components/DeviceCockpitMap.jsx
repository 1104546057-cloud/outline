/* eslint-disable react/prop-types */
import { useEffect, useRef, useState } from 'react'
import AMapLoader from '@amap/amap-jsapi-loader'
import { wgs84CoordinatesToGcj02 } from '../utils/coordinates'

const AMAP_KEY = import.meta.env.VITE_AMAP_API_KEY
const AMAP_SECURITY_KEY = import.meta.env.VITE_AMAP_API_SECURE_KEY

const validCoordinate = (lng, lat) => Number.isFinite(Number(lng)) && Number.isFinite(Number(lat))

export default function DeviceCockpitMap({ device, task }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const amapRef = useRef(null)
  const objectsRef = useRef([])
  const fittedKeyRef = useRef(null)
  const [status, setStatus] = useState(AMAP_KEY ? 'loading' : 'missing-key')

  useEffect(() => {
    if (!containerRef.current || !AMAP_KEY) return undefined
    let mounted = true
    window._AMapSecurityConfig = { securityJsCode: AMAP_SECURITY_KEY }
    AMapLoader.load({ key: AMAP_KEY, version: '2.0', plugins: ['AMap.Polyline', 'AMap.Marker'] })
      .then(AMap => {
        if (!mounted || !containerRef.current) return
        amapRef.current = AMap
        mapRef.current = new AMap.Map(containerRef.current, {
          zoom: 17,
          center: [113.584101, 22.349278],
          layers: [new AMap.TileLayer.Satellite(), new AMap.TileLayer.RoadNet({ opacity: .65 })],
          showLabel: true,
        })
        setStatus('ready')
      })
      .catch(error => {
        console.error('驾驶舱地图加载失败:', error)
        if (mounted) setStatus('error')
      })

    return () => {
      mounted = false
      mapRef.current?.destroy()
      mapRef.current = null
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    const AMap = amapRef.current
    if (status !== 'ready' || !map || !AMap || !device) return

    objectsRef.current.forEach(object => map.remove(object))
    objectsRef.current = []
    const objects = []
    const routePoints = task?.route?.points || []

    if (routePoints.length >= 2) {
      const routePath = routePoints.map(point => [Number(point.lng), Number(point.lat)])
      const routeLine = new AMap.Polyline({
        path: routePath,
        strokeColor: '#2f9dff',
        strokeWeight: 4,
        strokeOpacity: .9,
        strokeStyle: 'dashed',
        lineJoin: 'round',
      })
      map.add(routeLine)
      objects.push(routeLine)

      routePoints.forEach((point, index) => {
        const marker = new AMap.Marker({
          position: [Number(point.lng), Number(point.lat)],
          content: `<div class="cockpit-route-point">${index + 1}</div>`,
          anchor: 'center',
        })
        map.add(marker)
        objects.push(marker)
      })
    }

    const gpsPoints = (task?.gps_track || []).filter(point => validCoordinate(point.lng, point.lat)).slice(-200)
    const deviceHasLocation = validCoordinate(device.lng, device.lat)
    const rawCoordinates = gpsPoints.map(point => [Number(point.lng), Number(point.lat)])
    if (deviceHasLocation) rawCoordinates.push([Number(device.lng), Number(device.lat)])

    if (rawCoordinates.length > 0) {
      const locations = wgs84CoordinatesToGcj02(rawCoordinates)
      const trackLocations = locations.slice(0, gpsPoints.length)
      if (trackLocations.length >= 2) {
        const trackLine = new AMap.Polyline({
          path: trackLocations,
          strokeColor: '#36ef9b',
          strokeWeight: 4,
          strokeOpacity: .95,
          lineJoin: 'round',
          lineCap: 'round',
        })
        map.add(trackLine)
        objects.push(trackLine)
      }

      const currentLocation = deviceHasLocation ? locations[locations.length - 1] : trackLocations[trackLocations.length - 1]
      if (currentLocation) {
        const currentMarker = new AMap.Marker({
          position: currentLocation,
          content: '<div class="cockpit-current-marker"><i></i></div>',
          anchor: 'center',
          zIndex: 200,
        })
        map.add(currentMarker)
        objects.push(currentMarker)
      }

      objectsRef.current = objects
      const fitKey = `${device.id}:${task?.id || 'position'}`
      if (objects.length > 0 && fittedKeyRef.current !== fitKey) {
        map.setFitView(objects, false, [28, 28, 28, 28], 18)
        fittedKeyRef.current = fitKey
      }
    } else {
      objectsRef.current = objects
      if (objects.length > 0) map.setFitView(objects, false, [28, 28, 28, 28], 18)
    }
  }, [device, task, status])

  const noLocation = device && !validCoordinate(device.lng, device.lat) && !(task?.gps_track || []).length
  return (
    <div className="cockpit-map" ref={containerRef}>
      {(status !== 'ready' || noLocation) && (
        <div className="cockpit-map-state">
          <span className="cockpit-radar" />
          <strong>{noLocation ? '暂无实时定位' : status === 'missing-key' ? '地图密钥未配置' : status === 'error' ? '地图加载失败' : '地图加载中'}</strong>
          <small>{noLocation ? '等待设备上报 GPS 坐标' : status === 'missing-key' ? '请配置 VITE_AMAP_API_KEY' : '正在连接地图服务'}</small>
        </div>
      )}
    </div>
  )
}
