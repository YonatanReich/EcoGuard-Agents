import { useEffect, useState } from 'react'
import {
  normalizeNationalRiskScanResponse,
  type NationalRiskScan,
} from '../components/fireRiskScan'

const NATIONAL_RISK_REFRESH_INTERVAL_MS = 5 * 60 * 1000

export function useNationalRiskScan() {
  const [scan, setScan] = useState<NationalRiskScan | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    let requestInFlight = false
    let controller: AbortController | null = null

    const loadNationalRiskScan = async () => {
      if (requestInFlight) return
      requestInFlight = true
      controller = new AbortController()

      try {
        const response = await fetch('/api/fire-risk/national-scan', {
          signal: controller.signal,
        })
        if (!response.ok) throw new Error('National risk scan is unavailable')
        const nextScan = normalizeNationalRiskScanResponse(await response.json() as unknown)

        if (active) {
          setScan(nextScan)
          setError(null)
        }
      } catch (reason: unknown) {
        if (active && !controller.signal.aborted) {
          setError(
            reason instanceof Error
              ? reason.message
              : 'National risk scan is unavailable',
          )
        }
      } finally {
        requestInFlight = false
      }
    }

    void loadNationalRiskScan()
    const intervalId = window.setInterval(
      () => void loadNationalRiskScan(),
      NATIONAL_RISK_REFRESH_INTERVAL_MS,
    )

    return () => {
      active = false
      controller?.abort()
      window.clearInterval(intervalId)
    }
  }, [])

  return { scan, error }
}
