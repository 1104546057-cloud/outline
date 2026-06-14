/* eslint-disable react/prop-types */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/Login.css'

function LoginIcon({ name, size = 19 }) {
  const paths = {
    user: <><circle cx="12" cy="8" r="4"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/></>,
    lock: <><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/></>,
    eye: <><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2.5"/></>,
    eyeOff: <><path d="m3 3 18 18M10.6 6.2A10.8 10.8 0 0 1 12 6c6.5 0 10 6 10 6a17 17 0 0 1-3 3.7M6.2 6.2C3.5 8 2 12 2 12s3.5 6 10 6c1.3 0 2.5-.2 3.5-.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></>,
    shield: <><path d="M12 3 4.5 6v5.5c0 4.7 3.1 7.8 7.5 9.5 4.4-1.7 7.5-4.8 7.5-9.5V6L12 3Z"/><path d="m9 12 2 2 4-5"/></>,
    alert: <><circle cx="12" cy="12" r="9"/><path d="M12 7v6m0 4h.01"/></>,
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [rememberMe, setRememberMe] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [modalType, setModalType] = useState(null)
  const navigate = useNavigate()

  useEffect(() => {
    const saved = localStorage.getItem('dwc_remember')
    if (!saved) return
    try {
      const data = JSON.parse(saved)
      setUsername(data.username || '')
      setPassword(data.password || '')
      setRememberMe(true)
    } catch {
      localStorage.removeItem('dwc_remember')
    }
  }, [])

  const handleLogin = async event => {
    event.preventDefault()
    setError('')
    if (!username.trim()) { setError('请输入用户名'); return }
    if (!password.trim()) { setError('请输入密码'); return }
    setIsLoading(true)

    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password }),
      })
      const data = await response.json()
      if (!response.ok) {
        setError(data.detail || '用户名或密码错误')
        return
      }

      localStorage.setItem('user', JSON.stringify({ username: data.username, nickname: data.nickname, token: data.token }))
      if (rememberMe) localStorage.setItem('dwc_remember', JSON.stringify({ username: username.trim(), password }))
      else localStorage.removeItem('dwc_remember')
      navigate('/dashboard')
    } catch {
      setError('无法连接到服务器，请检查后端服务是否启动')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="login-page" id="login-page">
      <div className="login-scene" aria-hidden="true">
        <span className="login-grid" />
        <span className="login-orbit orbit-one" />
        <span className="login-orbit orbit-two" />
        <span className="login-beam beam-left" />
        <span className="login-beam beam-right" />
        <span className="campus-silhouette" />
      </div>

      <header className="login-system-title">
        <span className="title-line left" />
        <div>
          <small>SMART CAMPUS PATROL MANAGEMENT SYSTEM</small>
          <h1>智慧校园巡逻管理系统</h1>
        </div>
        <span className="title-line right" />
      </header>

      <main className="login-stage">
        <section className="login-console">
          <span className="console-corner corner-tl" /><span className="console-corner corner-tr" />
          <span className="console-corner corner-bl" /><span className="console-corner corner-br" />
          <div className="console-glow" />

          <div className="login-console-head">
            <span className="head-wing left" />
            <div className="console-title">
              <LoginIcon name="shield" size={21} />
              <div><h2>用户登录</h2><small>USER AUTHENTICATION</small></div>
            </div>
            <span className="head-wing right" />
          </div>

          <form className="tech-login-form" onSubmit={handleLogin} id="login-form">
            {error && <div className="login-error" id="error-message"><LoginIcon name="alert" size={17} /><span>{error}</span></div>}

            <label className="tech-field" htmlFor="username">
              <span className="field-icon"><LoginIcon name="user" /></span>
              <span className="field-divider" />
              <input id="username" type="text" placeholder="请输入用户名" value={username} onChange={event => setUsername(event.target.value)} autoComplete="username" disabled={isLoading} autoFocus />
              <i className="field-focus-line" />
            </label>

            <label className="tech-field" htmlFor="password">
              <span className="field-icon"><LoginIcon name="lock" /></span>
              <span className="field-divider" />
              <input id="password" type={showPassword ? 'text' : 'password'} placeholder="请输入密码" value={password} onChange={event => setPassword(event.target.value)} autoComplete="current-password" disabled={isLoading} />
              <button type="button" className="password-toggle" onClick={() => setShowPassword(value => !value)} aria-label={showPassword ? '隐藏密码' : '显示密码'}>
                <LoginIcon name={showPassword ? 'eyeOff' : 'eye'} size={17} />
              </button>
              <i className="field-focus-line" />
            </label>

            <div className="login-options">
              <label className="tech-checkbox">
                <input type="checkbox" checked={rememberMe} onChange={event => setRememberMe(event.target.checked)} />
                <span className="checkbox-ui"><i /></span>
                <span>记住登录信息</span>
              </label>
              <button type="button" onClick={() => setModalType('forgot')}>忘记密码？</button>
            </div>

            <button type="submit" className="tech-login-button" id="login-button" disabled={isLoading}>
              <span className="button-scan" />
              {isLoading ? <><i className="login-spinner" />身份验证中...</> : '登 录'}
            </button>

            <div className="secure-tip"><span className="secure-dot" />安全接入通道已启用 <b>SECURE CHANNEL</b></div>
          </form>
        </section>
      </main>

      <footer className="login-footer">
        <span>智慧校园无人巡逻综合管理平台</span>
        <i />
        <span>© 2026 SMART CAMPUS</span>
      </footer>

      {modalType && (
        <div className="login-modal-backdrop" onMouseDown={() => setModalType(null)}>
          <div className="login-modal" onMouseDown={event => event.stopPropagation()}>
            <span className="modal-alert-icon"><LoginIcon name="alert" size={27} /></span>
            <small>SYSTEM MESSAGE</small>
            <h3>{modalType === 'forgot' ? '忘记密码' : '账号申请'}</h3>
            <p>{modalType === 'forgot' ? '请联系系统管理员重置您的登录密码。' : '系统暂未开放自主注册，请联系管理员分配账号。'}</p>
            <button onClick={() => setModalType(null)}>我知道了</button>
          </div>
        </div>
      )}
    </div>
  )
}

export default Login
