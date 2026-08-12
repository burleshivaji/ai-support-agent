import { useRef, useState } from 'react'
import { execVoiceTool } from '../lib/api.js'

// Voice pipeline: the browser connects to the OpenAI Realtime API over
// WebRTC using a short-lived key minted by our backend. When the voice
// model wants a tool, we run it through the backend so the same policy
// engine and admin logs are used as in text chat.
export default function VoicePanel() {
  const [status, setStatus] = useState('idle') // idle | connecting | live | error
  const [note, setNote] = useState('')
  const [lines, setLines] = useState([])
  const pcRef = useRef(null)
  const streamRef = useRef(null)

  function addLine(kind, text) {
    setLines((l) => [...l.slice(-30), { kind, text }])
  }

  async function handleEvent(dc, e) {
    let ev
    try { ev = JSON.parse(e.data) } catch { return }

    if (ev.type === 'response.output_item.done' && ev.item?.type === 'function_call') {
      const args = JSON.parse(ev.item.arguments || '{}')
      addLine('tool', `tool: ${ev.item.name}(${JSON.stringify(args)})`)
      const result = await execVoiceTool(ev.item.name, args)
      dc.send(JSON.stringify({
        type: 'conversation.item.create',
        item: {
          type: 'function_call_output',
          call_id: ev.item.call_id,
          output: JSON.stringify(result),
        },
      }))
      dc.send(JSON.stringify({ type: 'response.create' }))
    }

    if (ev.type === 'response.output_audio_transcript.done' && ev.transcript) {
      addLine('agent', ev.transcript)
    }
    if (ev.type === 'error') {
      addLine('error', ev.error?.message || 'realtime error')
    }
  }

  async function start() {
    setStatus('connecting')
    setNote('')
    try {
      const sess = await fetch('/api/realtime/session', { method: 'POST' }).then((r) => r.json())
      if (sess.error) throw new Error(sess.error)

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      const pc = new RTCPeerConnection()
      pcRef.current = pc
      pc.addTrack(stream.getTracks()[0], stream)
      pc.ontrack = (e) => {
        const audio = new Audio()
        audio.srcObject = e.streams[0]
        audio.play()
      }

      const dc = pc.createDataChannel('oai-events')
      dc.onmessage = (e) => handleEvent(dc, e)

      const offer = await pc.createOffer()
      await pc.setLocalDescription(offer)

      const resp = await fetch(
        `https://api.openai.com/v1/realtime/calls?model=${sess.model}`,
        {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${sess.client_secret}`,
            'Content-Type': 'application/sdp',
          },
          body: offer.sdp,
        },
      )
      if (!resp.ok) throw new Error(`Realtime connect failed: ${resp.status}`)
      await pc.setRemoteDescription({ type: 'answer', sdp: await resp.text() })
      setStatus('live')
      window.voiceCallLive = true
      addLine('info', 'Voice call connected. Say hello.')
    } catch (err) {
      setStatus('error')
      setNote(String(err.message || err))
      stopMedia()
    }
  }

  function stopMedia() {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    pcRef.current?.close()
    streamRef.current = null
    pcRef.current = null
    window.voiceCallLive = false
  }

  function stop() {
    stopMedia()
    setStatus('idle')
    addLine('info', 'Voice call ended.')
  }

  return (
    <div className="card voice-card">
      <div className="panel-title">
        Voice support
        {status === 'live' && <span className="live-dot" title="live" />}
      </div>
      {status !== 'live' ? (
        <button className="voice-btn" onClick={start} disabled={status === 'connecting'}>
          {status === 'connecting' ? 'Connecting…' : 'Start voice call'}
        </button>
      ) : (
        <button className="voice-btn stop" onClick={stop}>End call</button>
      )}
      {note && <div className="voice-note">{note}</div>}
      {lines.length > 0 && (
        <div className="voice-lines">
          {lines.map((l, i) => (
            <div key={i} className={`voice-line ${l.kind}`}>{l.text}</div>
          ))}
        </div>
      )}
    </div>
  )
}
