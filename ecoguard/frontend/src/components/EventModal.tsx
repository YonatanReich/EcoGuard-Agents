/**
 * EventModal — the event panel docked under the map.
 *
 * No longer a modal overlay: the dashboard slides it open beneath the map and
 * the map shrinks to make room, so the incident stays in view while its
 * details are read. The panel is four boxes, each a summary until opened:
 *
 *   1. Event        type, address, evidence, confidence
 *   2. Responsible  the authority and police answering for the place, and the
 *                   nearest fire and MDA stations — phone numbers included
 *   3. Incident     a plain-language briefing: what is happening, how it may
 *                   develop, who is at risk, which settlements are affected
 *   4. Plan         who to call, the steps by urgency, evacuation and the
 *                   units assigned; sources and caveats folded away
 *
 * Hovering or clicking a box opens it to the side and shrinks the others; a
 * click pins it. The header carries "Show optimal routes" for events with
 * allocated stations, and once on, "Visualize emergency vehicles".
 */

import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import HazardIcon from './HazardIcon'
import { classify, hazardOf } from './hazards'
import AllocationVehicleSimulation from './layers/AllocationVehicleSimulation'
import { resourceAllocationSimulation } from '../utils/resourceAllocationSimulation'
import type {
  AirPollutionEvent,
  AllocatedStation,
  EarthquakeEvent,
  FireEvent,
  FloodEvent,
  ProtocolCitation,
  ResourceAllocationSummary,
  SharedEvent,
} from '../types/events'


// ===== Formatting ==========================================================

function formatTimestamp(timestamp: string) {
  const value = new Date(timestamp)
  return Number.isNaN(value.getTime())
    ? timestamp
    : new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Asia/Jerusalem',
        dateStyle: 'medium',
        timeStyle: 'short',
      }).format(value)
}

function formatDistance(distance: number | null | undefined) {
  if (distance == null) return null
  return distance >= 1000
    ? `${(distance / 1000).toFixed(1)} km`
    : `${Math.round(distance)} m`
}

function formatDuration(seconds: number | null) {
  if (seconds == null) return null
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`
  return `${(seconds / 3600).toFixed(1)} hr`
}

function formatComponentName(component: string) {
  return component
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function formatUnavailableReason(reason: string) {
  return reason.replaceAll('_', ' ')
}

function formatAllocationError(error: Record<string, unknown>) {
  const reason = typeof error.reason === 'string' ? formatUnavailableReason(error.reason) : null
  const message = typeof error.message === 'string' ? error.message : null
  return [reason, message].filter(Boolean).join(': ') || 'Allocation failed'
}

function websiteUrl(value: string) {
  return /^https?:\/\//i.test(value) ? value : `https://${value}`
}

function Phone({ number }: { number: string | null | undefined }) {
  if (!number) return <span className="event-box__muted">no phone on file</span>
  return <a href={`tel:${number.replace(/[^0-9+*]/g, '')}`}>{number}</a>
}

function capitalise(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1)
}


// ===== Box 2 data: who answers for this place ==============================

type PartyStation = {
  name: string
  address: string | null
  phone: string | null
  distance_m: number | null
}

type ResponsibleParties = {
  authority: {
    town_name_he: string | null
    town_name_en: string | null
    name: string | null
    type: string | null
    phone: string | null
    address: string | null
    website: string | null
    fire_district: string | null
    distance_m: number
  } | null
  police_station: (PartyStation & { basis: 'responsible' | 'nearest' }) | null
  nearest_fire_station: PartyStation | null
  nearest_mda_station: PartyStation | null
}

type PartiesState =
  | { status: 'loading' }
  | { status: 'ready'; data: ResponsibleParties }
  | { status: 'error' }

// Reference data for a fixed point, so one lookup per place per session.
// Failures are dropped from the cache so the next open retries.
const partiesCache = new Map<string, Promise<ResponsibleParties>>()

function fetchParties(event: SharedEvent) {
  const key = `${event.latitude.toFixed(5)},${event.longitude.toFixed(5)}`
  let request = partiesCache.get(key)
  if (!request) {
    const params = new URLSearchParams({
      latitude: String(event.latitude),
      longitude: String(event.longitude),
    })
    request = fetch(`/api/responsible-parties?${params}`).then((response) => {
      if (!response.ok) throw new Error('Responsible-party data is unavailable')
      return response.json() as Promise<ResponsibleParties>
    })
    request.catch(() => partiesCache.delete(key))
    partiesCache.set(key, request)
  }
  return request
}

function addressOf(parties: PartiesState, event: SharedEvent) {
  const coordinates = `${event.latitude.toFixed(4)}, ${event.longitude.toFixed(4)}`
  if (parties.status === 'loading') return 'Looking up…'
  const town = parties.status === 'ready' ? parties.data.authority : null
  if (!town) return coordinates
  const name = town.town_name_he ?? town.town_name_en ?? coordinates
  return town.distance_m > 0 ? `${formatDistance(town.distance_m)} from ${name}` : name
}


// ===== Shared sections ======================================================

function ListSection({ title, items, gaps = false }: {
  title: string
  items: string[] | undefined
  gaps?: boolean
}) {
  if (!items?.length) return null
  return (
    <section className={`event-modal__section${gaps ? ' event-modal__section--gaps' : ''}`}>
      <h3>{title}</h3>
      <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>
    </section>
  )
}

function Citations({ citations }: { citations: ProtocolCitation[] }) {
  if (citations.length === 0) return null
  return (
    <section className="event-modal__section">
      <h3>Protocol citations</h3>
      {citations.map((citation) => (
        <blockquote key={citation.chunk_id} className="event-modal__citation">
          <p>“{citation.quoted_text}”</p>
          <footer>{citation.document_title ?? citation.chunk_id}</footer>
        </blockquote>
      ))}
    </section>
  )
}

function compactAirPollutionLimitations(limitations: string[]) {
  const unique = new Map<string, string>()
  let hasMonitoringLocationLimitation = false

  for (const limitation of limitations) {
    const normalized = limitation.trim().replace(/\s+/g, ' ')
    const lower = normalized.toLowerCase()

    // These truths are already stated once beside the corresponding evidence.
    if (/transport|corridor|plume|downwind screening|sector geometry/.test(lower)) continue
    if (/population/.test(lower)) continue
    if (/\bp95\b|historically unusual|historical unusualness/.test(lower)) continue
    if (/unavailable:/.test(lower)) continue

    if (/monitoring location|emission source/.test(lower)) {
      hasMonitoringLocationLimitation = true
      continue
    }

    unique.set(lower, normalized)
  }

  if (hasMonitoringLocationLimitation) {
    unique.set(
      'monitoring-location-is-not-a-source',
      'The monitoring location is not a confirmed emission source.',
    )
  }

  return [...unique.values()]
}


// ===== Plain-language helpers ===============================================

const COMPASS: Record<string, string> = {
  N: 'north', NNE: 'north-north-east', NE: 'north-east', ENE: 'east-north-east',
  E: 'east', ESE: 'east-south-east', SE: 'south-east', SSE: 'south-south-east',
  S: 'south', SSW: 'south-south-west', SW: 'south-west', WSW: 'west-south-west',
  W: 'west', WNW: 'west-north-west', NW: 'north-west', NNW: 'north-north-west',
}

function compassWord(code: string) {
  return COMPASS[code.toUpperCase()] ?? code
}

function bearingWord(degrees: number) {
  const points = ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west']
  return points[Math.round((((degrees % 360) + 360) % 360) / 45) % 8]
}

function minutesWord(minutes: number) {
  if (minutes < 1) return 'under a minute'
  if (minutes < 60) return `${Math.round(minutes)} min`
  const hours = minutes / 60
  return `${hours.toFixed(hours < 10 ? 1 : 0)} h`
}

function clock(timestamp: string | null | undefined) {
  if (!timestamp) return null
  const value = new Date(timestamp)
  return Number.isNaN(value.getTime()) ? null : new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Jerusalem', hour: '2-digit', minute: '2-digit',
  }).format(value)
}

type Exposure = 'burning' | 'likely' | 'possible'

const EXPOSURE: Record<Exposure, { label: string; tone: string; rank: number }> = {
  burning: { label: 'In the fire', tone: 'critical', rank: 0 },
  likely: { label: 'Likely reached', tone: 'high', rank: 1 },
  possible: { label: 'Could be reached', tone: 'watch', rank: 2 },
}

const UNIT_LABEL: Record<string, string> = {
  fire_department: 'Fire & rescue',
  police: 'Police',
  medical_services: 'MDA',
}


// ===== Briefing blocks (box 3) ==============================================

function Brief({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="brief">
      <h3>{title}</h3>
      {children}
    </section>
  )
}

function Figure({ value, label }: { value: ReactNode; label: string }) {
  return (
    <p className="brief__figure">
      <strong>{value}</strong>
      <span>{label}</span>
    </p>
  )
}

function Tag({ tone = 'neutral', children }: { tone?: string; children: ReactNode }) {
  return <span className={`tag tag--${tone}`}>{children}</span>
}

type Place = {
  key: string
  name: string
  tag?: ReactNode
  detail: string[]
}

function Places({ places, empty }: { places: Place[]; empty: string }) {
  if (places.length === 0) return <p className="event-box__muted">{empty}</p>
  return (
    <ul className="places">
      {places.map((place) => (
        <li key={place.key}>
          <div className="places__head">
            <strong>{place.name}</strong>
            {place.tag}
          </div>
          {place.detail.length > 0 && <span className="places__detail">{place.detail.join(' · ')}</span>}
        </li>
      ))}
    </ul>
  )
}


// ===== Plan blocks (box 4) ==================================================

// The national lines, for when a service has no station number on file.
const NATIONAL_LINE = { police: '100', mda: '101', fire: '102' }

function Contacts({ parties }: { parties: PartiesState }) {
  if (parties.status === 'loading') {
    return <section className="plan-block"><h3>Who to call</h3><p className="event-box__muted">Looking up contacts…</p></section>
  }
  const data = parties.status === 'ready' ? parties.data : null
  const tiles: Array<{ role: string; name: string; phone: string | null; note?: string }> = [
    {
      role: data?.authority?.type ?? 'Local authority',
      name: data?.authority?.name ?? 'Not on file',
      phone: data?.authority?.phone ?? null,
    },
    {
      role: data?.police_station?.basis === 'nearest' ? 'Nearest police' : 'Police',
      name: data?.police_station?.name ?? 'Israel Police',
      phone: data?.police_station?.phone ?? NATIONAL_LINE.police,
      note: data?.police_station?.phone ? `or ${NATIONAL_LINE.police}` : 'national line',
    },
    {
      role: 'Fire & rescue',
      name: data?.nearest_fire_station ? `${data.nearest_fire_station.name} station` : 'Fire & rescue',
      phone: data?.nearest_fire_station?.phone ?? NATIONAL_LINE.fire,
      note: data?.nearest_fire_station?.phone ? `or ${NATIONAL_LINE.fire}` : 'national line',
    },
    {
      role: 'MDA',
      name: data?.nearest_mda_station ? `${data.nearest_mda_station.name} station` : 'Magen David Adom',
      phone: NATIONAL_LINE.mda,
      note: 'national line',
    },
  ]
  return (
    <section className="plan-block">
      <h3>Who to call</h3>
      <div className="contacts">
        {tiles.map((tile) => (
          <div key={tile.role} className="contact">
            <span className="contact__role">{tile.role}</span>
            <strong className="contact__name">{tile.name}</strong>
            {tile.phone
              ? <a className="contact__phone" href={`tel:${tile.phone.replace(/[^0-9+*]/g, '')}`}>{tile.phone}</a>
              : <span className="event-box__muted">no phone on file</span>}
            {tile.note && <span className="contact__note">{tile.note}</span>}
          </div>
        ))}
      </div>
    </section>
  )
}

type PlanStep = { text: string; unit?: string | null; note?: string | null; timeframe: string }

const TIMEFRAMES: Array<[key: string, label: string]> = [
  ['immediate', 'Now'],
  ['within_1_hour', 'Within the hour'],
  ['within_6_hours', 'Within 6 hours'],
  ['ongoing', 'Ongoing'],
]

/** The steps grouped by urgency, numbered straight through so "step 4" means
 *  the same thing to everyone reading it. */
function ActionPlan({ steps, intro }: { steps: PlanStep[]; intro?: string | null }) {
  const known = new Set(TIMEFRAMES.map(([key]) => key))
  const groups = [
    ...TIMEFRAMES.map(([key, label]) => ({ key, label, steps: steps.filter((step) => step.timeframe === key) })),
    { key: 'other', label: 'When possible', steps: steps.filter((step) => !known.has(step.timeframe)) },
  ].filter((group) => group.steps.length > 0)

  let number = 0
  return (
    <section className="plan-block">
      <h3>Action plan</h3>
      {intro && <p className="plan-block__intro">{intro}</p>}
      {groups.length === 0 && <p className="event-box__muted">No actions were produced for this event.</p>}
      {groups.map((group) => {
        const start = number + 1
        number += group.steps.length
        return (
          <div key={group.key} className="steps" data-when={group.key}>
            <h4 className="steps__when">{group.label}</h4>
            <ol start={start}>
              {group.steps.map((step, index) => (
                <li key={`${group.key}-${index}`}>
                  <span className="steps__text">{step.text}</span>
                  {(step.unit || step.note) && (
                    <span className="steps__meta">
                      {step.unit && <Tag>{step.unit}</Tag>}
                      {step.note && <span>{step.note}</span>}
                    </span>
                  )}
                </li>
              ))}
            </ol>
          </div>
        )
      })}
    </section>
  )
}

/** The stations sent, how long each takes, and turn-by-turn directions. */
function UnitsAssigned({ allocation }: { allocation: ResourceAllocationSummary }) {
  if (allocation.stations.length === 0) return null
  const partial = Object.values(allocation.requirements).some((requirement) => requirement.shortfall > 0)
  const unsupported = 'unsupported_units' in allocation ? (allocation.unsupported_units as string[]) : []
  return (
    <section className="plan-block">
      <h3>Units assigned</h3>
      <ul className="units">
        {allocation.stations.map((station: AllocatedStation) => {
          const eta = clock(station.route?.estimated_arrival_at)
          const travel = formatDuration(station.route?.duration_s ?? null)
          return (
            <li key={`${station.recommended_unit}-${station.database_id}`}>
              <div className="units__head">
                <Tag>{UNIT_LABEL[station.recommended_unit] ?? formatComponentName(station.recommended_unit)}</Tag>
                <strong>{station.name}</strong>
                <span className="units__time">
                  {travel ? `${travel} away` : 'travel time unknown'}
                  {station.distance_km != null && ` · ${station.distance_km.toFixed(1)} km`}
                  {eta && ` · ETA ${eta}`}
                </span>
              </div>
              {(station.response_actions?.length ?? 0) > 0 && (
                <ul className="units__tasks">
                  {station.response_actions?.map((action, index) => (
                    <li key={`${station.database_id}-task-${index}`}>{action.action}</li>
                  ))}
                </ul>
              )}
              {station.route?.requires_field_access_confirmation && (
                <span className="event-modal__allocation-warning">
                  The last stretch is off-road and unverified; its travel time is unknown.
                </span>
              )}
              {station.route?.steps_he && station.route.steps_he.length > 0 && (
                <details
                  id={`allocation-directions-${station.recommended_unit}-${station.database_id}`}
                  className="event-modal__directions"
                  dir="rtl"
                >
                  <summary>הוראות נסיעה</summary>
                  <ol>
                    {station.route.steps_he.map((step, index) => (
                      <li key={`${station.database_id}-step-${index}`}>
                        <span className="event-modal__direction-instruction">{step.instruction ?? 'המשך במסלול'}</span>
                        <span className="event-modal__direction-meta">
                          {step.distance_m != null && formatDistance(step.distance_m)}
                        </span>
                      </li>
                    ))}
                  </ol>
                </details>
              )}
            </li>
          )
        })}
      </ul>
      {partial && (
        <p className="event-modal__allocation-warning">
          Not every requested unit could be assigned; the allocation is partial.
        </p>
      )}
      {allocation.errors.length > 0 && (
        <p className="event-modal__allocation-warning">
          {allocation.errors.map(formatAllocationError).join('; ')}
        </p>
      )}
      {unsupported.length > 0 && (
        <p className="event-modal__allocation-warning">
          No station catalogue for: {unsupported.join(', ')}.
        </p>
      )}
    </section>
  )
}

/** Everything that qualifies the plan, folded away until asked for. */
function SourcesAndCaveats({ citations = [], lists = [], extra }: {
  citations?: ProtocolCitation[]
  lists?: Array<[title: string, items: string[] | undefined]>
  extra?: ReactNode
}) {
  const listed = lists.filter(([, items]) => (items?.length ?? 0) > 0)
  if (citations.length === 0 && listed.length === 0 && !extra) return null
  return (
    <details className="caveats">
      <summary>Sources and caveats</summary>
      {listed.map(([title, items]) => <ListSection key={title} title={title} items={items} />)}
      {extra}
      <Citations citations={citations} />
    </details>
  )
}

function planSummary(steps: PlanStep[], parties: PartiesState): Row[] {
  const first = steps.find((step) => step.timeframe === 'immediate') ?? steps[0]
  const authority = parties.status === 'ready' ? parties.data.authority : null
  const police = parties.status === 'ready' ? parties.data.police_station : null
  return [
    ['First step', first?.text ?? 'none produced'],
    ['Steps', `${steps.length} action${steps.length === 1 ? '' : 's'}`],
    ['Call', authority?.phone
      ? `${authority.name} · ${authority.phone}`
      : police?.phone ? `${police.name} · ${police.phone}` : parties.status === 'loading' ? 'Looking up…' : 'police 100'],
  ]
}


// ===== Per-hazard content ===================================================

type Row = [label: string, value: ReactNode]
type BoxContent = { summary: Row[]; body: ReactNode }
type HazardBoxes = { event: BoxContent; incident: BoxContent; plan: BoxContent }

function fireBoxes(event: FireEvent, parties: PartiesState): HazardBoxes {
  const details = event.details
  const assessed = event.analysis_status === 'success' && details.risk_level !== null
  const detection = details.detection
  const spread = details.spread
  const dispatch = details.dispatch
  const direction = spread?.heading_compass ? compassWord(spread.heading_compass) : null
  const settlements = [...details.exposed_settlements].sort((a, b) => (
    EXPOSURE[a.exposure].rank - EXPOSURE[b.exposure].rank
    || (a.arrival_minutes ?? Infinity) - (b.arrival_minutes ?? Infinity)
  ))
  const riskBreakdown = Object.entries(details.population_at_risk ?? {})
    .filter(([, count]) => count > 0)
    .sort(([a], [b]) => (EXPOSURE[a as Exposure]?.rank ?? 9) - (EXPOSURE[b as Exposure]?.rank ?? 9))

  const steps: PlanStep[] = details.response_actions.map((action) => ({
    text: action.action,
    unit: action.responsible_unit,
    timeframe: action.timeframe,
  }))

  return {
    event: {
      summary: [
        ['Evidence', detection && detection.verdict !== 'unassessed'
          ? `${capitalise(detection.verdict)} detection${detection.score != null ? ` · ${detection.score}/100` : ''}`
          : 'Detection not assessed'],
        ['Confidence', details.confidence ?? details.detection_confidence ?? 'not assessed'],
        ['Risk', assessed ? `${details.risk_level} · ${details.risk_score}` : 'not assessed'],
      ],
      body: (
        <>
          {detection && detection.reasons.length > 0 && (
            <section className="event-modal__section">
              <h3>Detection evidence</h3>
              <ul>
                {detection.reasons.map((reason) => (
                  <li key={reason.factor}>
                    <strong>{reason.factor}</strong> ({reason.points > 0 ? '+' : ''}{reason.points}) — {reason.detail}
                  </li>
                ))}
              </ul>
            </section>
          )}
          <ListSection title="Primary drivers" items={details.primary_drivers} />
          <ListSection title="Evidence gaps" items={details.evidence_gaps} gaps />
        </>
      ),
    },

    incident: {
      summary: [
        ['Now', direction ? `Spreading ${direction}` : assessed ? `${capitalise(details.risk_level ?? '')} risk fire` : 'Fire reported'],
        ['At risk', details.people_in_spread != null ? `${details.people_in_spread.toLocaleString()} people` : 'not counted'],
        ['Settlements', settlements.length > 0 ? `${settlements.length} in the path` : 'none in the path'],
      ],
      body: (
        <>
          <Brief title="What's happening">
            <p>{event.description || 'A fire has been detected at this location.'}</p>
            <p className="brief__tags">
              {assessed && <Tag tone={details.risk_level === 'critical' || details.risk_level === 'high' ? 'critical' : 'watch'}>{capitalise(details.risk_level ?? '')} risk</Tag>}
              {details.fire_weather_severity && <Tag tone="watch">{capitalise(details.fire_weather_severity)} fire weather</Tag>}
              {detection && detection.verdict !== 'unassessed' && <Tag>{capitalise(detection.verdict)} detection</Tag>}
            </p>
          </Brief>

          <Brief title="How it may spread">
            {direction ? (
              <p>
                The fire is expected to spread toward the <strong>{direction}</strong>
                {spread?.head_rate_m_per_min != null && <>, advancing about <strong>{Math.round(spread.head_rate_m_per_min)} m a minute</strong></>}.
                {spread?.horizon_minutes != null && spread.head_distance_m != null && (
                  <> Over the next {minutesWord(spread.horizon_minutes)} its front could move roughly <strong>{formatDistance(spread.head_distance_m)}</strong>.</>
                )}
                {' '}The likely and possible spread areas are drawn on the map.
              </p>
            ) : <p className="event-box__muted">No spread forecast was produced for this fire.</p>}
          </Brief>

          <Brief title="Population at risk">
            {details.people_in_spread != null ? (
              <>
                <Figure value={details.people_in_spread.toLocaleString()} label="people inside the forecast spread" />
                {riskBreakdown.length > 0 && (
                  <p className="brief__tags">
                    {riskBreakdown.map(([exposure, count]) => (
                      <Tag key={exposure} tone={EXPOSURE[exposure as Exposure]?.tone}>
                        {count.toLocaleString()} {EXPOSURE[exposure as Exposure]?.label.toLowerCase() ?? exposure}
                      </Tag>
                    ))}
                  </p>
                )}
              </>
            ) : <p className="event-box__muted">The population in the spread area could not be counted.</p>}
          </Brief>

          <Brief title="Affected settlements">
            <Places
              empty="No settlement lies in the forecast spread."
              places={settlements.map((settlement) => ({
                key: settlement.name,
                name: settlement.name_he ?? settlement.name,
                tag: <Tag tone={EXPOSURE[settlement.exposure].tone}>{EXPOSURE[settlement.exposure].label}</Tag>,
                detail: [
                  settlement.exposure === 'burning'
                    ? 'fire is already there'
                    : settlement.arrival_minutes != null ? `fire could arrive in ~${minutesWord(settlement.arrival_minutes)}` : '',
                  settlement.population != null ? `${settlement.population.toLocaleString()} residents` : '',
                  settlement.distance_m != null ? `${formatDistance(settlement.distance_m)} away` : '',
                ].filter(Boolean),
              }))}
            />
          </Brief>

          {details.sites_at_risk.length > 0 && (
            <Brief title="Sensitive sites in the path">
              <Places
                empty=""
                places={details.sites_at_risk.slice(0, 8).map((site) => ({
                  key: `${site.name}-${site.kind}`,
                  name: site.name,
                  tag: <Tag tone={site.category === 'hazard' ? 'critical' : site.category === 'life_safety' ? 'high' : 'neutral'}>
                    {site.category === 'life_safety' ? 'Life safety' : capitalise(site.category)}
                  </Tag>,
                  detail: [site.kind.replaceAll('_', ' '), site.distance_m != null ? `${formatDistance(site.distance_m)} away` : ''].filter(Boolean),
                }))}
              />
            </Brief>
          )}
        </>
      ),
    },

    plan: {
      summary: planSummary(steps, parties),
      body: (
        <>
          <Contacts parties={parties} />
          <ActionPlan steps={steps} />

          {details.evacuation.length > 0 && (
            <section className="plan-block">
              <h3>Evacuation</h3>
              <ul className="evacuation">
                {details.evacuation.map((item) => (
                  <li key={item.name} data-priority={item.priority}>
                    <Tag tone={item.priority === 'immediate' ? 'critical' : item.priority === 'prepare' ? 'high' : 'watch'}>
                      {item.priority === 'immediate' ? 'Evacuate now' : item.priority === 'prepare' ? 'Prepare' : 'Standby'}
                    </Tag>
                    <div className="evacuation__body">
                      <strong>{item.name}</strong>
                      <span>
                        {[item.population != null ? `${item.population.toLocaleString()} residents` : '',
                          item.arrival_minutes != null ? `fire in ~${minutesWord(item.arrival_minutes)}` : ''].filter(Boolean).join(' · ')}
                      </span>
                      <span className="event-box__muted">{item.reason}</span>
                    </div>
                    {item.authority_phone ? (
                      <a className="evacuation__call" href={`tel:${item.authority_phone.replace(/[^0-9+*]/g, '')}`}>
                        {item.authority} · {item.authority_phone}
                      </a>
                    ) : <span className="event-box__muted">no authority number</span>}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {dispatch && (
            <section className="plan-block">
              <h3>Fire service dispatch</h3>
              <p>
                <strong>Grade {dispatch.grade}</strong>
                {dispatch.teams_required != null && <> · {dispatch.teams_required} teams</>}
                {dispatch.is_national_event && <> · <Tag tone="critical">National event</Tag></>}
              </p>
              {dispatch.grade_reason && <p className="event-box__muted">{dispatch.grade_reason}</p>}
              {(dispatch.teams_shortfall ?? 0) > 0 && (
                <p className="event-modal__allocation-warning">
                  {dispatch.teams_shortfall} team(s) could not be filled from the stations on file.
                </p>
              )}
              <ul className="units">
                {dispatch.stations.map((station) => (
                  <li key={`${station.name}-${station.role}`}>
                    <div className="units__head">
                      <strong>{station.teams}× {station.name}</strong>
                      <span className="units__time">{[station.district, station.request_type].filter(Boolean).join(' · ')}</span>
                    </div>
                    {station.role.startsWith('initial_response') && (
                      <span className="event-modal__parallel">dispatched in parallel — no approval required</span>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {details.resource_allocation && <UnitsAssigned allocation={details.resource_allocation} />}

          <SourcesAndCaveats
            citations={details.protocol_citations}
            lists={[
              ['Recommended units', details.recommended_units],
              ['Not covered by doctrine', details.coverage_gaps],
              ['Assumptions', details.assumptions],
              ['Limitations', details.limitations],
            ]}
            extra={details.incident_report && (
              <section className="event-modal__section">
                <h3>Full incident report</h3>
                <pre className="event-modal__report">{details.incident_report}</pre>
              </section>
            )}
          />
        </>
      ),
    },
  }
}

function earthquakeBoxes(event: EarthquakeEvent, parties: PartiesState): HazardBoxes {
  const details = event.details
  const population = details.population_summary
  const people = population.status === 'available' ? population.estimated_population : null
  const steps: PlanStep[] = details.response_actions.map((action) => ({
    text: action.action,
    unit: action.responsible_unit,
    timeframe: action.timeframe,
  }))

  return {
    event: {
      summary: [
        ['Evidence', `${details.provider} report · M${details.magnitude.toFixed(1)} at ${details.depth_km.toFixed(1)} km`],
        ['Confidence', 'Official seismic network'],
        ['Provider event', details.provider_event_id],
      ],
      body: <ListSection title="Evidence gaps" items={details.evidence_gaps} gaps />,
    },

    incident: {
      summary: [
        ['Now', `Magnitude ${details.magnitude.toFixed(1)} earthquake`],
        ['Shaking area', `${details.estimated_impact_radius_km} km radius`],
        ['At risk', people != null ? `${people.toLocaleString()} people` : 'not estimated'],
        ['Towns', details.towns_status === 'unavailable' ? 'unavailable' : `${details.towns.length} in the area`],
      ],
      body: (
        <>
          <Brief title="What's happening">
            <p>
              {event.description || (
                <>A magnitude <strong>{details.magnitude.toFixed(1)}</strong> earthquake struck at a depth of <strong>{details.depth_km.toFixed(1)} km</strong>, reported by {details.provider}.</>
              )}
            </p>
          </Brief>
          <Brief title="Extent">
            <p>
              Damaging shaking is estimated within about <strong>{details.estimated_impact_radius_km} km</strong> of the epicentre; the towns inside it are outlined in red on the map.
              Aftershocks may follow; the area is a screening estimate, not a damage survey.
            </p>
          </Brief>
          <Brief title="Population at risk">
            {people != null
              ? <Figure value={people.toLocaleString()} label="people living inside the estimated impact area" />
              : <p className="event-box__muted">The population in the impact area could not be estimated.</p>}
          </Brief>
          <Brief title="Affected settlements">
            <Places
              empty={details.towns_status === 'unavailable' ? 'Town data is unavailable.' : 'No town lies inside the impact area.'}
              places={details.towns.map((town) => ({
                key: town.town_id,
                name: town.name_he || town.name_en,
                detail: town.name_he && town.name_en ? [town.name_en] : [],
              }))}
            />
          </Brief>
        </>
      ),
    },

    plan: {
      summary: planSummary(steps, parties),
      body: (
        <>
          <Contacts parties={parties} />
          <ActionPlan steps={steps} intro={details.plan_summary} />
          {details.resource_allocation && <UnitsAssigned allocation={details.resource_allocation} />}
          <SourcesAndCaveats
            citations={details.protocol_citations}
            lists={[['Recommended units', details.recommended_units], ['Limitations', details.limitations]]}
          />
        </>
      ),
    },
  }
}

function airPollutionBoxes(event: AirPollutionEvent, parties: PartiesState): HazardBoxes {
  const details = event.details
  const baseline = details.historical_baseline
  const official = details.official_pollutant_classification
  const transport = details.transport
  const population = details.population_within_screening_corridor
  const inside = details.relevant_settlements.filter((settlement) => settlement.inside_transport_corridor)
  const trendWord = details.trend === 'RISING' ? 'rising' : details.trend === 'FALLING' ? 'falling' : details.trend === 'STABLE' ? 'steady' : null
  const steps: PlanStep[] = details.recommendations.map((item) => ({
    text: item.recommendation,
    unit: item.responsible_authority_type,
    note: item.rationale,
    timeframe: item.timeframe,
  }))
  const unavailable = details.unavailable_components.map(
    (item) => `${formatComponentName(item.component)}: ${formatUnavailableReason(item.reason)}`,
  )

  return {
    event: {
      summary: [
        ['Evidence', `${details.pollutant} ${details.measured_value} ${details.unit}${baseline ? ` · usual high ${baseline.p95}` : ''}`],
        ['Confidence', official
          ? `Official index: ${official.classification.replaceAll('_', ' ').toLowerCase()}`
          : details.additional_verification?.status.replaceAll('_', ' ').toLowerCase() ?? 'advisory'],
        ['Station', details.station.name ?? details.station.id],
      ],
      body: (
        <>
          <section className="event-modal__section">
            <h3>Measurement</h3>
            <dl className="event-modal__facts event-modal__facts--compact">
              <div><dt>Pollutant</dt><dd>{details.pollutant}</dd></div>
              <div><dt>Measured</dt><dd>{details.measured_value} {details.unit}</dd></div>
              {baseline && <div><dt>Historical p95</dt><dd>{baseline.p95} {details.unit}</dd></div>}
              {details.ministry_aqi && <div><dt>Ministry index</dt><dd>{details.ministry_aqi.station_index} · {details.ministry_aqi.station_category}</dd></div>}
              <div><dt>Observed</dt><dd>{formatTimestamp(details.observation_timestamp)}</dd></div>
            </dl>
          </section>
          {details.additional_verification && (
            <section className="event-modal__section">
              <h3>Additional verification</h3>
              <p>{details.additional_verification.status.replaceAll('_', ' ').toLowerCase()}</p>
              {details.additional_verification.possible_source_correlations.map((correlation) => (
                <p key={`${correlation.source_hazard}-${correlation.source_incident_id}`}>{correlation.statement}</p>
              ))}
            </section>
          )}
        </>
      ),
    },

    incident: {
      summary: [
        ['Now', `${details.pollutant} ${details.measured_value} ${details.unit}${trendWord ? `, ${trendWord}` : ''}`],
        ['Drift', transport?.downwind_to_direction_deg != null ? `toward the ${bearingWord(transport.downwind_to_direction_deg)}` : 'not screened'],
        ['At risk', population ? `${population.total_relevant_population.toLocaleString()} people` : 'not estimated'],
        ['Settlements', `${inside.length} downwind`],
      ],
      body: (
        <>
          <Brief title="What's happening">
            <p>
              <strong>{details.pollutant}</strong> at {details.station.name ?? `station ${details.station.id}`} measured <strong>{details.measured_value} {details.unit}</strong>
              {baseline && <>, above its usual high for this hour and season ({baseline.p95} {details.unit})</>}.
              {trendWord && <> Levels are <strong>{trendWord}</strong>.</>}
            </p>
            {official && (
              <p className="brief__tags">
                <Tag tone={official.classification === 'MODERATE' ? 'watch' : 'high'}>
                  Official index: {official.classification.replaceAll('_', ' ').toLowerCase()}
                </Tag>
              </p>
            )}
          </Brief>

          <Brief title="Where it may drift">
            {details.wind && transport?.downwind_to_direction_deg != null ? (
              <p>
                With wind from the <strong>{bearingWord(details.wind.wind_from_direction_deg)}</strong> at {details.wind.wind_speed_mps.toFixed(1)} m/s,
                the polluted air may drift toward the <strong>{bearingWord(transport.downwind_to_direction_deg)}</strong>
                {transport.max_screening_distance_m != null && <>, up to about {formatDistance(transport.max_screening_distance_m)}</>}.
                {' '}The screening corridor is drawn on the map. It is an estimate, not a measured plume.
              </p>
            ) : <p className="event-box__muted">Wind data was not available to screen where the air may drift.</p>}
          </Brief>

          <Brief title="Population at risk">
            {population
              ? <Figure value={population.total_relevant_population.toLocaleString()} label="people living inside the screening corridor" />
              : <p className="event-box__muted">The population downwind could not be estimated.</p>}
          </Brief>

          <Brief title="Affected settlements">
            <Places
              empty="No settlement lies inside the screening corridor."
              places={inside.map((settlement) => ({
                key: settlement.id,
                name: settlement.name,
                tag: <Tag tone="watch">Downwind</Tag>,
                detail: [
                  settlement.transport_time?.status === 'estimated' && settlement.transport_time.seconds != null
                    ? `could be reached in ~${minutesWord(settlement.transport_time.seconds / 60)}` : '',
                  settlement.distance_m != null ? `${formatDistance(settlement.distance_m)} away` : '',
                ].filter(Boolean),
              }))}
            />
          </Brief>
        </>
      ),
    },

    plan: {
      summary: planSummary(steps, parties),
      body: (
        <>
          <Contacts parties={parties} />
          <ActionPlan steps={steps} />
          <SourcesAndCaveats
            lists={[
              ['Unavailable evidence', unavailable],
              ['Limitations', compactAirPollutionLimitations(details.limitations)],
            ]}
            extra={details.verified_references.length > 0 && (
              <section className="event-modal__section">
                <h3>Verified references</h3>
                {details.verified_references.map((reference) => (
                  <blockquote key={reference.id} className="event-modal__citation">
                    <p>“{reference.quoted_text}”</p>
                    <footer>
                      {reference.source_url
                        ? <a href={reference.source_url} target="_blank" rel="noreferrer">{reference.document_title}</a>
                        : reference.document_title}
                    </footer>
                  </blockquote>
                ))}
              </section>
            )}
          />
        </>
      ),
    },
  }
}

function floodBoxes(event: FloodEvent, parties: PartiesState): HazardBoxes {
  const details = event.details
  const streams = [...new Set(details.sources.map((source) => source.stream?.name).filter(Boolean))] as string[]
  const steps: PlanStep[] = [
    ...(details.response_actions ?? []).map((action) => ({
      text: action.action,
      unit: formatComponentName(action.responsible_unit),
      timeframe: action.timeframe,
    })),
    // Public instructions are part of what the operator puts out, so they
    // read as steps too.
    ...details.advisories.map((advisory) => ({
      text: advisory.instruction,
      unit: 'Public',
      timeframe: 'immediate',
    })),
  ]

  return {
    event: {
      summary: [
        ['Evidence', `${details.sources.length} hydrometric station(s) · severity ${details.severity_level}/6`],
        ['Confidence', details.risk_confidence ?? 'not assessed'],
        ['Risk', details.risk_level && details.risk_score != null ? `${details.risk_level} · ${details.risk_score}/100` : 'not assessed'],
      ],
      body: (
        <section className="event-modal__section">
          <h3>Hydrometric sources</h3>
          <ul className="event-modal__allocations">
            {details.sources.map((source) => (
              <li key={source.station.id}>
                <strong>Station {source.station.id}</strong>
                <span>Severity {source.station.severity_level}</span>
                <span>
                  {source.stream
                    ? `Stream: ${source.stream.name ?? source.stream.water_source_id}`
                    : `No matched stream · location precision ${Math.round(source.station.precision_m)} m`}
                </span>
                {source.station.observed_at && <span>Observed {formatTimestamp(source.station.observed_at)}</span>}
              </li>
            ))}
          </ul>
        </section>
      ),
    },

    incident: {
      summary: [
        ['Now', `Severity ${details.severity_level}/6 · ${details.return_period_label}`],
        ['Streams', streams.length > 0 ? streams.join(', ') : `${details.sources.length} station(s)`],
        ['Roads at risk', details.response_sites.length],
      ],
      body: (
        <>
          <Brief title="What's happening">
            <p>
              {event.description || (
                <>Streams are running high: a severity <strong>{details.severity_level} of 6</strong> warning ({details.return_period_label})
                {streams.length > 0 && <> on <strong>{streams.join(', ')}</strong></>}.</>
              )}
            </p>
            {details.risk_explanation && <p className="event-box__muted">{details.risk_explanation}</p>}
          </Brief>
          <Brief title="How it may develop">
            <p>
              {details.response_sites.length > 0
                ? <>Water may reach <strong>{details.response_sites.length} road crossing{details.response_sites.length === 1 ? '' : 's'}</strong> on the warned streams. Crossings with verified vehicle access are where units can close the road.</>
                : 'No road crossing on the warned streams was identified; the stream itself stays off-limits.'}
              {' '}The highlighted stream is under warning; it is not a flood outline.
            </p>
          </Brief>
          <Brief title="Roads at risk">
            <Places
              empty="No road crossing identified."
              places={details.response_sites.map((site) => ({
                key: site.target_id,
                name: site.road.ref ?? site.road.name ?? site.road.base_class ?? 'Unnamed road',
                tag: <Tag tone={site.allocation_eligible ? 'neutral' : 'watch'}>{site.allocation_eligible ? 'Access verified' : 'Access unverified'}</Tag>,
                detail: [
                  (site.crossing_type ?? 'crossing').replaceAll('_', ' '),
                  site.urban ? 'in town' : 'outside town',
                ],
              }))}
            />
          </Brief>
        </>
      ),
    },

    plan: {
      summary: planSummary(steps, parties),
      body: (
        <>
          <Contacts parties={parties} />
          <ActionPlan steps={steps} />
          {details.resource_allocation && <UnitsAssigned allocation={details.resource_allocation} />}
          <SourcesAndCaveats
            lists={[
              ['Assumptions', details.assumptions],
              ['Evidence gaps', details.evidence_gaps],
              ['Limitations', details.limitations],
            ]}
          />
        </>
      ),
    },
  }
}

function otherBoxes(event: SharedEvent, parties: PartiesState): HazardBoxes {
  return {
    event: { summary: [['Evidence', event.description || 'none recorded']], body: null },
    incident: {
      summary: [['Now', event.title]],
      body: <Brief title="What's happening"><p>{event.description || 'No analyser covers this event type yet.'}</p></Brief>,
    },
    plan: {
      summary: planSummary([], parties),
      body: <Contacts parties={parties} />,
    },
  }
}

function hazardBoxes(event: SharedEvent, parties: PartiesState): HazardBoxes {
  switch (event.type) {
    case 'fire': return fireBoxes(event, parties)
    case 'earthquake': return earthquakeBoxes(event, parties)
    case 'air_pollution': return airPollutionBoxes(event, parties)
    case 'flood': return floodBoxes(event, parties)
    default: return otherBoxes(event, parties)
  }
}


// ===== Box 2 ================================================================

function responsibleBox(parties: PartiesState, event: SharedEvent): BoxContent {
  if (parties.status === 'loading') {
    return { summary: [['Looking up', 'authority, police and stations…']], body: null }
  }

  // Offline fallback: an allocated event still carries its settlement's
  // authority, so the operator is never left without a number to call.
  if (parties.status === 'error') {
    const settlement = 'resource_allocation' in event.details
      ? (event.details.resource_allocation as ResourceAllocationSummary | null)?.settlement
      : null
    return {
      summary: settlement?.authority
        ? [['Authority', settlement.authority], ['Phone', <Phone number={settlement.authority_phone} />]]
        : [['Unavailable', 'responsible-party lookup failed']],
      body: <p className="event-box__muted">The responsible-party lookup is unavailable right now.</p>,
    }
  }

  const { authority, police_station: police, nearest_fire_station: fire, nearest_mda_station: mda } = parties.data
  return {
    summary: [
      ['Authority', authority?.name ?? 'none on file'],
      ['Police', police?.name ?? 'none on file'],
      ['Fire', fire ? `${fire.name} · ${formatDistance(fire.distance_m)}` : 'none on file'],
      ['MDA', mda ? `${mda.name} · ${formatDistance(mda.distance_m)}` : 'none on file'],
    ],
    body: (
      <div className="event-parties">
        <section className="event-party">
          <h3>Responsible authority</h3>
          {authority ? (
            <>
              <strong>{authority.name}</strong>
              {authority.type && <span>{authority.type}</span>}
              <span className="event-party__phone"><Phone number={authority.phone} /></span>
              {authority.address && <span>{authority.address}</span>}
              {authority.distance_m > 0 && (
                <span className="event-box__muted">
                  Event is {formatDistance(authority.distance_m)} outside {authority.town_name_he ?? authority.town_name_en}
                </span>
              )}
              {authority.website && (
                <a href={websiteUrl(authority.website)} target="_blank" rel="noreferrer">Authority website</a>
              )}
            </>
          ) : <span className="event-box__muted">No authority on file.</span>}
        </section>

        <section className="event-party">
          <h3>{police?.basis === 'nearest' ? 'Nearest police station' : 'Responsible police station'}</h3>
          {police ? (
            <>
              <strong>{police.name}</strong>
              <span className="event-party__phone"><Phone number={police.phone} /></span>
              {police.address && <span>{police.address}</span>}
              <span className="event-box__muted">{formatDistance(police.distance_m)} away</span>
            </>
          ) : <span className="event-box__muted">No police station on file.</span>}
        </section>

        <section className="event-party">
          <h3>Closest fire station</h3>
          {fire ? (
            <>
              <strong>{fire.name}</strong>
              {fire.phone && <span className="event-party__phone"><Phone number={fire.phone} /></span>}
              {fire.address && <span>{fire.address}</span>}
              <span className="event-box__muted">{formatDistance(fire.distance_m)} away, straight line</span>
            </>
          ) : <span className="event-box__muted">No fire station on file.</span>}
        </section>

        <section className="event-party">
          <h3>Closest MDA station</h3>
          {mda ? (
            <>
              <strong>{mda.name}</strong>
              {mda.address && <span>{mda.address}</span>}
              <span className="event-box__muted">{formatDistance(mda.distance_m)} away, straight line</span>
            </>
          ) : <span className="event-box__muted">No MDA station on file.</span>}
        </section>
      </div>
    ),
  }
}


// ===== The panel ============================================================

type BoxId = 'event' | 'responsible' | 'incident' | 'plan'

// Long enough that sweeping the pointer across the row does not open every
// box on the way; short enough that resting on one feels immediate.
const HOVER_INTENT_MS = 160

const NO_STATIONS: AllocatedStation[] = []

export type RoutesControl = {
  shown: boolean
  onToggle: () => void
  vehiclesShown: boolean
  onToggleVehicles: () => void
}

function RouteIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="6" cy="19" r="3" />
      <path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15" />
      <circle cx="18" cy="5" r="3" />
    </svg>
  )
}

function VehicleIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2" />
      <path d="M15 18H9" />
      <path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.62l-3.48-4.35A1 1 0 0 0 17.52 8H14" />
      <circle cx="17" cy="18" r="2" />
      <circle cx="7" cy="18" r="2" />
    </svg>
  )
}

function EventModal({ event, onClose, directionsStationKey = null, routes }: {
  event: SharedEvent
  onClose: () => void
  directionsStationKey?: string | null
  /** Present only for events with allocated stations. */
  routes?: RoutesControl
}) {
  const hazard = hazardOf(event)
  const urgency = classify(event)

  const [parties, setParties] = useState<PartiesState>({ status: 'loading' })
  useEffect(() => {
    let active = true
    fetchParties(event)
      .then((data) => { if (active) setParties({ status: 'ready', data }) })
      .catch(() => { if (active) setParties({ status: 'error' }) })
    return () => { active = false }
  }, [event])

  const boxes = hazardBoxes(event, parties)

  const stations = 'resource_allocation' in event.details
    ? (event.details.resource_allocation as ResourceAllocationSummary | null)?.stations ?? NO_STATIONS
    : NO_STATIONS
  const vehicles = useMemo(() => resourceAllocationSimulation(stations), [stations])

  // A click pins a box open; hovering opens one while the pointer rests on it.
  const [pinned, setPinned] = useState<BoxId | null>(directionsStationKey ? 'plan' : null)
  const [hovered, setHovered] = useState<BoxId | null>(null)
  const hoverTimer = useRef(0)
  const active = hovered ?? pinned

  const hoverBox = (id: BoxId) => {
    window.clearTimeout(hoverTimer.current)
    hoverTimer.current = window.setTimeout(() => setHovered(id), HOVER_INTENT_MS)
  }
  const leaveBoxes = () => {
    window.clearTimeout(hoverTimer.current)
    setHovered(null)
  }
  useEffect(() => () => window.clearTimeout(hoverTimer.current), [])

  useEffect(() => {
    const onKey = (keyboardEvent: KeyboardEvent) => {
      if (keyboardEvent.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // "Show directions" from a station popup: open the plan at that station.
  useEffect(() => {
    if (!directionsStationKey) return
    const frame = window.requestAnimationFrame(() => {
      const targetId = `allocation-directions-${directionsStationKey}`
      document.querySelectorAll<HTMLDetailsElement>('.event-modal__directions')
        .forEach((element) => {
          element.open = element.id === targetId
        })
      document.getElementById(targetId)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [directionsStationKey, event.id])

  const eventBox: BoxContent = {
    summary: [
      ['Type', (
        <span className="event-box__type">
          <HazardIcon kind={event.type} />
          {hazard.label}
        </span>
      )],
      ['Address', addressOf(parties, event)],
      ...boxes.event.summary,
    ],
    body: (
      <>
        <dl className="event-modal__facts event-modal__facts--compact">
          <div>
            <dt>{event.type === 'air_pollution' ? 'Monitoring location' : 'Location'}</dt>
            <dd>{event.latitude.toFixed(4)}, {event.longitude.toFixed(4)}</dd>
          </div>
          {event.observed_at && <div><dt>Observed</dt><dd>{formatTimestamp(event.observed_at)}</dd></div>}
        </dl>
        {event.processing?.failure_reason && (
          <section className="event-modal__section event-modal__section--gaps">
            <h3>Latest processing status</h3>
            <p>{event.processing.failure_stage ?? 'processing'}: {event.processing.failure_reason}</p>
            {event.processing.using_last_successful_payload && (
              <p>Showing the last projectable event state; recommendations from an older plan are not shown.</p>
            )}
          </section>
        )}
        {boxes.event.body}
      </>
    ),
  }

  const allBoxes: Array<[BoxId, string, BoxContent]> = [
    ['event', 'Event', eventBox],
    ['responsible', 'Responsible', responsibleBox(parties, event)],
    ['incident', 'Incident', boxes.incident],
    ['plan', 'Response plan', boxes.plan],
  ]

  const showVehicles = Boolean(routes?.shown && routes.vehiclesShown && vehicles.length > 0)

  return (
    <section
      className="event-panel"
      style={{ '--hazard': hazard.color } as CSSProperties}
      aria-label={`Event details: ${event.title}`}
    >
      <header className="event-panel__header">
        <span className="event-panel__glyph"><HazardIcon kind={event.type} /></span>
        <h2 className="event-panel__title">{event.title}</h2>
        <span className={`event-panel__urgency event-panel__urgency--${urgency}`}>{capitalise(urgency)}</span>
        {event.observed_at && (
          <time className="event-panel__time" dateTime={event.observed_at}>{formatTimestamp(event.observed_at)}</time>
        )}

        {routes && (
          <div className="event-panel__tools">
            <button
              type="button"
              className={`event-tool${routes.shown ? ' event-tool--on' : ''}`}
              aria-pressed={routes.shown}
              onClick={routes.onToggle}
            >
              <RouteIcon />
              Show optimal routes
            </button>
            {routes.shown && vehicles.length > 0 && (
              <button
                type="button"
                className={`event-tool${routes.vehiclesShown ? ' event-tool--on' : ''}`}
                aria-pressed={routes.vehiclesShown}
                onClick={routes.onToggleVehicles}
              >
                <VehicleIcon />
                Visualize emergency vehicles
              </button>
            )}
          </div>
        )}

        <button type="button" className="event-panel__close" onClick={onClose} aria-label="Close event details">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12" /></svg>
        </button>
      </header>

      {showVehicles && (
        <div className="event-panel__sim">
          <AllocationVehicleSimulation vehicles={vehicles} />
        </div>
      )}

      <div className="event-panel__boxes" onMouseLeave={leaveBoxes}>
        {allBoxes.map(([id, title, content]) => {
          const open = active === id
          return (
            <article
              key={id}
              className={`event-box${open ? ' event-box--open' : active ? ' event-box--closed' : ''}`}
              onMouseEnter={() => hoverBox(id)}
            >
              <button
                type="button"
                className="event-box__head"
                aria-expanded={open}
                onClick={() => setPinned((current) => (current === id ? null : id))}
              >
                <span className="event-box__title">
                  {title}
                  {pinned === id && <span className="event-box__pin">pinned</span>}
                </span>
                <dl className="event-box__summary">
                  {content.summary.map(([label, value]) => (
                    <div key={label}>
                      <dt>{label}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
              </button>
              {content.body && <div className="event-box__body">{content.body}</div>}
            </article>
          )
        })}
      </div>
    </section>
  )
}

export default EventModal
