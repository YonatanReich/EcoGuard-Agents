/**
 * The actors of the EcoGuard pipeline, as the System page presents them.
 *
 * `id` matches the `@live_actor("…")` marker on the actor's entry point in the
 * backend; `wiredTo` names that entry point, so the panel can say exactly what
 * "live" means for each box. Keep the two in step when an actor moves.
 */

export type StageId = 'detectors' | 'coordinator' | 'analyzers' | 'planners' | 'allocator'

export type ActorIcon =
  | 'fire' | 'flood' | 'earthquake' | 'air_pollution'
  | 'satellite' | 'thermometer' | 'message' | 'funnel' | 'send'
  | 'merge' | 'droplet' | 'clipboard' | 'truck'

export type Actor = {
  id: string
  stage: StageId
  name: string
  accent: string
  icon: ActorIcon
  /** One line on the box. */
  summary: string
  role: string
  how: string[]
  basedOn: string[]
  runs: string
  wiredTo: string
}

export const STAGES: Array<{ id: StageId; name: string; summary: string }> = [
  { id: 'detectors', name: 'Detectors', summary: 'Read what the collectors stored and raise signals.' },
  { id: 'coordinator', name: 'Coordinator', summary: 'Turns every signal into deduplicated incidents.' },
  { id: 'analyzers', name: 'Analysers', summary: 'Work out what each incident means on the ground.' },
  { id: 'planners', name: 'Response planners', summary: 'Write the protocol-grounded plan of action.' },
  { id: 'allocator', name: 'Resource allocator', summary: 'Commits and routes the units for emergencies.' },
]

const WAVE = 'Every pipeline wave, every 10 minutes.'

export const ACTORS: Actor[] = [
  // ----- Detectors -----
  {
    id: 'detector.fire_satellite',
    stage: 'detectors',
    name: 'Fire detector',
    accent: '#f97316',
    icon: 'satellite',
    summary: 'Spots active fires in satellite thermal hotspots.',
    role: 'The only detector that sees a fire directly. It turns satellite hotspots into fire signals and is the one that starts fire emergencies.',
    how: [
      'Reads the hotspots the FIRMS collector stored since its last run.',
      'Groups them by map cell and scores confidence from the pixels and how many satellites saw them.',
      'Screens out known false alarms, such as industrial sites that light up at the same hours every night, using each cell’s detection history.',
      'Emits a fire signal for each cell worth reporting.',
    ],
    basedOn: ['NASA FIRMS thermal hotspots (VIIRS, MODIS)', 'Each map cell’s detection history'],
    runs: `${WAVE} New hotspots arrive about every 30 minutes.`,
    wiredTo: 'detectors/fire/satellite.py · detect_new',
  },
  {
    id: 'detector.fire_weather',
    stage: 'detectors',
    name: 'Fire-weather detector',
    accent: '#fbbf24',
    icon: 'thermometer',
    summary: 'Flags weather that would make a fire spread fast.',
    role: 'Flags regions where the weather is unusually dangerous for fire. It cannot see a fire, so it raises advisories, never emergencies.',
    how: [
      'Reads the hourly weather stored since its last run, for every cell in the country.',
      'Scores how unusual the heat, dryness and wind are against that cell’s own climate.',
      'Emits a separate fire-weather signal, kept apart from real fires so it never outranks one.',
    ],
    basedOn: ['Open-Meteo hourly weather', 'Per-cell climate history'],
    runs: WAVE,
    wiredTo: 'detectors/fire/weather.py · detect_new',
  },
  {
    id: 'detector.air_pollution',
    stage: 'detectors',
    name: 'Air pollution detector',
    accent: '#a855f7',
    icon: 'air_pollution',
    summary: 'Catches pollutant readings far above their norm.',
    role: 'Watches the national air-monitoring stations and reports readings that are unusual for that station, month and hour.',
    how: [
      'Reads the station measurements stored since its last run.',
      'Compares each one to the station’s historical high for the same month and hour.',
      'Unusual readings become air-pollution signals.',
    ],
    basedOn: ['Ministry of Environmental Protection air-monitoring network', 'Historical per-station baselines'],
    runs: WAVE,
    wiredTo: 'detectors/air_pollution/observation_processing.py · detect_new',
  },
  {
    id: 'detector.flood',
    stage: 'detectors',
    name: 'Flood detector',
    accent: '#38bdf8',
    icon: 'flood',
    summary: 'Turns stream-gauge warnings into flood signals.',
    role: 'Reports streams whose gauges cross a warning level.',
    how: [
      'Reads the hydrometric readings stored since its last run.',
      'Requires an earlier consecutive reading at the same level, so one noisy reading cannot raise a flood.',
      'Emits a flood signal carrying the station’s severity level.',
    ],
    basedOn: ['Water Authority hydrometric stations (ten-minute readings)'],
    runs: WAVE,
    wiredTo: 'detectors/flood/observation_processing.py · detect_new',
  },
  {
    id: 'detector.earthquake',
    stage: 'detectors',
    name: 'Earthquake detector',
    accent: '#f87171',
    icon: 'earthquake',
    summary: 'Converts published earthquakes into signals.',
    role: 'Turns each earthquake the Geological Survey of Israel publishes into a signal.',
    how: [
      'Reads the GSI events stored since its last run.',
      'Converts each into a signal with its magnitude, depth and epicentre.',
    ],
    basedOn: ['Geological Survey of Israel seismic catalogue'],
    runs: WAVE,
    wiredTo: 'detectors/earthquake/observation_processing.py · detect_new',
  },
  {
    id: 'detector.text_classifier',
    stage: 'detectors',
    name: 'News & Telegram classifier',
    accent: '#60a5fa',
    icon: 'message',
    summary: 'Reads news and Telegram posts for hazard reports.',
    role: 'Labels stored news items and Telegram messages: is this a report of something happening, which hazard, and where.',
    how: [
      'Reads the text the RSS and Telegram collectors stored.',
      'Sends it in batches to a language model, one prompt for all four hazards, since one post can report several.',
      'Stores the labels. It never judges how trustworthy a source is; that comes from the source registry.',
    ],
    basedOn: ['RSS news feeds and Telegram channels', 'Claude Haiku 4.5'],
    runs: WAVE,
    wiredTo: 'detectors/text/classifier.py · classify_new_text',
  },
  {
    id: 'detector.text_triage',
    stage: 'detectors',
    name: 'Text triage',
    accent: '#60a5fa',
    icon: 'funnel',
    summary: 'Decides which text reports become incidents.',
    role: 'Turns labelled reports into signals or weak events: official reports become events, unofficial ones wait for corroboration.',
    how: [
      'Places each report with a gazetteer; a place it does not know is skipped, never guessed.',
      'A report from an authority or the media is promoted straight to a signal.',
      'An unofficial report becomes a weak event until an official report, a second independent source or other evidence agrees.',
    ],
    basedOn: ['Classifier labels', 'Source registry (authority, media, unofficial)', 'Settlement gazetteer'],
    runs: WAVE,
    wiredTo: 'detectors/text/run.py · run_text_triage',
  },
  {
    id: 'detector.telegram_evidence',
    stage: 'detectors',
    name: 'Telegram evidence',
    accent: '#29b6f6',
    icon: 'send',
    summary: 'Attaches matching Telegram posts to fire and flood signals.',
    role: 'Adds Telegram messages as supporting evidence to fire and flood signals. It never creates a signal of its own.',
    how: [
      'Looks for Telegram posts near a signal in place and time.',
      'Attaches the matches as evidence, and passes every signal through unchanged if anything fails.',
    ],
    basedOn: ['Stored Telegram messages', 'Fire and flood signals from this wave'],
    runs: WAVE,
    wiredTo: 'detectors/telegram/evidence.py · enrich_signals_with_telegram',
  },

  // ----- Coordinator -----
  {
    id: 'coordinator',
    stage: 'coordinator',
    name: 'Coordinator',
    accent: '#8cc63f',
    icon: 'merge',
    summary: 'Merges every detector’s signals into incidents.',
    role: 'The single entry point for every detector. It deduplicates and corroborates signals into incidents and routes each to the emergency or advisory queue, without knowing anything about specific hazards.',
    how: [
      'Closes incidents that have gone quiet.',
      'Loads the open incidents.',
      'Matches each signal to a nearby open incident or starts a new one, so a three-day fire lands dozens of signals on one incident.',
      'Routes each incident to its queue and hands what it touched to the analysers.',
    ],
    basedOn: ['Signals from every detector', 'The incident store'],
    runs: 'Once per pipeline wave, after all the detectors.',
    wiredTo: 'coordinator/agent.py · run',
  },

  // ----- Analysers -----
  {
    id: 'analyzer.fire',
    stage: 'analyzers',
    name: 'Fire analyser',
    accent: '#f97316',
    icon: 'fire',
    summary: 'Scores national fire risk and a fire’s likely spread.',
    role: 'Keeps the national fire-risk picture current, which drives the high-risk alerts, and assesses detected fires: how they may spread and who is in the way.',
    how: [
      'Scores every map cell’s fire risk from the stored weather, fuel and vegetation data.',
      'For a detected fire, models the likely and possible spread and the settlements and sites inside it.',
      'Grounds its assessment in fire-protocol text, checking every citation against the source.',
    ],
    basedOn: ['Stored weather, fire-weather index and vegetation', 'Fuel models and terrain', 'Fire protocols'],
    runs: 'The national risk refresh runs on its own timer.',
    wiredTo: 'analyzers/emergency/fire/refresh_orchestrator.py · refresh',
  },
  {
    id: 'analyzer.flood',
    stage: 'analyzers',
    name: 'Flood analyser',
    accent: '#38bdf8',
    icon: 'flood',
    summary: 'Finds the roads a flood may cut and rates the risk.',
    role: 'Analyses a flood incident: which streams are under warning, which road crossings they reach, and how serious it is operationally.',
    how: [
      'Matches the warning stations to their streams.',
      'Finds the road crossings on those streams and checks vehicle access with Mapbox.',
      'Computes a deterministic operational risk score.',
    ],
    basedOn: ['Hydrometric readings', 'Stream and road network', 'Mapbox road checks'],
    runs: 'Per flood incident, in each wave.',
    wiredTo: 'analyzers/emergency/flood · FloodEventAnalyzer.analyze, FloodRiskAnalyzer.analyze',
  },
  {
    id: 'analyzer.earthquake',
    stage: 'analyzers',
    name: 'Earthquake analyser',
    accent: '#f87171',
    icon: 'earthquake',
    summary: 'Estimates the area and people an earthquake affects.',
    role: 'Screens an earthquake’s impact: the area likely to feel damaging shaking, the towns inside it, and how many people live there.',
    how: [
      'Estimates an impact radius from magnitude and depth.',
      'Intersects that area with the town outlines and the population grid.',
    ],
    basedOn: ['GSI magnitude and depth', 'Town outlines', 'Population grid'],
    runs: 'Per earthquake incident, in each wave.',
    wiredTo: 'analyzers/emergency/earthquake/impact.py · estimate_impact',
  },
  {
    id: 'analyzer.air_pollution',
    stage: 'analyzers',
    name: 'Air pollution analyser',
    accent: '#a855f7',
    icon: 'air_pollution',
    summary: 'Works out where polluted air may drift, and who is downwind.',
    role: 'Builds the case for an air-pollution advisory: how unusual the reading is, the official index, the wind, where the air may drift and who lives there.',
    how: [
      'Checks the reading against its historical baseline and the ministry’s official index.',
      'Screens a downwind corridor from measured wind.',
      'Counts the settlements and people inside the corridor and infers the trend.',
      'Looks for supporting evidence, such as a fire nearby.',
    ],
    basedOn: ['Ministry air-quality data', 'IMS wind observations', 'Town outlines and population grid'],
    runs: 'Per air-pollution incident, in each wave.',
    wiredTo: 'analyzers/non_emergency/air_pollution/event_analyzer.py · analyze, assess_official_index',
  },
  {
    id: 'analyzer.water_level',
    stage: 'analyzers',
    name: 'Kinneret level analyser',
    accent: '#3b82f6',
    icon: 'droplet',
    summary: 'Turns lake-level readings into an advisory.',
    role: 'Compares the Kinneret’s level to the Water Authority’s operating lines and says what action, if any, is needed.',
    how: [
      'Looks the latest level up against the upper red, lower red and black lines.',
      'Estimates the trend from recent readings, and how long until the next line.',
      'Deterministic: the published thresholds, no model.',
    ],
    basedOn: ['Water Authority daily Kinneret survey', 'Published operating lines'],
    runs: 'Whenever the Kinneret card is requested.',
    wiredTo: 'analyzers/non_emergency/water_level/advisory.py · advise',
  },

  // ----- Planners -----
  {
    id: 'planner.emergency',
    stage: 'planners',
    name: 'Emergency response planner',
    accent: '#ef4444',
    icon: 'clipboard',
    summary: 'Writes the action plan for emergencies.',
    role: 'Produces the plan for analysed emergencies: what to do, by whom and how urgently. It fails closed: without a sound plan it produces none rather than a guess.',
    how: [
      'Retrieves the relevant passages from the national emergency protocols for the hazard.',
      'Asks a language model for a structured plan that may only cite those passages.',
      'Checks every citation against the protocol text before accepting the plan.',
    ],
    basedOn: ['National emergency protocols', 'Claude', 'The analyser’s findings'],
    runs: 'Per emergency incident, after its analyser.',
    wiredTo: 'response_planner/emergency/planner.py · plan_response',
  },
  {
    id: 'planner.advisory',
    stage: 'planners',
    name: 'Advisory response planner',
    accent: '#facc15',
    icon: 'clipboard',
    summary: 'Writes recommendations for non-emergency advisories.',
    role: 'Produces protocol-grounded recommendations for air-pollution advisories: who should act, and how urgently.',
    how: [
      'Retrieves the matching passages from the air-quality protocols.',
      'Drafts recommendations tied to those passages, and fails closed like the emergency planner.',
    ],
    basedOn: ['Air-quality protocols', 'The analyser’s findings'],
    runs: 'Per advisory incident, after its analyser.',
    wiredTo: 'response_planner/air_pollution/planner.py · plan_response',
  },

  // ----- Allocator -----
  {
    id: 'allocator',
    stage: 'allocator',
    name: 'Resource allocator',
    accent: '#22c55e',
    icon: 'truck',
    summary: 'Assigns the nearest available units and routes them.',
    role: 'Commits fire, police and MDA stations to each emergency plan and routes them there, before the plan is published.',
    how: [
      'Turns the plan’s recommended units into requests.',
      'Picks the nearest available stations by road travel time.',
      'Reserves them with an atomic database claim, so two processes never send the same unit twice.',
      'Routes each unit with Mapbox and attaches directions and arrival times.',
    ],
    basedOn: ['Fire, police and MDA station catalogue', 'Mapbox Directions'],
    runs: 'Per wave, for the emergencies it produced.',
    wiredTo: 'resource_allocator/allocation_agent.py · allocate_processing_results',
  },
]
