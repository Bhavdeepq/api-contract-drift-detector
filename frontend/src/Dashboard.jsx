
import React, { useEffect, useState } from "react";
import { analyzeContract, checkBackendHealth, createRemediationPlan, getContracts } from './services/api'

const label = value => value.replaceAll('_', ' ')

// Map a status string to a CSS tone class for the Badge.
// RESOLVED   → success (green)
// PROPOSED / NOT_RUN → pending (blue/muted)
// FAILED / VERIFICATION_FAILED → danger (red)
const statusTone = value => {
  if (value === 'RESOLVED') return 'success'
  if (value === 'FAILED' || value === 'VERIFICATION_FAILED') return 'danger'
  if (value === 'PROPOSED' || value === 'NOT_RUN') return 'pending'
  return 'neutral'
}

const Badge = ({ children, tone = 'neutral' }) => <span className={`badge ${tone}`}>{children}</span>
const State = ({ value }) => <Badge tone={statusTone(value)}>{label(value)}</Badge>
const Card = ({ t, n, c = '' }) => <article className={`card ${c}`}><span>{t}</span><strong>{n}</strong></article>
const Title = ({ over, title, count }) => <div className="title"><div><p className="eyebrow">{over}</p><h2>{title}</h2></div>{typeof count === 'string' ? <Badge>{count}</Badge> : count}</div>

export default function Dashboard() {
  const [online, setOnline] = useState(false), [contracts, setContracts] = useState({ expected: [], actual: [] })
  const [expected, setExpected] = useState('expected'), [actual, setActual] = useState('actual')
  const [analysis, setAnalysis] = useState(null), [plan, setPlan] = useState(null), [loading, setLoading] = useState(false), [error, setError] = useState('')

  useEffect(() => {
    Promise.all([checkBackendHealth(), getContracts()])
      .then(([, r]) => { setOnline(true); setContracts(r.data) })
      .catch(() => setOnline(false))
  }, [])

  const analyze = async () => {
    setLoading(true); setError(''); setPlan(null)
    try { setAnalysis((await analyzeContract({ expected, actual })).data) }
    catch (e) { setError(e.response?.data?.detail || 'Analysis could not be completed.') }
    finally { setLoading(false) }
  }

  const remediate = async () => {
    setLoading(true); setError('')
    try { setPlan((await createRemediationPlan()).data) }
    catch {
      setError('Bob plan could not be prepared; no source files were changed.')
      setPlan({
        status: 'FAILED',
        affected_files: [],
        proposed_changes: [],
        tests: { status: 'FAILED', detail: 'Plan generation failed.' },
        verification: { status: 'FAILED', detail: 'No verification was run.' },
      })
    }
    finally { setLoading(false) }
  }

  const totalProposed = plan ? plan.proposed_changes.length : 0
  const shownProposed = plan ? plan.proposed_changes.slice(0, 5) : []

  return <main className="app-shell">
    <header>
      <div className="brand"><b>⌁</b> Contract<span>Guard</span></div>
      <small><i className={online ? 'online' : ''} /> Backend {online ? 'Connected' : 'Unavailable'}</small>
    </header>

    <section className="hero">
      <p className="eyebrow">API CONTRACT DRIFT DETECTOR</p>
      <h1>Catch breaking API changes before your consumers do.</h1>
      <p>Compare your source-of-truth OpenAPI contract with the implementation, trace consumer impact, and prepare a scoped remediation plan.</p>
    </section>

    <section className="panel selector">
      <label>Expected contract <select value={expected} onChange={e => setExpected(e.target.value)}>{contracts.expected.map(x => <option key={x.id} value={x.id}>{x.label}</option>)}</select></label>
      <b className="swap">⇄</b>
      <label>Actual contract <select value={actual} onChange={e => setActual(e.target.value)}>{contracts.actual.map(x => <option key={x.id} value={x.id}>{x.label}</option>)}</select></label>
      <button onClick={analyze} disabled={!online || loading}>{loading ? 'Analyzing…' : 'Analyze contract'}</button>
    </section>

    {error && <p className="error">{error}</p>}

    {!analysis && !loading && <section className="empty">⌘<h2>Ready to inspect a contract</h2><p>Select the specifications, then run an analysis.</p></section>}

    {analysis && <>
      <section className="summary">
        <Card t="Total changes" n={analysis.summary.total} />
        <Card t="Breaking" n={analysis.summary.breaking} c="red" />
        <Card t="Warnings" n={analysis.summary.warnings} c="amber" />
        <Card t="Non-breaking" n={analysis.summary.non_breaking} c="green" />
      </section>
      <section className="grid">
        <section className="panel results">
          <Title over="DETECTED DRIFT" title="Contract changes" count={`${analysis.changes.length} found`} />
          {analysis.changes.map((x, i) =>
            <article className="change" key={i}>
              <div><Badge tone={x.severity}>{x.severity}</Badge> <code>{label(x.change_type)}</code></div>
              <h3><Badge tone="method">{x.method}</Badge> <code>{x.endpoint}</code></h3>
              <p>{x.explanation}</p>
            </article>
          )}
        </section>
        <aside className="panel impact">
          <Title over="CONSUMER IMPACT" title="Affected code" count={`${analysis.impacts.length} references`} />
          {analysis.impacts.map((x, i) =>
            <article key={i}>
              <code>{x.file_path}</code>
              <small>Line {x.line_number} · {x.language.toUpperCase()}</small>
              <p><strong>{x.related_drift.method} {x.related_drift.endpoint}</strong> · {label(x.related_drift.change_type)}</p>
            </article>
          )}
          <button className="bob" onClick={remediate} disabled={loading}>✦ Prepare Bob remediation plan</button>
        </aside>
      </section>
    </>}

    {plan && <section className="panel remediation">
      <Title over="BOB REMEDIATION" title="Scoped work plan" count={<State value={plan.status} />} />
      <p className="remediation-note">
        ⚠ This is a <strong>proposed plan only</strong>. Python has generated the scoped work order;
        Bob (the agent) has <strong>not yet executed any file edits</strong>.
        Apply the plan with a Bob agent session to advance from <em>PROPOSED</em> to <em>RESOLVED</em>.
      </p>
      <div className="rem-grid">
        <div>
          <h3>Affected files</h3>
          {plan.affected_files.map(x => <code className="file" key={x}>{x}</code>)}
        </div>
        <div>
          <h3>Proposed changes {totalProposed > 5 && <Badge>{totalProposed} total</Badge>}</h3>
          {shownProposed.map((x, i) =>
            <article className="proposal" key={i}>
              <code>{x.file_path}:{x.line_number}</code>
              <p>{x.proposed_change}</p>
            </article>
          )}
          {totalProposed > 5 && <p className="more-hint">…and {totalProposed - 5} more action{totalProposed - 5 !== 1 ? 's' : ''} in the full plan</p>}
        </div>
        <div>
          <h3>Verification</h3>
          <p><State value={plan.tests.status} /> {plan.tests.detail}</p>
          <p><State value={plan.verification.status} /> {plan.verification.detail}</p>
          <p className="key">
            <Badge tone="success">RESOLVED</Badge> all references removed &amp; tests pass<br />
            <Badge tone="pending">NOT RUN</Badge> awaiting Bob execution<br />
            <Badge tone="danger">FAILED</Badge> requires attention
          </p>
        </div>
      </div>
    </section>}
  </main>
}
