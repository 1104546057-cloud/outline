import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CameraFeed, CockpitPanel } from '../components/CockpitSensorFeed'
import ThemedSelect from '../components/ThemedSelect'
import { authFetch } from '../utils/authFetch'
import '../styles/Patrol.css'

const degToRad = value => (Number(value) * Math.PI) / 180

const formatNumber = value => (
  Number.isFinite(value) ? value.toFixed(3) : '--'
)

const formatMapDisplayName = name => String(name || '').replace(/\.yaml$/i, '')

const POSE_TRAIL_MIN_DISTANCE = 0.03
const POSE_TRAIL_MAX_POINTS = 1200
const MAP_MIN_SCALE = 0.25
const MAP_MAX_SCALE = 8
const MAP_ZOOM_STEP = 0.001
const MAP_DRAG_THRESHOLD = 4
const WAYPOINT_REACHED_DISTANCE = 0.35
const MOVE_BASE_SUCCEEDED = 3
const MOVE_BASE_FAILURE_STATUSES = new Set([2, 4, 5, 8, 9])
const NAV_MAP_CANVAS_BACKGROUND = '#031025'
const NAV_MAP_CANVAS_BACKGROUND_RGB = [3, 16, 37]
const NAV_MAP_FREE_RGB = [25, 115, 148]
const NAV_MAP_FREE_GRAY_MIN = 245
const NAV_MAP_UNKNOWN_GRAY_MIN = 190
const NAV_MAP_UNKNOWN_GRAY_MAX = 220

const createDefaultMapView = () => ({
  scale: 1,
  offsetX: 0,
  offsetY: 0,
  rotation: 0,
})

const clamp = (value, min, max) => Math.min(Math.max(value, min), max)

function decodeGray8(base64) {
  const binary = atob(base64 || '')
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  return bytes
}

function previewToMap(preview, px, py) {
  const [originX = 0, originY = 0, originYaw = 0] = preview.origin || []
  const scale = preview.previewScale || 1
  const resolution = Number(preview.resolution || 0)
  const localX = px * scale * resolution
  const localY = (preview.height - py * scale) * resolution
  const cos = Math.cos(originYaw)
  const sin = Math.sin(originYaw)
  return {
    x: originX + localX * cos - localY * sin,
    y: originY + localX * sin + localY * cos,
  }
}

function mapToPreview(preview, x, y) {
  const [originX = 0, originY = 0, originYaw = 0] = preview.origin || []
  const scale = preview.previewScale || 1
  const resolution = Number(preview.resolution || 0)
  const dx = x - originX
  const dy = y - originY
  const cos = Math.cos(originYaw)
  const sin = Math.sin(originYaw)
  const localX = dx * cos + dy * sin
  const localY = -dx * sin + dy * cos
  return {
    px: localX / resolution / scale,
    py: (preview.height - localY / resolution) / scale,
  }
}

function getMapBaseScale(preview, width, height) {
  if (!preview || width <= 0 || height <= 0) return 1
  return Math.min(width / preview.previewWidth, height / preview.previewHeight) * 0.96
}

function rotatePoint(x, y, angle) {
  const cos = Math.cos(angle)
  const sin = Math.sin(angle)
  return {
    x: x * cos - y * sin,
    y: x * sin + y * cos,
  }
}

function canvasToPreviewPoint(preview, view, canvasX, canvasY, width, height) {
  const baseScale = getMapBaseScale(preview, width, height)
  const scale = baseScale * view.scale
  if (!Number.isFinite(scale) || scale === 0) return null
  const dx = canvasX - width / 2 - view.offsetX
  const dy = canvasY - height / 2 - view.offsetY
  const unrotated = rotatePoint(dx, dy, -view.rotation)
  return {
    px: preview.previewWidth / 2 + unrotated.x / scale,
    py: preview.previewHeight / 2 + unrotated.y / scale,
  }
}

function getCanvasPoint(event, canvas) {
  const rect = canvas.getBoundingClientRect()
  return {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
    width: rect.width,
    height: rect.height,
  }
}

function poseDistance(a, b) {
  if (!a || !b) return Infinity
  const dx = Number(a.x) - Number(b.x)
  const dy = Number(a.y) - Number(b.y)
  return Math.hypot(dx, dy)
}

function normalizeTrailPoint(pose) {
  if (!pose || !Number.isFinite(pose.x) || !Number.isFinite(pose.y)) return null
  return {
    x: Number(pose.x),
    y: Number(pose.y),
    yaw: Number.isFinite(pose.yaw) ? Number(pose.yaw) : 0,
    ts: Date.now(),
  }
}

function mergeCurrentIntoTrail(trail, pose) {
  const current = normalizeTrailPoint(pose)
  if (!current) return trail
  if (!trail.length) return [current]
  const last = trail[trail.length - 1]
  if (poseDistance(last, current) < POSE_TRAIL_MIN_DISTANCE) {
    if (trail.length === 1) return trail
    return [...trail.slice(0, -1), current]
  }
  return [...trail, current]
}

function drawTrail(ctx, preview, trail) {
  if (!preview || trail.length === 0) return
  const points = trail.map(point => mapToPreview(preview, point.x, point.y))

  if (points.length > 1) {
    ctx.save()
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'
    ctx.strokeStyle = 'rgba(2, 8, 23, 0.78)'
    ctx.lineWidth = 8
    ctx.beginPath()
    points.forEach((point, index) => {
      if (index === 0) ctx.moveTo(point.px, point.py)
      else ctx.lineTo(point.px, point.py)
    })
    ctx.stroke()

    ctx.strokeStyle = '#22d3ee'
    ctx.lineWidth = 4
    ctx.beginPath()
    points.forEach((point, index) => {
      if (index === 0) ctx.moveTo(point.px, point.py)
      else ctx.lineTo(point.px, point.py)
    })
    ctx.stroke()
    ctx.restore()
  }
}

function drawArrow(ctx, px, py, mapYaw, fillStyle, radius = 18) {
  ctx.save()
  ctx.translate(px, py)
  // Canvas y-axis points down, while ROS map yaw is counterclockwise.
  ctx.rotate(-mapYaw)
  ctx.fillStyle = fillStyle
  ctx.strokeStyle = '#fff'
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(radius, 0)
  ctx.lineTo(-radius * 0.55, -radius * 0.45)
  ctx.lineTo(-radius * 0.32, 0)
  ctx.lineTo(-radius * 0.55, radius * 0.45)
  ctx.closePath()
  ctx.fill()
  ctx.stroke()
  ctx.restore()
}

function drawWaypointMarkers(ctx, preview, waypoints, activeWaypointId) {
  if (!preview || waypoints.length === 0) return
  const points = waypoints.map(point => ({
    ...point,
    ...mapToPreview(preview, point.x, point.y),
  }))

  if (points.length > 1) {
    ctx.save()
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'
    ctx.setLineDash([8, 6])
    ctx.strokeStyle = 'rgba(255, 79, 100, 0.72)'
    ctx.lineWidth = 4
    ctx.beginPath()
    points.forEach((point, index) => {
      if (index === 0) ctx.moveTo(point.px, point.py)
      else ctx.lineTo(point.px, point.py)
    })
    ctx.stroke()
    ctx.restore()
  }

  points.forEach((point, index) => {
    const reached = point.status === 'reached'
    const active = point.id === activeWaypointId
    ctx.save()
    ctx.beginPath()
    ctx.arc(point.px, point.py, 11, 0, Math.PI * 2)
    ctx.fillStyle = reached ? '#22c55e' : active ? '#f59e0b' : '#ff4f64'
    ctx.strokeStyle = active ? '#fef3c7' : '#ffffff'
    ctx.lineWidth = active ? 3 : 2
    ctx.fill()
    ctx.stroke()
    ctx.font = '700 10px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = '#ffffff'
    ctx.fillText(reached ? '✓' : String(index + 1), point.px, point.py + 0.5)
    ctx.restore()
  })
}

export default function PatrolNavigation() {
  const canvasRef = useRef(null)
  const dragRef = useRef(null)
  const waypointIdRef = useRef(1)
  const [devices, setDevices] = useState([])
  const [selectedDeviceId, setSelectedDeviceId] = useState('')
  const [maps, setMaps] = useState([])
  const [selectedMap, setSelectedMap] = useState('')
  const [preview, setPreview] = useState(null)
  const [previewPixels, setPreviewPixels] = useState(null)
  const [mapView, setMapView] = useState(createDefaultMapView)
  const [target, setTarget] = useState(null)
  const [waypoints, setWaypoints] = useState([])
  const [activeWaypointId, setActiveWaypointId] = useState(null)
  const [routeSending, setRouteSending] = useState(false)
  const [poseTrail, setPoseTrail] = useState([])
  const [yawDeg, setYawDeg] = useState(0)
  const [navStatus, setNavStatus] = useState(null)
  const [loadingDevices, setLoadingDevices] = useState(true)
  const [loadingMaps, setLoadingMaps] = useState(false)
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [busyAction, setBusyAction] = useState('')
  const [message, setMessage] = useState('')

  const selectedDevice = useMemo(
    () => devices.find(device => String(device.id) === String(selectedDeviceId)),
    [devices, selectedDeviceId],
  )
  const pendingWaypointCount = useMemo(
    () => waypoints.filter(point => point.status !== 'reached').length,
    [waypoints],
  )
  const robotPose = navStatus?.pose && Number.isFinite(navStatus.pose.x) && Number.isFinite(navStatus.pose.y)
    ? navStatus.pose
    : null
  const localization = navStatus?.localization || {}
  const globalLocalization = localization.globalLocalization || {}
  const localizationReady = Boolean(navStatus?.running && localization.valid)

  const drawMap = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas || !preview || !previewPixels) return
    const rect = canvas.getBoundingClientRect()
    if (rect.width <= 0 || rect.height <= 0) return
    const dpr = window.devicePixelRatio || 1
    const nextWidth = Math.round(rect.width * dpr)
    const nextHeight = Math.round(rect.height * dpr)
    if (canvas.width !== nextWidth) canvas.width = nextWidth
    if (canvas.height !== nextHeight) canvas.height = nextHeight
    const ctx = canvas.getContext('2d')
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, rect.width, rect.height)
    ctx.fillStyle = NAV_MAP_CANVAS_BACKGROUND
    ctx.fillRect(0, 0, rect.width, rect.height)

    const mapCanvas = document.createElement('canvas')
    mapCanvas.width = preview.previewWidth
    mapCanvas.height = preview.previewHeight
    const mapCtx = mapCanvas.getContext('2d')
    const imageData = mapCtx.createImageData(preview.previewWidth, preview.previewHeight)
    for (let i = 0; i < previewPixels.length; i += 1) {
      const value = previewPixels[i]
      const offset = i * 4
      const isUnknownGray = value >= NAV_MAP_UNKNOWN_GRAY_MIN && value <= NAV_MAP_UNKNOWN_GRAY_MAX
      const isFreeGray = value >= NAV_MAP_FREE_GRAY_MIN
      let red = value
      let green = value
      let blue = value
      if (isUnknownGray) {
        [red, green, blue] = NAV_MAP_CANVAS_BACKGROUND_RGB
      } else if (isFreeGray) {
        [red, green, blue] = NAV_MAP_FREE_RGB
      }
      imageData.data[offset] = red
      imageData.data[offset + 1] = green
      imageData.data[offset + 2] = blue
      imageData.data[offset + 3] = 255
    }
    mapCtx.putImageData(imageData, 0, 0)

    const baseScale = getMapBaseScale(preview, rect.width, rect.height)
    const displayScale = baseScale * mapView.scale
    ctx.save()
    ctx.translate(rect.width / 2 + mapView.offsetX, rect.height / 2 + mapView.offsetY)
    ctx.rotate(mapView.rotation)
    ctx.scale(displayScale, displayScale)
    ctx.translate(-preview.previewWidth / 2, -preview.previewHeight / 2)
    ctx.imageSmoothingEnabled = false
    ctx.drawImage(mapCanvas, 0, 0)

    const visibleTrail = localizationReady ? mergeCurrentIntoTrail(poseTrail, robotPose) : []
    drawTrail(ctx, preview, visibleTrail)
    if (localizationReady && robotPose) {
      const { px, py } = mapToPreview(preview, robotPose.x, robotPose.y)
      drawArrow(ctx, px, py, robotPose.yaw || 0, '#22c55e', 18)
      ctx.beginPath()
      ctx.arc(px, py, 5, 0, Math.PI * 2)
      ctx.fillStyle = '#dfffee'
      ctx.fill()
    }
    drawWaypointMarkers(ctx, preview, waypoints, activeWaypointId)
    if (target) {
      const { px, py } = mapToPreview(preview, target.x, target.y)
      drawArrow(ctx, px, py, degToRad(yawDeg), '#ff4f64', 16)
      ctx.beginPath()
      ctx.arc(px, py, 5, 0, Math.PI * 2)
      ctx.fillStyle = '#22d3ee'
      ctx.fill()
    }
    ctx.restore()
  }, [activeWaypointId, localizationReady, mapView, preview, previewPixels, poseTrail, robotPose, target, waypoints, yawDeg])

  const loadDevices = useCallback(async () => {
    setLoadingDevices(true)
    try {
      const response = await authFetch('/api/devices')
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      setDevices(data)
      const preferred = data.find(device => device.control_connected) || data.find(device => device.status === 'online') || data[0]
      if (preferred) setSelectedDeviceId(current => current || String(preferred.id))
    } catch (error) {
      setMessage(`加载设备失败：${error.message}`)
    } finally {
      setLoadingDevices(false)
    }
  }, [])

  const loadStatus = useCallback(async () => {
    if (!selectedDeviceId) return
    try {
      const response = await authFetch(`/api/navigation/status?robotId=${selectedDeviceId}`)
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      setNavStatus(data.response)
    } catch {
      setNavStatus(null)
    }
  }, [selectedDeviceId])

  const loadMaps = useCallback(async () => {
    if (!selectedDeviceId) return
    setLoadingMaps(true)
    setMaps([])
    setSelectedMap('')
    setPreview(null)
    setPreviewPixels(null)
    setMapView(createDefaultMapView())
    setTarget(null)
    setWaypoints([])
    setActiveWaypointId(null)
    setRouteSending(false)
    setPoseTrail([])
    try {
      const response = await authFetch(`/api/navigation/maps?robotId=${selectedDeviceId}`)
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      const nextMaps = data.maps || []
      setMaps(nextMaps)
      if (nextMaps[0]?.name) setSelectedMap(nextMaps[0].name)
      setMessage(nextMaps.length ? '' : '车端 slam_map 目录暂无地图')
    } catch (error) {
      setMessage(`加载地图失败：${error.message}`)
    } finally {
      setLoadingMaps(false)
    }
  }, [selectedDeviceId])

  const loadPreview = useCallback(async () => {
    if (!selectedDeviceId || !selectedMap) return
    setLoadingPreview(true)
    setPreview(null)
    setPreviewPixels(null)
    setMapView(createDefaultMapView())
    setTarget(null)
    setWaypoints([])
    setActiveWaypointId(null)
    setRouteSending(false)
    setPoseTrail([])
    try {
      const response = await authFetch('/api/navigation/map-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robotId: Number(selectedDeviceId), mapName: selectedMap }),
      })
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      setPreview(data.preview)
      setPreviewPixels(decodeGray8(data.preview.data))
      setMessage('')
    } catch (error) {
      setMessage(`加载地图预览失败：${error.message}`)
    } finally {
      setLoadingPreview(false)
    }
  }, [selectedDeviceId, selectedMap])

  useEffect(() => { loadDevices() }, [loadDevices])
  useEffect(() => { loadMaps(); loadStatus() }, [loadMaps, loadStatus])
  useEffect(() => { loadPreview() }, [loadPreview])
  useEffect(() => {
    if (!preview) return undefined
    const handleResize = () => drawMap()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [drawMap, preview])
  useEffect(() => {
    if (!localizationReady) {
      setPoseTrail(current => current.length ? [] : current)
      return
    }
    const point = normalizeTrailPoint(robotPose)
    if (!point) return
    setPoseTrail(current => {
      const next = mergeCurrentIntoTrail(current, point)
      if (next.length > POSE_TRAIL_MAX_POINTS) {
        return [next[0], ...next.slice(next.length - POSE_TRAIL_MAX_POINTS + 1)]
      }
      return next
    })
  }, [localizationReady, robotPose])
  useEffect(() => { drawMap() }, [drawMap])
  useEffect(() => {
    if (!selectedDeviceId) return undefined
    const timer = setInterval(loadStatus, 1500)
    return () => clearInterval(timer)
  }, [loadStatus, selectedDeviceId])

  const runAction = async (action, request, successMessage) => {
    if (!selectedDeviceId) return null
    setBusyAction(action)
    setMessage('')
    try {
      const response = await authFetch(`/api/navigation/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      })
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      if (!data.ok) throw new Error(data.response?.error || '车端拒绝了该指令')
      if (data.response?.type === 'nav_status') setNavStatus(data.response)
      setMessage(successMessage || (action === 'goal' ? '目标点已发送' : '指令已下发'))
      await loadStatus()
      return data
    } catch (error) {
      setMessage(`指令失败：${error.message}`)
      return null
    } finally {
      setBusyAction('')
    }
  }

  const startNavigation = () => {
    setPoseTrail([])
    setRouteSending(false)
    setActiveWaypointId(null)
    setWaypoints(current => current.map(point => ({ ...point, status: 'pending', sentAt: null })))
    return runAction('start', {
      robotId: Number(selectedDeviceId),
      mapName: selectedMap,
    })
  }

  const stopNavigation = () => {
    setRouteSending(false)
    setActiveWaypointId(null)
    setWaypoints(current => current.map(point => (
      point.status === 'active' ? { ...point, status: 'pending', sentAt: null } : point
    )))
    return runAction('stop', {
      robotId: Number(selectedDeviceId),
    })
  }

  const setInitialPose = () => {
    if (!target) return null
    return runAction('initial-pose', {
      robotId: Number(selectedDeviceId),
      x: target.x,
      y: target.y,
      yaw: degToRad(yawDeg),
    }, '已发布 AMCL 初始位姿，正在等待雷达匹配收敛')
  }

  const startGlobalLocalization = () => {
    if (!window.confirm('全局定位会取消当前导航目标并清空 AMCL 粒子分布。车辆不会自动移动；请确认周围安全后再低速旋转或短距离移动。')) return null
    return runAction('global-localization', {
      robotId: Number(selectedDeviceId),
    }, 'AMCL 全局定位已启动，请在安全情况下低速旋转或短距离移动')
  }

  const stopGlobalLocalization = () => runAction('global-localization/stop', {
    robotId: Number(selectedDeviceId),
  }, localizationReady ? '全局定位已结束，当前定位可信' : '全局定位已结束，但当前定位仍未达到可信状态')

  const sendWaypointGoal = waypoint => runAction('goal', {
    robotId: Number(selectedDeviceId),
    x: waypoint.x,
    y: waypoint.y,
    yaw: waypoint.yaw,
  }, `巡航点 ${waypoints.findIndex(point => point.id === waypoint.id) + 1} 已发送`)

  const markWaypointActive = waypointId => {
    const sentAt = Date.now() / 1000
    setWaypoints(current => current.map(point => (
      point.id === waypointId ? { ...point, status: 'active', sentAt } : point
    )))
    setActiveWaypointId(waypointId)
    return sentAt
  }

  const addWaypoint = () => {
    if (!target) return
    setWaypoints(current => [
      ...current,
      {
        id: waypointIdRef.current,
        x: target.x,
        y: target.y,
        yaw: degToRad(yawDeg),
        status: 'pending',
        sentAt: null,
      },
    ])
    waypointIdRef.current += 1
    setMessage(`已添加巡航点 ${waypoints.length + 1}`)
  }

  const sendRoute = async () => {
    if (!localizationReady) {
      setMessage(`AMCL 定位未就绪：${localization.lastError || '请等待自动恢复或完成全局定位'}`)
      return
    }
    const next = waypoints.find(point => point.status !== 'reached')
    if (!next) return
    setRouteSending(true)
    markWaypointActive(next.id)
    const result = await sendWaypointGoal(next)
    if (!result?.ok) {
      setRouteSending(false)
      setActiveWaypointId(null)
      setWaypoints(current => current.map(point => (
        point.id === next.id ? { ...point, status: 'pending', sentAt: null } : point
      )))
    }
  }

  useEffect(() => {
    if (!routeSending || !activeWaypointId) return
    const activeWaypoint = waypoints.find(point => point.id === activeWaypointId)
    if (!activeWaypoint || activeWaypoint.status === 'reached') return

    const goalStatus = navStatus?.goalStatus
    const goalStatusCode = Number(goalStatus?.status)
    const goalUpdatedAt = Number(goalStatus?.updatedAt)
    const sentAt = Number(activeWaypoint.sentAt)
    const goalStatusMatchesActive = (
      Number.isFinite(goalUpdatedAt)
      && Number.isFinite(sentAt)
      && goalUpdatedAt >= sentAt - 0.5
    )
    const reachedByMoveBase = goalStatusMatchesActive && goalStatusCode === MOVE_BASE_SUCCEEDED
    const failedByMoveBase = goalStatusMatchesActive && MOVE_BASE_FAILURE_STATUSES.has(goalStatusCode)

    if (failedByMoveBase) {
      const activeIndex = waypoints.findIndex(point => point.id === activeWaypointId)
      setRouteSending(false)
      setActiveWaypointId(null)
      setWaypoints(current => current.map(point => (
        point.id === activeWaypointId ? { ...point, status: 'pending', sentAt: null } : point
      )))
      setMessage(`巡航点 ${activeIndex + 1} 导航失败：${goalStatus?.label || goalStatusCode}${goalStatus?.text ? `，${goalStatus.text}` : ''}`)
      return
    }

    const reachedByDistance = robotPose && poseDistance(robotPose, activeWaypoint) <= WAYPOINT_REACHED_DISTANCE
    if (!reachedByMoveBase && !reachedByDistance) return

    const activeIndex = waypoints.findIndex(point => point.id === activeWaypointId)
    const nextWaypoint = waypoints.slice(activeIndex + 1).find(point => point.status !== 'reached')
    setWaypoints(current => current.map(point => (
      point.id === activeWaypointId ? { ...point, status: 'reached', sentAt: null } : point
    )))

    if (!nextWaypoint) {
      setActiveWaypointId(null)
      setRouteSending(false)
      setMessage('巡航线路已完成')
      return
    }

    markWaypointActive(nextWaypoint.id)
    sendWaypointGoal(nextWaypoint).then(result => {
      if (result?.ok) return
      setRouteSending(false)
      setActiveWaypointId(null)
      setWaypoints(current => current.map(point => (
        point.id === nextWaypoint.id ? { ...point, status: 'pending', sentAt: null } : point
      )))
    })
  }, [activeWaypointId, navStatus, robotPose, routeSending, waypoints])

  const handleCanvasClick = event => {
    const canvas = event.currentTarget
    if (!preview || !canvas) return
    const canvasPoint = getCanvasPoint(event, canvas)
    const previewPoint = canvasToPreviewPoint(preview, mapView, canvasPoint.x, canvasPoint.y, canvasPoint.width, canvasPoint.height)
    if (!previewPoint) return
    const { px, py } = previewPoint
    if (px < 0 || py < 0 || px > preview.previewWidth || py > preview.previewHeight) return
    const point = previewToMap(preview, px, py)
    setTarget(point)
  }

  const handleCanvasMouseDown = event => {
    if (!preview || event.button !== 0) return
    event.preventDefault()
    const canvas = event.currentTarget
    const point = getCanvasPoint(event, canvas)
    dragRef.current = {
      mode: event.ctrlKey ? 'rotate' : 'pan',
      startX: point.x,
      startY: point.y,
      width: point.width,
      height: point.height,
      startView: mapView,
      startPointerAngle: Math.atan2(point.y - point.height / 2, point.x - point.width / 2),
      moved: false,
    }
    canvas.setPointerCapture?.(event.pointerId)
  }

  const handleCanvasMouseMove = event => {
    const drag = dragRef.current
    if (!drag) return
    event.preventDefault()
    const point = getCanvasPoint(event, event.currentTarget)
    const dx = point.x - drag.startX
    const dy = point.y - drag.startY
    if (!drag.moved && Math.hypot(dx, dy) >= MAP_DRAG_THRESHOLD) drag.moved = true
    if (!drag.moved) return

    if (drag.mode === 'rotate') {
      const pointerAngle = Math.atan2(point.y - point.height / 2, point.x - point.width / 2)
      setMapView(current => ({
        ...current,
        rotation: drag.startView.rotation + pointerAngle - drag.startPointerAngle,
      }))
      return
    }

    setMapView(current => ({
      ...current,
      offsetX: drag.startView.offsetX + dx,
      offsetY: drag.startView.offsetY + dy,
    }))
  }

  const finishCanvasDrag = event => {
    const drag = dragRef.current
    if (!drag) return
    dragRef.current = null
    event.currentTarget.releasePointerCapture?.(event.pointerId)
    if (!drag.moved && drag.mode === 'pan') handleCanvasClick(event)
  }

  const cancelCanvasDrag = event => {
    if (!dragRef.current) return
    dragRef.current = null
    event.currentTarget.releasePointerCapture?.(event.pointerId)
  }

  const handleCanvasWheel = useCallback(event => {
    if (!preview) return
    event.preventDefault()
    const canvas = event.currentTarget
    const point = getCanvasPoint(event, canvas)
    setMapView(current => {
      const nextScale = clamp(current.scale * Math.exp(-event.deltaY * MAP_ZOOM_STEP), MAP_MIN_SCALE, MAP_MAX_SCALE)
      if (nextScale === current.scale) return current
      const previewPoint = canvasToPreviewPoint(preview, current, point.x, point.y, point.width, point.height)
      if (!previewPoint) return current
      const baseScale = getMapBaseScale(preview, point.width, point.height)
      const relX = previewPoint.px - preview.previewWidth / 2
      const relY = previewPoint.py - preview.previewHeight / 2
      const rotated = rotatePoint(relX * baseScale * nextScale, relY * baseScale * nextScale, current.rotation)
      return {
        ...current,
        scale: nextScale,
        offsetX: point.x - point.width / 2 - rotated.x,
        offsetY: point.y - point.height / 2 - rotated.y,
      }
    })
  }, [preview])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !preview) return undefined
    canvas.addEventListener('wheel', handleCanvasWheel, { passive: false })
    return () => canvas.removeEventListener('wheel', handleCanvasWheel)
  }, [handleCanvasWheel, preview])

  return (
    <div className="patrol-page patrol-navigation-page">
      <div className="patrol-header">
        <div className="patrol-header-left">
          <h1>室内实时导航</h1>
          <span className="patrol-subtitle">室内 SLAM 地图定位与目标点导航</span>
        </div>
        <div className="patrol-header-actions">
          <ThemedSelect
            className="patrol-header-select"
            value={selectedDeviceId}
            onChange={event => setSelectedDeviceId(event.target.value)}
            disabled={loadingDevices}
          >
            <option value="">选择设备</option>
            {devices.map(device => (
              <option key={device.id} value={device.id}>
                {device.name} · {device.control_connected ? '控制已连接' : device.status}
              </option>
            ))}
          </ThemedSelect>
          <button className="patrol-btn patrol-btn-secondary" onClick={loadDevices} disabled={loadingDevices}>刷新设备</button>
        </div>
      </div>

      <div className="patrol-body patrol-nav-layout">
        <aside className="patrol-sidebar patrol-nav-sidebar">
          <div className="patrol-sidebar-toolbar">
            <ThemedSelect
              className="patrol-header-select"
              value={selectedMap}
              onChange={event => setSelectedMap(event.target.value)}
              disabled={!selectedDeviceId || loadingMaps || maps.length === 0}
            >
              <option value="">选择地图</option>
              {maps.map(map => <option key={map.name} value={map.name}>{formatMapDisplayName(map.name)}</option>)}
            </ThemedSelect>
          </div>
          <div className="patrol-sidebar-list">
            <div className="patrol-card active">
              <div className="patrol-card-header">
                <span className="patrol-card-title">{selectedDevice?.name || '未选择设备'}</span>
              </div>
              <div className="patrol-card-meta">
                <span className="patrol-card-tag">{selectedDevice?.control_connected ? '控制已连接' : '控制未连接'}</span>
                <span className={`patrol-status-badge ${navStatus?.running ? 'patrol-status-running' : 'patrol-status-pending'}`}>
                  {navStatus?.running ? '导航运行中' : '导航未运行'}
                </span>
              </div>
              <div className="patrol-card-desc">
                地图：{formatMapDisplayName(navStatus?.mapName || selectedMap) || '--'}
              </div>
            </div>

            <div className="patrol-nav-panel">
              <label className="patrol-nav-label">当前车位</label>
              <div className="patrol-nav-coordinate">
                <span>X {formatNumber(robotPose?.x)}</span>
                <span>Y {formatNumber(robotPose?.y)}</span>
                <span>Yaw {robotPose ? Math.round((robotPose.yaw || 0) * 180 / Math.PI) : '--'}°</span>
              </div>
              <div className={`patrol-localization-state ${localizationReady ? 'ready' : 'waiting'}`}>
                <strong>{localizationReady ? 'AMCL 定位可信' : 'AMCL 定位未就绪'}</strong>
                <span>{localizationReady
                  ? `来源：${localization.source || 'amcl'} · 位姿已自动保存`
                  : localization.restoreState === 'pending'
                    ? '正在恢复该地图上次可信位姿…'
                    : localization.restoreError || localization.lastError || '请先启动导航'}</span>
              </div>
            </div>

            <div className="patrol-nav-panel patrol-localization-panel">
              <label className="patrol-nav-label">雷达定位</label>
              <p>建图保存时会记录车辆位姿；再次启用同一地图时自动恢复。车辆被搬动后，可点击地图设置大致位置，或启动全局搜索。</p>
              <div className="patrol-nav-actions patrol-localization-actions">
                <button className="patrol-btn patrol-btn-success" onClick={setInitialPose} disabled={!navStatus?.running || !target || busyAction === 'initial-pose'}>
                  设为车辆位置
                </button>
                {globalLocalization.active ? (
                  <button className="patrol-btn patrol-btn-warning" onClick={stopGlobalLocalization} disabled={busyAction === 'global-localization/stop'}>
                    结束全局定位
                  </button>
                ) : (
                  <button className="patrol-btn patrol-btn-secondary" onClick={startGlobalLocalization} disabled={!navStatus?.running || busyAction === 'global-localization'}>
                    全图雷达搜索
                  </button>
                )}
              </div>
              {globalLocalization.active && (
                <span className="patrol-localization-hint">
                  {localizationReady ? '粒子已收敛，可以结束全局定位。' : '正在搜索；车辆不会自动移动，请在安全情况下低速辅助。'}
                </span>
              )}
            </div>

            <div className="patrol-nav-panel patrol-nav-target-panel">
              <label className="patrol-nav-label">待添加巡航点</label>
              <div className="patrol-nav-coordinate">
                <span>X {formatNumber(target?.x)}</span>
                <span>Y {formatNumber(target?.y)}</span>
                <span>Yaw {yawDeg}°</span>
              </div>
              <input
                className="patrol-nav-range"
                type="range"
                min="-180"
                max="180"
                step="1"
                value={yawDeg}
                onChange={event => setYawDeg(Number(event.target.value))}
              />
              <div className="patrol-nav-heading-buttons">
                {[-180, -90, 0, 90, 180].map(value => (
                  <button key={value} className="patrol-btn patrol-btn-secondary patrol-btn-sm" onClick={() => setYawDeg(value)}>
                    {value}°
                  </button>
                ))}
              </div>
            </div>

            <div className="patrol-nav-panel patrol-waypoint-panel">
              <label className="patrol-nav-label">巡航点</label>
              {waypoints.length ? (
                <div className="patrol-waypoint-list">
                  {waypoints.map((point, index) => (
                    <div key={point.id} className={`patrol-waypoint-item ${point.status}`}>
                      <span className="patrol-waypoint-marker">{point.status === 'reached' ? '✓' : index + 1}</span>
                      <span className="patrol-waypoint-text">
                        X {formatNumber(point.x)} · Y {formatNumber(point.y)} · {Math.round(point.yaw * 180 / Math.PI)}°
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="patrol-waypoint-empty">暂无巡航点</div>
              )}
            </div>

            <div className="patrol-nav-actions patrol-nav-actions-primary">
              <button className="patrol-btn patrol-btn-primary" onClick={startNavigation} disabled={!selectedMap || busyAction === 'start'}>
                {busyAction === 'start' ? '启动中...' : '启动导航'}
              </button>
              <button className="patrol-btn patrol-btn-warning" onClick={stopNavigation} disabled={busyAction === 'stop'}>
                停止导航
              </button>
            </div>
            <div className="patrol-nav-actions patrol-nav-actions-route">
              <button className="patrol-btn patrol-btn-success" onClick={addWaypoint} disabled={!target || routeSending}>
                添加巡航点
              </button>
              <button className="patrol-btn patrol-btn-primary" onClick={sendRoute} disabled={!pendingWaypointCount || !localizationReady || routeSending || busyAction === 'goal'}>
                {routeSending || busyAction === 'goal' ? '发送中...' : '发送巡航线路'}
              </button>
            </div>

            {message && <div className="patrol-form-error">{message}</div>}
          </div>
        </aside>

        <section className="patrol-nav-map-section">
          <div className="patrol-map-container patrol-nav-map-container">
            {loadingPreview ? (
              <div className="patrol-loading"><div className="patrol-spinner" /><span>加载地图...</span></div>
            ) : preview ? (
              <canvas
                ref={canvasRef}
                className="patrol-nav-map-canvas"
                onPointerDown={handleCanvasMouseDown}
                onPointerMove={handleCanvasMouseMove}
                onPointerUp={finishCanvasDrag}
                onPointerCancel={cancelCanvasDrag}
              />
            ) : (
              <div className="patrol-empty">
                <p>{selectedDeviceId ? '暂无可用地图' : '请选择设备'}</p>
              </div>
            )}

            {preview && (
              <div className="patrol-map-badge patrol-nav-map-info">
                <strong>SLAM 地图</strong>
                <span>分辨率：{preview.resolution} m/px</span>
                <span>尺寸：{preview.width} x {preview.height}</span>
                <span>地图原点：{preview.origin?.slice(0, 2).map(formatNumber).join(', ')}</span>
              </div>
            )}

            {target && (
              <div className="patrol-map-badge patrol-nav-target-badge">
                <strong>待添加巡航点</strong>
                <span>X：{formatNumber(target.x)} m</span>
                <span>Y：{formatNumber(target.y)} m</span>
                <span>Yaw：{yawDeg}°</span>
              </div>
            )}
            <div className="patrol-legend patrol-nav-legend">
              <div className="patrol-legend-item"><div className="patrol-legend-line" style={{ background: '#22d3ee' }} />可信定位轨迹</div>
              <div className="patrol-legend-item"><div className="patrol-legend-dot" style={{ background: '#22c55e' }} />当前车位</div>
              <div className="patrol-legend-item"><div className="patrol-legend-dot" style={{ background: '#ff4f64' }} />巡航点</div>
            </div>
          </div>
        </section>

        <aside className="patrol-nav-sensors">
          <CockpitPanel title="摄像头画面" code="CAMERA" meta="01">
            <CameraFeed device={selectedDevice} label="可见光摄像头" view="color" />
          </CockpitPanel>
          <CockpitPanel title="双目深度图" code="DEPTH" meta="02">
            <CameraFeed device={selectedDevice} label="双目深度图" view="depth" />
          </CockpitPanel>
          <CockpitPanel title="激光雷达" code="LIDAR" meta="03">
            <CameraFeed device={selectedDevice} label="C16 16线点云" view="lidar" />
          </CockpitPanel>
        </aside>
      </div>
    </div>
  )
}
