import { useState, useEffect, useRef } from 'react'
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
          <button aria-pressed={view !== 'clinician'} className={view !== 'clinician' ? 'active' : ''} onClick={() => setView('welcome')}>Patient</button>
          <button aria-pressed={view === 'clinician'} className={view === 'clinician' ? 'active' : ''} onClick={() => setView('clinician')}>Clinician</button>
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
  const headingRef = useRef(null)
  useEffect(() => { headingRef.current?.focus() }, [step])
  const set = (k) => (e) => setValues({ ...values, [k]: e.target.value })
  const psaOk = parseFloat(values.psa) > 0
  const volOk = values.volume === '' || parseFloat(values.volume) > 0

  const steps = [
    {
      title: 'What was your most recent PSA?',
      help: 'This is on your blood test results, in ng/mL. For example: 5.4',
      ok: psaOk,
      field: (
        <label className="eb-field" htmlFor="patient-psa">
          <span>PSA (ng/mL)</span>
          <input type="number" inputMode="decimal" min="0.1" step="0.1" id="patient-psa" aria-describedby="step-help" value={values.psa} onChange={set('psa')} placeholder="e.g. 5.4" />
        </label>
      ),
    },
    {
      title: 'What was your MRI PI-RADS score?',
      help: 'Your MRI report gives a PI-RADS score from 1 to 5. If there were several spots, use the highest one.',
      ok: !!values.pirads,
      field: (
        <fieldset className="eb-choices" aria-describedby="step-help">
          <legend className="eb-sr-only">PI-RADS score</legend>
          {PIRADS.map((o) => (
            <label key={o.value} className={`eb-choice ${String(values.pirads) === String(o.value) ? 'selected' : ''}`}>
              <input type="radio" name="patient-pirads" value={o.value}
                checked={String(values.pirads) === String(o.value)} onChange={set('pirads')} />
              <span><strong>{o.label}</strong><span>{o.plain}</span></span>
            </label>
          ))}
        </fieldset>
      ),
    },
    {
      title: 'What is your prostate volume?',
      help: 'Usually listed on the MRI report as "prostate volume" or "gland volume", in mL or cc (they are the same). Leave blank if you don\'t know it.',
      ok: volOk,
      field: (
        <label className="eb-field" htmlFor="patient-volume">
          <span>Prostate volume (mL) — optional</span>
          <input type="number" inputMode="decimal" min="1" step="1" id="patient-volume" aria-describedby="step-help" value={values.volume} onChange={set('volume')} placeholder="e.g. 45" />
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
      <p className="eb-eyebrow">Patient mode · Step {step + 1} of {steps.length}</p>
      <h1 ref={headingRef} tabIndex={-1}>{s.title}</h1>
      <p className="eb-help" id="step-help">{s.help}</p>
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
  const r = score(values)
  if (!r) return null
  const text = TIER_TEXT[r.tier.key]
  const outOf100 = Math.round(r.percent)

  return (
    <section className={`eb-card eb-result tier-${r.tier.key}`}>
      <p className="eb-eyebrow">Your e-Biopsy result</p>
      <h1>Your estimated risk</h1>
      <p className="eb-risk-value">{r.percent.toFixed(1)}<span>%</span></p>
      <p className="eb-risk-label">Chance of Grade Group 2 or higher prostate cancer</p>
      <span className="eb-pill">{r.tier.label}</span>
      <p className="eb-threshold">
        {r.percent >= BIOPSY_THRESHOLD * 100 ? 'At or above' : 'Below'} the model’s {(BIOPSY_THRESHOLD * 100).toFixed(0)}% biopsy decision threshold.
        <span> This reference point helps guide a discussion; it does not decide whether you need a biopsy.</span>
      </p>
      <div className="eb-meter" aria-hidden="true">
        <div className="eb-meter-fill" style={{ width: `${Math.min(r.percent, 100)}%` }} />
        <div className="eb-meter-mark" style={{ left: `${BIOPSY_THRESHOLD * 100}%` }} title="Biopsy threshold" />
      </div>
      <div className="eb-meter-scale" aria-hidden="true"><span>0%</span><span>Marker: {(BIOPSY_THRESHOLD * 100).toFixed(0)}% threshold</span><span>100%</span></div>
      <h2>{text.headline}</h2>
      <p className="eb-big">About <strong>{outOf100} in 100</strong> men with results like yours have a prostate cancer that needs treatment (Grade Group 2 or higher).</p>
      <p>{text.body}</p>
      {!r.reliable && (
        <p className="eb-note">With a PI-RADS score of {values.pirads}, this estimate is less certain. Your urologist may also look at other tests.</p>
      )}

      <details className="eb-disclosure">
        <summary>Clinical detail for your doctor</summary>
        <dl className="eb-detail">
          <dt>P(GG≥2)</dt><dd>{r.percent.toFixed(1)}%</dd>
          <dt>Tier</dt><dd>{r.tier.label}</dd>
          <dt>Interpretation</dt><dd>{r.interpretation}</dd>
          <dt>PI-RADS {values.pirads} population rate</dt><dd>{r.guidelineRate} (AUA/SUO 2026)</dd>
          {r.psad != null && (<><dt>PSA density</dt><dd>{r.psad.toFixed(3)} — {r.psadTier}</dd></>)}
          <dt>Model</dt><dd>{r.modelVersion} · threshold {BIOPSY_THRESHOLD} · engine {ENGINE_VERSION}</dd>
        </dl>
      </details>

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
      <p className="eb-eyebrow">Clinician mode · GG≥2 risk assessment</p>
      <h1>Biopsy risk workspace</h1>
      <p className="eb-help">Results update as you type. Enter PSA and PI-RADS; prostate volume is optional. Nothing is stored; CSV files are generated in your browser.</p>
      <div className="eb-patients">
        {scored.map((r, i) => (
          <article className="eb-patient" key={r.id} aria-labelledby={`patient-${r.id}`}>
            <div className="eb-patient-heading">
              <h2 id={`patient-${r.id}`}>Patient {i + 1}</h2>
              <button className="eb-icon" disabled={rows.length === 1} aria-label={`Remove patient ${i + 1}`}
                onClick={() => setRows((rs) => rs.filter((x) => x.id !== r.id))}>×</button>
            </div>
            <div className="eb-patient-layout">
              <div className={`eb-clin-result tier-${r.result?.tier.key ?? 'pending'}`} role="status" aria-atomic="true">
                <p className="eb-risk-label">Estimated P(GG≥2)</p>
                {r.result ? (
                  <>
                    <p className="eb-risk-value">{r.result.percent.toFixed(1)}<span>%</span></p>
                    <span className="eb-pill">{r.result.tier.label}</span>
                    <p className="eb-threshold">{r.result.percent >= BIOPSY_THRESHOLD * 100 ? 'At or above' : 'Below'} {(BIOPSY_THRESHOLD * 100).toFixed(0)}% decision threshold</p>
                    <span className="eb-muted">{r.result.psad != null && `PSAD ${r.result.psad.toFixed(3)} · `}{r.result.modelVersion}</span>
                    {!r.result.reliable && <p className="eb-warn">PI-RADS 1–3: lower reliability</p>}
                  </>
                ) : <p className="eb-empty">Enter PSA and PI-RADS to see the risk estimate.</p>}
              </div>
              <fieldset className="eb-clin-fields">
                <legend>Clinical inputs · Patient {i + 1}</legend>
                <label className="eb-field" htmlFor={`psa-${r.id}`}>PSA (ng/mL)
                  <input id={`psa-${r.id}`} type="number" min="0.1" step="0.1" inputMode="decimal" placeholder="e.g. 5.2" value={r.psa} onChange={(e) => edit(r.id, 'psa', e.target.value)} />
                </label>
                <label className="eb-field" htmlFor={`pirads-${r.id}`}>MRI PI-RADS
                  <select id={`pirads-${r.id}`} value={r.pirads} onChange={(e) => edit(r.id, 'pirads', e.target.value)}>
                    <option value="">Select score</option>
                    {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
                </label>
                <label className="eb-field" htmlFor={`volume-${r.id}`}>Prostate volume (mL) · optional
                  <input id={`volume-${r.id}`} type="number" min="1" step="1" inputMode="decimal" placeholder="e.g. 45" value={r.volume} onChange={(e) => edit(r.id, 'volume', e.target.value)} />
                </label>
              </fieldset>
            </div>
          </article>
        ))}
      </div>
      <div className="eb-nav eb-nav-left">
        <button className="eb-btn" onClick={() => setRows((rs) => [...rs, newRow()])}>+ Add patient</button>
        <button className="eb-btn" onClick={exportCsv} disabled={!scored.some((r) => r.result)}>Export CSV</button>
      </div>
      <details className="eb-disclosure" open>
        <summary>Model performance &amp; cohort</summary>
      <p className="eb-fine">ePSA biopsy model {scored.find((r) => r.result)?.result.modelVersion ?? 'v4'}: logistic regression on log(PSA), log(volume) and PI-RADS, N=126 Mount Sinai biopsies, OOF AUC 0.74 (95% CI 0.65–0.83). Decision threshold {BIOPSY_THRESHOLD}. Not externally validated.</p>
      </details>
    </section>
  )
}

function Limitations() {
  return (
    <aside className="eb-limitations" aria-label="Important model limitations">
      <details className="eb-disclosure">
        <summary>For clinical decision support only · Read model limitations</summary>
        <div className="eb-disclosure-body">
          <p>This estimate supports a conversation with your clinician. It is not a diagnosis and does not replace medical advice.</p>
          <p>The model was developed using a training cohort of 126 Mount Sinai biopsies. Reported performance comes from that cohort, not independent validation. The model has not been externally validated.</p>
          <p>Your clinician should interpret the result alongside your medical history, MRI findings, and other tests.</p>
        </div>
      </details>
    </aside>
  )
}

// ── App ──────────────────────────────────────────────────────
const EMPTY = { psa: '', pirads: '', volume: '' }

export default function App() {
  const [view, setView] = useState('welcome')
  const [values, setValues] = useState(EMPTY)
  const mainRef = useRef(null)
  useEffect(() => {
    window.scrollTo(0, 0)
    mainRef.current?.focus({ preventScroll: true })
  }, [view])

  return (
    <div className={`eb-app eb-mode-${view === 'clinician' ? 'clinician' : 'patient'}`}>
      <a className="eb-skip" href="#main-content">Skip to content</a>
      <Header view={view} setView={setView} />
      <main className="eb-main" id="main-content" ref={mainRef} tabIndex={-1}>
        {view === 'welcome' && <Welcome onStart={() => setView('form')} />}
        {view === 'form' && <Questionnaire values={values} setValues={setValues} onBack={() => setView('welcome')} onDone={() => setView('result')} />}
        {view === 'result' && <Result values={values} onRestart={() => { setValues(EMPTY); setView('welcome') }} />}
        {view === 'clinician' && <Clinician />}
        <Limitations />
      </main>
      <footer className="eb-footer">
        e-Biopsy supports shared decision-making between you and your clinician. It is not a diagnosis and does not replace medical advice.
        <br />© Icahn School of Medicine at Mount Sinai · Department of Urology
      </footer>
    </div>
  )
}
