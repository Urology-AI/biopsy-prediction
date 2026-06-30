import { useState } from 'react'
import './App.css'

const PIRADS_LABELS = {
  1: '1 — Very low',
  2: '2 — Low',
  3: '3 — Intermediate',
  4: '4 — High',
  5: '5 — Very high',
}

function riskClass(prob) {
  if (prob < 0.20) return 'risk-low'
  if (prob < 0.30) return 'risk-below'
  if (prob < 0.45) return 'risk-mid'
  return 'risk-high'
}

function ResultCard({ data }) {
  const cls = riskClass(data.prob)
  const details = [
    ['Model', data.model_version],
    ['Decision threshold', `${(data.threshold * 100).toFixed(0)}%`],
    ['AUC (OOF)', '0.703'],
    ['Guideline GG≥2 rate', data.guideline_rate],
    ...(data.psad != null ? [['PSAD', `${data.psad.toFixed(3)} ng/mL²`]] : []),
    ...(data.psad_tier ? [['PSAD tier', data.psad_tier]] : []),
  ]

  return (
    <div className="result-card">
      <div className={`prob-display ${cls}`}>
        <span className="pct">{data.percent.toFixed(1)}%</span>
        <span className="prob-label">P(Grade Group ≥2)</span>
      </div>
      <p className="interpretation">{data.interpretation}</p>
      <dl className="details">
        {details.map(([k, v]) => (
          <div key={k} className="detail-row">
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

export default function App() {
  const [psa, setPsa] = useState('')
  const [pirads, setPirads] = useState('')
  const [volume, setVolume] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setResult(null)

    const psaVal = parseFloat(psa)
    const piradsVal = parseInt(pirads)

    if (!psaVal || psaVal <= 0) { setError('Enter a valid PSA value.'); return }
    if (!piradsVal) { setError('Select a PI-RADS score.'); return }

    const body = { psa: psaVal, pirads: piradsVal }
    const vol = parseFloat(volume)
    if (vol > 0) body.prostate_volume = vol

    setLoading(true)
    try {
      const res = await fetch('/predict', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) throw new Error(`Server error ${res.status}`)
      setResult(await res.json())
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page">
      <div className="card">
        <div className="card-header">
          <h1>ePSA Biopsy Prediction</h1>
          <p className="subtitle">GG≥2 prostate cancer risk · Model v3 · AUC 0.703</p>
        </div>

        <form onSubmit={handleSubmit} noValidate>
          <div className="field">
            <label htmlFor="psa">PSA (ng/mL)</label>
            <input
              id="psa"
              type="number"
              min="0.1"
              step="0.1"
              placeholder="e.g. 5.2"
              value={psa}
              onChange={e => setPsa(e.target.value)}
            />
          </div>

          <div className="field">
            <label htmlFor="pirads">PI-RADS Score</label>
            <select id="pirads" value={pirads} onChange={e => setPirads(e.target.value)}>
              <option value="">Select…</option>
              {[1, 2, 3, 4, 5].map(n => (
                <option key={n} value={n}>{PIRADS_LABELS[n]}</option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="volume">
              Prostate Volume (mL) <span className="optional">— optional</span>
            </label>
            <input
              id="volume"
              type="number"
              min="1"
              step="1"
              placeholder="e.g. 40"
              value={volume}
              onChange={e => setVolume(e.target.value)}
            />
            <p className="hint">Used to compute PSAD. Enables v3 model; omit for v2 fallback.</p>
          </div>

          <button type="submit" disabled={loading}>
            {loading ? 'Calculating…' : 'Calculate Risk'}
          </button>
        </form>

        {error && <p className="error">{error}</p>}
        {result && <ResultCard data={result} />}

        <p className="disclaimer">
          For clinical decision support only. Not a replacement for physician judgment.
        </p>
      </div>
    </div>
  )
}
