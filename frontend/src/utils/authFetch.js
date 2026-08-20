/**
 * 带认证处理的 fetch 封装
 *
 * 自动携带 credentials: 'include'，并在收到 401 响应时
 * 清除本地用户信息、跳转到登录页面。
 */

/**
 * 封装 fetch，统一处理未登录 / token 过期的情况。
 *
 * @param {string|Request} input  - fetch 的 URL 或 Request 对象
 * @param {RequestInit}    [init] - fetch 的配置项
 * @returns {Promise<Response>}
 */
export async function authFetch(input, init = {}) {
  // 自动携带 cookie
  const mergedInit = {
    ...init,
    credentials: 'include',
  }

  const response = await fetch(input, mergedInit)

  // 401 表示未登录或 token 过期，自动跳转到登录页
  if (response.status === 401) {
    localStorage.removeItem('user')
    // 使用 window.location 强制跳转，确保在任何路由上下文中都能正常工作
    window.location.href = '/login'
    // 抛出错误阻止后续代码继续执行
    throw new Error('认证已过期，正在跳转到登录页面...')
  }

  return response
}

export default authFetch
