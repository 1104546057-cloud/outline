import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login'
import MainLayout from './layouts/MainLayout'
import Dashboard from './pages/Dashboard'
import UserManagement from './pages/UserManagement'
import DeviceManagement from './pages/DeviceManagement'
import DeviceControl from './pages/DeviceControl'
import ClusterManagement from './pages/ClusterManagement'
import ClusterControl from './pages/ClusterControl'
import PlaceholderPage from './pages/PlaceholderPage'

/**
 * 应用根组件
 *
 * 路由结构：
 * /login       - 登录页
 * /dashboard   - 数据看板（需登录）
 * /users       - 用户管理（需登录）
 * /devices     - 设备管理（占位）
 * /device-control - 设备控制（占位）
 * /cluster     - 集群管理（占位）
 * /cluster-control - 集群控制（占位）
 */
/**
 * 路由守卫组件
 * 用于保护需要登录才能访问的路由。如果未登录，则重定向到登录页面。
 */
const ProtectedRoute = ({ children }) => {
  const userStr = localStorage.getItem('user')
  let isAuthenticated = false
  
  if (userStr) {
    try {
      const user = JSON.parse(userStr)
      if (user && user.token) {
        isAuthenticated = true
      }
    } catch (e) {
      console.error('Invalid user data in localStorage', e)
    }
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return children
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* 登录页面 - 独立布局 */}
        <Route path="/login" element={<Login />} />

        {/* 主布局 - 侧栏 + 内容区域，需要登录 */}
        <Route path="/" element={<ProtectedRoute><MainLayout /></ProtectedRoute>}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="users" element={<UserManagement />} />
          <Route path="devices" element={<DeviceManagement />} />
          <Route path="device-control" element={<DeviceControl />} />
          <Route path="cluster" element={<ClusterManagement />} />
          <Route path="cluster-control" element={<ClusterControl />} />
        </Route>

        {/* 其他路径重定向到登录 */}
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
