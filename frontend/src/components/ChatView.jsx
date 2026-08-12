import { useEffect, useRef, useState } from 'react'
import { sendChat, sessionId } from '../lib/api.js'
import VoicePanel from './VoicePanel.jsx'

const WELCOME = "Hi, I'm the Northwind support assistant. Could you share the email " +
  "address or phone number on your account? Once I verify you, I'll be happy to help " +
  "you further."

// The model answers with light markdown (bold, line breaks). Render just
// that, with everything HTML-escaped first.
function renderText(text) {
  const esc = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const html = esc.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\n/g, '<br/>')
  return <span dangerouslySetInnerHTML={{ __html: html }} />
}

export default function ChatView() {
  const [messages, setMessages] = useState([{ role: 'agent', text: WELCOME }])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const bottomRef = useRef(null)
  const fileRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, busy])

  async function send() {
    const text = input.trim()
    if (!text || busy) return
    setInput('')
    setMessages((m) => [...m, { role: 'user', text }])
    setBusy(true)
    try {
      const data = await sendChat(text)
      setMessages((m) => [...m, { role: 'agent', text: data.reply, error: !!data.error }])
    } catch {
      setMessages((m) => [...m, { role: 'agent', text: 'Connection problem. Is the backend running?', error: true }])
    } finally {
      setBusy(false)
    }
  }

  async function uploadPhoto(e) {
    const files = Array.from(e.target.files || [])
    e.target.value = ''
    if (files.length === 0 || busy) return
    setBusy(true)
    const names = files.map((f) => f.name).join(', ')
    setMessages((m) => [...m, { role: 'user', text: `Uploading: ${names}…` }])
    try {
      const stored = []
      for (const file of files) {
        const form = new FormData()
        form.append('session_id', sessionId)
        form.append('file', file)
        const res = await fetch('/api/upload', { method: 'POST', body: form })
        const data = await res.json()
        stored.push(data.stored_as)
      }
      const label = files.length === 1 ? `Photo uploaded: ${names}` : `Photos uploaded: ${names}`
      if (window.voiceCallLive) {
        // Mid-call upload: the voice agent picks the photos up itself, so
        // don't wake the chat agent - just say thanks here.
        const thanks = files.length === 1
          ? 'Thank you, your photo has been received. You can upload more, or just tell the agent on the call that you are done.'
          : `Thank you, your ${files.length} photos have been received. You can upload more, or just tell the agent on the call that you are done.`
        setMessages((m) => [...m.slice(0, -1),
          { role: 'user', text: label },
          { role: 'agent', text: thanks }])
        return
      }
      const note = files.length === 1
        ? `I have uploaded a photo. The file name is ${stored[0]}.`
        : `I have uploaded ${files.length} photos. The file names are ${stored.join(', ')}.`
      const reply = await sendChat(note)
      setMessages((m) => [...m.slice(0, -1),
        { role: 'user', text: label },
        { role: 'agent', text: reply.reply, error: !!reply.error }])
    } catch {
      setMessages((m) => [...m.slice(0, -1),
        { role: 'agent', text: 'The upload failed. Please try again.', error: true }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="chat-layout">
      <section className="chat-panel card">
        <div className="panel-title">Chat with support</div>
        <div className="chat-scroll">
          {messages.map((m, i) => (
            <div key={i} className={`bubble-row ${m.role}`}>
              <div className={`bubble ${m.role} ${m.error ? 'error' : ''}`}>{renderText(m.text)}</div>
            </div>
          ))}
          {busy && (
            <div className="bubble-row agent">
              <div className="bubble agent typing"><span></span><span></span><span></span></div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
        <div className="chat-input">
          <input type="file" accept="image/*" multiple ref={fileRef} hidden onChange={uploadPhoto} />
          <button className="attach-btn" title="Upload a damage photo"
                  onClick={() => fileRef.current?.click()} disabled={busy}>&#128206;</button>
          <input
            value={input}
            placeholder="Type your message…"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && send()}
            disabled={busy}
          />
          <button onClick={send} disabled={busy || !input.trim()}>Send</button>
        </div>
      </section>

      <aside className="chat-side">
        <VoicePanel />
        <div className="card demo-card">
          <div className="panel-title">Demo accounts</div>
          <ul className="demo-list">
            <li><b>ethan.miller@example.com</b> — standard refund (ORD-1001), cancel before shipping (ORD-1016), duplicate refund (ORD-1021)</li>
            <li><b>olivia.turner@example.com</b> — final sale denial (ORD-1004)</li>
            <li><b>ava.collins@example.com</b> — damaged item, photo upload required (ORD-1006)</li>
            <li><b>sophia.carter@example.com</b> — VIP late-return split (ORD-1002)</li>
            <li><b>benjamin.ward@example.com</b> — high-value escalation (ORD-1013)</li>
            <li><b>charlotte.gray@example.com</b> — blocked by suspicious flags (ORD-1014), carrier-lost override (ORD-1017)</li>
            <li><b>james.cooper@example.com</b> — stolen-after-delivery denial (ORD-1011)</li>
          </ul>
        </div>
      </aside>
    </div>
  )
}
