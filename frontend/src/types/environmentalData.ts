export type EnvironmentalData = {
  metadata: {
    timestamp: string
    collection_status: string
    services: {
      weather: {
        status: string
        source: string
      }
      geospatial: {
        status: string
        source: string
      }
    }
  }
  location: {
    latitude: number
    longitude: number
  }
  geospatial_context: {
    terrain_type: string
    region_type: string
    vegetation_density: number
    distance_to_water_m: number
    nearby_roads?: Array<{
      name?: string | null
      ref?: string | null
      type: string
      latitude?: number | null
      longitude?: number | null
    }>
    nearby_settlements?: Array<{
      name: string
      type: string
      latitude: number
      longitude: number
      osm_type?: string
      osm_id?: number
      population?: string | null
    }>
    nearby_hospitals?: Array<{
      name: string
      type: string
      latitude: number
      longitude: number
      osm_type?: string
      osm_id?: number
    }>
    nearby_police_stations?: Array<{
      name: string
      type: string
      latitude: number
      longitude: number
      osm_type?: string
      osm_id?: number
    }>
    nearby_fire_stations?: Array<{
      name: string
      type: string
      latitude: number
      longitude: number
      osm_type?: string
      osm_id?: number
    }>
    [key: string]: unknown
  }
  weather: {
    current: {
      temperature_c: number
      humidity_percent: number
      wind_speed_kmh: number
      precipitation_mm: number
      weather_code: number
    }
    forecast: {
      daily: {
        max_temp_c: number[]
        min_temp_c: number[]
        max_wind_speed_kmh: number[]
        precipitation_sum_mm: number[]
      }
    }
  }
  summary?: Record<string, unknown>
  missing_layers?: string[]
}
