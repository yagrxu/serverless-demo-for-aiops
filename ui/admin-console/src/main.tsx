import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

type Cat = { cat_id: string; name?: string; breed?: string; birthday?: string };

function App() {
  const [cats, setCats] = useState<Cat[]>([]);
  const [form, setForm] = useState<Cat>({ cat_id: '', name: '', breed: '' });
  const [selected, setSelected] = useState<string | null>(null);
  const [feedings, setFeedings] = useState<any[]>([]);
  const [alerts, setAlerts] = useState<any[]>([]);

  async function refresh() {
    const r = await fetch(`${API}/cats`);
    setCats(await r.json());
  }

  useEffect(() => { refresh(); }, []);

  async function createCat() {
    await fetch(`${API}/cats`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    });
    setForm({ cat_id: '', name: '', breed: '' });
    refresh();
  }

  async function open(catId: string) {
    setSelected(catId);
    const [f, a] = await Promise.all([
      fetch(`${API}/feedings?cat_id=${catId}`).then(r => r.json()),
      fetch(`${API}/health/${catId}/alerts`).then(r => r.json()),
    ]);
    setFeedings(f);
    setAlerts(a);
  }

  return (
    <div style={{ fontFamily: 'system-ui', maxWidth: 900, margin: '2rem auto', padding: '0 1rem' }}>
      <h1>Admin Console</h1>

      <h2>Cats</h2>
      <ul>
        {cats.map(c => (
          <li key={c.cat_id}>
            <button onClick={() => open(c.cat_id)}>{c.name ?? c.cat_id}</button>
            {' — '}{c.breed}
          </li>
        ))}
      </ul>

      <h3>Create a cat</h3>
      <div style={{ display: 'grid', gap: '.5rem', gridTemplateColumns: 'auto 1fr', maxWidth: 380 }}>
        <label>cat_id:</label><input value={form.cat_id} onChange={e => setForm({ ...form, cat_id: e.target.value })} />
        <label>name:</label><input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
        <label>breed:</label><input value={form.breed} onChange={e => setForm({ ...form, breed: e.target.value })} />
      </div>
      <button style={{ marginTop: '.5rem' }} onClick={createCat}>create</button>

      {selected && (
        <>
          <h2>Feedings — {selected}</h2>
          <pre style={{ background: '#f5f5f5', padding: '.5rem' }}>{JSON.stringify(feedings, null, 2)}</pre>
          <h2>Alerts — {selected}</h2>
          <pre style={{ background: '#f5f5f5', padding: '.5rem' }}>{JSON.stringify(alerts, null, 2)}</pre>
        </>
      )}
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
