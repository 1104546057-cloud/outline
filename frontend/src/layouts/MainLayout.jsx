import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import '../styles/MainLayout.css'

/**
 * 主布局组件
 * 包含侧边栏导航和内容区域，登录后的所有页面共享此布局
 */
function MainLayout() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const navigate = useNavigate()

  // 获取当前登录用户信息
  const user = JSON.parse(localStorage.getItem('user') || '{}')

  // 导航菜单配置
  const menuItems = [
    {
      key: 'dashboard',
      label: '数据看板',
      path: '/dashboard',
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="7" height="7"></rect>
          <rect x="14" y="3" width="7" height="7"></rect>
          <rect x="14" y="14" width="7" height="7"></rect>
          <rect x="3" y="14" width="7" height="7"></rect>
        </svg>
      ),
    },
    {
      key: 'users',
      label: '用户管理',
      path: '/users',
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
          <circle cx="9" cy="7" r="4"></circle>
          <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
          <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
        </svg>
      ),
    },
    {
      key: 'devices',
      label: '设备管理',
      path: '/devices',
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect>
          <rect x="9" y="9" width="6" height="6"></rect>
          <line x1="9" y1="1" x2="9" y2="4"></line>
          <line x1="15" y1="1" x2="15" y2="4"></line>
          <line x1="9" y1="20" x2="9" y2="23"></line>
          <line x1="15" y1="20" x2="15" y2="23"></line>
          <line x1="20" y1="9" x2="23" y2="9"></line>
          <line x1="20" y1="14" x2="23" y2="14"></line>
          <line x1="1" y1="9" x2="4" y2="9"></line>
          <line x1="1" y1="14" x2="4" y2="14"></line>
        </svg>
      ),
    },
    {
      key: 'device-control',
      label: '设备控制',
      path: '/device-control',
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3"></circle>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
        </svg>
      ),
    },
    {
      key: 'cluster',
      label: '集群管理',
      path: '/cluster',
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="2"></circle>
          <circle cx="12" cy="5" r="2"></circle>
          <circle cx="12" cy="19" r="2"></circle>
          <circle cx="5" cy="8.5" r="2"></circle>
          <circle cx="19" cy="8.5" r="2"></circle>
          <circle cx="5" cy="15.5" r="2"></circle>
          <circle cx="19" cy="15.5" r="2"></circle>
          <line x1="12" y1="7" x2="12" y2="10"></line>
          <line x1="12" y1="14" x2="12" y2="17"></line>
          <line x1="6.7" y1="9.5" x2="10.3" y2="11"></line>
          <line x1="13.7" y1="11" x2="17.3" y2="9.5"></line>
          <line x1="6.7" y1="14.5" x2="10.3" y2="13"></line>
          <line x1="13.7" y1="13" x2="17.3" y2="14.5"></line>
        </svg>
      ),
    },
    {
      key: 'cluster-control',
      label: '集群控制',
      path: '/cluster-control',
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
          <polyline points="2 17 12 22 22 17"></polyline>
          <polyline points="2 12 12 17 22 12"></polyline>
        </svg>
      ),
    },
  ]

  const handleLogout = () => {
    localStorage.removeItem('user')
    navigate('/login')
  }

  return (
    <div className="main-layout" id="main-layout">
      {/* ===== 侧边栏 ===== */}
      <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`} id="sidebar">
        {/* Logo 区域 */}
        <div className="sidebar-header">
          <div className="sidebar-logo">
            <span className="logo-icon">🛰️</span>
            {!sidebarCollapsed && <span className="logo-text">集群管理平台</span>}
          </div>
        </div>

        {/* 用户信息 */}
        <div className="sidebar-user">
          <div className="user-avatar">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
              <circle cx="12" cy="7" r="4"></circle>
            </svg>
          </div>
          {!sidebarCollapsed && (
            <div className="user-info">
              <span className="user-name">{user.nickname || user.username || '管理员'}</span>
              <span className="user-role">系统管理员</span>
            </div>
          )}
        </div>

        {/* 导航菜单 */}
        <nav className="sidebar-nav">
          {menuItems.map((item) => (
            <NavLink
              key={item.key}
              to={item.path}
              className={({ isActive }) =>
                `nav-item ${isActive ? 'active' : ''}`
              }
              id={`nav-${item.key}`}
              title={sidebarCollapsed ? item.label : ''}
            >
              <span className="nav-icon">{item.icon}</span>
              {!sidebarCollapsed && <span className="nav-label">{item.label}</span>}
            </NavLink>
          ))}
        </nav>

        {/* 底部操作 */}
        <div className="sidebar-footer">
          <button
            className="sidebar-btn collapse-btn"
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            title={sidebarCollapsed ? '展开侧栏' : '收起侧栏'}
            id="toggle-sidebar"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
              style={{ transform: sidebarCollapsed ? 'rotate(180deg)' : 'none', transition: 'transform 0.3s ease' }}>
              <polyline points="11 17 6 12 11 7"></polyline>
              <polyline points="18 17 13 12 18 7"></polyline>
            </svg>
            {!sidebarCollapsed && <span>收起侧栏</span>}
          </button>
          <button className="sidebar-btn logout-btn" onClick={handleLogout} id="logout-btn" title="退出登录">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
              <polyline points="16 17 21 12 16 7"></polyline>
              <line x1="21" y1="12" x2="9" y2="12"></line>
            </svg>
            {!sidebarCollapsed && <span>退出登录</span>}
          </button>
        </div>
      </aside>

      {/* ===== 主内容区域 ===== */}
      <main className="main-content" id="main-content">
        <Outlet />
      </main>
    </div>
  )
}

export default MainLayout
