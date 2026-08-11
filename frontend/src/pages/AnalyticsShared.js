/**
 * 数据统计研判模块 · 共用工具与 ECharts 主题
 *
 * 提供：
 * - echarts 动态导入与共享主题
 * - 通用 fetch 封装（基于 authFetch）
 * - 数字/日期格式化
 * - 共用色彩
 */

import { useEffect, useRef, useState } from 'react'
import { authFetch } from '../utils/authFetch'

/* 共用调色板（与 SubpageTheme 对齐） */
export const ANALYTICS_COLORS = {
  cyan: '#2bd2ff',
  blue: '#2385ff',
  success: '#31e3a1',
  warning: '#ffb64a',
  danger: '#ff5b72',
  purple: '#a78bfa',
  text: '#d8f0fb',
  textSecondary: '#8db4c8',
  muted: '#527890',
  border: 'rgba(45, 169, 229, .2)',
  palette: ['#2bd2ff', '#2385ff', '#31e3a1', '#ffb64a', '#ff5b72', '#a78bfa'],
}

/**
 * 动态 import echarts，避免首屏加载全部 echarts。
 * 第一次调用时挂到 window.__ECHARTS__。
 */
export async function loadECharts() {
  if (window.__ECHARTS__) return window.__ECHARTS__
  const echarts = await import('echarts')
  window.__ECHARTS__ = echarts
  return echarts
}

/**
 * React Hook：在给定 ref 上创建并销毁 ECharts 实例。
 * deps 变化时自动 setOption。
 *
 * @param {object} option - ECharts option（不含 theme）
 * @param {array} deps - 触发 setOption 的依赖
 * @returns {RefObject<HTMLDivElement>} chartRef - 绑定到 <div ref>
 */
export function useChart(option, deps) {
  const chartRef = useRef(null)
  const instanceRef = useRef(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let disposed = false
    loadECharts().then((echarts) => {
      if (disposed || !chartRef.current) return
      if (!instanceRef.current) {
        instanceRef.current = echarts.init(chartRef.current, null, { renderer: 'canvas' })
      }
      instanceRef.current.setOption(option, true)
      setReady(true)
    })
    return () => { disposed = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  // 响应窗口尺寸
  useEffect(() => {
    const onResize = () => instanceRef.current && instanceRef.current.resize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // 卸载时销毁
  useEffect(() => {
    return () => {
      if (instanceRef.current) {
        instanceRef.current.dispose()
        instanceRef.current = null
      }
    }
  }, [])

  return { chartRef, ready }
}

/* 通用 API 封装 */
export async function api(url, options = {}) {
  const res = await authFetch(`/api/analytics${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let msg = `请求失败 (${res.status})`
    try {
      const body = await res.json()
      msg = body.detail || msg
    } catch { /* noop */ }
    throw new Error(msg)
  }
  if (res.status === 204) return null
  return res.json()
}

export async function adminApi(url, options = {}) {
  return api(`/admin${url}`, options)
}

/* 格式化 */
export function fmtNum(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return '--'
  const n = Number(v)
  if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2) + ' 亿'
  if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(2) + ' 万'
  return n.toFixed(digits)
}

export function fmtDate(iso) {
  if (!iso) return '--'
  return new Date(iso).toLocaleDateString('zh-CN')
}

export function fmtDateTime(iso) {
  if (!iso) return '--'
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

/* 类别标签映射 */
export const CATEGORY_LABELS = {
  device: '设备',
  patrol: '巡检',
  alert: '告警',
  energy: '能耗',
  external: '外部',
  manual: '人工',
}
