import test from 'node:test'
import assert from 'node:assert/strict'
import { bindStyles } from '../src/utils/bindStyles.js'

test('dynamic state classes retain both component styling and the shared theme', () => {
  const cx = bindStyles(
    { card: 'card_local', online: 'online_local' },
    { card: 'card_theme', online: 'online_theme' },
  )
  assert.equal(cx('card online'), 'card_local card_theme online_local online_theme')
})

test('a child preserves already scoped classes supplied by its parent', () => {
  const parent = bindStyles({ slot: 'parent_slot' })
  const child = bindStyles({ panel: 'child_panel' })
  assert.equal(child(`panel ${parent('slot')}`), 'child_panel parent_slot')
})

test('shared CSS module exports and repeated classes do not duplicate class tokens', () => {
  const cx = bindStyles({ panel: 'local_panel shared_panel' }, { panel: 'shared_panel' })
  assert.equal(cx('panel panel'), 'local_panel shared_panel')
})

test('empty values and external classes work without matching inherited object properties', () => {
  const cx = bindStyles({ card: 'local_card' })
  assert.equal(cx(null), '')
  assert.equal(cx(false), '')
  assert.equal(cx('  card  maplibregl-map toString  '), 'local_card maplibregl-map toString')
})
