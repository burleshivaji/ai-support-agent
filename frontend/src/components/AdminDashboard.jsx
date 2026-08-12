import { useEffect, useRef, useState } from 'react'
import { getJSON, openLogSocket } from '../lib/api.js'

const TYPE_LABELS = {
  user_message: 'CUSTOMER',
  assistant_message: 'AGENT',
  tool_call: 'TOOL CALL',
  tool_result: 'TOOL RESULT',
  policy_check: 'POLICY',
  decision: 'DECISION',
  retry: 'RETRY',
  error: 'ERROR',
}

function summarize(log) {
  const c = log.content
  switch (log.type) {
    case 'user_message':
      return c.text
    case 'assistant_message':
      if (c.kind === 'tool_request')
        return 'requests ' + c.tools.map((t) => `${t.name}(${JSON.stringify(t.args)})`).join(', ')
      return c.text
    case 'tool_call':
      return `${c.tool}(${JSON.stringify(c.args)})`
    case 'tool_result':
      return `${c.tool} → ${JSON.stringify(c.result)}`
    case 'policy_check':
      return `${c.rule} [${c.result.toUpperCase()}] ${c.detail}`
    case 'decision':
      if (c.stage === 'eligibility')
        return `eligibility for ${c.order_id}: ${c.decision} (rule: ${c.rule})`
      if (c.stage === 'refund_processed')
        return `refund processed for ${c.order_id}: $${c.total} (${c.confirmation})`
      if (c.stage === 'process_refund_blocked')
        return `refund BLOCKED for ${c.order_id}: ${c.decision} (rule: ${c.rule})`
      if (c.stage === 'return_created')
        return `return ${c.rma} created for ${c.order_id} (opened: ${c.opened ? 'yes' : 'no'}, ship by ${c.ship_by}) — refund after facility inspection`
      if (c.stage === 'return_rejected')
        return `return ${c.rma} REJECTED at facility inspection for ${c.order_id} — no refund`
      if (c.stage === 'create_return_blocked')
        return `return BLOCKED for ${c.order_id}: ${c.decision} (rule: ${c.rule})`
      if (c.stage === 'escalated')
        return `escalated ${c.order_id || ''} → ticket ${c.ticket}`
      return JSON.stringify(c)
    case 'retry':
      return `LLM call attempt ${c.attempt} failed: ${c.error}`
    case 'error':
      return JSON.stringify(c)
    default:
      return JSON.stringify(c)
  }
}

export default function AdminDashboard() {
  const [logs, setLogs] = useState([])
  const [refunds, setRefunds] = useState([])
  const [returns, setReturns] = useState([])
  const [escalations, setEscalations] = useState([])
  const [customers, setCustomers] = useState([])
  const [channel, setChannel] = useState('all')
  const [paused, setPaused] = useState(false)
  const feedRef = useRef(null)
  const pausedRef = useRef(false)
  pausedRef.current = paused

  async function refreshTables() {
    const [r, t, e, c] = await Promise.all([
      getJSON('/api/refunds'), getJSON('/api/returns'),
      getJSON('/api/escalations'), getJSON('/api/customers'),
    ])
    setRefunds(r.refunds)
    setReturns(t.returns)
    setEscalations(e.escalations)
    setCustomers(c.customers)
  }

  async function resolveReturn(id, outcome) {
    await fetch(`/api/returns/${id}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ outcome }),
    })
    refreshTables()
  }

  useEffect(() => {
    getJSON('/api/logs?limit=300').then((d) => setLogs(d.logs))
    refreshTables()
    const ws = openLogSocket((event) => {
      setLogs((l) => [...l.slice(-500), event])
      if (event.type === 'decision') refreshTables()
    })
    return () => ws.close()
  }, [])

  useEffect(() => {
    if (!pausedRef.current)
      feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight })
  }, [logs])

  const visible = logs.filter((l) => channel === 'all' || l.channel === channel)

  return (
    <div className="admin-layout">
      <section className="card feed-panel">
        <div className="panel-title feed-head">
          <span>Live agent reasoning</span>
          <span className="feed-controls">
            {['all', 'chat', 'voice', 'admin'].map((ch) => (
              <button key={ch}
                      className={channel === ch ? 'chip active' : 'chip'}
                      onClick={() => setChannel(ch)}>{ch}</button>
            ))}
            <button className={paused ? 'chip active' : 'chip'}
                    onClick={() => setPaused(!paused)}>
              {paused ? 'resume scroll' : 'pause scroll'}
            </button>
          </span>
        </div>
        <div className="feed" ref={feedRef}>
          {visible.length === 0 && <div className="feed-empty">No agent activity yet. Start a chat.</div>}
          {visible.map((log, i) => (
            <div key={log.id ?? i} className={`log-row t-${log.type}`}>
              <span className="log-time">{(log.created_at || '').slice(11, 19)}</span>
              <span className={`log-badge t-${log.type}`}>{TYPE_LABELS[log.type] || log.type}</span>
              {log.channel === 'voice' && <span className="log-badge voice">VOICE</span>}
              <span className="log-text">{summarize(log)}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="admin-side">
        <div className="card">
          <div className="panel-title">Returns (facility)</div>
          <table>
            <thead><tr><th>RMA</th><th>Order</th><th>Customer</th><th>Item</th><th>Opened</th><th>Refund due</th><th>Ship by</th><th>Status</th></tr></thead>
            <tbody>
              {returns.map((t) => (
                <tr key={t.id}>
                  <td>RET-{String(t.id).padStart(4, '0')}</td>
                  <td>{t.order_id}</td><td>{t.customer_name}</td><td>{t.item}</td>
                  <td>{t.opened ? 'yes' : 'no'}</td>
                  <td>${t.refund_plan.reduce((s, p) => s + p.amount, 0).toFixed(2)}</td>
                  <td>{t.ship_by}</td>
                  <td>
                    {t.status === 'AWAITING_ARRIVAL' ? (
                      <span className="return-actions">
                        <button className="mini pass" onClick={() => resolveReturn(t.id, 'pass')}
                                title="Item arrived and passed inspection: issue refund">Pass</button>
                        <button className="mini fail" onClick={() => resolveReturn(t.id, 'fail')}
                                title="Inspection failed: no refund">Reject</button>
                      </span>
                    ) : t.status}
                  </td>
                </tr>
              ))}
              {returns.length === 0 && <tr><td colSpan="8" className="empty">none yet</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="card">
          <div className="panel-title">Refunds issued</div>
          <table>
            <thead><tr><th>Order</th><th>Customer</th><th>Amount</th><th>To</th><th>Rule</th><th>Conf.</th></tr></thead>
            <tbody>
              {refunds.map((r) => (
                <tr key={r.id}>
                  <td>{r.order_id}</td><td>{r.customer_name}</td>
                  <td>${r.amount.toFixed(2)}</td><td>{r.destination}</td>
                  <td>{r.rule}</td><td>{r.confirmation}</td>
                </tr>
              ))}
              {refunds.length === 0 && <tr><td colSpan="6" className="empty">none yet</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="card">
          <div className="panel-title">Escalations</div>
          <table>
            <thead><tr><th>#</th><th>Order</th><th>Customer</th><th>Reason</th><th>Status</th></tr></thead>
            <tbody>
              {escalations.map((e) => (
                <tr key={e.id}>
                  <td>ESC-{String(e.id).padStart(4, '0')}</td><td>{e.order_id}</td>
                  <td>{e.customer_name}</td><td className="wrap">{e.reason}</td><td>{e.status}</td>
                </tr>
              ))}
              {escalations.length === 0 && <tr><td colSpan="5" className="empty">none yet</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="card">
          <div className="panel-title">CRM customers</div>
          <table>
            <thead><tr><th>ID</th><th>Name</th><th>Tier</th><th>Spend</th><th>Flags</th><th>Orders</th></tr></thead>
            <tbody>
              {customers.map((c) => (
                <tr key={c.id}>
                  <td>{c.id}</td><td>{c.name}</td><td>{c.tier}</td>
                  <td>${Math.round(c.lifetime_spend).toLocaleString()}</td>
                  <td className={c.suspicious_flags >= 5 ? 'flag-bad' : ''}>{c.suspicious_flags}</td>
                  <td>{c.order_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
