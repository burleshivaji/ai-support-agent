import { useState } from 'react'
import ChatView from './components/ChatView.jsx'
import AdminDashboard from './components/AdminDashboard.jsx'

export default function App() {
  const [view, setView] = useState('chat')
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">N</span>
          <div>
            <div className="brand-name">Northwind Outfitters</div>
            <div className="brand-sub">AI Customer Support</div>
          </div>
        </div>
        <nav className="tabs">
          <button className={view === 'chat' ? 'tab active' : 'tab'}
                  onClick={() => setView('chat')}>Customer Chat</button>
          <button className={view === 'admin' ? 'tab active' : 'tab'}
                  onClick={() => setView('admin')}>Admin Dashboard</button>
        </nav>
      </header>
      {view === 'chat' ? <ChatView /> : <AdminDashboard />}
    </div>
  )
}
