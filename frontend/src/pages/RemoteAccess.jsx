/* eslint-disable react/prop-types */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import RFB from '@novnc/novnc'
import '@xterm/xterm/css/xterm.css'
import ThemedSelect from '../components/ThemedSelect'
import { authFetch } from '../utils/authFetch'
import '../styles/RemoteAccess.css'


function Icon({ name, size = 17 }) {
  const paths = {
    terminal: <><path d="M4 5h16v14H4z" /><path d="m7 9 3 3-3 3m5 0h5" /></>,
    desktop: <><rect x="3" y="4" width="18" height="14" rx="2" /><path d="M8 22h8m-4-4v4" /></>,
    folder: <path d="M3 6h7l2 2h9v11H3z" />,
    file: <><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v5h5" /></>,
    link: <><path d="M10 13a5 5 0 0 0 7.5.5l2-2a5 5 0 0 0-7-7l-1 1" /><path d="M14 11a5 5 0 0 0-7.5-.5l-2 2a5 5 0 0 0 7 7l1-1" /></>,
    refresh: <><path d="M20 6v5h-5" /><path d="M18 17a8 8 0 1 1 1.8-8.5L20 11" /></>,
    upload: <><path d="M12 16V4m-4 4 4-4 4 4" /><path d="M4 15v5h16v-5" /></>,
    download: <><path d="M12 4v12m-4-4 4 4 4-4" /><path d="M4 20h16" /></>,
    plus: <><path d="M12 5v14M5 12h14" /></>,
    edit: <><path d="m4 20 4-1 11-11-3-3L5 16z" /><path d="m14 7 3 3" /></>,
    trash: <><path d="M4 7h16M9 7V4h6v3m3 0-1 14H7L6 7" /><path d="M10 11v6m4-6v6" /></>,
    fullscreen: <path d="M8 3H3v5m13-5h5v5m0 8v5h-5M3 16v5h5" />,
    clipboard: <><rect x="6" y="5" width="12" height="16" rx="2" /><path d="M9 5V3h6v2M9 10h6m-6 4h6" /></>,
    keys: <><rect x="3" y="6" width="18" height="12" rx="2" /><path d="M7 10h.01M11 10h.01M15 10h.01M7 14h7m2 0h1" /></>,
  }
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {paths[name] || paths.file}
    </svg>
  )
}


function joinPath(parent, name) {
  const cleanParent = parent === '/' ? '' : parent.replace(/\/$/, '')
  return `${cleanParent}/${name}`.replace(/\/+/g, '/') || '/'
}


function parentPath(path) {
  if (!path || path === '/') return '/'
  const value = path.replace(/\/$/, '')
  const index = value.lastIndexOf('/')
  return index <= 0 ? '/' : value.slice(0, index)
}


function formatSize(size) {
  if (!Number.isFinite(size)) return '--'
  if (size < 1024) return `${size} B`
  if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KB`
  if (size < 1024 ** 3) return `${(size / 1024 ** 2).toFixed(1)} MB`
  return `${(size / 1024 ** 3).toFixed(1)} GB`
}


async function responseError(response, fallback) {
  try {
    const data = await response.json()
    return data.detail || data.error || fallback
  } catch {
    return fallback
  }
}


function FileTreeRow({ entry, depth, expanded, selected, onSelect, onToggle, onDownload, onRename, onDelete }) {
  const isDirectory = entry.type === 'directory'
  return (
    <div
      className={`ra-file-row ${selected ? 'selected' : ''} ${entry.hidden ? 'hidden-file' : ''}`}
      style={{ '--tree-depth': depth }}
      onClick={() => onSelect(entry)}
      onDoubleClick={() => isDirectory && onToggle(entry)}
      title={`${entry.path}\n${entry.permissions || ''}`}
    >
      <button
        className={`ra-tree-toggle ${isDirectory ? '' : 'placeholder'}`}
        onClick={(event) => { event.stopPropagation(); if (isDirectory) onToggle(entry) }}
        aria-label={expanded ? '折叠目录' : '展开目录'}
      >
        {isDirectory ? (expanded ? '▾' : '▸') : ''}
      </button>
      <span className={`ra-file-icon ${entry.type}`}>
        <Icon name={isDirectory ? 'folder' : entry.type === 'symlink' ? 'link' : 'file'} size={15} />
      </span>
      <span className="ra-file-name">{entry.name}</span>
      <span className="ra-file-actions">
        {entry.type === 'file' && (
          <button onClick={(event) => { event.stopPropagation(); onDownload(entry) }} title="下载"><Icon name="download" size={13} /></button>
        )}
        <button onClick={(event) => { event.stopPropagation(); onRename(entry) }} title="重命名"><Icon name="edit" size={13} /></button>
        <button className="danger" onClick={(event) => { event.stopPropagation(); onDelete(entry) }} title="删除"><Icon name="trash" size={13} /></button>
      </span>
    </div>
  )
}


export default function RemoteAccess() {
  const [devices, setDevices] = useState([])
  const [selectedDeviceId, setSelectedDeviceId] = useState('')
  const [remoteStatus, setRemoteStatus] = useState({ connected: false, capabilities: {} })
  const [statusMessage, setStatusMessage] = useState('请选择无人设备')
  const [activeMode, setActiveMode] = useState('ssh')
  const [username, setUsername] = useState('wheeltec')
  const [terminalState, setTerminalState] = useState('disconnected')
  const [vncState, setVncState] = useState('disconnected')
  const [vncMessage, setVncMessage] = useState('尚未连接桌面')
  const [vncPassword, setVncPassword] = useState('')
  const [viewOnly, setViewOnly] = useState(false)
  const [directoryEntries, setDirectoryEntries] = useState({})
  const [expandedPaths, setExpandedPaths] = useState(new Set())
  const [selectedEntry, setSelectedEntry] = useState(null)
  const [loadingPaths, setLoadingPaths] = useState(new Set())
  const [fileMessage, setFileMessage] = useState('连接 Agent 后可管理设备文件')
  const [fileBusy, setFileBusy] = useState(false)

  const terminalHostRef = useRef(null)
  const terminalRef = useRef(null)
  const fitAddonRef = useRef(null)
  const terminalSocketRef = useRef(null)
  const vncHostRef = useRef(null)
  const vncStageRef = useRef(null)
  const rfbRef = useRef(null)
  const fileInputRef = useRef(null)

  const loadDevices = useCallback(async () => {
    try {
      const response = await authFetch('/api/devices')
      if (!response.ok) throw new Error(await responseError(response, '设备列表加载失败'))
      const data = await response.json()
      setDevices(data)
      setSelectedDeviceId(current => current || (data[0] ? String(data[0].id) : ''))
    } catch (error) {
      setStatusMessage(error.message)
    }
  }, [])

  useEffect(() => { loadDevices() }, [loadDevices])

  const loadStatus = useCallback(async () => {
    if (!selectedDeviceId) {
      setRemoteStatus({ connected: false, capabilities: {} })
      setStatusMessage('请选择无人设备')
      return
    }
    try {
      const response = await authFetch(`/api/remote-access/devices/${selectedDeviceId}/status`)
      if (!response.ok) throw new Error(await responseError(response, '远程访问状态获取失败'))
      const data = await response.json()
      setRemoteStatus(data)
      setStatusMessage(data.connected ? '远程访问 Agent 已连接' : '远程访问 Agent 未连接')
      const agentUser = data.capabilities?.user
      if (agentUser) setUsername(current => current || agentUser)
    } catch (error) {
      setRemoteStatus({ connected: false, capabilities: {} })
      setStatusMessage(error.message)
    }
  }, [selectedDeviceId])

  useEffect(() => {
    loadStatus()
    if (!selectedDeviceId) return undefined
    const timer = setInterval(loadStatus, 5000)
    return () => clearInterval(timer)
  }, [loadStatus, selectedDeviceId])

  const loadDirectory = useCallback(async (path = '/') => {
    if (!selectedDeviceId) return
    setLoadingPaths(current => new Set(current).add(path))
    try {
      const response = await authFetch(`/api/remote-access/devices/${selectedDeviceId}/files?path=${encodeURIComponent(path)}`)
      if (!response.ok) throw new Error(await responseError(response, '目录加载失败'))
      const data = await response.json()
      setDirectoryEntries(current => ({ ...current, [data.path]: data.entries || [] }))
      setFileMessage(`${data.entries?.length || 0} 个项目 · ${data.path}`)
    } catch (error) {
      setFileMessage(error.message)
    } finally {
      setLoadingPaths(current => {
        const next = new Set(current)
        next.delete(path)
        return next
      })
    }
  }, [selectedDeviceId])

  useEffect(() => {
    if (remoteStatus.connected && selectedDeviceId && !directoryEntries['/']) loadDirectory('/')
  }, [remoteStatus.connected, selectedDeviceId, directoryEntries, loadDirectory])

  const disconnectTerminal = useCallback((announce = true) => {
    const socket = terminalSocketRef.current
    terminalSocketRef.current = null
    if (socket) {
      socket.onopen = null
      socket.onmessage = null
      socket.onerror = null
      socket.onclose = null
      if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) socket.close(1000, 'client disconnect')
    }
    setTerminalState('disconnected')
    if (announce && terminalRef.current) terminalRef.current.writeln('\r\n\x1b[33m[SSH 会话已断开]\x1b[0m')
  }, [])

  const disconnectVnc = useCallback(() => {
    const rfb = rfbRef.current
    rfbRef.current = null
    if (rfb) {
      try { rfb.disconnect() } catch { /* no-op */ }
    }
    if (vncHostRef.current) vncHostRef.current.replaceChildren()
    setVncState('disconnected')
    setVncMessage('尚未连接桌面')
  }, [])

  useEffect(() => {
    const host = terminalHostRef.current
    if (!host || terminalRef.current) return undefined
    const terminal = new Terminal({
      cursorBlink: true,
      cursorStyle: 'bar',
      fontFamily: 'Cascadia Mono, JetBrains Mono, Consolas, monospace',
      fontSize: 14,
      lineHeight: 1.18,
      scrollback: 5000,
      allowTransparency: true,
      theme: {
        background: '#020813',
        foreground: '#d6edf7',
        cursor: '#43d6ff',
        cursorAccent: '#020813',
        selectionBackground: '#165f84aa',
        black: '#07101d', red: '#ff6176', green: '#38dba3', yellow: '#f2bd5a',
        blue: '#3e9cff', magenta: '#bd83ff', cyan: '#3bdcff', white: '#d6edf7',
        brightBlack: '#5a7890', brightRed: '#ff8b9a', brightGreen: '#6ef3c1', brightYellow: '#ffda83',
        brightBlue: '#76baff', brightMagenta: '#d4adff', brightCyan: '#83eaff', brightWhite: '#f4fcff',
      },
    })
    const fitAddon = new FitAddon()
    terminal.loadAddon(fitAddon)
    terminal.open(host)
    terminal.writeln('\x1b[36mDevicesWebControl SSH Console\x1b[0m')
    terminal.writeln('\x1b[90m选择设备后点击“连接 SSH”，认证由车端 OpenSSH 处理。\x1b[0m\r\n')
    const inputDisposable = terminal.onData(data => {
      const socket = terminalSocketRef.current
      if (socket?.readyState === WebSocket.OPEN) socket.send(new TextEncoder().encode(data))
    })
    const sendResize = () => {
      if (host.clientWidth < 30 || host.clientHeight < 30) return
      try { fitAddon.fit() } catch { return }
      const socket = terminalSocketRef.current
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'resize', cols: terminal.cols, rows: terminal.rows }))
      }
    }
    const observer = new ResizeObserver(sendResize)
    observer.observe(host)
    terminalRef.current = terminal
    fitAddonRef.current = fitAddon
    requestAnimationFrame(sendResize)
    return () => {
      observer.disconnect()
      inputDisposable.dispose()
      disconnectTerminal(false)
      terminal.dispose()
      terminalRef.current = null
      fitAddonRef.current = null
    }
  }, [disconnectTerminal])

  useEffect(() => () => disconnectVnc(), [disconnectVnc])

  useEffect(() => {
    disconnectTerminal(false)
    disconnectVnc()
    setDirectoryEntries({})
    setExpandedPaths(new Set())
    setSelectedEntry(null)
    setFileMessage(selectedDeviceId ? '正在读取设备文件…' : '请选择无人设备')
  }, [selectedDeviceId, disconnectTerminal, disconnectVnc])

  const connectTerminal = () => {
    if (!selectedDeviceId || !remoteStatus.connected || !terminalRef.current) return
    disconnectTerminal(false)
    const terminal = terminalRef.current
    try { fitAddonRef.current?.fit() } catch { /* hidden panel */ }
    terminal.clear()
    terminal.writeln(`\x1b[36m[正在通过 Agent 建立 ${username}@127.0.0.1 的 OpenSSH 会话…]\x1b[0m`)
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const params = new URLSearchParams({ username, cols: String(terminal.cols), rows: String(terminal.rows) })
    const socket = new WebSocket(`${protocol}//${window.location.host}/api/remote-access/devices/${selectedDeviceId}/terminal?${params}`)
    socket.binaryType = 'arraybuffer'
    terminalSocketRef.current = socket
    setTerminalState('connecting')
    socket.onopen = () => {
      setTerminalState('connected')
      socket.send(JSON.stringify({ type: 'resize', cols: terminal.cols, rows: terminal.rows }))
      terminal.focus()
    }
    socket.onmessage = event => {
      if (event.data instanceof ArrayBuffer) terminal.write(new Uint8Array(event.data))
      else if (event.data instanceof Blob) event.data.arrayBuffer().then(buffer => terminal.write(new Uint8Array(buffer)))
      else terminal.write(event.data)
    }
    socket.onerror = () => setTerminalState('error')
    socket.onclose = event => {
      if (terminalSocketRef.current === socket) terminalSocketRef.current = null
      setTerminalState('disconnected')
      terminal.writeln(`\r\n\x1b[33m[SSH 连接已关闭${event.code !== 1000 ? ` · ${event.code}` : ''}]\x1b[0m`)
    }
  }

  const connectVnc = () => {
    if (!selectedDeviceId || !remoteStatus.connected || !vncHostRef.current) return
    disconnectVnc()
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/api/remote-access/devices/${selectedDeviceId}/vnc`
    setVncState('connecting')
    setVncMessage('正在建立 VNC 桌面连接…')
    try {
      const rfb = new RFB(vncHostRef.current, url, { credentials: { password: vncPassword } })
      rfb.scaleViewport = true
      rfb.resizeSession = false
      rfb.clipViewport = false
      rfb.viewOnly = viewOnly
      rfb.qualityLevel = 7
      rfb.compressionLevel = 6
      rfb.addEventListener('connect', () => {
        setVncState('connected')
        setVncMessage('VNC 桌面已连接')
        rfb.focus()
      })
      rfb.addEventListener('disconnect', event => {
        setVncState('disconnected')
        setVncMessage(event.detail?.clean ? 'VNC 会话已断开' : 'VNC 连接异常断开')
        if (rfbRef.current === rfb) rfbRef.current = null
      })
      rfb.addEventListener('credentialsrequired', () => {
        if (vncPassword) rfb.sendCredentials({ password: vncPassword })
        else {
          setVncState('credentials')
          setVncMessage('VNC 服务要求密码，请输入后重新连接')
        }
      })
      rfb.addEventListener('securityfailure', event => {
        setVncState('error')
        setVncMessage(event.detail?.reason || 'VNC 安全协商失败')
      })
      rfbRef.current = rfb
    } catch (error) {
      setVncState('error')
      setVncMessage(error.message || 'VNC 客户端初始化失败')
    }
  }

  useEffect(() => {
    if (rfbRef.current) rfbRef.current.viewOnly = viewOnly
  }, [viewOnly])

  const toggleDirectory = async entry => {
    if (entry.type !== 'directory') return
    const willExpand = !expandedPaths.has(entry.path)
    setExpandedPaths(current => {
      const next = new Set(current)
      if (willExpand) next.add(entry.path)
      else next.delete(entry.path)
      return next
    })
    if (willExpand && !directoryEntries[entry.path]) await loadDirectory(entry.path)
  }

  const flattenedEntries = useMemo(() => {
    const rows = []
    const visit = (path, depth) => {
      for (const entry of directoryEntries[path] || []) {
        rows.push({ entry, depth })
        if (entry.type === 'directory' && expandedPaths.has(entry.path)) visit(entry.path, depth + 1)
      }
    }
    visit('/', 0)
    return rows
  }, [directoryEntries, expandedPaths])

  const uploadDirectory = selectedEntry?.type === 'directory'
    ? selectedEntry.path
    : selectedEntry ? parentPath(selectedEntry.path) : '/'

  const createDirectory = async () => {
    if (!remoteStatus.connected || fileBusy) return
    const name = window.prompt(`在 ${uploadDirectory} 中新建目录：`, 'new-folder')
    if (!name) return
    if (name === '.' || name === '..' || /[\\/\0]/.test(name)) {
      setFileMessage('目录名称不能包含路径分隔符')
      return
    }
    setFileBusy(true)
    try {
      const response = await authFetch(`/api/remote-access/devices/${selectedDeviceId}/files/mkdir`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: joinPath(uploadDirectory, name) }),
      })
      if (!response.ok) throw new Error(await responseError(response, '新建目录失败'))
      await loadDirectory(uploadDirectory)
      setExpandedPaths(current => new Set(current).add(uploadDirectory))
      setFileMessage(`目录 ${name} 已创建`)
    } catch (error) {
      setFileMessage(error.message)
    } finally {
      setFileBusy(false)
    }
  }

  const uploadFile = async file => {
    if (!file || !selectedDeviceId) return
    const path = joinPath(uploadDirectory, file.name)
    setFileBusy(true)
    const send = async overwrite => authFetch(`/api/remote-access/devices/${selectedDeviceId}/files/upload?path=${encodeURIComponent(path)}&overwrite=${overwrite ? 'true' : 'false'}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/octet-stream' }, body: file,
    })
    try {
      setFileMessage(`正在上传 ${file.name}（${formatSize(file.size)}）…`)
      let response = await send(false)
      if (response.status === 409 && window.confirm(`${file.name} 已存在，是否覆盖？`)) response = await send(true)
      if (!response.ok) throw new Error(await responseError(response, '文件上传失败'))
      await loadDirectory(uploadDirectory)
      setFileMessage(`${file.name} 上传完成`)
    } catch (error) {
      setFileMessage(error.message)
    } finally {
      setFileBusy(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const downloadFile = async entry => {
    setFileBusy(true)
    try {
      const response = await authFetch(`/api/remote-access/devices/${selectedDeviceId}/files/download?path=${encodeURIComponent(entry.path)}`)
      if (!response.ok) throw new Error(await responseError(response, '文件下载失败'))
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = entry.name
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      setFileMessage(`${entry.name} 下载完成`)
    } catch (error) {
      setFileMessage(error.message)
    } finally {
      setFileBusy(false)
    }
  }

  const renameEntry = async entry => {
    const name = window.prompt('输入新名称：', entry.name)
    if (!name || name === entry.name) return
    if (name === '.' || name === '..' || /[\\/\0]/.test(name)) {
      setFileMessage('名称不能包含路径分隔符')
      return
    }
    const parent = parentPath(entry.path)
    setFileBusy(true)
    try {
      const response = await authFetch(`/api/remote-access/devices/${selectedDeviceId}/files/rename`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: entry.path, destination: joinPath(parent, name) }),
      })
      if (!response.ok) throw new Error(await responseError(response, '重命名失败'))
      setDirectoryEntries(current => {
        const next = { ...current }
        for (const key of Object.keys(next)) if (key === entry.path || key.startsWith(`${entry.path}/`)) delete next[key]
        return next
      })
      setSelectedEntry(null)
      await loadDirectory(parent)
      setFileMessage(`${entry.name} 已重命名为 ${name}`)
    } catch (error) {
      setFileMessage(error.message)
    } finally {
      setFileBusy(false)
    }
  }

  const deleteEntry = async entry => {
    const hint = entry.type === 'directory' ? '（仅允许删除空目录）' : ''
    if (!window.confirm(`确定删除 ${entry.path}？${hint}`)) return
    setFileBusy(true)
    try {
      const response = await authFetch(`/api/remote-access/devices/${selectedDeviceId}/files/delete`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: entry.path }),
      })
      if (!response.ok) throw new Error(await responseError(response, '删除失败'))
      const parent = parentPath(entry.path)
      setDirectoryEntries(current => {
        const next = { ...current }
        for (const key of Object.keys(next)) if (key === entry.path || key.startsWith(`${entry.path}/`)) delete next[key]
        return next
      })
      setSelectedEntry(null)
      await loadDirectory(parent)
      setFileMessage(`${entry.name} 已删除`)
    } catch (error) {
      setFileMessage(error.message)
    } finally {
      setFileBusy(false)
    }
  }

  const capabilities = remoteStatus.capabilities || {}
  const selectedDevice = devices.find(device => String(device.id) === selectedDeviceId)
  const remoteRoot = capabilities.files?.root || '/home/device'
  const remoteAvailable = Boolean(remoteStatus.connected)

  return (
    <div className="remote-access-page">
      <header className="ra-header">
        <div className="ra-title-block">
          <span className="ra-title-kicker">REMOTE OPERATIONS</span>
          <h1>无人设备 SSH / VNC 控制</h1>
          <p>车端主动连接 · OpenSSH 终端 · 安全文件管理 · noVNC 桌面</p>
        </div>
        <div className="ra-device-control">
          <label htmlFor="ra-device-select">目标设备</label>
          <ThemedSelect id="ra-device-select" value={selectedDeviceId} onChange={event => setSelectedDeviceId(event.target.value)}>
            <option value="">请选择设备</option>
            {devices.map(device => <option key={device.id} value={device.id}>{device.name} · {device.type}</option>)}
          </ThemedSelect>
          <button className="ra-icon-button" onClick={() => { loadDevices(); loadStatus() }} title="刷新状态"><Icon name="refresh" /></button>
          <span className={`ra-agent-status ${remoteAvailable ? 'online' : 'offline'}`}><i />{statusMessage}</span>
        </div>
      </header>

      <div className="ra-workspace">
        <aside className="ra-files-panel">
          <div className="ra-panel-heading">
            <div>
              <span className="ra-panel-label">DEVICE FILES</span>
              <h2>文件管理</h2>
            </div>
            <span className="ra-root-path" title={remoteRoot}>{remoteRoot}</span>
          </div>
          <div className="ra-file-toolbar">
            <button onClick={createDirectory} disabled={!remoteAvailable || fileBusy} title="新建目录"><Icon name="plus" /><span>目录</span></button>
            <button onClick={() => fileInputRef.current?.click()} disabled={!remoteAvailable || fileBusy} title={`上传到 ${uploadDirectory}`}><Icon name="upload" /><span>上传</span></button>
            <button onClick={() => loadDirectory('/')} disabled={!remoteAvailable || fileBusy} title="刷新文件树"><Icon name="refresh" /></button>
            <input ref={fileInputRef} type="file" hidden onChange={event => uploadFile(event.target.files?.[0])} />
          </div>
          <div className="ra-upload-target" title={uploadDirectory}>当前目录 <strong>{uploadDirectory}</strong></div>
          <div className="ra-file-tree">
            {!remoteAvailable && <div className="ra-file-empty">等待车端 Remote Access Agent 连接</div>}
            {remoteAvailable && loadingPaths.has('/') && !directoryEntries['/'] && <div className="ra-file-empty">正在读取目录…</div>}
            {remoteAvailable && !loadingPaths.has('/') && directoryEntries['/']?.length === 0 && <div className="ra-file-empty">目录为空</div>}
            {flattenedEntries.map(({ entry, depth }) => (
              <FileTreeRow
                key={entry.path}
                entry={entry}
                depth={depth}
                expanded={expandedPaths.has(entry.path)}
                selected={selectedEntry?.path === entry.path}
                onSelect={setSelectedEntry}
                onToggle={toggleDirectory}
                onDownload={downloadFile}
                onRename={renameEntry}
                onDelete={deleteEntry}
              />
            ))}
          </div>
          {selectedEntry && (
            <div className="ra-file-detail">
              <strong>{selectedEntry.name}</strong>
              <span>{selectedEntry.type} · {formatSize(selectedEntry.size)}</span>
              <span>{selectedEntry.permissions} · {new Date(selectedEntry.modified).toLocaleString('zh-CN')}</span>
            </div>
          )}
          <div className={`ra-file-message ${fileBusy ? 'busy' : ''}`}>{fileBusy && <i />}{fileMessage}</div>
        </aside>

        <section className="ra-console-panel">
          <div className="ra-mode-tabs">
            <button className={activeMode === 'ssh' ? 'active' : ''} onClick={() => setActiveMode('ssh')}><Icon name="terminal" />SSH 终端</button>
            <button className={activeMode === 'vnc' ? 'active' : ''} onClick={() => setActiveMode('vnc')}><Icon name="desktop" />VNC 桌面</button>
            <div className="ra-target-summary">
              <span>{selectedDevice?.name || '未选择设备'}</span>
              <small>{selectedDeviceId ? `ID ${selectedDeviceId}` : '--'} · Agent {remoteAvailable ? 'ONLINE' : 'OFFLINE'}</small>
            </div>
          </div>

          <div className={`ra-mode-content ${activeMode === 'ssh' ? 'active' : ''}`}>
            <div className="ra-session-toolbar">
              <label>SSH 用户<input value={username} onChange={event => setUsername(event.target.value)} disabled={terminalState === 'connected'} /></label>
              <span className={`ra-session-state ${terminalState}`}>{terminalState === 'connected' ? '已连接' : terminalState === 'connecting' ? '连接中' : terminalState === 'error' ? '连接异常' : '未连接'}</span>
              <button className="primary" onClick={connectTerminal} disabled={!remoteAvailable || terminalState === 'connecting'}>{terminalState === 'connected' ? '重新连接' : '连接 SSH'}</button>
              <button onClick={() => disconnectTerminal()} disabled={terminalState === 'disconnected'}>断开</button>
            </div>
            <div className="ra-terminal-frame"><div ref={terminalHostRef} className="ra-terminal-host" /></div>
            <div className="ra-session-note">浏览器只传输终端字节流；用户名、密码与权限校验均由设备本机 OpenSSH 完成。</div>
          </div>

          <div className={`ra-mode-content ${activeMode === 'vnc' ? 'active' : ''}`}>
            <div className="ra-session-toolbar">
              <label>VNC 密码<input type="password" value={vncPassword} onChange={event => setVncPassword(event.target.value)} placeholder="未设置可留空" /></label>
              <label className="ra-check"><input type="checkbox" checked={viewOnly} onChange={event => setViewOnly(event.target.checked)} />只读</label>
              <span className={`ra-session-state ${vncState}`}>{vncMessage}</span>
              <button className="primary" onClick={connectVnc} disabled={!remoteAvailable || vncState === 'connecting'}>{vncState === 'connected' ? '重新连接' : '连接 VNC'}</button>
              <button onClick={disconnectVnc} disabled={vncState === 'disconnected'}>断开</button>
              <button onClick={() => rfbRef.current?.sendCtrlAltDel()} disabled={vncState !== 'connected' || viewOnly} title="发送 Ctrl+Alt+Del"><Icon name="keys" /></button>
              <button onClick={() => {
                const text = window.prompt('发送到远程桌面的剪贴板文本：')
                if (text != null) rfbRef.current?.clipboardPasteFrom(text)
              }} disabled={vncState !== 'connected' || viewOnly} title="发送剪贴板"><Icon name="clipboard" /></button>
              <button onClick={() => vncStageRef.current?.requestFullscreen()} disabled={vncState !== 'connected'} title="全屏"><Icon name="fullscreen" /></button>
            </div>
            <div ref={vncStageRef} className="ra-vnc-stage">
              <div ref={vncHostRef} className="ra-vnc-host" />
              {vncState !== 'connected' && (
                <div className="ra-vnc-placeholder">
                  <Icon name="desktop" size={52} />
                  <strong>{vncMessage}</strong>
                  <span>{capabilities.vnc?.available === false ? '车端 127.0.0.1:5900 未检测到 VNC 服务' : '桌面画面经 Agent 反向通道传输，不暴露 VNC 公网端口'}</span>
                </div>
              )}
            </div>
            <div className="ra-session-note">客户端使用 noVNC；当前目标为车端本机 5900 端口，鼠标和键盘事件直接交给 RFB 会话。</div>
          </div>
        </section>
      </div>
    </div>
  )
}
