import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  TRANSPORT_PRESENTATION_LIMITATIONS,
  TRANSPORT_SCREENING_SUMMARY,
  formatTransportAngle,
  formatTransportDistance,
  formatTransportDuration,
  inCorridorRankedSettlements,
  outsideCorridorSettlements,
  settlementCandidateScopeLimitation,
  transportExclusionReasonLabel,
} from '../src/utils/airPollutionTransportPresentation.ts'
import {
  eventSelectionKey,
  isAirPollutionEvent,
} from '../src/utils/airPollutionEvents.ts'


test('formats only backend-provided distance and angle values', () => {
  assert.equal(formatTransportDistance(4800), '4.8 km')
  assert.equal(formatTransportDistance(600), '600 m')
  assert.equal(formatTransportDistance(-4700), '-4.7 km')
  assert.equal(formatTransportAngle(7), '7°')
  assert.equal(formatTransportAngle(7.4), '7.4°')
})


test('formats nullable backend duration without presenting an arrival time', () => {
  assert.equal(formatTransportDuration(1140), '~19 min')
  assert.equal(
    formatTransportDuration(null),
    'Transport duration screening unavailable',
  )
})


test('maps only known backend exclusion reasons', () => {
  assert.equal(
    transportExclusionReasonLabel('outside_transport_corridor'),
    'Outside screening angle',
  )
  assert.equal(
    transportExclusionReasonLabel('upwind_of_origin'),
    'Upwind of analysis origin',
  )
  assert.equal(
    transportExclusionReasonLabel('beyond_screening_range'),
    'Beyond configured screening distance',
  )
  assert.equal(
    transportExclusionReasonLabel('insufficient_wind_evidence'),
    'Insufficient wind evidence',
  )
  assert.equal(transportExclusionReasonLabel('unknown_reason'), null)
})


test('preserves backend order and ranks while excluding unranked outside records', () => {
  const settlements = [
    { settlement_id: 'rank-2', inside_transport_corridor: true, rank: 2 },
    { settlement_id: 'outside', inside_transport_corridor: false, rank: null },
    { settlement_id: 'rank-1', inside_transport_corridor: true, rank: 1 },
  ]

  assert.deepEqual(
    inCorridorRankedSettlements(settlements).map((item) => [item.settlement_id, item.rank]),
    [['rank-2', 2], ['rank-1', 1]],
  )
  assert.deepEqual(
    outsideCorridorSettlements(settlements).map((item) => item.settlement_id),
    ['outside'],
  )
})


test('limitations state monitoring-origin, exposure, duration, and candidate scope', () => {
  const limitations = [
    ...TRANSPORT_PRESENTATION_LIMITATIONS,
    settlementCandidateScopeLimitation(2),
  ].join(' ')

  assert.match(limitations, /monitoring location/)
  assert.match(limitations, /not necessarily the pollution emission source/)
  assert.match(limitations, /Exposure is not confirmed/)
  assert.match(limitations, /geometric downwind relevance only/)
  assert.match(limitations, /not an ETA or confirmed arrival time/)
  assert.match(limitations, /2 km for this event/)
  assert.match(limitations, /may not include settlements farther along the corridor/)
  assert.equal(TRANSPORT_SCREENING_SUMMARY.includes('%'), false)
})


test('transport frontend contains no scientific recomputation', () => {
  const sources = [
    '../src/components/AirPollutionTransportLayer.tsx',
    '../src/components/AirPollutionTransportPanel.tsx',
    '../src/utils/airPollutionTransport.ts',
    '../src/utils/airPollutionTransportPresentation.ts',
  ].map((path) => readFileSync(new URL(path, import.meta.url), 'utf8')).join('\n')

  assert.doesNotMatch(sources, /Math\.(?:sin|cos|tan|atan|atan2|asin|acos)/)
})


test('transport UI avoids affirmative exposure, probability, and arrival claims', () => {
  const sources = [
    '../src/components/AirPollutionTransportLayer.tsx',
    '../src/components/AirPollutionTransportPanel.tsx',
    '../src/utils/airPollutionTransportPresentation.ts',
  ].map((path) => readFileSync(new URL(path, import.meta.url), 'utf8').toLowerCase())
    .join('\n')

  for (const forbidden of [
    'will be affected',
    'will reach',
    'confirmed exposure',
    'confirmed source',
    'risk percentage',
    'impact probability',
  ]) {
    assert.equal(sources.includes(forbidden), false, forbidden)
  }
})


test('hazard-qualified identity keeps Fire and Pollution selections isolated', () => {
  const fire = { id: 'shared-id', type: 'fire' }
  const pollution = { id: 'shared-id', type: 'air_pollution' }

  assert.equal(isAirPollutionEvent(fire), false)
  assert.equal(isAirPollutionEvent(pollution), true)
  assert.notEqual(eventSelectionKey(fire), eventSelectionKey(pollution))
})
