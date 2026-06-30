import { useState, useCallback, useEffect } from 'react'
import './App.css'

const API = import.meta.env.VITE_API_URL ?? ''

const PIRADS_OPTIONS = [
  { value: 1, label: '1 — Very low' },
  { value: 2, label: '2 — Low' },
  { value: 3, label: '3 — Intermediate' },
  { value: 4, label: '4 — High' },
  { value: 5, label: '5 — Very high' },
]

function newRow(id) {
  return { id, psa: '', pirads: '', volume: '', result: null, error: null, loading: false }
}

let nextId = 2

function riskClass(prob) {
  if (prob < 0.20) return 'risk-low'
  if (prob < 0.30) return 'risk-below'
  if (prob < 0.45) return 'risk-mid'
  return 'risk-high'
}

function riskLabel(prob) {
  if (prob < 0.20) return 'Low'
  if (prob < 0.30) return 'Below avg'
  if (prob < 0.45) return 'Intermediate'
  return 'Elevated'
}

async function runPredict(row) {
  const psa = parseFloat(row.psa)
  const pirads = parseInt(row.pirads)
  if (!psa || psa <= 0 || !pirads) throw new Error('Missing PSA or PI-RADS')
  const body = { psa, pirads }
  const vol = parseFloat(row.volume)
  if (vol > 0) body.prostate_volume = vol
  const res = await fetch(`${API}/predict`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`Server error ${res.status}`)
  return res.json()
}

function exportCSV(rows) {
  const done = rows.filter(r => r.result)
  if (!done.length) return
  const header = 'Patient,PSA,PI-RADS,Volume,PSAD,P(GG>=2)%,Risk,Model'
  const lines = done.map((r, i) => [
    `P${String(i + 1).padStart(3, '0')}`,
    r.psa, r.pirads, r.volume || '',
    r.result.psad ?? '',
    r.result.percent.toFixed(1),
    riskLabel(r.result.prob),
    r.result.model_version,
  ].join(','))
  const blob = new Blob([[header, ...lines].join('\n')], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'biopsy-predictions.csv'
  a.click()
}

// ── Info Modal ───────────────────────────────────────────────
function InfoModal({ onClose }) {
  useEffect(() => {
    const handler = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="About this model">
        <div className="modal-header">
          <h2>About This Model</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="modal-body">

          <section className="info-section">
            <h3>What does this predict?</h3>
            <p>
              This tool estimates the probability of clinically significant prostate cancer —
              defined as Grade Group ≥2 (Gleason ≥3+4) — on prostate biopsy. It is intended
              to support shared decision-making between clinician and patient, not to replace it.
            </p>
          </section>

          <section className="info-section">
            <h3>How predictions are made</h3>
            <p>A logistic regression model combines three inputs:</p>
            <div className="info-table">
              <div className="info-row"><span className="info-key">log(PSA)</span><span className="info-val">Serum PSA in ng/mL, log-transformed</span></div>
              <div className="info-row"><span className="info-key">PI-RADS</span><span className="info-val">mpMRI score 1–5 (reference: 1–2)</span></div>
              <div className="info-row"><span className="info-key">PSAD</span><span className="info-val">PSA density = PSA ÷ prostate volume (v3 only)</span></div>
            </div>
            <p className="info-formula">
              logit(GG≥2) = −1.49 + 0.15·log(PSA) + 0.94·PSAD − 1.18·[PI-RADS 3] + 0.47·[PI-RADS 4] + 0.74·[PI-RADS 5]
            </p>
            <p>
              When prostate volume is not entered, the v2 model (PSA + PI-RADS only, AUC 0.670) is used automatically as a fallback.
            </p>
          </section>

          <section className="info-section">
            <h3>Performance</h3>
            <div className="info-table">
              <div className="info-row"><span className="info-key">Training cohort</span><span className="info-val">N=120, Mount Sinai biopsy registry</span></div>
              <div className="info-row"><span className="info-key">GG≥2 prevalence</span><span className="info-val">29.2%</span></div>
              <div className="info-row"><span className="info-key">AUC (OOF)</span><span className="info-val">0.703 (5-fold CV × 100 repeats)</span></div>
              <div className="info-row"><span className="info-key">Decision threshold</span><span className="info-val">0.30 (OOF-optimal)</span></div>
              <div className="info-row"><span className="info-key">Sensitivity @ 0.30</span><span className="info-val">~94% — catches most GG≥2 cancers</span></div>
              <div className="info-row"><span className="info-key">High-grade missed</span><span className="info-val">0 GG3+ cancers missed at threshold 0.30</span></div>
            </div>
            <p className="info-note">
              ⚠ Performance is out-of-fold on the training cohort. Independent prospective
              validation (ePSA-VALIDATE) is underway. Results should be interpreted accordingly.
            </p>
          </section>

          <section className="info-section">
            <h3>Interpreting the result</h3>
            <div className="info-table">
              <div className="info-row risk-low"><span className="info-key">Low (&lt;20%)</span><span className="info-val">Below population baseline — biopsy deferral may be appropriate</span></div>
              <div className="info-row risk-below"><span className="info-key">Below avg (20–30%)</span><span className="info-val">Approaching threshold — discuss with patient</span></div>
              <div className="info-row risk-mid"><span className="info-key">Intermediate (30–45%)</span><span className="info-val">Above threshold — biopsy recommended</span></div>
              <div className="info-row risk-high"><span className="info-key">Elevated (≥45%)</span><span className="info-val">High probability — biopsy strongly recommended</span></div>
            </div>
          </section>

          <section className="info-section">
            <h3>Sources</h3>
            <ol className="info-sources">
              <li>AUA/SUO Early Detection of Prostate Cancer Guidelines 2026. <em>J Urol.</em> 2026.</li>
              <li>Tewari A, et al. "Factors predicting the need for biopsy in patients with PSA levels ≤4.0 ng/ml." <em>J Urol.</em> 1998;159(5):1529–34.</li>
              <li>ePSA Model v3 — Mount Sinai Urology, retrained 2026-06-30.</li>
            </ol>
          </section>

        </div>
      </div>
    </div>
  )
}

// ── Summary ──────────────────────────────────────────────────
function Summary({ rows }) {
  const done = rows.filter(r => r.result)
  if (done.length === 0) return null
  const probs = done.map(r => r.result.prob)
  const avg = probs.reduce((a, b) => a + b, 0) / probs.length
  const positive = done.filter(r => r.result.prob >= 0.30).length
  const buckets = [
    { label: 'Low (<20%)',           cls: 'risk-low',   count: done.filter(r => r.result.prob < 0.20).length },
    { label: 'Below avg (20–30%)',   cls: 'risk-below', count: done.filter(r => r.result.prob >= 0.20 && r.result.prob < 0.30).length },
    { label: 'Intermediate (30–45%)',cls: 'risk-mid',   count: done.filter(r => r.result.prob >= 0.30 && r.result.prob < 0.45).length },
    { label: 'Elevated (≥45%)',      cls: 'risk-high',  count: done.filter(r => r.result.prob >= 0.45).length },
  ]
  return (
    <div className="summary">
      <h2>Summary — {done.length} patient{done.length !== 1 ? 's' : ''}</h2>
      <div className="summary-stats">
        <div className="stat">
          <span className="stat-val">{(avg * 100).toFixed(1)}%</span>
          <span className="stat-key">Mean P(GG≥2)</span>
        </div>
        <div className="stat">
          <span className="stat-val">{positive}/{done.length}</span>
          <span className="stat-key">Above threshold (≥30%)</span>
        </div>
      </div>
      <div className="buckets">
        {buckets.map(b => (
          <div key={b.label} className={`bucket ${b.cls}`}>
            <span className="bucket-count">{b.count}</span>
            <span className="bucket-label">{b.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Patient row (mobile card view) ───────────────────────────
function PatientCard({ row, index, onUpdate, onRun, onRemove }) {
  const update = patch => onUpdate(row.id, { ...patch, result: null, error: null })
  return (
    <div className={`patient-card ${row.result ? riskClass(row.result.prob) + '-card' : ''}`}>
      <div className="card-top">
        <span className="card-num">Patient {index + 1}</span>
        <div className="card-actions">
          <button className="btn-run" onClick={() => onRun(row.id)} disabled={row.loading || !row.psa || !row.pirads}>▶</button>
          <button className="btn-remove" onClick={() => onRemove(row.id)} disabled={false}>×</button>
        </div>
      </div>
      <div className="card-fields">
        <div className="card-field">
          <label>PSA (ng/mL)</label>
          <input type="number" min="0.1" step="0.1" placeholder="e.g. 5.2" value={row.psa} onChange={e => update({ psa: e.target.value })} />
        </div>
        <div className="card-field">
          <label>PI-RADS</label>
          <select value={row.pirads} onChange={e => update({ pirads: e.target.value })}>
            <option value="">—</option>
            {PIRADS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.value}</option>)}
          </select>
        </div>
        <div className="card-field">
          <label>Volume (mL)</label>
          <input type="number" min="1" step="1" placeholder="optional" value={row.volume} onChange={e => update({ volume: e.target.value })} />
        </div>
      </div>
      {row.loading && <div className="card-result"><span className="spinner" /></div>}
      {row.error && <div className="card-result"><span className="err-cell" title={row.error}>!</span> <span className="err-text">{row.error}</span></div>}
      {row.result && (
        <div className="card-result">
          <span className={`pct-badge ${riskClass(row.result.prob)}`}>{row.result.percent.toFixed(1)}%</span>
          <span className={`risk-tag ${riskClass(row.result.prob)}`}>{riskLabel(row.result.prob)}</span>
          {row.result.psad != null && <span className="card-detail">PSAD {row.result.psad.toFixed(3)}</span>}
          <span className="card-detail">{row.result.guideline_rate} guideline</span>
        </div>
      )}
    </div>
  )
}

// ── Main App ─────────────────────────────────────────────────
export default function App() {
  const [rows, setRows] = useState([newRow(1)])
  const [showInfo, setShowInfo] = useState(false)
  const [theme, setTheme] = useState(() => {
    const saved = localStorage.getItem('theme')
    if (saved) return saved
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  })

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
  }, [theme])

  const update = useCallback((id, patch) => {
    setRows(rs => rs.map(r => r.id === id ? { ...r, ...patch } : r))
  }, [])

  function addRow() { setRows(rs => [...rs, newRow(nextId++)]) }
  function removeRow(id) { setRows(rs => rs.length > 1 ? rs.filter(r => r.id !== id) : rs) }
  function clearAll() { setRows([newRow(nextId++)]) }

  async function runOne(id) {
    const row = rows.find(r => r.id === id)
    update(id, { loading: true, error: null, result: null })
    try {
      update(id, { result: await runPredict(row), loading: false })
    } catch (e) {
      update(id, { error: e.message, loading: false })
    }
  }

  async function runAll() {
    const eligible = rows.filter(r => r.psa && r.pirads)
    eligible.forEach(r => update(r.id, { loading: true, error: null, result: null }))
    await Promise.all(eligible.map(async r => {
      try { update(r.id, { result: await runPredict(r), loading: false }) }
      catch (e) { update(r.id, { error: e.message, loading: false }) }
    }))
  }

  const anyLoading = rows.some(r => r.loading)
  const anyResults = rows.some(r => r.result)

  return (
    <>
      <div className="page">
        <header className="app-header">
          <div className="header-title">
            <h1>ePSA Biopsy Prediction</h1>
            <div className="header-badges">
              <span className="badge badge-purple">Model v3</span>
              <span className="badge badge-green">AUC 0.703</span>
              <span className="badge badge-gray">Threshold 0.30</span>
            </div>
          </div>
          <div className="header-actions">
            <button className="btn-icon" onClick={() => setShowInfo(true)} aria-label="About this model" title="About this model">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
              </svg>
            </button>
            <button className="btn-icon" onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')} aria-label="Toggle theme" title="Toggle light/dark mode">
              {theme === 'dark'
                ? <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
                : <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
              }
            </button>
            {anyResults && <button className="btn-secondary" onClick={() => exportCSV(rows)}>Export CSV</button>}
            <button className="btn-secondary" onClick={clearAll}>Clear</button>
            <button className="btn-primary" onClick={runAll} disabled={anyLoading}>
              {anyLoading ? 'Running…' : `Run all (${rows.length})`}
            </button>
          </div>
        </header>

        {/* Desktop table */}
        <div className="table-wrap desktop-only">
          <table className="patient-table">
            <thead>
              <tr>
                <th>#</th>
                <th>PSA (ng/mL)</th>
                <th>PI-RADS</th>
                <th>Volume (mL)</th>
                <th>PSAD</th>
                <th>P(GG≥2)</th>
                <th>Risk</th>
                <th>Guideline rate</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={row.id} className={row.result ? riskClass(row.result.prob) + '-row' : ''}>
                  <td className="row-num">{i + 1}</td>
                  <td>
                    <input type="number" min="0.1" step="0.1" placeholder="e.g. 5.2" value={row.psa}
                      onChange={e => update(row.id, { psa: e.target.value, result: null, error: null })} />
                  </td>
                  <td>
                    <select value={row.pirads} onChange={e => update(row.id, { pirads: e.target.value, result: null, error: null })}>
                      <option value="">—</option>
                      {PIRADS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.value}</option>)}
                    </select>
                  </td>
                  <td>
                    <input type="number" min="1" step="1" placeholder="optional" value={row.volume}
                      onChange={e => update(row.id, { volume: e.target.value, result: null, error: null })} />
                  </td>
                  <td className="result-cell">
                    {row.result?.psad != null ? row.result.psad.toFixed(3) : <span className="muted">—</span>}
                  </td>
                  <td className="result-cell">
                    {row.loading && <span className="spinner" />}
                    {row.result && <span className={`pct-badge ${riskClass(row.result.prob)}`}>{row.result.percent.toFixed(1)}%</span>}
                    {row.error && <span className="err-cell" title={row.error}>!</span>}
                    {!row.result && !row.loading && !row.error && <span className="muted">—</span>}
                  </td>
                  <td className="result-cell">
                    {row.result ? <span className={`risk-tag ${riskClass(row.result.prob)}`}>{riskLabel(row.result.prob)}</span> : <span className="muted">—</span>}
                  </td>
                  <td className="result-cell">
                    {row.result ? <span className="guideline">{row.result.guideline_rate}</span> : <span className="muted">—</span>}
                  </td>
                  <td className="actions-cell">
                    <button className="btn-run" onClick={() => runOne(row.id)} disabled={row.loading || !row.psa || !row.pirads}>▶</button>
                    <button className="btn-remove" onClick={() => removeRow(row.id)} disabled={rows.length === 1}>×</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className="btn-add" onClick={addRow}>+ Add patient</button>
        </div>

        {/* Mobile cards */}
        <div className="mobile-only">
          {rows.map((row, i) => (
            <PatientCard key={row.id} row={row} index={i}
              onUpdate={update} onRun={runOne} onRemove={removeRow} />
          ))}
          <button className="btn-add-mobile" onClick={addRow}>+ Add patient</button>
        </div>

        <Summary rows={rows} />

        <p className="disclaimer">
          For clinical decision support only · Not a replacement for physician judgment ·{' '}
          <button className="link-btn" onClick={() => setShowInfo(true)}>About this model</button>
        </p>
      </div>

      {showInfo && <InfoModal onClose={() => setShowInfo(false)} />}
    </>
  )
}
