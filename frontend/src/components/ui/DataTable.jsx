/* eslint-disable react/prop-types */
import './ui.css'

/**
 * 数据表格
 *
 * 用法：
 * <DataTable
 *   columns={[
 *     { key: 'name', label: '名称', width: '30%' },
 *     { key: 'status', label: '状态', render: row => <StatusBadge ... /> },
 *   ]}
 *   data={rows}
 *   rowKey="id"
 *   loading={loading}
 *   empty="暂无数据"
 * />
 */
export default function DataTable({ columns = [], data = [], rowKey, loading = false, empty = '暂无数据', onRowClick, className = '' }) {
  return (
    <div className={`ui-data-table ${className}`}>
      <div className="ui-data-table-scroll">
        <table>
          <thead>
            <tr>
              {columns.map(col => (
                <th key={col.key} style={col.width ? { width: col.width } : undefined} className={col.align ? `text-${col.align}` : ''}>
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr className="ui-data-table-loading-row">
                <td colSpan={columns.length}>
                  <div className="ui-state-loading-inline"><span className="ui-spinner" /> 加载中…</div>
                </td>
              </tr>
            ) : data.length === 0 ? (
              <tr className="ui-data-table-empty-row">
                <td colSpan={columns.length}>
                  <div className="ui-state-empty-inline">{empty}</div>
                </td>
              </tr>
            ) : (
              data.map((row, rowIndex) => (
                <tr
                  key={rowKey ? (typeof rowKey === 'function' ? rowKey(row) : row[rowKey]) : rowIndex}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={onRowClick ? 'ui-data-table-row-clickable' : ''}
                >
                  {columns.map(col => (
                    <td key={col.key} className={col.align ? `text-${col.align}` : ''}>
                      {col.render ? col.render(row) : row[col.key]}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
