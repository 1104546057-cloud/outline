/* eslint-disable react/prop-types */
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login/Login.jsx'
import MainLayout from './layouts/MainLayout/MainLayout.jsx'
import Dashboard from './pages/Dashboard/Dashboard.jsx'
import UserManagement from './pages/UserManagement/UserManagement.jsx'
import DeviceManagement from './pages/DeviceManagement/DeviceManagement.jsx'
import DeviceControl from './pages/DeviceControl/DeviceControl.jsx'
import DeviceCockpit from './pages/DeviceCockpit/DeviceCockpit.jsx'
import ClusterManagement from './pages/ClusterManagement/ClusterManagement.jsx'
import ClusterControl from './pages/ClusterControl/ClusterControl.jsx'
import LiveVideo from './pages/LiveVideo/LiveVideo.jsx'
import VideoAnalysis from './pages/VideoAnalysis/VideoAnalysis.jsx'
import PlaceholderPage from './pages/PlaceholderPage/PlaceholderPage.jsx'
import PatrolAreas from './pages/PatrolAreas/PatrolAreas.jsx'
import PatrolPoints from './pages/PatrolPoints/PatrolPoints.jsx'
import PatrolRoutes from './pages/PatrolRoutes/PatrolRoutes.jsx'
import OutdoorRtkNavigation from './pages/OutdoorRtkNavigation/OutdoorRtkNavigation.jsx'
import PatrolTasks from './pages/PatrolTasks/PatrolTasks.jsx'
import PatrolResults from './pages/PatrolResults/PatrolResults.jsx'
import PatrolNavigation from './pages/PatrolNavigation/PatrolNavigation.jsx'
import IndoorMapManagement from './pages/IndoorMapManagement/IndoorMapManagement.jsx'
import RemoteAccess from './pages/RemoteAccess/RemoteAccess.jsx'

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
          <Route path="remote-access" element={<RemoteAccess />} />
          <Route path="device-cockpit/:deviceId" element={<DeviceCockpit />} />
          <Route path="cluster" element={<ClusterManagement />} />
          <Route path="cluster-control" element={<ClusterControl />} />
          <Route path="live-video" element={<LiveVideo />} />
          <Route path="patrol" element={<Navigate to="/patrol/indoor" replace />} />
          <Route path="patrol/indoor" element={<Navigate to="/patrol/indoor/navigation" replace />} />
          <Route path="patrol/indoor/navigation" element={<PatrolNavigation />} />
          <Route path="patrol/indoor/maps" element={<IndoorMapManagement />} />
          <Route path="patrol/outdoor" element={<Navigate to="/patrol/outdoor/areas" replace />} />
          <Route path="patrol/outdoor/areas" element={<PatrolAreas />} />
          <Route path="patrol/outdoor/points" element={<PatrolPoints />} />
          <Route path="patrol/outdoor/routes" element={<PatrolRoutes />} />
          <Route path="patrol/outdoor/navigation" element={<OutdoorRtkNavigation />} />
          <Route path="patrol/tasks" element={<PatrolTasks />} />
          <Route path="patrol/results" element={<PatrolResults />} />
          <Route path="patrol/areas" element={<Navigate to="/patrol/outdoor/areas" replace />} />
          <Route path="patrol/points" element={<Navigate to="/patrol/outdoor/points" replace />} />
          <Route path="patrol/routes" element={<Navigate to="/patrol/outdoor/routes" replace />} />
          <Route path="patrol/navigation" element={<Navigate to="/patrol/indoor/navigation" replace />} />
          <Route path="video-analysis" element={<VideoAnalysis />} />
          <Route path="statistics-analysis" element={<PlaceholderPage title="数据统计研判" description="综合数据统计与趋势研判模块正在建设中" icon="◇" />} />
        </Route>

        {/* 其他路径重定向到登录 */}
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
