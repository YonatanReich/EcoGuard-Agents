import { NavLink } from 'react-router-dom'
import { architectureRoutes } from '../navigation/architectureRoutes'

function ArchitectureNavigation() {
  return (
    <header className="architecture-header">
      <NavLink className="architecture-brand" to="/dashboard">
        EcoGuard
      </NavLink>

      <nav className="architecture-navigation" aria-label="Main navigation">
        <ul className="architecture-navigation__list">
          {architectureRoutes.map((route) => (
            <li key={route.path}>
              <NavLink
                to={route.path}
                className={({ isActive }) =>
                  `architecture-navigation__link${isActive ? ' architecture-navigation__link--active' : ''}`
                }
              >
                {route.navigationLabel}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  )
}

export default ArchitectureNavigation
