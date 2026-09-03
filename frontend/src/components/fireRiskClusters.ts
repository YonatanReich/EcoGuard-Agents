import type { NationalRiskCell } from './fireRiskScan'

export type FireRiskCluster = {
  cluster_id: string
  member_cell_ids: string[]
  cells: NationalRiskCell[]
  cell_count: number
  highest_risk_score: number
  representative_cell: NationalRiskCell
  bounds: [[number, number], [number, number]]
  centroid: { latitude: number; longitude: number }
  evaluation_time: string
}

const GRID_ID = /-r(\d+)-c(\d+)$/
const HALF_CELL_KM = 2.5

function gridPosition(cell: NationalRiskCell) {
  const match = GRID_ID.exec(cell.cell_id)
  return match ? { row: Number(match[1]), column: Number(match[2]) } : null
}

export function clusterHighRiskCells(cells: NationalRiskCell[]): FireRiskCluster[] {
  const high = cells.filter((cell) => cell.risk_level === 'high')
  const byPosition = new Map<string, NationalRiskCell>()
  for (const cell of high) {
    const position = gridPosition(cell)
    if (position) byPosition.set(`${position.row}:${position.column}`, cell)
  }

  const visited = new Set<string>()
  const groups: NationalRiskCell[][] = []
  for (const start of [...high].sort((a, b) => a.cell_id.localeCompare(b.cell_id))) {
    if (visited.has(start.cell_id)) continue
    const group: NationalRiskCell[] = []
    const queue = [start]
    visited.add(start.cell_id)
    while (queue.length) {
      const cell = queue.shift()!
      group.push(cell)
      const position = gridPosition(cell)
      if (!position) continue
      for (let rowDelta = -1; rowDelta <= 1; rowDelta += 1) {
        for (let columnDelta = -1; columnDelta <= 1; columnDelta += 1) {
          if (!rowDelta && !columnDelta) continue
          const neighbour = byPosition.get(`${position.row + rowDelta}:${position.column + columnDelta}`)
          if (neighbour && !visited.has(neighbour.cell_id)) {
            visited.add(neighbour.cell_id)
            queue.push(neighbour)
          }
        }
      }
    }
    groups.push(group)
  }

  return groups.map((group) => {
    const ordered = [...group].sort((a, b) => a.cell_id.localeCompare(b.cell_id))
    const representative = [...ordered].sort(
      (a, b) => b.risk_score - a.risk_score || a.cell_id.localeCompare(b.cell_id),
    )[0]
    const extents = ordered.map((cell) => {
      const latitudeDelta = HALF_CELL_KM / 111.32
      const longitudeDelta = HALF_CELL_KM / (111.32 * Math.cos(cell.latitude * Math.PI / 180))
      return [cell.longitude - longitudeDelta, cell.latitude - latitudeDelta,
        cell.longitude + longitudeDelta, cell.latitude + latitudeDelta]
    })
    const bounds: [[number, number], [number, number]] = [
      [Math.min(...extents.map((value) => value[0])), Math.min(...extents.map((value) => value[1]))],
      [Math.max(...extents.map((value) => value[2])), Math.max(...extents.map((value) => value[3]))],
    ]
    return {
      cluster_id: `high-area-${ordered[0].cell_id}`,
      member_cell_ids: ordered.map((cell) => cell.cell_id),
      cells: ordered,
      cell_count: ordered.length,
      highest_risk_score: representative.risk_score,
      representative_cell: representative,
      bounds,
      centroid: {
        latitude: ordered.reduce((sum, cell) => sum + cell.latitude, 0) / ordered.length,
        longitude: ordered.reduce((sum, cell) => sum + cell.longitude, 0) / ordered.length,
      },
      evaluation_time: representative.evaluation_time,
    }
  }).sort((a, b) => b.highest_risk_score - a.highest_risk_score || a.cluster_id.localeCompare(b.cluster_id))
}
