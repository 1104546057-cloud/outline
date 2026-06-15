import { Children, isValidElement, useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export default function ThemedSelect({
  children,
  className = '',
  defaultValue = '',
  disabled = false,
  id,
  name,
  onChange,
  value,
}) {
  const rootRef = useRef(null)
  const menuRef = useRef(null)
  const generatedId = useId().replace(/:/g, '')
  const listboxId = `${id || `themed-select-${generatedId}`}-listbox`
  const controlled = value !== undefined
  const [internalValue, setInternalValue] = useState(String(defaultValue ?? ''))
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const [menuStyle, setMenuStyle] = useState(null)

  const options = useMemo(() => Children.toArray(children)
    .filter(child => isValidElement(child) && child.type === 'option')
    .map(child => ({
      disabled: Boolean(child.props.disabled),
      key: child.key ?? String(child.props.value ?? ''),
      label: child.props.children,
      value: String(child.props.value ?? ''),
    })), [children])

  const selectedValue = String((controlled ? value : internalValue) ?? '')
  const selectedIndex = options.findIndex(option => option.value === selectedValue)
  const selectedOption = options[selectedIndex] || options[0]

  const updateMenuPosition = () => {
    const rect = rootRef.current?.getBoundingClientRect()
    if (!rect) return
    const spaceBelow = window.innerHeight - rect.bottom
    const openAbove = spaceBelow < 180 && rect.top > spaceBelow
    setMenuStyle(openAbove
      ? { bottom: window.innerHeight - rect.top + 4, left: rect.left, minWidth: rect.width, width: rect.width }
      : { left: rect.left, minWidth: rect.width, top: rect.bottom + 4, width: rect.width })
  }

  const openMenu = () => {
    if (disabled || options.length === 0) return
    updateMenuPosition()
    const firstEnabled = options.findIndex(option => !option.disabled)
    setActiveIndex(selectedIndex >= 0 && !options[selectedIndex].disabled ? selectedIndex : firstEnabled)
    setOpen(true)
  }

  const closeMenu = () => setOpen(false)

  const selectOption = (option) => {
    if (!option || option.disabled) return
    const event = {
      currentTarget: { name, value: option.value },
      target: { name, value: option.value },
    }
    if (!controlled) setInternalValue(option.value)
    onChange?.(event)
    if (!controlled && event.target.value !== option.value) {
      setInternalValue(String(event.target.value ?? ''))
    }
    closeMenu()
    rootRef.current?.querySelector('button')?.focus()
  }

  const moveActive = (direction) => {
    if (!options.length) return
    let next = activeIndex
    for (let i = 0; i < options.length; i += 1) {
      next = (next + direction + options.length) % options.length
      if (!options[next].disabled) {
        setActiveIndex(next)
        return
      }
    }
  }

  const handleKeyDown = (event) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      if (!open) openMenu()
      else moveActive(event.key === 'ArrowDown' ? 1 : -1)
      return
    }
    if ((event.key === 'Enter' || event.key === ' ') && open) {
      event.preventDefault()
      selectOption(options[activeIndex])
      return
    }
    if (event.key === 'Escape' && open) {
      event.preventDefault()
      closeMenu()
    }
  }

  useEffect(() => {
    if (!open) return undefined
    const handlePointerDown = (event) => {
      if (!rootRef.current?.contains(event.target) && !menuRef.current?.contains(event.target)) closeMenu()
    }
    const handleViewportChange = () => closeMenu()
    document.addEventListener('pointerdown', handlePointerDown)
    window.addEventListener('resize', handleViewportChange)
    window.addEventListener('scroll', handleViewportChange, true)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      window.removeEventListener('resize', handleViewportChange)
      window.removeEventListener('scroll', handleViewportChange, true)
    }
  }, [open])

  return (
    <div ref={rootRef} className={`themed-select${open ? ' is-open' : ''}${disabled ? ' is-disabled' : ''}`}>
      <button
        type="button"
        id={id}
        className={`themed-select-trigger ${className}`.trim()}
        aria-controls={listboxId}
        aria-expanded={open}
        aria-haspopup="listbox"
        disabled={disabled}
        onClick={() => open ? closeMenu() : openMenu()}
        onKeyDown={handleKeyDown}
      >
        <span className="themed-select-value">{selectedOption?.label}</span>
        <span className="themed-select-arrow" aria-hidden="true" />
      </button>
      {open && menuStyle && createPortal(
        <div
          ref={menuRef}
          id={listboxId}
          className="themed-select-menu"
          role="listbox"
          style={menuStyle}
        >
          {options.map((option, index) => (
            <div
              key={option.key}
              className={`themed-select-option${index === activeIndex ? ' is-active' : ''}${option.value === selectedValue ? ' is-selected' : ''}${option.disabled ? ' is-disabled' : ''}`}
              role="option"
              aria-disabled={option.disabled}
              aria-selected={option.value === selectedValue}
              onMouseEnter={() => !option.disabled && setActiveIndex(index)}
              onMouseDown={event => event.preventDefault()}
              onClick={() => selectOption(option)}
            >
              {option.label}
            </div>
          ))}
        </div>,
        document.body,
      )}
    </div>
  )
}
