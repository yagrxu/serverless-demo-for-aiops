import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

function App() {
  const [deviceId, setDeviceId] = useState('feeder-1');
  const [food, setFood] = useState(420);
  const [log, setLog] = useState<string[]>([]);

  async function sendTelemetry() {
    const r = await fetch(`${API}/devices/${deviceId}/telemetry`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ metrics: { food_grams: food } }),
    });
    setLog(l => [`telemetry ${r.status}`, ...l]);
  }

  async function dispense() {
    const r = await fetch(`${API}/devices/${deviceId}/commands`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: 'dispense', args: { grams: 20 } }),
    });
    setLog(l => [`dispense ${r.status}`, ...l]);
  }

  return (
    <div style={{ fontFamily: 'system-ui', maxWidth: 720, margin: '2rem auto', padding: '0 1rem' }}>
      <h1>Device Simulator</h1>
      <div style={{ display: 'grid', gap: '.5rem', gridTemplateColumns: 'auto 1fr', maxWidth: 380 }}>
        <label>device_id:</label>
        <input value={deviceId} onChange={e => setDeviceId(e.target.value)} />
        <label>food_grams:</label>
        <input type="number" value={food} onChange={e => setFood(Number(e.target.value))} />
      </div>
      <div style={{ marginTop: '1rem', display: 'flex', gap: '.5rem' }}>
        <button onClick={sendTelemetry}>send telemetry</button>
        <button onClick={dispense}>dispense 20g</button>
      </div>
      <pre style={{ marginTop: '1rem', background: '#f5f5f5', padding: '.5rem' }}>
        {log.join('\n')}
      </pre>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
