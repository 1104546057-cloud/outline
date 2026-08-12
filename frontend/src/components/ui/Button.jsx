/* eslint-disable react/prop-types */
import './ui.css'

/**
 * 按钮组件（统一变体）
 *
 * 用法：
 * <Button variant="primary" onClick={...}>新建</Button>
 * <Button variant="danger" loading={submitting} disabled={!isValid}>删除</Button>
 */
export default function Button({
  variant = 'default',
  size = 'md',
  loading = false,
  disabled = false,
  icon,
  children,
  className = '',
  type = 'button',
  ...rest
}) {
  const isDisabled = disabled || loading
  return (
    <button
      type={type}
      className={`ui-btn ui-btn-${variant} ui-btn-${size} ${loading ? 'ui-btn-loading' : ''} ${className}`}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading && <span className="ui-btn-spinner" aria-hidden="true" />}
      {icon && !loading && <span className="ui-btn-icon" aria-hidden="true">{icon}</span>}
      <span>{children}</span>
    </button>
  )
}
