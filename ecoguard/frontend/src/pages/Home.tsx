/**
 * Home page — the landing and "log in" screen at /.
 *
 * Responsible for introducing the product and sending the user through to
 * the dashboard. There is no real authentication yet: the button is a
 * navigation trigger, not a credential check.
 *
 * Styling comes from the global index.css (the .home__* classes), not a
 * page-specific stylesheet.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

function Home() {
  const navigate = useNavigate()

  /**
   * True once the user has clicked through, which adds the .home--leaving
   * class and starts the exit animation. Kept in state purely to drive CSS.
   */
  const [leaving, setLeaving] = useState(false)

  /**
   * Play the exit animation, then navigate to the dashboard.
   *
   * The 700ms delay must stay in step with the transition duration defined
   * for .home--leaving in index.css — navigating sooner would unmount the
   * page mid-animation.
   */
  const handleLogin = () => {
    setLeaving(true)
    setTimeout(() => navigate('/dashboard'), 700)
  }

  /** Same exit animation, different destination. */
  const handleDemo = () => {
    setLeaving(true)
    setTimeout(() => navigate('/demo'), 700)
  }

  return (
    <main className={`home${leaving ? ' home--leaving' : ''}`}>
      <img src="/logo-bot.png" alt="EcoGuard bot" className="home__bot" />
      <h1 className="home__title">EcoGuard Agents</h1>
      <p className="home__subtitle">
        Multi-source intelligence for natural disaster detection in Israel
      </p>
      <button className="login-button" onClick={handleLogin}>
        Log in
      </button>

      <button className="demo-button" onClick={handleDemo}>
        Show incidents demo
      </button>
    </main>
  )
}

export default Home
