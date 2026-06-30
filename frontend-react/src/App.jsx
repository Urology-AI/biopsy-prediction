import { useState, useCallback } from 'react'
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

function Summary({ rows }) {
  const done = rows.filter(r => r.result)
  if (done.length === 0) return null

  const probs = done.map(r => r.result.prob)
  const avg = probs.reduce((a, b) => a + b, 0) / probs.length
  const positive = done.filter(r => r.result.prob >= 0.30).length
  const buckets = [
    { label: 'Low (<20%)', count: done.filter(r => r.result.prob < 0.20).length, cls: 'risk-low' },
    { label: 'Below avg (20–30%)', count: done.filter(r => r.result.prob >= 0.20 && r.result.prob < 0.30).length, cls: 'risk-below' },
    { label: 'Intermediate (30–45%)', count: done.filter(r => r.result.prob >= 0.30 && r.result.prob < 0.45).length, cls: 'risk-mid' },
    { label: 'Elevated (≥45%)', count: done.filter(r => r.result.prob >= 0.45).length, cls: 'risk-high' },
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

function exportCSV(rows) {
  const done = rows.filter(r => r.result)
  if (!done.length) return
  const header = 'Patient,PSA,PI-RADS,Volume,PSAD,P(GG≥2)%,Risk,Model'
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

export default function App() {
  const [rows, setRows] = useState([newRow(1)])

  const update = useCallback((id, patch) => {
    setRows(rs => rs.map(r => r.id === id ? { ...r, ...patch } : r))
  }, [])

  function addRow() {
    setRows(rs => [...rs, newRow(nextId++)])
  }

  function removeRow(id) {
    setRows(rs => rs.length > 1 ? rs.filter(r => r.id !== id) : rs)
  }

  function clearAll() {
    setRows([newRow(nextId++)])
  }

  async function runOne(id) {
    const row = rows.find(r => r.id === id)
    update(id, { loading: true, error: null, result: null })
    try {
      const result = await runPredict(row)
      update(id, { result, loading: false })
    } catch (e) {
      update(id, { error: e.message, loading: false })
    }
  }

  async function runAll() {
    const eligible = rows.filter(r => r.psa && r.pirads)
    eligible.forEach(r => update(r.id, { loading: true, error: null, result: null }))
    await Promise.all(eligible.map(async r => {
      try {
        const result = await runPredict(r)
        update(r.id, { result, loading: false })
      } catch (e) {
        update(r.id, { error: e.message, loading: false })
      }
    }))
  }

  const anyLoading = rows.some(r => r.loading)
  const anyResults = rows.some(r => r.result)

  return (
    <div className="page">
      <header className="app-header">
        <div>
          <h1>ePSA Biopsy Prediction</h1>
          <p className="subtitle">GG≥2 prostate cancer risk · Model v3 · AUC 0.703 · Threshold 0.30</p>
        </div>
        <div className="header-actions">
          {anyResults && (
            <button className="btn-secondary" onClick={() => exportCSV(rows)}>Export CSV</button>
          )}
          <button className="btn-secondary" onClick={clearAll}>Clear all</button>
          <button className="btn-primary" onClick={runAll} disabled={anyLoading}>
            {anyLoading ? 'Running…' : `Run all (${rows.length})`}
          </button>
        </div>
      </header>

      <div className="table-wrap">
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
                  <input
                    type="number" min="0.1" step="0.1" placeholder="e.g. 5.2"
                    value={row.psa}
                    onChange={e => update(row.id, { psa: e.target.value, result: null, error: null })}
                  />
                </td>

                <td>
                  <select
                    value={row.pirads}
                    onChange={e => update(row.id, { pirads: e.target.value, result: null, error: null })}
                  >
                    <option value="">—</option>
                    {PIRADS_OPTIONS.map(o => (
                      <option key={o.value} value={o.value}>{o.value}</option>
                    ))}
                  </select>
                </td>

                <td>
                  <input
                    type="number" min="1" step="1" placeholder="optional"
                    value={row.volume}
                    onChange={e => update(row.id, { volume: e.target.value, result: null, error: null })}
                  />
                </td>

                <td className="result-cell">
                  {row.result?.psad != null ? row.result.psad.toFixed(3) : <span className="muted">—</span>}
                </td>

                <td className="result-cell">
                  {row.loading && <span className="spinner" />}
                  {row.result && (
                    <span className={`pct-badge ${riskClass(row.result.prob)}`}>
                      {row.result.percent.toFixed(1)}%
                    </span>
                  )}
                  {row.error && <span className="err-cell" title={row.error}>!</span>}
                  {!row.result && !row.loading && !row.error && <span className="muted">—</span>}
                </td>

                <td className="result-cell">
                  {row.result
                    ? <span className={`risk-tag ${riskClass(row.result.prob)}`}>{riskLabel(row.result.prob)}</span>
                    : <span className="muted">—</span>}
                </td>

                <td className="result-cell">
                  {row.result
                    ? <span className="guideline">{row.result.guideline_rate}</span>
                    : <span className="muted">—</span>}
                </td>

                <td className="actions-cell">
                  <button className="btn-run" onClick={() => runOne(row.id)} disabled={row.loading || !row.psa || !row.pirads} title="Run this patient">
                    ▶
                  </button>
                  <button className="btn-remove" onClick={() => removeRow(row.id)} title="Remove row" disabled={rows.length === 1}>
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <button className="btn-add" onClick={addRow}>+ Add patient</button>
      </div>

      <Summary rows={rows} />

      <p className="disclaimer">
        For clinical decision support only. Not a replacement for physician judgment.
        AUC 0.703 OOF · N=120 · threshold 0.30.
      </p>
    </div>
  )
}
