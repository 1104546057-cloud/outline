import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ThemedSelect from '../components/ThemedSelect'
import RtkSurveyCockpit from '../components/RtkSurveyCockpit'
import { authFetch } from '../utils/authFetch'
import { gcj02ToWgs84 } from '../utils/coordinates'
import '../styles/OutdoorRtkNavigation.css'

const DEFAULT_CENTER = [113.584101, 22.349278]
const EARTH_RADIUS_M = 6378137
const DIRECT_GOAL_MAX_DISTANCE_M = Number(import.meta.env.VITE_RTK_DIRECT_GOAL_MAX_DISTANCE_M || 10)
const ROAD_NETWORK_MAX_SNAP_M = Number(import.meta.env.VITE_RTK_ROAD_NETWORK_MAX_SNAP_M || 5)
const MAP_STYLE_URL = import.meta.env.VITE_RTK_MAP_STYLE_URL
const RASTER_TILE_URL = import.meta.env.VITE_RTK_RASTER_TILE_URL
  || 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
const MAP_PROVIDER_NAME = import.meta.env.VITE_RTK_MAP_PROVIDER_NAME || 'Esri World Imagery WGS-84 卫星底图'
const RASTER_ATTRIBUTION = import.meta.env.VITE_RTK_RASTER_ATTRIBUTION
  || 'Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community'
const DEFAULT_ROUTE_MAX_DISTANCE_M = 50
const ROUTE_STATE_LABELS = {
  idle: '待命',
  starting: '正在启动',
  driving: '自动驾驶中',
  paused: '已暂停',
  stopping: '正在停车',
  stopped: '已停车',
  completed: '已完成',
  failed: '执行失败',
}

const EMPTY_LINE = {
  type: 'Feature',
  properties: {},
  geometry: { type: 'LineString', coordinates: [] },
}

const EMPTY_FEATURE_COLLECTION = { type: 'FeatureCollection', features: [] }

const buildMapStyle = () => MAP_STYLE_URL || ({
  version: 8,
  sources: {
    base: {
      type: 'raster',
      tiles: [RASTER_TILE_URL],
      tileSize: 256,
      attribution: RASTER_ATTRIBUTION,
      maxzoom: 19,
    },
  },
  layers: [{ id: 'base', type: 'raster', source: 'base' }],
})

const readError = async (response, fallback) => {
  try {
    const body = await response.json()
    return body.detail || body.response?.error || fallback
  } catch {
    return fallback
  }
}

const pointYaw = (point, nextPoint) => {
  if (!point || !nextPoint) return 0
  const meanLatitude = ((point.lat + nextPoint.lat) / 2) * Math.PI / 180
  const east = (nextPoint.lng - point.lng) * Math.cos(meanLatitude)
  const north = nextPoint.lat - point.lat
  return Math.atan2(north, east)
}

const distanceMetres = (from, to) => {
  if (!from || !to) return null
  const lat1 = from.latitude * Math.PI / 180
  const lat2 = to.latitude * Math.PI / 180
  const deltaLat = lat2 - lat1
  const deltaLng = (to.longitude - from.longitude) * Math.PI / 180
  const value = Math.sin(deltaLat / 2) ** 2
    + Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLng / 2) ** 2
  return EARTH_RADIUS_M * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value))
}

const formatAge = value => Number.isFinite(value) ? `${value.toFixed(1)} s` : '--'
const formatDistance = value => Number.isFinite(value) ? `${value.toFixed(value < 10 ? 1 : 0)} m` : '--'
const formatCoordinate = value => Number.isFinite(value) ? value.toFixed(8) : '--'

const createMarkerElement = (className, text = '') => {
  const element = document.createElement('div')
  element.className = className
  element.textContent = text
  return element
}

export default function OutdoorRtkNavigation() {
  const mapElementRef = useRef(null)
  const mapOverlayRef = useRef(null)
  const mapRef = useRef(null)
  const maplibreRef = useRef(null)
  const markersRef = useRef([])
  const centeredOnVehicleRef = useRef(false)
  const fittedSavedTracksRef = useRef('')
  const [devices, setDevices] = useState([])
  const [areas, setAreas] = useState([])
  const [routes, setRoutes] = useState([])
  const [deviceId, setDeviceId] = useState('')
  const [areaId, setAreaId] = useState('')
  const [routeId, setRouteId] = useState('')
  const [navigationMode, setNavigationMode] = useState('survey')
  const [draftGoal, setDraftGoal] = useState(null)
  const [surveyName, setSurveyName] = useState('校园道路采集')
  const [tracks, setTracks] = useState([])
  const [selectedTrackIds, setSelectedTrackIds] = useState([])
  const [selectedTrackDetails, setSelectedTrackDetails] = useState([])
  const [networkName, setNetworkName] = useState('校园RTK道路网络')
  const [networks, setNetworks] = useState([])
  const [networkId, setNetworkId] = useState('')
  const [networkData, setNetworkData] = useState(null)
  const [plannedRoute, setPlannedRoute] = useState(null)
  const [nextPointIndex, setNextPointIndex] = useState(0)
  const [status, setStatus] = useState(null)
  const [mapReady, setMapReady] = useState(false)
  const [mapError, setMapError] = useState('')
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')

  const selectedDevice = useMemo(
    () => devices.find(device => device.id === Number(deviceId)),
    [devices, deviceId],
  )
  const selectedRoute = useMemo(
    () => routes.find(route => route.id === Number(routeId)),
    [routes, routeId],
  )
  const routePointsWgs84 = useMemo(() => (selectedRoute?.points || []).map(point => {
    const [lng, lat] = gcj02ToWgs84([point.lng, point.lat])
    return { ...point, lng, lat }
  }), [selectedRoute])
  const nextPoint = routePointsWgs84[nextPointIndex]
  const rtk = status?.rtk || {}
  const routeExecution = status?.routeExecution || {}
  const routeActive = Boolean(routeExecution.active)
  const routePaused = Boolean(routeExecution.paused)
  const routeMaxDistanceM = Number(status?.routeLimits?.maxDistanceM || DEFAULT_ROUTE_MAX_DISTANCE_M)
  const positionLongitude = rtk.position?.longitude
  const positionLatitude = rtk.position?.latitude
  const currentPosition = useMemo(() => (
    Number.isFinite(positionLongitude) && Number.isFinite(positionLatitude)
      ? { longitude: positionLongitude, latitude: positionLatitude }
      : null
  ), [positionLongitude, positionLatitude])
  const survey = status?.roadSurvey || {}
  const networkNodeById = useMemo(
    () => new Map((networkData?.nodes || []).map(node => [String(node.id), node])),
    [networkData],
  )
  const networkFeatures = useMemo(() => ({
    type: 'FeatureCollection',
    features: (networkData?.edges || []).flatMap((edge, index) => {
      const first = networkNodeById.get(String(edge.from))
      const second = networkNodeById.get(String(edge.to))
      return first && second ? [{
        type: 'Feature',
        properties: { id: index, distanceM: edge.distanceM },
        geometry: {
          type: 'LineString',
          coordinates: [
            [first.longitude, first.latitude],
            [second.longitude, second.latitude],
          ],
        },
      }] : []
    }),
  }), [networkData, networkNodeById])
  const savedTrackFeatures = useMemo(() => ({
    type: 'FeatureCollection',
    features: selectedTrackDetails.flatMap(track => {
      const coordinates = (track.points || [])
        .filter(point => Number.isFinite(point.longitude) && Number.isFinite(point.latitude))
        .map(point => [point.longitude, point.latitude])
      if (!coordinates.length) return []
      const points = coordinates.map((coordinate, index) => ({
        type: 'Feature',
        properties: { kind: 'point', trackId: track.id, sequence: index + 1 },
        geometry: { type: 'Point', coordinates: coordinate },
      }))
      return coordinates.length > 1 ? [{
        type: 'Feature',
        properties: { kind: 'line', trackId: track.id },
        geometry: { type: 'LineString', coordinates },
      }, ...points] : points
    }),
  }), [selectedTrackDetails])
  const selectedSavedPointCount = useMemo(
    () => selectedTrackDetails.reduce((total, track) => total + (track.points?.length || 0), 0),
    [selectedTrackDetails],
  )
  const directGoalDistance = useMemo(
    () => distanceMetres(currentPosition, draftGoal),
    [currentPosition, draftGoal],
  )
  const directGoalInRange = Number.isFinite(directGoalDistance)
    && directGoalDistance <= DIRECT_GOAL_MAX_DISTANCE_M
  const plannedRouteInRange = Number.isFinite(plannedRoute?.distanceM)
    && plannedRoute.distanceM > 0
    && plannedRoute.distanceM <= routeMaxDistanceM
  const goalAvailable = status?.running && rtk.valid && !status?.safety?.goalActive && !busy
  const canSendDirectGoal = Boolean(goalAvailable && draftGoal && currentPosition && directGoalInRange)
  const canSendRouteGoal = Boolean(goalAvailable && routePointsWgs84.length && nextPoint)

  useEffect(() => {
    let cancelled = false
    Promise.all([authFetch('/api/devices'), authFetch('/api/patrol/areas')])
      .then(async ([deviceResponse, areaResponse]) => {
        const [deviceData, areaData] = await Promise.all([
          deviceResponse.ok ? deviceResponse.json() : [],
          areaResponse.ok ? areaResponse.json() : [],
        ])
        if (cancelled) return
        setDevices(deviceData)
        setAreas(areaData)
        const preferred = deviceData.find(device => device.control_connected) || deviceData[0]
        if (preferred) setDeviceId(String(preferred.id))
        if (areaData[0]) setAreaId(String(areaData[0].id))
      })
      .catch(error => !cancelled && setMessage(error.message))
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    setRouteId('')
    setNextPointIndex(0)
    if (!areaId) {
      setRoutes([])
      return undefined
    }
    let cancelled = false
    authFetch(`/api/patrol/routes?area_id=${areaId}`)
      .then(response => response.ok ? response.json() : [])
      .then(data => {
        if (cancelled) return
        setRoutes(data)
        if (data[0]) setRouteId(String(data[0].id))
      })
      .catch(error => !cancelled && setMessage(error.message))
    return () => { cancelled = true }
  }, [areaId])

  const refreshStatus = useCallback(async (quiet = false) => {
    if (!deviceId) return
    try {
      const response = await authFetch(`/api/navigation/rtk/status?robotId=${deviceId}`)
      if (!response.ok) throw new Error(await readError(response, '读取 RTK 状态失败'))
      const body = await response.json()
      setStatus(body.response)
      if (!quiet) setMessage('状态已刷新')
    } catch (error) {
      if (!quiet) setMessage(error.message)
    }
  }, [deviceId])

  useEffect(() => {
    setStatus(null)
    centeredOnVehicleRef.current = false
    if (!deviceId) return undefined
    refreshStatus(true)
    const timer = setInterval(() => refreshStatus(true), 2000)
    return () => clearInterval(timer)
  }, [deviceId, refreshStatus])

  const refreshRoadAssets = useCallback(async (quiet = false) => {
    if (!deviceId) return
    try {
      const [trackResponse, networkResponse] = await Promise.all([
        authFetch(`/api/navigation/rtk/roads/tracks?robotId=${deviceId}`),
        authFetch(`/api/navigation/rtk/roads/networks?robotId=${deviceId}`),
      ])
      if (!trackResponse.ok) throw new Error(await readError(trackResponse, '读取采集轨迹失败'))
      if (!networkResponse.ok) throw new Error(await readError(networkResponse, '读取道路网络失败'))
      const [trackBody, networkBody] = await Promise.all([trackResponse.json(), networkResponse.json()])
      const nextTracks = trackBody.tracks || []
      setTracks(nextTracks)
      setNetworks(networkBody.networks || [])
      setSelectedTrackIds(previous => {
        const validSelection = previous.filter(id => nextTracks.some(track => track.id === id))
        return validSelection.length ? validSelection : (nextTracks[0] ? [nextTracks[0].id] : [])
      })
      setNetworkId(previous => previous || networkBody.networks?.[0]?.id || '')
      if (!quiet) setMessage('道路数据已刷新')
    } catch (error) {
      if (!quiet) setMessage(error.message)
    }
  }, [deviceId])

  useEffect(() => {
    setTracks([])
    setNetworks([])
    setSelectedTrackIds([])
    setSelectedTrackDetails([])
    setNetworkId('')
    setNetworkData(null)
    setPlannedRoute(null)
    if (deviceId) refreshRoadAssets(true)
  }, [deviceId, refreshRoadAssets])

  useEffect(() => {
    fittedSavedTracksRef.current = ''
    if (!deviceId || !selectedTrackIds.length) {
      setSelectedTrackDetails([])
      return undefined
    }
    let cancelled = false
    Promise.all(selectedTrackIds.map(async trackId => {
      const response = await authFetch(
        `/api/navigation/rtk/roads/tracks/${encodeURIComponent(trackId)}?robotId=${deviceId}`,
      )
      if (!response.ok) throw new Error(await readError(response, '读取已保存轨迹坐标失败'))
      const body = await response.json()
      if (!body.ok || !body.track) throw new Error(body.response?.error || '已保存轨迹坐标为空')
      return body.track
    }))
      .then(details => {
        if (!cancelled) setSelectedTrackDetails(details)
      })
      .catch(error => {
        if (!cancelled) {
          setSelectedTrackDetails([])
          setMessage(error.message)
        }
      })
    return () => { cancelled = true }
  }, [deviceId, selectedTrackIds])

  useEffect(() => {
    setNetworkData(null)
    setPlannedRoute(null)
    if (!deviceId || !networkId) return undefined
    let cancelled = false
    authFetch(`/api/navigation/rtk/roads/networks/${networkId}?robotId=${deviceId}`)
      .then(async response => {
        if (!response.ok) throw new Error(await readError(response, '读取道路网络失败'))
        return response.json()
      })
      .then(body => {
        if (!cancelled) setNetworkData(body.network || null)
      })
      .catch(error => !cancelled && setMessage(error.message))
    return () => { cancelled = true }
  }, [deviceId, networkId])

  useEffect(() => {
    if (!mapElementRef.current || mapRef.current) return undefined
    let disposed = false
    let map
    let mapErrorHandler
    Promise.all([
      import('maplibre-gl'),
      import('maplibre-gl/dist/maplibre-gl.css'),
    ]).then(([module]) => {
      if (disposed) return
      const maplibregl = module.default || module
      maplibreRef.current = maplibregl
      map = new maplibregl.Map({
        container: mapElementRef.current,
        style: buildMapStyle(),
        center: DEFAULT_CENTER,
        zoom: 18,
        maxZoom: 22,
        attributionControl: true,
      })
      mapRef.current = map
      map.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'top-right')
      map.on('load', () => {
        if (disposed) return
        map.addSource('rtk-route', { type: 'geojson', data: EMPTY_LINE })
        map.addSource('rtk-survey', { type: 'geojson', data: EMPTY_LINE })
        map.addSource('rtk-saved-tracks', { type: 'geojson', data: EMPTY_FEATURE_COLLECTION })
        map.addSource('rtk-road-network', { type: 'geojson', data: EMPTY_FEATURE_COLLECTION })
        map.addSource('rtk-planned-route', { type: 'geojson', data: EMPTY_LINE })
        map.addLayer({
          id: 'rtk-road-network-line',
          type: 'line',
          source: 'rtk-road-network',
          paint: {
            'line-color': '#25a7ff',
            'line-width': 6,
            'line-opacity': 0.72,
          },
        })
        map.addLayer({
          id: 'rtk-route-line',
          type: 'line',
          source: 'rtk-route',
          paint: {
            'line-color': '#31e3a1',
            'line-width': 5,
            'line-opacity': 0.9,
          },
        })
        map.addLayer({
          id: 'rtk-survey-line',
          type: 'line',
          source: 'rtk-survey',
          paint: {
            'line-color': '#20e3d2',
            'line-width': 5,
            'line-opacity': 0.95,
          },
        })
        map.addLayer({
          id: 'rtk-saved-tracks-line',
          type: 'line',
          source: 'rtk-saved-tracks',
          filter: ['==', ['get', 'kind'], 'line'],
          paint: {
            'line-color': '#18e0ff',
            'line-width': 4,
            'line-opacity': 0.9,
          },
        })
        map.addLayer({
          id: 'rtk-saved-tracks-points',
          type: 'circle',
          source: 'rtk-saved-tracks',
          filter: ['==', ['get', 'kind'], 'point'],
          paint: {
            'circle-radius': 4,
            'circle-color': '#fff36b',
            'circle-stroke-color': '#06243c',
            'circle-stroke-width': 1.5,
            'circle-opacity': 0.95,
          },
        })
        map.addLayer({
          id: 'rtk-planned-route-line',
          type: 'line',
          source: 'rtk-planned-route',
          paint: {
            'line-color': '#ff9d3d',
            'line-width': 8,
            'line-opacity': 0.95,
          },
        })
        setMapReady(true)
      })
      mapErrorHandler = event => {
        if (!disposed && event.error?.message) setMapError(`底图加载异常：${event.error.message}`)
      }
      map.on('error', mapErrorHandler)
    }).catch(error => {
      if (!disposed) setMapError(`MapLibre 加载失败：${error.message}`)
    })
    return () => {
      disposed = true
      markersRef.current.forEach(marker => marker.remove())
      markersRef.current = []
      if (map && mapErrorHandler) map.off('error', mapErrorHandler)
      map?.remove()
      mapRef.current = null
      maplibreRef.current = null
    }
  }, [])

  const selectGoalCoordinates = useCallback((longitude, latitude) => {
    if (!['direct', 'network'].includes(navigationMode)) return
    if (routeActive) {
      setMessage('自动驾驶路线正在执行，请先停车后再重新选择目标。')
      return
    }
    const goal = { longitude, latitude }
    setDraftGoal(goal)
    setPlannedRoute(null)
    setMessage(navigationMode === 'network'
      ? `已选择目标意图：${goal.longitude.toFixed(8)}, ${goal.latitude.toFixed(8)}；请执行道路吸附与规划。`
      : `已选择临时目标：${goal.longitude.toFixed(8)}, ${goal.latitude.toFixed(8)}；确认前不会下发。`)
  }, [navigationMode, routeActive])

  const selectMapGoal = useCallback(event => {
    selectGoalCoordinates(event.lngLat.lng, event.lngLat.lat)
  }, [selectGoalCoordinates])

  const captureMapGoal = useCallback(event => {
    if (!['direct', 'network'].includes(navigationMode)) return
    const map = mapRef.current
    const canvas = map?.getCanvas()
    if (!map || !canvas) return
    const bounds = canvas.getBoundingClientRect()
    const point = map.unproject([event.clientX - bounds.left, event.clientY - bounds.top])
    selectGoalCoordinates(point.lng, point.lat)
  }, [navigationMode, selectGoalCoordinates])

  useEffect(() => {
    const map = mapRef.current
    if (!mapReady || !map || !['direct', 'network'].includes(navigationMode)) return undefined
    map.on('click', selectMapGoal)
    return () => map.off('click', selectMapGoal)
  }, [mapReady, navigationMode, selectMapGoal])

  useEffect(() => {
    const map = mapRef.current
    const maplibregl = maplibreRef.current
    if (!mapReady || !map || !maplibregl) return

    markersRef.current.forEach(marker => marker.remove())
    const markers = []
    const visibleRoute = navigationMode === 'route' ? routePointsWgs84 : []
    const routeSource = map.getSource('rtk-route')
    routeSource?.setData(visibleRoute.length > 1 ? {
      type: 'Feature',
      properties: {},
      geometry: { type: 'LineString', coordinates: visibleRoute.map(point => [point.lng, point.lat]) },
    } : EMPTY_LINE)
    const surveyCoordinates = navigationMode === 'survey'
      ? (survey.preview || []).map(point => [point.longitude, point.latitude])
      : []
    map.getSource('rtk-survey')?.setData(surveyCoordinates.length > 1 ? {
      type: 'Feature',
      properties: {},
      geometry: { type: 'LineString', coordinates: surveyCoordinates },
    } : EMPTY_LINE)
    map.getSource('rtk-saved-tracks')?.setData(
      ['survey', 'network'].includes(navigationMode) ? savedTrackFeatures : EMPTY_FEATURE_COLLECTION,
    )
    map.getSource('rtk-road-network')?.setData(
      navigationMode === 'network' ? networkFeatures : EMPTY_FEATURE_COLLECTION,
    )
    const plannedCoordinates = navigationMode === 'network'
      ? (plannedRoute?.path || []).map(point => [point.longitude, point.latitude])
      : []
    map.getSource('rtk-planned-route')?.setData(plannedCoordinates.length > 1 ? {
      type: 'Feature',
      properties: {},
      geometry: { type: 'LineString', coordinates: plannedCoordinates },
    } : EMPTY_LINE)

    visibleRoute.forEach((point, index) => {
      const marker = new maplibregl.Marker({
        element: createMarkerElement(`rtk-map-point${index === nextPointIndex ? ' active' : ''}`, String(index + 1)),
        anchor: 'center',
      }).setLngLat([point.lng, point.lat]).addTo(map)
      markers.push(marker)
    })

    if (currentPosition) {
      const vehicle = createMarkerElement('rtk-vehicle-marker')
      vehicle.appendChild(createMarkerElement('rtk-vehicle-core'))
      markers.push(new maplibregl.Marker({ element: vehicle, anchor: 'center' })
        .setLngLat([currentPosition.longitude, currentPosition.latitude])
        .addTo(map))
      if (!centeredOnVehicleRef.current) {
        map.easeTo({ center: [currentPosition.longitude, currentPosition.latitude], zoom: Math.max(map.getZoom(), 19) })
        centeredOnVehicleRef.current = true
      }
    }

    if (['direct', 'network'].includes(navigationMode) && draftGoal) {
      markers.push(new maplibregl.Marker({
        element: createMarkerElement('rtk-direct-goal-marker', navigationMode === 'network' ? '目标意图' : '目标'),
        anchor: 'bottom',
      }).setLngLat([draftGoal.longitude, draftGoal.latitude]).addTo(map))
    }

    const snappedGoal = plannedRoute?.path?.[plannedRoute.path.length - 1]
    if (navigationMode === 'network' && snappedGoal) {
      markers.push(new maplibregl.Marker({
        element: createMarkerElement('rtk-snapped-goal-marker', '已吸附'),
        anchor: 'bottom',
      }).setLngLat([snappedGoal.longitude, snappedGoal.latitude]).addTo(map))
    }

    markersRef.current = markers
  }, [
    currentPosition,
    draftGoal,
    mapReady,
    navigationMode,
    networkFeatures,
    nextPointIndex,
    plannedRoute,
    routePointsWgs84,
    savedTrackFeatures,
    survey.preview,
  ])

  useEffect(() => {
    const map = mapRef.current
    const maplibregl = maplibreRef.current
    if (!mapReady || !map || !maplibregl || !['survey', 'network'].includes(navigationMode)) return
    if (navigationMode === 'survey' && survey.active) return
    const coordinates = navigationMode === 'network'
      ? (networkData?.nodes || [])
        .filter(node => Number.isFinite(node.longitude) && Number.isFinite(node.latitude))
        .map(node => [node.longitude, node.latitude])
      : selectedTrackDetails.flatMap(track => (track.points || [])
        .filter(point => Number.isFinite(point.longitude) && Number.isFinite(point.latitude))
        .map(point => [point.longitude, point.latitude]))
    if (!coordinates.length) return
    const fitKey = navigationMode === 'network'
      ? `network:${networkData?.id || ''}:${coordinates.length}`
      : `survey:${selectedTrackDetails.map(track => `${track.id}:${track.points?.length || 0}`).join('|')}`
    if (fittedSavedTracksRef.current === fitKey) return
    fittedSavedTracksRef.current = fitKey
    if (coordinates.length === 1) {
      map.easeTo({ center: coordinates[0], zoom: Math.max(map.getZoom(), 20) })
      return
    }
    const bounds = coordinates.reduce(
      (nextBounds, coordinate) => nextBounds.extend(coordinate),
      new maplibregl.LngLatBounds(coordinates[0], coordinates[0]),
    )
    map.fitBounds(bounds, { padding: 60, maxZoom: 20, duration: 500 })
  }, [mapReady, navigationMode, networkData, selectedTrackDetails, survey.active])

  useEffect(() => {
    const map = mapRef.current
    const canvas = mapOverlayRef.current
    if (!mapReady || !map || !canvas) return undefined
    let animationFrame = 0

    const drawOverlay = () => {
      animationFrame = 0
      const width = map.getCanvas().clientWidth
      const height = map.getCanvas().clientHeight
      if (!width || !height) return
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2)
      const renderWidth = Math.round(width * pixelRatio)
      const renderHeight = Math.round(height * pixelRatio)
      if (canvas.width !== renderWidth || canvas.height !== renderHeight) {
        canvas.width = renderWidth
        canvas.height = renderHeight
      }
      const context = canvas.getContext('2d')
      if (!context) return
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0)
      context.clearRect(0, 0, width, height)

      const project = coordinate => map.project(coordinate)
      const strokeSegments = (segments, color, lineWidth, shadowColor = 'transparent') => {
        if (!segments.length) return
        context.save()
        context.beginPath()
        segments.forEach(coordinates => {
          coordinates.forEach((coordinate, index) => {
            const point = project(coordinate)
            if (index === 0) context.moveTo(point.x, point.y)
            else context.lineTo(point.x, point.y)
          })
        })
        context.strokeStyle = color
        context.lineWidth = lineWidth
        context.lineCap = 'round'
        context.lineJoin = 'round'
        context.shadowColor = shadowColor
        context.shadowBlur = shadowColor === 'transparent' ? 0 : 5
        context.stroke()
        context.restore()
      }

      if (navigationMode === 'network') {
        strokeSegments(
          networkFeatures.features.map(feature => feature.geometry.coordinates),
          '#168dff',
          7,
          'rgba(22, 141, 255, .75)',
        )
      }

      if (['survey', 'network'].includes(navigationMode)) {
        const savedSegments = selectedTrackDetails
          .map(track => (track.points || []).map(point => [point.longitude, point.latitude]))
          .filter(coordinates => coordinates.length > 1)
        const activeSegment = navigationMode === 'survey'
          ? [(survey.preview || []).map(point => [point.longitude, point.latitude])]
            .filter(coordinates => coordinates.length > 1)
          : []
        strokeSegments(
          [...savedSegments, ...activeSegment],
          '#18e0ff',
          3.5,
          'rgba(24, 224, 255, .7)',
        )
        context.save()
        context.fillStyle = '#fff36b'
        context.strokeStyle = '#06243c'
        context.lineWidth = 1.5
        selectedTrackDetails.forEach(track => {
          const points = track.points || []
          points.forEach(point => {
            const projected = project([point.longitude, point.latitude])
            if (projected.x < -8 || projected.y < -8 || projected.x > width + 8 || projected.y > height + 8) return
            context.beginPath()
            context.arc(projected.x, projected.y, 4, 0, Math.PI * 2)
            context.fill()
            context.stroke()
          })
        })
        context.restore()
      }

      if (navigationMode === 'network' && (plannedRoute?.path || []).length > 1) {
        strokeSegments(
          [(plannedRoute.path || []).map(point => [point.longitude, point.latitude])],
          '#ff9d3d',
          8,
          'rgba(255, 157, 61, .8)',
        )
      }
    }

    const scheduleDraw = () => {
      if (!animationFrame) animationFrame = window.requestAnimationFrame(drawOverlay)
    }
    scheduleDraw()
    map.on('move', scheduleDraw)
    map.on('resize', scheduleDraw)
    map.on('idle', scheduleDraw)
    return () => {
      map.off('move', scheduleDraw)
      map.off('resize', scheduleDraw)
      map.off('idle', scheduleDraw)
      if (animationFrame) window.cancelAnimationFrame(animationFrame)
      const context = canvas.getContext('2d')
      context?.clearRect(0, 0, canvas.width, canvas.height)
    }
  }, [mapReady, navigationMode, networkFeatures, plannedRoute, selectedTrackDetails, survey.preview])

  const postAction = async (name, url, body) => {
    setBusy(name)
    setMessage('')
    try {
      const response = await authFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!response.ok) throw new Error(await readError(response, `${name}失败`))
      const data = await response.json()
      if (!data.ok) throw new Error(data.response?.error || `${name}失败`)
      if (data.response?.type === 'rtk_nav_status') setStatus(data.response)
      setMessage(`${name}成功`)
      return true
    } catch (error) {
      setMessage(error.message)
      return false
    } finally {
      setBusy('')
    }
  }

  const startRtk = async () => {
    const ok = await postAction('启动 RTK 模式', '/api/navigation/rtk/start', { robotId: Number(deviceId) })
    if (ok && navigationMode === 'route') setNextPointIndex(0)
  }

  const stopRtk = () => postAction('停止导航', '/api/navigation/rtk/stop', { robotId: Number(deviceId) })

  const sendDirectGoal = async () => {
    if (!draftGoal || !currentPosition || !directGoalInRange) return
    await postAction('发送临时目标', '/api/navigation/rtk/goal', {
      robotId: Number(deviceId),
      longitude: draftGoal.longitude,
      latitude: draftGoal.latitude,
      yaw: pointYaw(
        { lng: currentPosition.longitude, lat: currentPosition.latitude },
        { lng: draftGoal.longitude, lat: draftGoal.latitude },
      ),
    })
    await refreshStatus(true)
  }

  const sendNextPoint = async () => {
    if (!nextPoint) return
    const following = routePointsWgs84[nextPointIndex + 1]
    const ok = await postAction('发送航点', '/api/navigation/rtk/goal', {
      robotId: Number(deviceId),
      longitude: nextPoint.lng,
      latitude: nextPoint.lat,
      yaw: pointYaw(nextPoint, following),
    })
    if (ok) {
      setNextPointIndex(index => Math.min(index + 1, routePointsWgs84.length))
      await refreshStatus(true)
    }
  }

  const postRoadAction = async (name, url, body = {}) => {
    setBusy(name)
    setMessage('')
    try {
      const response = await authFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robotId: Number(deviceId), ...body }),
      })
      if (!response.ok) throw new Error(await readError(response, `${name}失败`))
      const data = await response.json()
      if (!data.ok) throw new Error(data.response?.error || `${name}失败`)
      const nextSurvey = data.response?.survey
      if (nextSurvey) setStatus(previous => ({ ...(previous || {}), roadSurvey: nextSurvey }))
      setMessage(`${name}成功`)
      return data
    } catch (error) {
      setMessage(error.message)
      return null
    } finally {
      setBusy('')
    }
  }

  const stopSurvey = async () => {
    const data = await postRoadAction('停止并保存采集', '/api/navigation/rtk/roads/stop')
    if (!data) return
    const trackId = data.response?.track?.id
    await refreshRoadAssets(true)
    if (trackId) setSelectedTrackIds(previous => [...new Set([...previous, trackId])])
  }

  const discardSurvey = async () => {
    if (!window.confirm('确定放弃本次尚未保存的道路采集数据吗？')) return
    await postRoadAction('放弃本次采集', '/api/navigation/rtk/roads/discard')
  }

  const toggleTrack = trackId => {
    setSelectedTrackIds(previous => previous.includes(trackId)
      ? previous.filter(id => id !== trackId)
      : [...previous, trackId])
  }

  const buildRoadNetwork = async () => {
    const data = await postRoadAction('生成道路网络', '/api/navigation/rtk/roads/networks/build', {
      name: networkName,
      trackIds: selectedTrackIds,
    })
    if (!data?.network) return
    await refreshRoadAssets(true)
    setNetworkId(data.network.id)
    setNetworkData(data.network)
    setNavigationMode('network')
  }

  const planNetworkGoal = async () => {
    if (!draftGoal || !networkId) return
    const data = await postRoadAction('道路吸附与路径规划', '/api/navigation/rtk/roads/plan', {
      networkId,
      goalLongitude: draftGoal.longitude,
      goalLatitude: draftGoal.latitude,
      maxSnapM: ROAD_NETWORK_MAX_SNAP_M,
    })
    if (data?.plan) setPlannedRoute(data.plan)
  }

  const startAutoRoute = async () => {
    if (!plannedRoute || !draftGoal || !networkId || !plannedRouteInRange) return
    const confirmed = window.confirm(
      `即将启动自动驾驶：规划长度 ${formatDistance(plannedRoute.distanceM)}，安全上限 ${routeMaxDistanceM} 米。\n\n`
      + '请确认车辆周围无人、现场人员持有急停手段并持续看护。是否开始？',
    )
    if (!confirmed) return
    await postAction('启动自动驾驶', '/api/navigation/rtk/route/start', {
      robotId: Number(deviceId),
      networkId,
      goalLongitude: draftGoal.longitude,
      goalLatitude: draftGoal.latitude,
      maxSnapM: ROAD_NETWORK_MAX_SNAP_M,
    })
  }

  const pauseAutoRoute = () => postAction(
    '暂停自动驾驶',
    '/api/navigation/rtk/route/pause',
    { robotId: Number(deviceId) },
  )

  const resumeAutoRoute = async () => {
    if (!window.confirm('继续后车辆会恢复移动。确认道路仍安全并继续自动驾驶吗？')) return
    await postAction('继续自动驾驶', '/api/navigation/rtk/route/resume', { robotId: Number(deviceId) })
  }

  const stopAutoRoute = () => postAction(
    '紧急停车',
    '/api/navigation/rtk/route/stop',
    { robotId: Number(deviceId) },
  )

  return (
    <div className="rtk-page">
      <header className="rtk-header">
        <div>
          <h1>厘米级 RTK 室外导航</h1>
          <p>WGS-84道路采集 · 目标吸附 · 自动路径规划 · 下发前人工确认</p>
        </div>
        <div className={`rtk-fixed-badge ${rtk.valid ? 'valid' : 'invalid'}`}>
          {rtk.valid ? 'RTK FIXED 可导航' : (rtk.qualityLabel || '等待 G70')}
        </div>
      </header>

      <section className={`rtk-toolbar ${navigationMode !== 'route' ? 'direct' : ''}`}>
        <label>车辆<ThemedSelect value={deviceId} disabled={routeActive} onChange={event => setDeviceId(event.target.value)}>
          <option value="">请选择车辆</option>
          {devices.map(device => <option key={device.id} value={device.id}>{device.name} · {device.control_connected ? 'Agent 已连接' : '未连接'}</option>)}
        </ThemedSelect></label>
        <label>导航方式<ThemedSelect value={navigationMode} disabled={routeActive} onChange={event => setNavigationMode(event.target.value)}>
          <option value="survey">人工驾驶道路采集</option>
          <option value="network">道路网络选点规划</option>
          <option value="direct">近距离临时目标（试验）</option>
          <option value="route">已保存固定线路</option>
        </ThemedSelect></label>
        {navigationMode === 'route' ? <>
          <label>区域<ThemedSelect value={areaId} onChange={event => setAreaId(event.target.value)}>
            <option value="">请选择区域</option>
            {areas.map(area => <option key={area.id} value={area.id}>{area.name}</option>)}
          </ThemedSelect></label>
          <label>线路<ThemedSelect value={routeId} onChange={event => { setRouteId(event.target.value); setNextPointIndex(0) }}>
            <option value="">请选择线路</option>
            {routes.map(route => <option key={route.id} value={route.id}>{route.name}（{route.point_count} 点）</option>)}
          </ThemedSelect></label>
        </> : navigationMode === 'network' ? <label>道路网络<ThemedSelect value={networkId} disabled={routeActive} onChange={event => setNetworkId(event.target.value)}>
          <option value="">尚未生成道路网络</option>
          {networks.map(network => <option key={network.id} value={network.id}>{network.name}（{network.statistics?.nodeCount || 0}节点）</option>)}
        </ThemedSelect></label> : <div className="rtk-toolbar-note">
          {navigationMode === 'survey'
            ? '开始后由车辆端自动记录Fixed轨迹；人工驾驶过程中无需逐点操作。'
            : '地图单击只生成待确认目标，不会直接让车辆移动。'}
        </div>}
      </section>

      <div className={`rtk-workspace${navigationMode === 'survey' ? ' survey' : ''}`}>
        <div className="rtk-visual-column">
          <div
            className={`rtk-map-shell${['direct', 'network'].includes(navigationMode) ? ' selecting' : ''}`}
            onClickCapture={captureMapGoal}
          >
            <div className="rtk-map" ref={mapElementRef} />
            <canvas className="rtk-map-overlay" ref={mapOverlayRef} aria-hidden="true" />
            <div className="rtk-map-provider">{MAP_PROVIDER_NAME}</div>
            {navigationMode === 'direct' ? <div className="rtk-map-hint">单击地图选择临时目标</div> : null}
            {navigationMode === 'network' ? <div className="rtk-map-hint">单击地图表达目标，随后吸附到蓝色实测道路</div> : null}
            {navigationMode === 'survey' && survey.active ? <div className="rtk-map-hint">正在自动记录WGS-84轨迹 · {survey.pointCount || 0}点</div> : null}
            {mapError ? <div className="rtk-map-error">{mapError}；不影响车端继续采集 RTK 轨迹。</div> : null}
          </div>
          {navigationMode === 'survey' ? <RtkSurveyCockpit
            deviceId={deviceId}
            device={selectedDevice}
            onNotice={setMessage}
          /> : null}
        </div>
        <aside className="rtk-panel">
          <section>
            <h2>定位与安全门</h2>
            <dl className="rtk-status-grid">
              <div><dt>导航进程</dt><dd>{status?.running ? '运行中' : '未启动'}</dd></div>
              <div><dt>GGA 质量</dt><dd>{rtk.quality ?? '--'} / {rtk.qualityLabel || '--'}</dd></div>
              <div><dt>定位时效</dt><dd>{formatAge(rtk.fixAge)}</dd></div>
              <div><dt>跳点检测</dt><dd>{rtk.jump?.active ? '已拦截' : '正常'}</dd></div>
              <div><dt>失锁停车</dt><dd>{status?.safety?.tripped ? '已触发' : '待命'}</dd></div>
              <div><dt>差分方式</dt><dd>{status?.provider?.correctionMode || '--'}</dd></div>
            </dl>
            {rtk.lastError ? <div className="rtk-alert">{rtk.lastError}</div> : null}
            {status?.safety?.reason ? <div className="rtk-alert danger">安全停车：{status.safety.reason}</div> : null}
          </section>

          {navigationMode === 'survey' ? <>
            <section>
              <h2>人工驾驶道路采集</h2>
              <label className="rtk-field">本次采集名称
                <input className="rtk-text-input" value={surveyName} maxLength={80} onChange={event => setSurveyName(event.target.value)} />
              </label>
              <dl className="rtk-status-grid rtk-survey-grid">
                <div><dt>采集状态</dt><dd>{survey.active ? (survey.manualPaused ? '人工暂停' : survey.qualityPaused ? '等待Fixed' : '自动记录中') : '未开始'}</dd></div>
                <div><dt>有效点数</dt><dd>{survey.pointCount || 0}</dd></div>
                <div><dt>采集距离</dt><dd>{formatDistance(survey.distanceM)}</dd></div>
                <div><dt>原始Fix</dt><dd>{survey.rawFixes || 0}</dd></div>
                <div><dt>质量拒绝</dt><dd>{survey.skippedInvalid || 0}</dd></div>
                <div><dt>近距去重</dt><dd>{survey.skippedDistance || 0}</dd></div>
              </dl>
              {survey.qualityPaused ? <div className="rtk-alert danger">RTK失去Fixed，车端已自动停止收点；恢复Fixed后会继续记录。</div> : null}
              <div className="rtk-actions rtk-actions-wide">
                <button className="success" disabled={!selectedDevice?.control_connected || !rtk.valid || survey.active || Boolean(busy)} onClick={() => postRoadAction('开始道路采集', '/api/navigation/rtk/roads/start', { name: surveyName })}>开始采集</button>
                <button disabled={!survey.active || survey.manualPaused || Boolean(busy)} onClick={() => postRoadAction('暂停采集', '/api/navigation/rtk/roads/pause')}>暂停</button>
                <button disabled={!survey.active || !survey.manualPaused || !rtk.valid || Boolean(busy)} onClick={() => postRoadAction('继续采集', '/api/navigation/rtk/roads/resume')}>继续</button>
                <button className="primary" disabled={!survey.active || survey.pointCount < 2 || Boolean(busy)} onClick={stopSurvey}>停止并保存</button>
                <button className="danger" disabled={!survey.active || Boolean(busy)} onClick={discardSurvey}>放弃本次</button>
                <button disabled={!deviceId || Boolean(busy)} onClick={() => refreshStatus(false)}>刷新状态</button>
              </div>
              <small>开始后由车端自动连续记录。这里只采集定位数据，不启动自主导航，也不会发送速度或目标。</small>
            </section>
            <section>
              <h2>采集轨迹与道路网络</h2>
              {tracks.length ? <div className="rtk-track-list">
                {tracks.map(track => <label key={track.id}>
                  <input type="checkbox" checked={selectedTrackIds.includes(track.id)} onChange={() => toggleTrack(track.id)} />
                  <span><strong>{track.name}</strong><small>{track.statistics?.pointCount || 0}点 · {formatDistance(track.statistics?.distanceM)}</small></span>
                </label>)}
              </div> : <div className="rtk-empty-state">尚无已保存的RTK道路轨迹</div>}
              {selectedTrackIds.length ? <div className="rtk-alert">
                已在地图显示 {selectedTrackDetails.length} 条轨迹、{selectedSavedPointCount} 个采集点；取消勾选即可隐藏。
              </div> : null}
              <label className="rtk-field">道路网络名称
                <input className="rtk-text-input" value={networkName} maxLength={80} onChange={event => setNetworkName(event.target.value)} />
              </label>
              <div className="rtk-actions">
                <button className="primary" disabled={!selectedTrackIds.length || Boolean(busy)} onClick={buildRoadNetwork}>生成道路网络</button>
                <button disabled={!deviceId || Boolean(busy)} onClick={() => refreshRoadAssets(false)}>刷新列表</button>
              </div>
              <small>先勾选要使用的轨迹（黄点、青线），再生成道路网络。可以分多次采集不同支路后合并；相近路口会自动连接，现场仍需人工核查连通关系。</small>
            </section>
          </> : navigationMode === 'network' ? <section>
            <h2>道路吸附与路径规划</h2>
            <p className="rtk-route-name">{networkData?.name || '尚未选择道路网络'}</p>
            <dl className="rtk-goal-grid">
              <div><dt>道路节点</dt><dd>{networkData?.statistics?.nodeCount ?? '--'}</dd></div>
              <div><dt>道路边</dt><dd>{networkData?.statistics?.edgeCount ?? '--'}</dd></div>
              <div><dt>目标经度</dt><dd>{formatCoordinate(draftGoal?.longitude)}</dd></div>
              <div><dt>目标纬度</dt><dd>{formatCoordinate(draftGoal?.latitude)}</dd></div>
              <div><dt>目标吸附距离</dt><dd>{formatDistance(plannedRoute?.goalSnapDistanceM)}</dd></div>
              <div><dt>规划路径长度</dt><dd>{formatDistance(plannedRoute?.distanceM)}</dd></div>
            </dl>
            {!networkData ? <div className="rtk-alert">请先完成道路采集并生成道路网络。</div> : null}
            <div className="rtk-actions">
              <button className="success" disabled={!networkData || !draftGoal || !rtk.valid || routeActive || Boolean(busy)} onClick={planNetworkGoal}>吸附并规划</button>
              <button disabled={!draftGoal || routeActive || Boolean(busy)} onClick={() => { setDraftGoal(null); setPlannedRoute(null) }}>清除目标</button>
              <button disabled={!deviceId || Boolean(busy)} onClick={() => refreshRoadAssets(false)}>刷新网络</button>
            </div>
            <div className="rtk-alert">地图图例：黄点/青线为原始采集轨迹，蓝线为生成的道路网络，橙线为规划结果。</div>
            <small>最大吸附距离为 {ROAD_NETWORK_MAX_SNAP_M} 米。车端会按约 {status?.routeLimits?.waypointSpacingM || 2} 米间距逐点执行；单次自动路线安全上限为 {routeMaxDistanceM} 米。</small>
            {plannedRoute && !plannedRouteInRange ? <div className="rtk-alert danger">
              当前规划 {formatDistance(plannedRoute.distanceM)}，超过 {routeMaxDistanceM} 米上限，请重新选择较近目标。
            </div> : null}
            {plannedRoute ? <div className="rtk-alert">规划完成：{plannedRoute.path?.length || 0}个道路节点，等待人工确认启动。</div> : null}
            <div className="rtk-route-execution">
              <div className="rtk-route-execution-title">
                <strong>自动驾驶执行</strong>
                <span className={`state-${routeExecution.state || 'idle'}`}>
                  {ROUTE_STATE_LABELS[routeExecution.state] || routeExecution.state || '待命'}
                </span>
              </div>
              <progress max="100" value={routeExecution.progressPct || 0} />
              <dl className="rtk-goal-grid">
                <div><dt>执行进度</dt><dd>{routeExecution.progressPct || 0}%</dd></div>
                <div><dt>完成节点</dt><dd>{routeExecution.completedPoints || 0} / {routeExecution.pointCount || '--'}</dd></div>
                <div><dt>执行路线</dt><dd>{formatDistance(routeExecution.distanceM)}</dd></div>
                <div><dt>当前节点</dt><dd>{routeExecution.active ? (routeExecution.currentIndex || 0) + 1 : '--'}</dd></div>
              </dl>
              {routeExecution.error ? <div className="rtk-alert danger">{routeExecution.error}</div> : null}
              <div className="rtk-actions rtk-route-driving-actions">
                <button className="success" disabled={!plannedRouteInRange || routeActive || !rtk.valid || Boolean(busy)} onClick={startAutoRoute}>确认并开始自动驾驶</button>
                <button disabled={!routeActive || routePaused || Boolean(busy)} onClick={pauseAutoRoute}>暂停</button>
                <button className="primary" disabled={!routeActive || !routePaused || !rtk.valid || Boolean(busy)} onClick={resumeAutoRoute}>继续</button>
                <button className="danger" disabled={!routeActive || Boolean(busy)} onClick={stopAutoRoute}>立即停车</button>
              </div>
            </div>
          </section> : navigationMode === 'direct' ? <section>
            <h2>地图点选临时目标</h2>
            <dl className="rtk-goal-grid">
              <div><dt>经度（WGS-84）</dt><dd>{formatCoordinate(draftGoal?.longitude)}</dd></div>
              <div><dt>纬度（WGS-84）</dt><dd>{formatCoordinate(draftGoal?.latitude)}</dd></div>
              <div><dt>距车辆</dt><dd className={directGoalDistance > DIRECT_GOAL_MAX_DISTANCE_M ? 'danger' : ''}>{formatDistance(directGoalDistance)}</dd></div>
              <div><dt>首测距离限制</dt><dd>≤ {DIRECT_GOAL_MAX_DISTANCE_M} m</dd></div>
            </dl>
            {draftGoal && !currentPosition ? <div className="rtk-alert">尚未收到车辆 RTK 坐标，不能计算目标距离。</div> : null}
            {directGoalDistance > DIRECT_GOAL_MAX_DISTANCE_M ? <div className="rtk-alert danger">目标超过首版安全距离，请选择车辆周围 {DIRECT_GOAL_MAX_DISTANCE_M} 米内的位置。</div> : null}
            <div className="rtk-actions">
              <button className="primary" disabled={!selectedDevice?.control_connected || Boolean(busy)} onClick={startRtk}>启动 RTK 模式</button>
              <button className="success" disabled={!canSendDirectGoal} onClick={sendDirectGoal}>确认导航到此点</button>
              <button disabled={!draftGoal || Boolean(busy)} onClick={() => setDraftGoal(null)}>清除目标</button>
              <button className="danger" disabled={!deviceId || Boolean(busy)} onClick={stopRtk}>停车并退出</button>
            </div>
            <small>点击地图只生成待确认目标。只有 Agent 在线、RTK Fixed、导航已启动、无活动目标且距离合规时，确认按钮才会启用。</small>
            <div className="rtk-alert">校园道路网络和禁行区尚未录入，因此第一版只允许近距离目标，不代表已具备跨校园自动选路能力。</div>
          </section> : <section>
            <h2>固定线路执行</h2>
            <p className="rtk-route-name">{selectedRoute?.name || '尚未选择线路'}</p>
            <p className="rtk-next-point">下一航点：{nextPoint ? `${nextPointIndex + 1}. ${nextPoint.name}` : '线路已发送完毕'}</p>
            <div className="rtk-actions">
              <button className="primary" disabled={!selectedDevice?.control_connected || Boolean(busy)} onClick={startRtk}>启动 RTK 模式</button>
              <button className="success" disabled={!canSendRouteGoal} onClick={sendNextPoint}>发送下一航点</button>
              <button className="danger" disabled={!deviceId || Boolean(busy)} onClick={stopRtk}>停车并退出</button>
              <button disabled={!deviceId || Boolean(busy)} onClick={() => refreshStatus(false)}>刷新状态</button>
            </div>
            <small>旧线路点位仍按 GCJ-02 保存，仅在显示和下发前转换为 WGS-84；后续再统一迁移数据真值。</small>
          </section>}

          <section className="rtk-coordinate-note">
            <h2>坐标与底图</h2>
            <p>MapLibre 交互坐标：WGS-84</p>
            <p>G70、FindCM 与车端目标：WGS-84</p>
            <p>当前底图：{MAP_PROVIDER_NAME}</p>
            <p>可通过环境变量切换为合法授权的卫星瓦片或自建正射影像。</p>
          </section>
          {message ? <div className="rtk-message">{message}</div> : null}
        </aside>
      </div>
    </div>
  )
}
