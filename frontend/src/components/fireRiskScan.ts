export type RiskLevel = 'low' | 'medium' | 'high'

export type NationalRiskCell = {
  cell_id: string
  latitude: number
  longitude: number
  risk_score: number
  risk_level: RiskLevel
  evaluation_time: string
}

export type NationalRiskScan = {
  status: 'success' | 'partial' | 'unavailable'
  evaluation_time: string
  summary: Record<string, unknown>
  cells: NationalRiskCell[]
  unavailable_cells: unknown[]
  semantics: string
  refresh_metadata: Record<string, unknown> | null
}

/** Map the current backend transport shape explicitly from response.cells. */
export function normalizeNationalRiskScanResponse(payload: unknown): NationalRiskScan {
  if (!payload || typeof payload !== 'object') throw new Error('National risk scan response is invalid')
  const response = payload as Record<string, unknown>
  if (!Array.isArray(response.cells)) throw new Error('National risk scan response is missing cells')
  const evaluationTime = String(response.evaluation_time ?? '')
  const cells = response.cells.map((value) => {
    if (!value || typeof value !== 'object') throw new Error('National risk scan contains an invalid cell')
    const cell = value as Record<string, unknown>
    const riskLevel = String(cell.risk_level ?? '').toLowerCase()
    const latitude = Number(cell.latitude)
    const longitude = Number(cell.longitude)
    const riskScore = Number(cell.risk_score)
    if (!cell.cell_id || !['low', 'medium', 'high'].includes(riskLevel)
      || !Number.isFinite(latitude) || !Number.isFinite(longitude) || !Number.isFinite(riskScore)) {
      throw new Error('National risk scan contains an invalid evaluated cell')
    }
    return {
      cell_id: String(cell.cell_id), latitude, longitude, risk_score: riskScore,
      risk_level: riskLevel as RiskLevel,
      evaluation_time: String(cell.evaluation_time ?? evaluationTime),
    }
  })
  return {
    status: response.status as NationalRiskScan['status'],
    evaluation_time: evaluationTime,
    summary: (response.summary as Record<string, unknown>) ?? {},
    cells,
    unavailable_cells: Array.isArray(response.unavailable_cells) ? response.unavailable_cells : [],
    semantics: String(response.semantics ?? ''),
    refresh_metadata: response.refresh_metadata && typeof response.refresh_metadata === 'object'
      ? response.refresh_metadata as Record<string, unknown> : null,
  }
}
