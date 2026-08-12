/* eslint-disable react/prop-types */
import './ui.css'

/**
 * 筛选栏
 *
 * 用法：
 * <FilterBar>
 *   <input ... />
 *   <Button variant="primary">查询</Button>
 * </FilterBar>
 */
export default function FilterBar({ children, className = '' }) {
  return <div className={`ui-filter-bar ${className}`}>{children}</div>
}
