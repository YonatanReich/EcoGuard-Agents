import type { FireRiskAssessment } from '../types/riskAnalysis'

export async function fetchCurrentRiskAssessment(
  latitude: number,
  longitude: number,
): Promise<FireRiskAssessment> {
  const response = await fetch('/api/fire-risk', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ latitude, longitude }),
  })

  if (!response.ok) throw new Error('Current risk metadata is unavailable')
  return response.json() as Promise<FireRiskAssessment>
}
