import type { CSSProperties } from 'react'
import type { FireRiskCluster } from './fireRiskClusters'

type Props = {
  clusters: FireRiskCluster[]
  evaluationTime: string
  snapshotStale: boolean
  onViewOnMap: (cluster: FireRiskCluster) => void
  onDismiss: () => void
}

function FireRiskAlert({ clusters, evaluationTime, snapshotStale, onViewOnMap, onDismiss }: Props) {
  if (clusters.length === 0) return null
  return (
    <div role="status" style={containerStyle}>
      <div style={{ flex: 1 }}>
        <strong style={titleStyle}>HIGH estimated fire risk</strong>
        <div style={detailStyle}>
          {clusters.length} HIGH-risk {clusters.length === 1 ? 'area' : 'areas'} · highest score {(clusters[0].highest_risk_score * 100).toFixed(1)}%
        </div>
        <div style={noteStyle}>
          Conditions-based estimate, not an actual fire detection · {new Date(evaluationTime).toLocaleString()}
        </div>
        {snapshotStale && <div style={staleStyle}>Data may be outdated</div>}
        <div style={areaListStyle}>
          {clusters.map((cluster, index) => (
            <button key={cluster.cluster_id} type="button" style={buttonStyle} onClick={() => onViewOnMap(cluster)}>
              View area {index + 1} ({cluster.cell_count} {cluster.cell_count === 1 ? 'cell' : 'cells'})
            </button>
          ))}
        </div>
      </div>
      <button type="button" aria-label="Dismiss HIGH fire risk alert" title="Dismiss" style={closeStyle} onClick={onDismiss}>×</button>
    </div>
  )
}

const containerStyle: CSSProperties = { position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)',
  zIndex: 7, display: 'flex', alignItems: 'center', gap: 14, maxWidth: 'min(720px, calc(100% - 440px))',
  minWidth: 390, padding: '10px 12px', borderRadius: 8, color: '#e4ebf5', background: 'rgba(8,14,26,.93)', border: '1px solid rgba(239,68,68,.45)', borderLeft: '3px solid #ef4444',
  boxShadow: '0 8px 24px rgba(0,0,0,.45)', fontSize: '.82rem' }
const titleStyle: CSSProperties = { color: '#fca5a5', fontSize: '.94rem' }
const detailStyle: CSSProperties = { marginTop: 3, fontWeight: 600 }
const noteStyle: CSSProperties = { marginTop: 2, color: '#8594ab', fontSize: '.74rem' }
const staleStyle: CSSProperties = { marginTop: 3, color: '#fbbf24', fontWeight: 700, fontSize: '.76rem' }
const buttonStyle: CSSProperties = { flexShrink: 0, border: '1px solid rgba(239,68,68,.5)', borderRadius: 6,
  padding: '6px 10px', cursor: 'pointer', background: 'rgba(239,68,68,.14)', color: '#fecaca', fontWeight: 600,
  font: 'inherit' }
const areaListStyle: CSSProperties = { display: 'flex', flexWrap: 'wrap', gap: 7, marginTop: 8, maxHeight: 92, overflowY: 'auto' }
const closeStyle: CSSProperties = { alignSelf: 'flex-start', border: 0, background: 'transparent', color: '#8594ab',
  cursor: 'pointer', fontSize: '1.4rem', lineHeight: 1, padding: '0 2px' }

export default FireRiskAlert
