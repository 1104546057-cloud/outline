import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/Login.css'

function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [rememberMe, setRememberMe] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  // 处理登录提交
  const handleLogin = async (e) => {
    e.preventDefault()
    setError('')

    // 前端基础校验
    if (!username.trim()) {
      setError('请输入用户名')
      return
    }
    if (!password.trim()) {
      setError('请输入密码')
      return
    }

    setIsLoading(true)

    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: username.trim(),
          password: password,
        }),
      })

      const data = await response.json()

      if (response.ok) {
        // 登录成功，保存用户信息并跳转
        localStorage.setItem('user', JSON.stringify({
          username: data.username,
          nickname: data.nickname,
          token: data.token,
        }))
        navigate('/dashboard')
      } else {
        setError(data.detail || '用户名或密码错误')
      }
    } catch {
      setError('无法连接到服务器，请检查后端服务是否启动')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="login-page" id="login-page">
      {/* ===== 左侧品牌区域 ===== */}
      <div className="login-brand">
        <div className="brand-grid"></div>
        <div className="brand-content">
          <div className="brand-logo">🛰️</div>
          <h2 className="brand-title">异构无人集群管理平台</h2>
          <p className="brand-subtitle">
            统一管理无人车、无人机、无人船等多类型设备，
            <br />
            实现实时监控、远程控制与智能调度。
          </p>
          <div className="brand-devices">
            <div className="brand-device-item">
              <span className="device-emoji">🚗</span>
              <span className="device-label">无人车</span>
            </div>
            <div className="brand-device-item">
              <span className="device-emoji">✈️</span>
              <span className="device-label">无人机</span>
            </div>
            <div className="brand-device-item">
              <span className="device-emoji">🚢</span>
              <span className="device-label">无人船</span>
            </div>
          </div>
        </div>
      </div>

      {/* ===== 右侧登录表单区域 ===== */}
      <div className="login-form-area">
        <div className="login-topbar">
          <span>还没有账号？</span>
          <a href="#register" id="register-link">注册账号</a>
        </div>

        <div className="login-form-container">
          <div className="form-header">
            <h1>欢迎回来</h1>
            <p>请登录您的账号以继续使用管理平台</p>
          </div>

          {/* 错误提示 */}
          {error && (
            <div className="error-message" id="error-message">
              <span className="error-icon">⚠️</span>
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleLogin} id="login-form">
            {/* 用户名 */}
            <div className="form-group">
              <label className="form-label" htmlFor="username">
                用户名
              </label>
              <div className="form-input-wrapper">
                <span className="form-input-icon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                    <circle cx="12" cy="7" r="4"></circle>
                  </svg>
                </span>
                <input
                  type="text"
                  id="username"
                  className="form-input"
                  placeholder="请输入用户名"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  disabled={isLoading}
                />
              </div>
            </div>

            {/* 密码 */}
            <div className="form-group">
              <label className="form-label" htmlFor="password">
                密码
              </label>
              <div className="form-input-wrapper">
                <span className="form-input-icon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                    <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                  </svg>
                </span>
                <input
                  type={showPassword ? 'text' : 'password'}
                  id="password"
                  className="form-input"
                  placeholder="请输入密码"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  disabled={isLoading}
                />
                <button
                  type="button"
                  className="password-toggle"
                  id="password-toggle"
                  onClick={() => setShowPassword(!showPassword)}
                  tabIndex={-1}
                  aria-label={showPassword ? '隐藏密码' : '显示密码'}
                >
                  {showPassword ? (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"></path>
                      <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"></path>
                      <line x1="1" y1="1" x2="23" y2="23"></line>
                    </svg>
                  ) : (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                      <circle cx="12" cy="12" r="3"></circle>
                    </svg>
                  )}
                </button>
              </div>
            </div>

            {/* 记住我 & 忘记密码 */}
            <div className="form-options">
              <label className="remember-me" id="remember-me">
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                />
                <span>记住我</span>
              </label>
              <a href="#forgot" className="forgot-password" id="forgot-password-link">
                忘记密码？
              </a>
            </div>

            {/* 登录按钮 */}
            <button
              type="submit"
              className="login-button"
              id="login-button"
              disabled={isLoading}
            >
              {isLoading && <span className="spinner"></span>}
              {isLoading ? '登录中...' : '登  录'}
            </button>
          </form>
        </div>

        <div className="login-footer">
          © 2026 异构无人集群管理平台 · 技术支持
        </div>
      </div>
    </div>
  )
}

export default Login
