/** Bind semantic class names to CSS Modules, including shared theme classes.
 * Unknown classes (for example classes passed by a parent) remain intact.
 */
export function bindStyles(...stylesheets) {
  return (value = '') => {
    if (!value) return ''
    const classes = String(value).split(/\s+/).filter(Boolean).flatMap(name => {
      const mapped = stylesheets
        .filter(styles => Object.hasOwn(styles, name))
        .map(styles => styles[name])
      return mapped.length ? mapped.flatMap(value => value.split(/\s+/)) : [name]
    })
    return [...new Set(classes)].join(' ')
  }
}
