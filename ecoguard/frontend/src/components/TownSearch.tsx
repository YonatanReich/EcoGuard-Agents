/**
 * TownSearch — find a settlement by name, frame it, and read its details.
 *
 * The operator types a name in Hebrew or English, picks from the matches, and
 * the map flies to that town with its outline drawn and a card open inside it:
 * population, which fire district it falls in, which police station answers
 * for it, and the local authority's phone number.
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


function TownSearch() {
  const { current: map } = useMap()

  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Town[]>([])
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<Town | null>(null)
  const [outline, setOutline] = useState<TownFeature | null>(null)
  const [searching, setSearching] = useState(false)

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

  const choose = useCallback((town: Town) => {
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
  }, [map])

  const clear = useCallback(() => {
    setSelected(null)
    setOutline(null)
    setQuery('')
    setResults([])
  }, [])

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
            id="town-selected-fill"
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

      {selected && (
        <Popup
          longitude={selected.label.longitude}
          latitude={selected.label.latitude}
          anchor="bottom"
          offset={12}
          closeOnClick={false}
          maxWidth="320px"
          className="town-popup"
          onClose={() => setSelected(null)}
        >
          <div className="town-card">
            <div className="town-card__name">{selected.name_he}</div>
            <div className="town-card__sub">
              {selected.name_en}
              {selected.place ? ` · ${selected.place}` : ''}
            </div>

            <div className="town-card__population">
              {selected.population != null
                ? <><strong>{selected.population.toLocaleString()}</strong> residents</>
                // Population is only known for about one town in seven — OSM
                // tags it on cities and rarely on villages. Saying so beats
                // showing a zero the operator might act on.
                : <span className="town-card__unknown">Population not recorded</span>}
            </div>

            <dl className="town-card__facts">
              {selected.fire_district && (
                <><dt>Fire district</dt><dd>{selected.fire_district}</dd></>
              )}
              {selected.police_station && (
                <><dt>Police</dt><dd>{selected.police_station}</dd></>
              )}
              {selected.authority && (
                <><dt>Authority</dt><dd>{selected.authority}</dd></>
              )}
              {selected.authority_phone && (
                <>
                  <dt>Phone</dt>
                  <dd>
                    <a href={`tel:${selected.authority_phone.replace(/[^0-9+]/g, '')}`}>
                      {selected.authority_phone}
                    </a>
                  </dd>
                </>
              )}
              {selected.households != null && (
                <><dt>Households</dt><dd>{selected.households.toLocaleString()}</dd></>
              )}
              {selected.area_km2 != null && (
                <>
                  <dt>Area</dt>
                  <dd>
                    {selected.area_km2.toFixed(2)} km²
                    {/* A municipal-boundary outline is the jurisdiction, not
                        the built-up town, and is the larger of the two. Say so
                        rather than letting the number read as the town. */}
                    {selected.outline_source === 'municipal boundary' && (
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
