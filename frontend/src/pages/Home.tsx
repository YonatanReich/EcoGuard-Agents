import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

function Home() {
  const navigate = useNavigate()
  const [leaving, setLeaving] = useState(false)
  //Handle logging in, by navigating to the dashboard page
  const handleLogin = () => {
    setLeaving(true)
    setTimeout(() => navigate('/dashboard'), 700)
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
    </main>
  )
}

export default Home
