import { useState, useEffect } from 'react'
import { predictBiopsyRisk, BIOPSY_THRESHOLD, ENGINE_VERSION } from '@urology-ai/epsa-engine'
import './App.css'

// e-Biopsy — the ePSA companion for men deciding whether to have a prostate
// biopsy. Scoring runs entirely in the browser through @urology-ai/epsa-engine
// (the same predictBiopsyRisk ePSA uses), so every surface gives the same
// answer for the same patient and nothing entered here leaves the device.

const PIRADS = [
  { value: 1, label: 'PI-RADS 1', plain: 'Very unlikely to be significant cancer' },
  { value: 2, label: 'PI-RADS 2', plain: 'Unlikely to be significant cancer' },
  { value: 3, label: 'PI-RADS 3', plain: 'Uncertain — could go either way' },
  { value: 4, label: 'PI-RADS 4', plain: 'Significant cancer is likely' },
  { value: 5, label: 'PI-RADS 5', plain: 'Significant cancer is very likely' },
]

const TIER_TEXT = {
  biopsy_not_indicated: {
    headline: 'Your estimated risk is low',
    body: 'Based on your PSA and MRI, a biopsy may not be needed right now. Many men in this range choose to keep checking their PSA instead. Talk this through with your urologist.',
  },
  monitoring_advised: {
    headline: 'Your estimated risk is below average',
    body: 'Your risk is on the lower side. Some men in this range have a biopsy and some choose close monitoring. Your urologist can help you decide what fits you.',
  },
  biopsy_discussion_advised: {
    headline: 'A biopsy is worth discussing',
    body: 'Your risk is high enough that most guidelines would suggest a biopsy. Ask your urologist what a biopsy involves and what the alternatives are.',
  },
  biopsy_recommended: {
    headline: 'A biopsy is recommended',
    body: 'Your PSA and MRI point to a meaningful chance of cancer that needs treatment. A biopsy is the way to find out for sure. Please follow up with your urologist.',
  },
}

function score({ psa, pirads, volume }) {
  const p = parseFloat(psa)
  const r = parseInt(pirads, 10)
  const v = parseFloat(volume)
  if (!(p > 0) || !(r >= 1 && r <= 5)) return null
  const hasVol = v > 0
  return predictBiopsyRisk(r, p, hasVol ? v : null, hasVol ? p / v : null)
}

// ── Header ───────────────────────────────────────────────────
function Header({ view, setView }) {
  return (
    <header className="eb-header">
      <div className="eb-header-inner">
        <button className="eb-brand" onClick={() => setView('welcome')}>
          <span className="eb-logo" aria-hidden="true">e</span>
          <span>
            <span className="eb-brand-name">e-Biopsy</span>
            <span className="eb-brand-sub">Mount Sinai · Tewari Lab</span>
          </span>
        </button>
        <nav className="eb-tabs" aria-label="Mode">
          <button className={view !== 'clinician' ? 'active' : ''} onClick={() => setView('welcome')}>Patient</button>
          <button className={view === 'clinician' ? 'active' : ''} onClick={() => setView('clinician')}>Clinician</button>
        </nav>
      </div>
      <div className="eb-accent" />
    </header>
  )
}

// ── Welcome ──────────────────────────────────────────────────
function Welcome({ onStart }) {
  return (
    <section className="eb-card eb-hero">
      <div className="eb-hero-head">
        <p className="eb-eyebrow">The next step after ePSA</p>
        <h1>Should I have a prostate biopsy?</h1>
        <p>If your PSA was raised and you've had an MRI, e-Biopsy estimates your chance of a prostate cancer that needs treatment. Use it to prepare for the conversation with your urologist. It doesn't make the decision for you.</p>
      </div>
      <div className="eb-hero-body">
        <ul className="eb-need">
          <li><strong>Your latest PSA</strong> (ng/mL), from your blood test</li>
          <li><strong>Your PI-RADS score</strong> (1–5), from your MRI report</li>
          <li><strong>Prostate volume</strong> (mL), also on the MRI report. This is optional but makes the estimate more accurate.</li>
        </ul>
        <button className="eb-btn eb-btn-primary" onClick={onStart}>Start</button>
        <p className="eb-fine">Takes about a minute. Nothing you enter is stored or sent anywhere.</p>
      </div>
    </section>
  )
}

// ── Patient questionnaire ────────────────────────────────────
function Questionnaire({ values, setValues, onDone, onBack }) {
  const [step, setStep] = useState(0)
  const set = (k) => (e) => setValues({ ...values, [k]: e.target.value })
  const psaOk = parseFloat(values.psa) > 0
  const volOk = values.volume === '' || parseFloat(values.volume) > 0

  const steps = [
    {
      title: 'What was your most recent PSA?',
      help: 'This is on your blood test results, in ng/mL. For example: 5.4',
      ok: psaOk,
      field: (
        <label className="eb-field">
          <span>PSA (ng/mL)</span>
          <input type="number" inputMode="decimal" min="0.1" step="0.1" autoFocus value={values.psa} onChange={set('psa')} placeholder="e.g. 5.4" />
        </label>
      ),
    },
    {
      title: 'What was your MRI PI-RADS score?',
      help: 'Your MRI report gives a PI-RADS score from 1 to 5. If there were several spots, use the highest one.',
      ok: !!values.pirads,
      field: (
        <div className="eb-choices" role="radiogroup" aria-label="PI-RADS score">
          {PIRADS.map((o) => (
            <button key={o.value} role="radio" aria-checked={String(values.pirads) === String(o.value)}
              className={`eb-choice ${String(values.pirads) === String(o.value) ? 'selected' : ''}`}
              onClick={() => setValues({ ...values, pirads: String(o.value) })}>
              <strong>{o.label}</strong><span>{o.plain}</span>
            </button>
          ))}
        </div>
      ),
    },
    {
      title: 'What is your prostate volume?',
      help: 'Usually listed on the MRI report as "prostate volume" or "gland volume", in mL or cc (they are the same). Leave blank if you don\'t know it.',
      ok: volOk,
      field: (
        <label className="eb-field">
          <span>Prostate volume (mL) — optional</span>
          <input type="number" inputMode="decimal" min="1" step="1" autoFocus value={values.volume} onChange={set('volume')} placeholder="e.g. 45" />
        </label>
      ),
    },
  ]
  const s = steps[step]
  const last = step === steps.length - 1

  return (
    <section className="eb-card eb-step">
      <div className="eb-progress" aria-label={`Step ${step + 1} of ${steps.length}`}>
        {steps.map((_, i) => <span key={i} className={i <= step ? 'on' : ''} />)}
      </div>
      <h2>{s.title}</h2>
      <p className="eb-help">{s.help}</p>
      {s.field}
      <div className="eb-nav">
        <button className="eb-btn" onClick={() => (step ? setStep(step - 1) : onBack())}>Back</button>
        <button className="eb-btn eb-btn-primary" disabled={!s.ok} onClick={() => (last ? onDone() : setStep(step + 1))}>
          {last ? 'See my result' : 'Next'}
        </button>
      </div>
    </section>
  )
}

// ── Patient result ───────────────────────────────────────────
function Result({ values, onRestart }) {
  const [detail, setDetail] = useState(false)
  const r = score(values)
  if (!r) return null
  const text = TIER_TEXT[r.tier.key]
  const outOf100 = Math.round(r.percent)

  return (
    <section className={`eb-card eb-result tier-${r.tier.key}`}>
      <p className="eb-eyebrow">Your e-Biopsy result</p>
      <h2>{text.headline}</h2>
      <div className="eb-meter" role="img" aria-label={`About ${outOf100} in 100`}>
        <div className="eb-meter-fill" style={{ width: `${Math.min(r.percent, 100)}%` }} />
        <div className="eb-meter-mark" style={{ left: `${BIOPSY_THRESHOLD * 100}%` }} title="Biopsy threshold" />
      </div>
      <p className="eb-big">About <strong>{outOf100} in 100</strong> men with results like yours have a prostate cancer that needs treatment (Grade Group 2 or higher).</p>
      <p>{text.body}</p>
      {!r.reliable && (
        <p className="eb-note">With a PI-RADS score of {values.pirads}, this estimate is less certain. Your urologist may also look at other tests.</p>
      )}

      <button className="eb-link" onClick={() => setDetail(!detail)} aria-expanded={detail}>
        {detail ? 'Hide clinical detail' : 'Show clinical detail (for your doctor)'}
      </button>
      {detail && (
        <dl className="eb-detail">
          <dt>P(GG≥2)</dt><dd>{r.percent.toFixed(1)}%</dd>
          <dt>Tier</dt><dd>{r.tier.label}</dd>
          <dt>Interpretation</dt><dd>{r.interpretation}</dd>
          <dt>PI-RADS {values.pirads} population rate</dt><dd>{r.guidelineRate} (AUA/SUO 2026)</dd>
          {r.psad != null && (<><dt>PSA density</dt><dd>{r.psad.toFixed(3)} — {r.psadTier}</dd></>)}
          <dt>Model</dt><dd>{r.modelVersion} · threshold {BIOPSY_THRESHOLD} · engine {ENGINE_VERSION}</dd>
        </dl>
      )}

      <div className="eb-nav">
        <button className="eb-btn" onClick={() => window.print()}>Print for my visit</button>
        <button className="eb-btn eb-btn-primary" onClick={onRestart}>Start over</button>
      </div>
    </section>
  )
}

// ── Clinician view (multi-patient) ───────────────────────────
let nextId = 1
const newRow = () => ({ id: nextId++, psa: '', pirads: '', volume: '' })

function Clinician() {
  const [rows, setRows] = useState(() => [newRow()])
  const edit = (id, k, v) => setRows((rs) => rs.map((r) => (r.id === id ? { ...r, [k]: v } : r)))
  const scored = rows.map((r) => ({ ...r, result: score(r) }))

  function exportCsv() {
    const done = scored.filter((r) => r.result)
    if (!done.length) return
    const header = 'Patient,PSA,PI-RADS,Volume (mL),PSAD,P(GG>=2) %,Tier,Model'
    const lines = done.map((r, i) => [
      `P${String(i + 1).padStart(3, '0')}`, r.psa, r.pirads, r.volume || '',
      r.result.psad != null ? r.result.psad.toFixed(3) : '',
      r.result.percent.toFixed(1), r.result.tier.label, `"${r.result.modelVersion}"`,
    ].join(','))
    const url = URL.createObjectURL(new Blob([[header, ...lines].join('\n')], { type: 'text/csv' }))
    const a = document.createElement('a')
    a.href = url
    a.download = 'e-biopsy-predictions.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <section className="eb-card eb-clin">
      <h2>Clinician view</h2>
      <p className="eb-help">GG≥2 risk for one or more patients. Results update as you type. Nothing is stored; the CSV is generated in your browser.</p>
      <div className="eb-table-wrap">
        <table className="eb-table">
          <thead>
            <tr><th>#</th><th>PSA (ng/mL)</th><th>PI-RADS</th><th>Volume (mL)</th><th>Result</th><th aria-label="Remove" /></tr>
          </thead>
          <tbody>
            {scored.map((r, i) => (
              <tr key={r.id}>
                <td className="eb-num">{i + 1}</td>
                <td><input type="number" min="0.1" step="0.1" inputMode="decimal" placeholder="5.2" aria-label={`PSA ${i + 1}`} value={r.psa} onChange={(e) => edit(r.id, 'psa', e.target.value)} /></td>
                <td>
                  <select aria-label={`PI-RADS ${i + 1}`} value={r.pirads} onChange={(e) => edit(r.id, 'pirads', e.target.value)}>
                    <option value="">—</option>
                    {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
                </td>
                <td><input type="number" min="1" step="1" inputMode="decimal" placeholder="optional" aria-label={`Volume ${i + 1}`} value={r.volume} onChange={(e) => edit(r.id, 'volume', e.target.value)} /></td>
                <td className="eb-res" aria-live="polite">
                  {r.result ? (
                    <>
                      <span className={`eb-pill tier-${r.result.tier.key}`}><strong>{r.result.percent.toFixed(1)}%</strong> {r.result.tier.label}</span>
                      <span className="eb-muted">{r.result.psad != null && `PSAD ${r.result.psad.toFixed(3)} · `}{r.result.modelVersion}</span>
                      {!r.result.reliable && <span className="eb-warn">PI-RADS 1–3: lower reliability</span>}
                    </>
                  ) : <span className="eb-muted">Enter PSA and PI-RADS</span>}
                </td>
                <td>
                  <button className="eb-icon" disabled={rows.length === 1} aria-label={`Remove patient ${i + 1}`}
                    onClick={() => setRows((rs) => rs.filter((x) => x.id !== r.id))}>×</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="eb-nav eb-nav-left">
        <button className="eb-btn" onClick={() => setRows((rs) => [...rs, newRow()])}>+ Add patient</button>
        <button className="eb-btn" onClick={exportCsv} disabled={!scored.some((r) => r.result)}>Export CSV</button>
      </div>
      <p className="eb-fine">ePSA biopsy model {scored.find((r) => r.result)?.result.modelVersion ?? 'v4'}: logistic regression on log(PSA), log(volume) and PI-RADS, N=126 Mount Sinai biopsies, OOF AUC 0.74 (95% CI 0.65–0.83). Decision threshold {BIOPSY_THRESHOLD}. Not externally validated.</p>
    </section>
  )
}

// ── App ──────────────────────────────────────────────────────
const EMPTY = { psa: '', pirads: '', volume: '' }

export default function App() {
  const [view, setView] = useState('welcome')
  const [values, setValues] = useState(EMPTY)
  useEffect(() => { window.scrollTo(0, 0) }, [view])

  return (
    <div className="eb-app">
      <Header view={view} setView={setView} />
      <main className="eb-main">
        {view === 'welcome' && <Welcome onStart={() => setView('form')} />}
        {view === 'form' && <Questionnaire values={values} setValues={setValues} onBack={() => setView('welcome')} onDone={() => setView('result')} />}
        {view === 'result' && <Result values={values} onRestart={() => { setValues(EMPTY); setView('welcome') }} />}
        {view === 'clinician' && <Clinician />}
      </main>
      <footer className="eb-footer">
        e-Biopsy supports shared decision-making between you and your clinician. It is not a diagnosis and does not replace medical advice.
        <br />© Icahn School of Medicine at Mount Sinai · Department of Urology
      </footer>
    </div>
  )
}
