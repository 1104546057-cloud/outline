import { useState, useEffect } from 'react'
import ThemedSelect from '../components/ThemedSelect'
import { authFetch } from '../utils/authFetch'
import '../styles/ClusterManagement.css'

export default function ClusterManagement() {
  const [clusters, setClusters] = useState([])
  const [allDevices, setAllDevices] = useState([])
  const [loading, setLoading] = useState(true)

  // Edit / Create Cluster Modal
  const [showModal, setShowModal] = useState(false)
  const [editingCluster, setEditingCluster] = useState(null)
  const [formData, setFormData] = useState({ name: '', description: '' })

  // Delete Cluster Confirm
  const [deleteClusterConfirm, setDeleteClusterConfirm] = useState(null)

  // Remove Device from Cluster Confirm
  const [removeDeviceConfirm, setRemoveDeviceConfirm] = useState(null)

  // Add Device Modal
  const [showAddDeviceModal, setShowAddDeviceModal] = useState(false)
  const [selectedClusterForDevice, setSelectedClusterForDevice] = useState(null)
  const [deviceToAdd, setDeviceToAdd] = useState('')

  const fetchClusters = async () => {
    try {
      const res = await authFetch('/api/clusters')
      if (res.ok) {
        const data = await res.json()
        setClusters(data)
      }
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const fetchDevices = async () => {
    try {
      const res = await authFetch('/api/devices')
      if (res.ok) {
        const data = await res.json()
        setAllDevices(data)
      }
    } catch (e) {
      console.error(e)
    }
  }

  useEffect(() => {
    fetchClusters()
    fetchDevices()
  }, [])

  // Create / Edit Cluster
  const handleSaveCluster = async (e) => {
    e.preventDefault()
    try {
      const method = editingCluster ? 'PUT' : 'POST'
      const url = editingCluster ? `/api/clusters/${editingCluster.id}` : '/api/clusters'
      const res = await authFetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      })
      
      if (res.ok) {
        setShowModal(false)
        fetchClusters()
      } else {
        const err = await res.json()
        alert(err.detail || '操作失败')
      }
    } catch (e) {
      console.error(e)
    }
  }

  const handleDeleteCluster = async (id) => {
    try {
      const res = await authFetch(`/api/clusters/${id}`, { method: 'DELETE' })
      if (res.ok) {
        setDeleteClusterConfirm(null)
        fetchClusters()
      }
    } catch (e) {
      console.error(e)
    }
  }

  const openCreateModal = () => {
    setEditingCluster(null)
    setFormData({ name: '', description: '' })
    setShowModal(true)
  }

  const openEditModal = (cluster) => {
    setEditingCluster(cluster)
    setFormData({ name: cluster.name, description: cluster.description || '' })
    setShowModal(true)
  }

  // Device Management within Cluster
  const handleRemoveDevice = async (clusterId, deviceId) => {
    try {
      const res = await authFetch(`/api/clusters/${clusterId}/devices/${deviceId}`, {
        method: 'DELETE'
      })
      if (res.ok) {
        setRemoveDeviceConfirm(null)
        fetchClusters()
      }
    } catch (e) {
      console.error(e)
    }
  }

  const openAddDeviceModal = (cluster) => {
    setSelectedClusterForDevice(cluster)
    setDeviceToAdd('')
    setShowAddDeviceModal(true)
  }

  const handleAddDevice = async (e) => {
    e.preventDefault()
    if (!deviceToAdd) {
      alert('请选择一个设备')
      return
    }
    try {
      const res = await authFetch(`/api/clusters/${selectedClusterForDevice.id}/devices`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device_id: parseInt(deviceToAdd) })
      })
      if (res.ok) {
        setShowAddDeviceModal(false)
        fetchClusters()
      } else {
        const err = await res.json()
        alert(err.detail || '添加设备失败')
      }
    } catch (e) {
      console.error(e)
    }
  }

  // 获取当前集群可用的（未在集群内）设备列表
  const getAvailableDevicesForCluster = (cluster) => {
    if (!cluster) return []
    const clusterDeviceIds = cluster.devices.map(d => d.id)
    return allDevices.filter(d => !clusterDeviceIds.includes(d.id))
  }

  return (
    <div className="cluster-management">
      <div className="cm-header">
        <div className="cm-header-left">
          <h1 className="page-title">集群管理</h1>
          <span className="page-subtitle">编组无人设备，实现异构设备的协同工作</span>
        </div>
        <button className="cm-btn-create" onClick={openCreateModal}>
          <span>➕</span> 创建新集群
        </button>
      </div>

      <div className="cm-grid">
        {clusters.map(cluster => (
          <div className="cm-card" key={cluster.id}>
            <div className="cm-card-header">
              <div>
                <h3 className="cm-title">{cluster.name}</h3>
                <p className="cm-desc">{cluster.description || '暂无描述'}</p>
              </div>
              <div className="cm-actions">
                <button className="cm-btn-icon edit" onClick={() => openEditModal(cluster)} title="编辑">✏️</button>
                <button className="cm-btn-icon delete" onClick={() => setDeleteClusterConfirm(cluster)} title="删除">🗑️</button>
              </div>
            </div>

            <div className="cm-device-list">
              <h4>
                <span>已包含设备 ({cluster.devices.length})</span>
              </h4>
              {cluster.devices.map(dev => (
                <div className="cm-device-item" key={dev.id}>
                  <div className="cm-device-info">
                    <span className={`cm-device-status ${dev.status}`}></span>
                    <span>{dev.name} ({dev.type})</span>
                  </div>
                  <button className="cm-btn-remove-device" onClick={() => setRemoveDeviceConfirm({ clusterId: cluster.id, device: dev })} title="移除设备">×</button>
                </div>
              ))}
              {cluster.devices.length === 0 && (
                <div style={{ color: '#64748b', fontSize: '0.85rem', marginBottom: '0.5rem' }}>该集群暂无设备</div>
              )}
              <button className="cm-btn-add-device" onClick={() => openAddDeviceModal(cluster)}>
                + 添加设备
              </button>
            </div>
          </div>
        ))}
        {clusters.length === 0 && !loading && (
          <div style={{ gridColumn: '1 / -1', textAlign: 'center', color: '#94a3b8', padding: '3rem' }}>
            暂无集群，请点击上方按钮创建
          </div>
        )}
      </div>

      {/* 创建/编辑集群弹窗 */}
      {showModal && (
        <div className="cm-modal-overlay">
          <div className="cm-modal" onClick={e => e.stopPropagation()}>
            <div className="cm-modal-header">
              <h2>{editingCluster ? '编辑集群' : '创建新集群'}</h2>
              <button className="cm-modal-close" onClick={() => setShowModal(false)}>✕</button>
            </div>
            <form onSubmit={handleSaveCluster}>
              <div className="cm-form-group">
                <label>集群名称</label>
                <input 
                  type="text" 
                  value={formData.name} 
                  onChange={e => setFormData({...formData, name: e.target.value})} 
                  placeholder="输入集群名称"
                  required 
                />
              </div>
              <div className="cm-form-group">
                <label>描述</label>
                <textarea 
                  value={formData.description} 
                  onChange={e => setFormData({...formData, description: e.target.value})} 
                  placeholder="输入集群描述信息（可选）"
                />
              </div>
              <div className="cm-modal-footer">
                <button type="button" className="cm-btn-cancel" onClick={() => setShowModal(false)}>取消</button>
                <button type="submit" className="cm-btn-submit">保存</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 添加设备弹窗 */}
      {showAddDeviceModal && (
        <div className="cm-modal-overlay">
          <div className="cm-modal" onClick={e => e.stopPropagation()}>
            <div className="cm-modal-header">
              <h2>添加设备到 {selectedClusterForDevice?.name}</h2>
              <button className="cm-modal-close" onClick={() => setShowAddDeviceModal(false)}>✕</button>
            </div>
            <form onSubmit={handleAddDevice}>
              <div className="cm-form-group">
                <label>选择设备</label>
                <ThemedSelect value={deviceToAdd} onChange={e => setDeviceToAdd(e.target.value)}>
                  <option value="" disabled>-- 请选择一台设备 --</option>
                  {getAvailableDevicesForCluster(selectedClusterForDevice).map(dev => (
                    <option key={dev.id} value={dev.id}>{dev.name} ({dev.type} - {dev.ip_address})</option>
                  ))}
                </ThemedSelect>
                {getAvailableDevicesForCluster(selectedClusterForDevice).length === 0 && (
                  <p style={{ color: '#ef4444', fontSize: '0.85rem', marginTop: '0.25rem' }}>所有设备已加入该集群或暂无设备</p>
                )}
              </div>
              <div className="cm-modal-footer">
                <button type="button" className="cm-btn-cancel" onClick={() => setShowAddDeviceModal(false)}>取消</button>
                <button type="submit" className="cm-btn-submit" disabled={getAvailableDevicesForCluster(selectedClusterForDevice).length === 0}>添加</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 删除集群确认弹窗 */}
      {deleteClusterConfirm && (
        <div className="cm-modal-overlay">
          <div className="cm-modal cm-delete-modal" onClick={e => e.stopPropagation()}>
            <div className="cm-delete-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="15" y1="9" x2="9" y2="15"></line>
                <line x1="9" y1="9" x2="15" y2="15"></line>
              </svg>
            </div>
            <h3>确认删除</h3>
            <p>确定要删除集群 <strong>{deleteClusterConfirm.name}</strong> 吗？其包含的设备关联也会被解除（设备本身不会被删除）。</p>
            <div className="cm-modal-footer" style={{ justifyContent: 'center', borderTop: 'none', marginTop: '0' }}>
              <button className="cm-btn-cancel" onClick={() => setDeleteClusterConfirm(null)}>取消</button>
              <button className="cm-btn-danger" onClick={() => handleDeleteCluster(deleteClusterConfirm.id)}>确认删除</button>
            </div>
          </div>
        </div>
      )}

      {/* 移除设备确认弹窗 */}
      {removeDeviceConfirm && (
        <div className="cm-modal-overlay">
          <div className="cm-modal cm-delete-modal" onClick={e => e.stopPropagation()}>
            <div className="cm-delete-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="8" x2="12" y2="12"></line>
                <line x1="12" y1="16" x2="12.01" y2="16"></line>
              </svg>
            </div>
            <h3>确认移除</h3>
            <p>确定将设备 <strong>{removeDeviceConfirm.device.name}</strong> 从集群中移除吗？</p>
            <div className="cm-modal-footer" style={{ justifyContent: 'center', borderTop: 'none', marginTop: '0' }}>
              <button className="cm-btn-cancel" onClick={() => setRemoveDeviceConfirm(null)}>取消</button>
              <button className="cm-btn-danger" onClick={() => handleRemoveDevice(removeDeviceConfirm.clusterId, removeDeviceConfirm.device.id)}>确认移除</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
