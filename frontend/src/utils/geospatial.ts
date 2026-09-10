const EARTH_RADIUS_KM = 6371

function toRadians(value: number) {
  return value * Math.PI / 180
}

/** Calculate straight-line distance between two WGS84 coordinates. */
export function straightLineDistanceKm(
  origin: { latitude: number; longitude: number },
  destination: { latitude: number; longitude: number },
) {
  const latitudeDelta = toRadians(destination.latitude - origin.latitude)
  const longitudeDelta = toRadians(destination.longitude - origin.longitude)
  const originLatitude = toRadians(origin.latitude)
  const destinationLatitude = toRadians(destination.latitude)

  const haversine = Math.sin(latitudeDelta / 2) ** 2
    + Math.cos(originLatitude)
    * Math.cos(destinationLatitude)
    * Math.sin(longitudeDelta / 2) ** 2

  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(haversine)))
}
