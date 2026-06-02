import { useState, useEffect } from 'react'
import { authFetch } from '../utils/authFetch'
import '../styles/UserManagement.css'

/**
 * 用户管理页面
 *
 * 支持查看用户列表、新增用户、编辑用户、删除用户
 */
function UserManagement() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editingUser, setEditingUser] = useState(null)
  const [formData, setFormData] = useState({
    username: '',
    password: '',
    nickname: '',
    is_active: true,
  })
  const [formError, setFormError] = useState('')
  const [deleteConfirm, setDeleteConfirm] = useState(null)
  const [searchTerm, setSearchTerm] = useState('')
  const [notification, setNotification] = useState(null)

  // 加载用户列表
  const fetchUsers = async () => {
    try {
      setLoading(true)
      const response = await authFetch('/api/users')
      if (response.ok) {
        const data = await response.json()
        setUsers(data)
      }
    } catch (err) {
      console.error('获取用户列表失败:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchUsers()
  }, [])

  // 显示通知
  const showNotification = (message, type = 'success') => {
    setNotification({ message, type })
    setTimeout(() => setNotification(null), 3000)
  }

  // 打开新增/编辑弹窗
  const openModal = (user = null) => {
    if (user) {
      setEditingUser(user)
      setFormData({
        username: user.username,
        password: '',
        nickname: user.nickname || '',
        is_active: user.is_active,
      })
    } else {
      setEditingUser(null)
      setFormData({
        username: '',
        password: '',
        nickname: '',
        is_active: true,
      })
    }
    setFormError('')
    setShowModal(true)
  }

  // 提交表单
  const handleSubmit = async (e) => {
    e.preventDefault()
    setFormError('')

    if (!formData.username.trim()) {
      setFormError('请输入用户名')
      return
    }
    if (!editingUser && !formData.password.trim()) {
      setFormError('请输入密码')
      return
    }

    try {
      const url = editingUser
        ? `/api/users/${editingUser.id}`
        : '/api/users'
      const method = editingUser ? 'PUT' : 'POST'

      const body = { ...formData }
      if (editingUser && !body.password) {
        delete body.password
      }

      const response = await authFetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      if (response.ok) {
        showNotification(editingUser ? '用户更新成功' : '用户创建成功')
        setShowModal(false)
        fetchUsers()
      } else {
        const data = await response.json()
        setFormError(data.detail || '操作失败')
      }
    } catch {
      setFormError('服务器连接失败')
    }
  }

  // 删除用户
  const handleDelete = async (userId) => {
    try {
      const response = await authFetch(`/api/users/${userId}`, {
        method: 'DELETE',
      })
      if (response.ok) {
        showNotification('用户删除成功')
        setDeleteConfirm(null)
        fetchUsers()
      } else {
        const data = await response.json()
        showNotification(data.detail || '删除失败', 'error')
      }
    } catch {
      showNotification('服务器连接失败', 'error')
    }
  }

  // 过滤用户
  const filteredUsers = users.filter(user =>
    user.username.toLowerCase().includes(searchTerm.toLowerCase()) ||
    (user.nickname && user.nickname.toLowerCase().includes(searchTerm.toLowerCase()))
  )

  return (
    <div className="user-management" id="user-management-page">
      {/* 通知 */}
      {notification && (
        <div className={`toast-notification ${notification.type}`}>
          <span className="toast-icon">
            {notification.type === 'success' ? '✓' : '✕'}
          </span>
          <span>{notification.message}</span>
        </div>
      )}

      {/* ===== 页面头部 ===== */}
      <div className="um-header">
        <div className="um-header-left">
          <h1 className="page-title">用户管理</h1>
          <span className="page-subtitle">管理系统用户账号</span>
        </div>
        <div className="um-header-right">
          <div className="um-search">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <input
              type="text"
              placeholder="搜索用户..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              id="search-users"
            />
          </div>
          <button className="btn-primary" onClick={() => openModal()} id="add-user-btn">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
            新增用户
          </button>
        </div>
      </div>

      {/* ===== 统计卡片 ===== */}
      <div className="um-stats">
        <div className="um-stat-card">
          <div className="um-stat-icon total">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
              <circle cx="9" cy="7" r="4"></circle>
              <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
              <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
            </svg>
          </div>
          <div className="um-stat-info">
            <span className="um-stat-number">{users.length}</span>
            <span className="um-stat-label">用户总数</span>
          </div>
        </div>
        <div className="um-stat-card">
          <div className="um-stat-icon active">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
              <polyline points="22 4 12 14.01 9 11.01"></polyline>
            </svg>
          </div>
          <div className="um-stat-info">
            <span className="um-stat-number">{users.filter(u => u.is_active).length}</span>
            <span className="um-stat-label">已启用</span>
          </div>
        </div>
        <div className="um-stat-card">
          <div className="um-stat-icon inactive">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="4.93" y1="4.93" x2="19.07" y2="19.07"></line>
            </svg>
          </div>
          <div className="um-stat-info">
            <span className="um-stat-number">{users.filter(u => !u.is_active).length}</span>
            <span className="um-stat-label">已禁用</span>
          </div>
        </div>
      </div>

      {/* ===== 用户表格 ===== */}
      <div className="um-table-container">
        {loading ? (
          <div className="um-loading">
            <div className="um-spinner"></div>
            <span>加载中...</span>
          </div>
        ) : filteredUsers.length === 0 ? (
          <div className="um-empty">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#b4bcd0" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
              <circle cx="9" cy="7" r="4"></circle>
              <line x1="17" y1="11" x2="23" y2="11"></line>
            </svg>
            <p>暂无用户数据</p>
          </div>
        ) : (
          <table className="um-table" id="users-table">
            <thead>
              <tr>
                <th>用户名</th>
                <th>昵称</th>
                <th>状态</th>
                <th>创建时间</th>
                <th>更新时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map((user) => (
                <tr key={user.id} id={`user-row-${user.id}`}>
                  <td>
                    <div className="user-cell">
                      <div className="user-cell-avatar">
                        {(user.nickname || user.username).charAt(0).toUpperCase()}
                      </div>
                      <span className="user-cell-name">{user.username}</span>
                    </div>
                  </td>
                  <td>
                    <span className="user-nickname">{user.nickname || '-'}</span>
                  </td>
                  <td>
                    <span className={`status-badge ${user.is_active ? 'active' : 'inactive'}`}>
                      <span className="status-dot"></span>
                      {user.is_active ? '已启用' : '已禁用'}
                    </span>
                  </td>
                  <td className="time-cell">
                    {new Date(user.created_at).toLocaleString('zh-CN', { hour12: false })}
                  </td>
                  <td className="time-cell">
                    {new Date(user.updated_at).toLocaleString('zh-CN', { hour12: false })}
                  </td>
                  <td>
                    <div className="action-btns">
                      <button
                        className="action-btn edit"
                        onClick={() => openModal(user)}
                        title="编辑"
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                        </svg>
                      </button>
                      <button
                        className="action-btn delete"
                        onClick={() => setDeleteConfirm(user)}
                        title="删除"
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <polyline points="3 6 5 6 21 6"></polyline>
                          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        </svg>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ===== 新增/编辑弹窗 ===== */}
      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} id="user-modal">
            <div className="modal-header">
              <h2>{editingUser ? '编辑用户' : '新增用户'}</h2>
              <button className="modal-close" onClick={() => setShowModal(false)}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
              </button>
            </div>

            {formError && (
              <div className="modal-error">
                <span>⚠️</span>
                <span>{formError}</span>
              </div>
            )}

            <form onSubmit={handleSubmit} className="modal-form">
              <div className="modal-form-group">
                <label>用户名</label>
                <input
                  type="text"
                  value={formData.username}
                  onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                  placeholder="请输入用户名"
                  disabled={!!editingUser}
                  id="modal-username"
                />
              </div>
              <div className="modal-form-group">
                <label>密码 {editingUser && <span className="optional-hint">(留空则不修改)</span>}</label>
                <input
                  type="password"
                  value={formData.password}
                  onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  placeholder={editingUser ? '留空则不修改密码' : '请输入密码'}
                  id="modal-password"
                />
              </div>
              <div className="modal-form-group">
                <label>昵称</label>
                <input
                  type="text"
                  value={formData.nickname}
                  onChange={(e) => setFormData({ ...formData, nickname: e.target.value })}
                  placeholder="请输入昵称（可选）"
                  id="modal-nickname"
                />
              </div>
              <div className="modal-form-group">
                <label>状态</label>
                <div className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={formData.is_active}
                    onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                    id="modal-active"
                  />
                  <span className="toggle-slider"></span>
                  <span className="toggle-label">{formData.is_active ? '启用' : '禁用'}</span>
                </div>
              </div>
              <div className="modal-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowModal(false)}>
                  取消
                </button>
                <button type="submit" className="btn-primary">
                  {editingUser ? '保存修改' : '创建用户'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ===== 删除确认弹窗 ===== */}
      {deleteConfirm && (
        <div className="modal-overlay" onClick={() => setDeleteConfirm(null)}>
          <div className="modal-content delete-modal" onClick={(e) => e.stopPropagation()} id="delete-confirm-modal">
            <div className="delete-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="15" y1="9" x2="9" y2="15"></line>
                <line x1="9" y1="9" x2="15" y2="15"></line>
              </svg>
            </div>
            <h3>确认删除</h3>
            <p>确定要删除用户 <strong>{deleteConfirm.username}</strong> 吗？此操作不可撤销。</p>
            <div className="modal-actions">
              <button className="btn-secondary" onClick={() => setDeleteConfirm(null)}>
                取消
              </button>
              <button className="btn-danger" onClick={() => handleDelete(deleteConfirm.id)}>
                确认删除
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default UserManagement
