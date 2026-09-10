import type { EnvironmentalData } from '../types/environmentalData'

export async function fetchEnvironmentalData(
  latitude: number,
  longitude: number,
): Promise<EnvironmentalData> {
  const params = new URLSearchParams({
    latitude: String(latitude),
    longitude: String(longitude),
  })
  const response = await fetch(`/api/environmental-data?${params.toString()}`)

  if (!response.ok) {
    let errorMessage = `Error ${response.status}`

    try {
      const errorData = await response.json() as { detail?: string }
      if (errorData.detail) errorMessage = errorData.detail
    } catch {
      // Keep the HTTP status when the response is not JSON.
    }

    throw new Error(errorMessage)
  }

  return response.json() as Promise<EnvironmentalData>
}
