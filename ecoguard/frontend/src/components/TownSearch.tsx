/**
 * TownSearch — find a settlement by name, frame it, and read its details.
 *
 * The operator types a name in Hebrew or English, picks from the matches, and
 * the map flies to that town with its outline drawn. The card is not forced on
 * them: hovering the outline shows it, moving off hides it again, and clicking
 * pins it until it is closed. Picking a town answers "where is it"; the details
 * — population, fire district, responsible police station, the authority's
 * phone number — are asked for separately.
 *
 * Two requests, not one. Search returns no geometry — the operator may type
 * six characters before choosing, and shipping polygons per keystroke to
 * populate a dropdown would be absurd. The outline arrives only once a town is
 * actually selected. The bounding box comes back with the search result, so
 * the camera can start moving without waiting for the second request.
 *
 * Rendered as a child of MapView, like LayersControl: the box itself is an
 * absolutely-positioned div, and the Source/Layer/Popup it owns are map
 * children, so one component holds the whole feature.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Layer, Popup, Source, useMap } from 'react-map-gl/mapbox'

import '../pages/visuals/townsearch.css'


export type Town = {
  town_id: string
  name_he: string
  name_en: string
  place: string | null
  population: number | null
  households: number | null
  cbs_code: string | null
  outline_source: string | null
  fire_district: string | null
  authority: string | null
  authority_type: string | null
  authority_phone: string | null
  authority_address: string | null
  authority_website: string | null
  police_station: string | null
  police_region: string | null
  police_district: string | null
  area_km2: number | null
  label: { latitude: number; longitude: number }
  bbox: [number, number, number, number]
}

type TownFeature = {
  type: 'Feature'
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon
  properties: Town
}


/** Long enough that a fast typist sends one request, not eight. */
const DEBOUNCE_MS = 220

/** Below this the result set is everything and the ranking is meaningless. */
const MIN_QUERY = 2

/**
 * Padding for the fitted camera, in pixels.
 *
 * "Comfortably in view" means the outline is not touching the window edges,
 * and the bottom has room for the popup that opens over it.
 */
const FIT_PADDING = { top: 90, bottom: 180, left: 80, right: 80 }

/**
 * A kibbutz is a few hundred metres across; fitting its bounds exactly would
 * push the camera past street level and lose all context. This caps the zoom
 * so a small village still arrives with its surroundings visible.
 */
const MAX_FIT_ZOOM = 14.5

/**
 * How long the card is kept mounted after it is dismissed.
 *
 * Unmounting on the same frame as the close leaves nothing to animate, so the
 * popup outlives its own dismissal by exactly the length of the exit
 * animation. Must match the --closing duration in townsearch.css.
 */
const CLOSE_MS = 150

/**
 * Grace period between the pointer leaving the outline and the card fading.
 *
 * A town is often several disjoint parts — Ariel is six, its built-up area
 * plus the industrial estate — and crossing the gap between two of them fires
 * mouseleave then mouseenter. Without this pause the card would blink every
 * time the pointer crossed open ground inside the town it is describing.
 */
const LEAVE_GRACE_MS = 90

/** The drawn outline's fill, which is what the pointer interacts with. */
const FILL_LAYER_ID = 'town-selected-fill'


function TownSearch() {
  const { current: map } = useMap()

  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Town[]>([])
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<Town | null>(null)
  const [outline, setOutline] = useState<TownFeature | null>(null)
  const [searching, setSearching] = useState(false)

  /**
   * Two ways for the card to be up, and they behave differently.
   *
   * `hovered` follows the pointer and is transient. `pinned` is a deliberate
   * click and stays until dismissed. A pin outranks a hover, so moving the
   * pointer off a pinned town does not take its card away.
   */
  const [hovered, setHovered] = useState<Town | null>(null)
  const [pinned, setPinned] = useState<Town | null>(null)
  const [closing, setClosing] = useState(false)
  const closeTimer = useRef<number | null>(null)

  // The pointer-leave handler has to know whether a pin is up. Reading it from
  // a ref rather than the closure keeps the listener effect from re-binding on
  // every pin, and keeps the check out of a state updater, which React is
  // free to run twice.
  const pinnedRef = useRef<Town | null>(null)
  useEffect(() => { pinnedRef.current = pinned }, [pinned])

  const leaveTimer = useRef<number | null>(null)

  // Identifies the most recent request, so a slow early response cannot
  // overwrite the results of a later, faster one.
  const latestQuery = useRef(0)

  const needle = query.trim()
  const tooShort = needle.length < MIN_QUERY

  // Derived, not stored. Clearing `results` from inside the effect when the
  // query gets too short would be a second render for something already known
  // at render time — and the lint rule against setState-in-effect is right.
  const visible = tooShort ? [] : results

  useEffect(() => {
    if (tooShort) return

    const ticket = ++latestQuery.current
    const timer = setTimeout(() => {
      // Inside the timeout rather than the effect body: this is a callback
      // firing later, not a synchronous cascade off the render.
      setSearching(true)
      fetch(`/api/towns/search?q=${encodeURIComponent(needle)}`)
        .then((response) => (response.ok ? response.json() : { towns: [] }))
        .then((payload) => {
          if (ticket !== latestQuery.current) return
          setResults(payload.towns ?? [])
          setOpen(true)
        })
        .catch(() => {
          if (ticket === latestQuery.current) setResults([])
        })
        .finally(() => {
          if (ticket === latestQuery.current) setSearching(false)
        })
    }, DEBOUNCE_MS)

    return () => clearTimeout(timer)
  }, [needle, tooShort])

  // Unmounting on the same frame as the close would leave nothing to animate,
  // so the card is held for the length of the exit animation first.
  const dismiss = useCallback(() => {
    if (closeTimer.current !== null) return
    setClosing(true)
    closeTimer.current = window.setTimeout(() => {
      setHovered(null)
      setPinned(null)
      setClosing(false)
      closeTimer.current = null
    }, CLOSE_MS)
  }, [])

  const cancelDismiss = useCallback(() => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current)
      closeTimer.current = null
    }
    setClosing(false)
  }, [])

  const cancelLeave = useCallback(() => {
    if (leaveTimer.current !== null) {
      window.clearTimeout(leaveTimer.current)
      leaveTimer.current = null
    }
  }, [])

  useEffect(() => () => {
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current)
    if (leaveTimer.current !== null) window.clearTimeout(leaveTimer.current)
  }, [])

  // Hover and click on the drawn outline. Bound to the layer rather than the
  // canvas, so the pointer leaving the polygon for the basemap counts as
  // leaving even without leaving the map.
  useEffect(() => {
    if (!map || !selected) return

    const show = () => {
      cancelLeave()
      cancelDismiss()
      setHovered(selected)
      map.getCanvas().style.cursor = 'pointer'
    }

    const hide = () => {
      map.getCanvas().style.cursor = ''
      // A pinned card is not the pointer's to take away.
      if (pinnedRef.current || leaveTimer.current !== null) return
      leaveTimer.current = window.setTimeout(() => {
        leaveTimer.current = null
        dismiss()
      }, LEAVE_GRACE_MS)
    }

    const pin = () => {
      cancelLeave()
      cancelDismiss()
      setPinned(selected)
      setHovered(selected)
    }

    map.on('mouseenter', FILL_LAYER_ID, show)
    map.on('mouseleave', FILL_LAYER_ID, hide)
    map.on('click', FILL_LAYER_ID, pin)

    return () => {
      map.off('mouseenter', FILL_LAYER_ID, show)
      map.off('mouseleave', FILL_LAYER_ID, hide)
      map.off('click', FILL_LAYER_ID, pin)
      map.getCanvas().style.cursor = ''
    }
  }, [map, selected, dismiss, cancelDismiss, cancelLeave])

  const choose = useCallback((town: Town) => {
    // No card on selection: flying somewhere answers "where", not "what". The
    // previous town's card goes immediately — it describes a place the map is
    // no longer looking at.
    cancelLeave()
    cancelDismiss()
    setHovered(null)
    setPinned(null)
    setSelected(town)
    setOpen(false)
    setQuery(town.name_he)
    setOutline(null)

    const [minLon, minLat, maxLon, maxLat] = town.bbox
    map?.fitBounds([[minLon, minLat], [maxLon, maxLat]], {
      padding: FIT_PADDING,
      maxZoom: MAX_FIT_ZOOM,
      duration: 1200,
      // Level the camera. MapView starts pitched for terrain, and a tilted
      // view of a town outline is harder to read than a plan one.
      pitch: 0,
      bearing: 0,
    })

    fetch(`/api/towns/${encodeURIComponent(town.town_id)}`)
      .then((response) => (response.ok ? response.json() : null))
      .then((feature: TownFeature | null) => {
        // Ignore a late outline for a town the operator has since moved off.
        setOutline((current) =>
          feature && feature.properties.town_id === town.town_id ? feature : current,
        )
      })
      .catch(() => undefined)
  }, [map, cancelDismiss, cancelLeave])

  // A pin outranks a hover, so the card does not swap to a different town
  // just because the pointer wandered.
  const shown = pinned ?? hovered

  const clear = useCallback(() => {
    cancelLeave()
    cancelDismiss()
    setSelected(null)
    setOutline(null)
    setHovered(null)
    setPinned(null)
    setQuery('')
    setResults([])
  }, [cancelDismiss, cancelLeave])

  return (
    <>
      <div className="town-search">
        <div className="town-search__field">
          <span className="town-search__icon" aria-hidden="true">⌕</span>

          <input
            className="town-search__input"
            type="search"
            value={query}
            placeholder="Search a town or village…"
            aria-label="Search for a town or village"
            onChange={(event) => setQuery(event.target.value)}
            onFocus={() => visible.length > 0 && setOpen(true)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') clear()
              if (event.key === 'Enter' && visible.length > 0) choose(visible[0])
            }}
          />

          {(query || selected) && (
            <button
              className="town-search__clear"
              onClick={clear}
              aria-label="Clear search"
            >
              ×
            </button>
          )}
        </div>

        {open && visible.length > 0 && (
          <ul className="town-search__results">
            {visible.map((town) => (
              <li key={town.town_id}>
                <button
                  className="town-search__result"
                  onClick={() => choose(town)}
                >
                  <span className="town-search__he">{town.name_he}</span>
                  <span className="town-search__en">{town.name_en}</span>
                  {town.population != null && (
                    <span className="town-search__pop">
                      {town.population.toLocaleString()}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}

        {open && !searching && !tooShort && visible.length === 0 && (
          <div className="town-search__empty">No town matches that name.</div>
        )}
      </div>

      {outline && (
        <Source id="town-selected" type="geojson" data={outline}>
          <Layer
            id={FILL_LAYER_ID}
            type="fill"
            paint={{ 'fill-color': '#38bdf8', 'fill-opacity': 0.22 }}
          />
          <Layer
            id="town-selected-outline"
            type="line"
            paint={{ 'line-color': '#38bdf8', 'line-width': 2.4 }}
          />
        </Source>
      )}

      {shown && (
        <Popup
          key={shown.town_id}
          longitude={shown.label.longitude}
          latitude={shown.label.latitude}
          anchor="bottom"
          offset={12}
          closeOnClick={false}
          maxWidth="320px"
          // A hovered card has no close button — there is nothing to close,
          // moving the pointer away is the dismissal — and it must not eat
          // pointer events, or opening over the cursor would immediately read
          // as leaving the polygon and flicker the card away.
          closeButton={Boolean(pinned)}
          className={[
            'town-popup',
            closing ? 'town-popup--closing' : 'town-popup--open',
            pinned ? 'town-popup--pinned' : 'town-popup--transient',
          ].join(' ')}
          onClose={dismiss}
        >
          <div className="town-card">
            <div className="town-card__name">{shown.name_he}</div>
            <div className="town-card__sub">
              {shown.name_en}
              {shown.place ? ` · ${shown.place}` : ''}
            </div>

            <div className="town-card__population">
              {shown.population != null
                ? <><strong>{shown.population.toLocaleString()}</strong> residents</>
                // Population is only known for about one town in seven — OSM
                // tags it on cities and rarely on villages. Saying so beats
                // showing a zero the operator might act on.
                : <span className="town-card__unknown">Population not recorded</span>}
            </div>

            <dl className="town-card__facts">
              {shown.fire_district && (
                <><dt>Fire district</dt><dd>{shown.fire_district}</dd></>
              )}
              {shown.police_station && (
                <><dt>Police</dt><dd>{shown.police_station}</dd></>
              )}
              {shown.authority && (
                <><dt>Authority</dt><dd>{shown.authority}</dd></>
              )}
              {shown.authority_phone && (
                <>
                  <dt>Phone</dt>
                  <dd>
                    <a href={`tel:${shown.authority_phone.replace(/[^0-9+]/g, '')}`}>
                      {shown.authority_phone}
                    </a>
                  </dd>
                </>
              )}
              {shown.households != null && (
                <><dt>Households</dt><dd>{shown.households.toLocaleString()}</dd></>
              )}
              {shown.area_km2 != null && (
                <>
                  <dt>Area</dt>
                  <dd>
                    {shown.area_km2.toFixed(2)} km²
                    {/* A municipal-boundary outline is the jurisdiction, not
                        the built-up town, and is the larger of the two. Say so
                        rather than letting the number read as the town. */}
                    {shown.outline_source === 'municipal boundary' && (
                      <span className="town-card__qualifier"> (municipal area)</span>
                    )}
                  </dd>
                </>
              )}
            </dl>
          </div>
        </Popup>
      )}
    </>
  )
}


export default TownSearch
