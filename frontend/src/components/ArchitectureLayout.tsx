import { Outlet } from 'react-router-dom'
import ArchitectureNavigation from './ArchitectureNavigation'

import './architecture-navigation.css'

function ArchitectureLayout() {
  return (
    <div className="architecture-layout">
      <ArchitectureNavigation />
      <div className="architecture-layout__content">
        <Outlet />
      </div>
    </div>
  )
}

export default ArchitectureLayout
