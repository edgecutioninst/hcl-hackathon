import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, fmtDate } from './api.jsx';

export const DOC_TYPES = ['PAN_CARD', 'AADHAAR_CARD', 'ELECTRICITY_BILL', 'BANK_STATEMENT', 'DRIVING_LICENCE'];
const OCCUPATIONS = ['SALARIED_PRIVATE', 'SALARIED_GOVT', 'PROFESSIONAL', 'STUDENT', 'HOMEMAKER', 'RETIRED', 'SELF_EMPLOYED', 'BUSINESS_OWNER', 'JEWELLER_BULLION_DEALER', 'MONEY_CHANGER', 'REAL_ESTATE_AGENT', 'CRYPTO_ASSET_TRADER'];
const guessType = (name) => {
  const n = name.toUpperCase();
  return n.includes('PAN') ? 'PAN_CARD' : n.includes('AADHAAR') ? 'AADHAAR_CARD' : n.includes('BILL') ? 'ELECTRICITY_BILL' : n.includes('STATEMENT') ? 'BANK_STATEMENT' : n.includes('LICENCE') || n.includes('DL') ? 'DRIVING_LICENCE' : '';
};



export function ApplicantHome() {
  const [apps, setApps] = useState(null);
  useEffect(() => { api('/applications/mine').then(setApps); }, []);
  return (
    <main>
      <h1>My applications</h1>
      <p><Link to="/applicant/new">Start a new application</Link></p>
      {!apps ? <p>Loading...</p> : !apps.length ? <p>No applications yet.</p> : (
        <table>
          <thead><tr><th>Application</th><th>Name</th><th>PAN</th><th>Date</th><th>Status</th></tr></thead>
          <tbody>{apps.map((a) => (
            <tr key={a.id}><td><Link to={`/applicant/${a.id}`}>{a.id}</Link></td><td>{a.fullName}</td><td>{a.panNumber}</td><td>{a.applicationDate}</td><td><span className={`badge s-${a.status}`}>{a.statusText}</span></td></tr>
          ))}</tbody>
        </table>
      )}
    </main>
  );
}

function Input({ name, label, errors, ...p }) {
  return (
    <label>{label}
      <input name={name} aria-invalid={!!errors[name]} aria-describedby={errors[name] ? `${name}-err` : undefined} {...p} />
      {errors[name] && <span id={`${name}-err`} className="error">{errors[name]}</span>}
    </label>
  );
}

export function ApplicationForm() {
  const nav = useNavigate();
  const [f, setF] = useState({ full_name: '', dob: '', gender: 'M', pan_number: '', aadhaar_last4: '', mobile: '', email: '', address: '', city: '', state: '', pincode: '', occupation_code: 'SALARIED_PRIVATE', annual_income: '', consent: false });
  const [errors, setErrors] = useState({});
  const [msg, setMsg] = useState('');
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : k === 'pan_number' ? e.target.value.toUpperCase() : e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    setErrors({}); setMsg('');
    try {
      const r = await api('/applications', { method: 'POST', body: { ...f, annual_income: Number(f.annual_income) } });
      nav(`/applicant/${r.id}`);
    } catch (x) { setErrors(x.errors); setMsg(x.message); }
  };
  const p = { errors };
  return (
    <main>
      <h1>New savings account application</h1>
      <form onSubmit={submit} className="card grid" noValidate>
        <Input {...p} name="full_name" label="Full name (as on PAN)" value={f.full_name} onChange={set('full_name')} required />
        <Input {...p} name="dob" label="Date of birth" type="date" value={f.dob} onChange={set('dob')} required />
        <label>Gender<select value={f.gender} onChange={set('gender')}><option value="M">Male</option><option value="F">Female</option><option value="O">Other</option></select></label>
        <Input {...p} name="pan_number" label="PAN" value={f.pan_number} onChange={set('pan_number')} placeholder="ABCDE1234F" maxLength={10} required />
        <Input {...p} name="aadhaar_last4" label="Aadhaar - last 4 digits only" value={f.aadhaar_last4} onChange={set('aadhaar_last4')} inputMode="numeric" placeholder="1234" required />
        <Input {...p} name="mobile" label="Mobile" value={f.mobile} onChange={set('mobile')} inputMode="numeric" maxLength={10} required />
        <Input {...p} name="email" label="Email" type="email" value={f.email} onChange={set('email')} required />
        <Input {...p} name="address" label="Address" value={f.address} onChange={set('address')} required />
        <Input {...p} name="city" label="City" value={f.city} onChange={set('city')} required />
        <Input {...p} name="state" label="State" value={f.state} onChange={set('state')} required />
        <Input {...p} name="pincode" label="Pincode" value={f.pincode} onChange={set('pincode')} inputMode="numeric" maxLength={6} required />
        <label>Occupation<select value={f.occupation_code} onChange={set('occupation_code')}>{OCCUPATIONS.map((o) => <option key={o}>{o}</option>)}</select></label>
        <Input {...p} name="annual_income" label="Annual income (Rs.)" type="number" min="0" value={f.annual_income} onChange={set('annual_income')} required />
        <label className="full check"><input type="checkbox" checked={f.consent} onChange={set('consent')} aria-invalid={!!errors.consent} /> I consent to KYC checks, including sanctions and PEP screening, on the details and documents I provide.</label>
        {errors.consent && <span className="error full">{errors.consent}</span>}
        {msg && <p className="error full" role="alert">{msg}</p>}
        <button type="submit" className="full">Continue to document upload</button>
      </form>
    </main>
  );
}

export function UploadForm({ id, resubmission, onDone }) {
  const [rows, setRows] = useState([]);
  const [errors, setErrors] = useState({});
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const add = (e) => { setRows([...rows, ...[...e.target.files].map((file) => ({ file, type: guessType(file.name) }))]); e.target.value = ''; };
  const submit = async (e) => {
    e.preventDefault();
    setErrors({}); setMsg(''); setBusy(true);
    const form = new FormData();
    rows.forEach((r) => { form.append('files', r.file); form.append('declared_doc_type', r.type); });
    try {
      const r = await api(`/applications/${id}/documents`, { method: 'POST', form });
      const dup = r.documents.filter((d) => d.duplicate).length;
      setRows([]); setMsg(dup ? `${dup} file(s) were already uploaded and were not added again.` : '');
      onDone();
    } catch (x) { setErrors(x.errors); setMsg(x.message); } finally { setBusy(false); }
  };
  return (
    <form onSubmit={submit} className="card">
      <h2>{resubmission ? 'Upload new documents' : 'Upload documents'}</h2>
      <p className="muted small">PAN card, Aadhaar card and one address proof (electricity bill, bank statement or driving licence). .txt up to 1 MB; .png, .jpg or .pdf up to 5 MB.</p>
      <label>Add files<input type="file" multiple accept=".txt,.png,.jpg,.jpeg,.pdf" onChange={add} /></label>
      {rows.length > 0 && (
        <table>
          <thead><tr><th>File</th><th>Size</th><th>Document type</th><th /></tr></thead>
          <tbody>{rows.map((r, i) => (
            <tr key={i}>
              <td>{r.file.name}{errors[`files[${i}]`] && <div className="error">{errors[`files[${i}]`]}</div>}</td>
              <td>{(r.file.size / 1024).toFixed(1)} KB</td>
              <td><select aria-label={`Document type for ${r.file.name}`} value={r.type} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, type: e.target.value } : x)))} required>
                <option value="">Choose...</option>{DOC_TYPES.map((t) => <option key={t}>{t}</option>)}</select></td>
              <td><button type="button" className="link" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</button></td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {Object.entries(errors).filter(([k]) => !k.startsWith('files[')).map(([k, v]) => <p key={k} className="error">{v}</p>)}
      {msg && <p className={Object.keys(errors).length ? 'error' : 'ok'} role="status">{msg}</p>}
      <button type="submit" disabled={busy || !rows.length || rows.some((r) => !r.type)}>{busy ? 'Uploading...' : 'Submit documents'}</button>
    </form>
  );
}

export function ApplicationStatus() {
  const { id } = useParams();
  const [a, setA] = useState(null);
  const [err, setErr] = useState('');
  const load = () => api(`/applications/${id}`).then(setA, (x) => setErr(x.message));
  useEffect(() => { load(); }, [id]);
  useEffect(() => { // poll while documents are being checked
    if (!a || !['EXTRACTING', 'SUBMITTED'].includes(a.status)) return;
    const t = setTimeout(load, 1500);
    return () => clearTimeout(t);
  }, [a]);
  if (err) return <main><p className="error">{err}</p></main>;
  if (!a) return <main><p>Loading...</p></main>;
  return (
    <main>
      <h1>Application {a.id}</h1>
      <div className="card">
        <p><span className={`badge s-${a.status}`}>{a.statusText}</span></p>
        <p>{a.fullName} - PAN {a.panNumber} - Aadhaar XXXX XXXX {a.aadhaarLast4}</p>
        {a.account && <p className="ok">Account opened. Customer ID <strong>{a.account.customerId}</strong>, account number <strong>{a.account.accountNumber}</strong>.</p>}
        {a.reasons.length > 0 && <><h2>What we found</h2><ul>{a.reasons.map((r) => <li key={r}>{r}</li>)}</ul></>}
        {a.resubmissionDue && <p className="warn">Please upload new documents by {fmtDate(a.resubmissionDue)}.</p>}
      </div>
      {(a.status === 'DRAFT' || a.status === 'RESUBMISSION_REQUESTED') && <UploadForm id={a.id} resubmission={a.status === 'RESUBMISSION_REQUESTED'} onDone={load} />}
      {a.documents.length > 0 && (
        <div className="card"><h2>Documents</h2>
          <ul>{a.documents.map((d) => <li key={d.id}>{d.fileName} - {d.declaredDocType} - {d.extractionStatus === 'DONE' || d.extractionStatus === 'FAILED' ? 'checked' : 'checking...'}</li>)}</ul>
        </div>
      )}
      <div className="card"><h2>Timeline</h2>
        <ol className="timeline">{a.timeline.map((t, i) => <li key={i}><time>{fmtDate(t.at)}</time> {t.text}</li>)}</ol>
      </div>
    </main>
  );
}
