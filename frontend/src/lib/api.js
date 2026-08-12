export const sessionId = 'web-' + Math.random().toString(36).slice(2, 10)

export async function sendChat(message) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, message }),
  })
  return res.json()
}

export async function getJSON(path) {
  const res = await fetch(path)
  return res.json()
}

export async function execVoiceTool(name, args) {
  const res = await fetch('/api/realtime/tool', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, name, arguments: args }),
  })
  const data = await res.json()
  return data.result
}

export function openLogSocket(onEvent) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${proto}://${location.host}/ws/logs`)
  ws.onmessage = (e) => onEvent(JSON.parse(e.data))
  const ping = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) ws.send('ping')
  }, 20000)
  ws.onclose = () => clearInterval(ping)
  return ws
}
