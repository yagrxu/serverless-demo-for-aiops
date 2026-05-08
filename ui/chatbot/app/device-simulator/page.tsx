'use client';

import { useState } from 'react';

export default function DeviceSimulator() {
  const [deviceId, setDeviceId] = useState('feeder-hotpot');
  const [food, setFood] = useState(420);
  const [log, setLog] = useState<string[]>([]);

  async function sendTelemetry() {
    const r = await fetch(`/api/proxy/devices/${deviceId}/telemetry`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ metrics: { food_grams: food } }),
    });
    setLog((l) => [`[${new Date().toLocaleTimeString()}] telemetry → ${r.status}`, ...l]);
  }

  async function dispense() {
    const r = await fetch(`/api/proxy/devices/${deviceId}/commands`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: 'dispense', args: { grams: 20 } }),
    });
    setLog((l) => [`[${new Date().toLocaleTimeString()}] dispense → ${r.status}`, ...l]);
  }

  return (
    <div className="min-h-screen bg-white text-gray-900">
      <header className="flex items-center gap-3 px-6 py-4 border-b border-gray-200">
        <span className="text-lg">📡</span>
        <h1 className="text-base font-semibold">Device Simulator</h1>
        <a href="/" className="ml-auto text-xs text-gray-400 hover:text-gray-600">← Chatbot</a>
      </header>

      <main className="max-w-xl mx-auto px-6 py-8 space-y-6">
        <div className="grid grid-cols-[auto_1fr] gap-3 items-center">
          <label className="text-sm font-medium text-gray-600">device_id</label>
          <input
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
            className="px-3 py-2 rounded-lg border border-gray-300 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
          />
          <label className="text-sm font-medium text-gray-600">food_grams</label>
          <input
            type="number"
            value={food}
            onChange={(e) => setFood(Number(e.target.value))}
            className="px-3 py-2 rounded-lg border border-gray-300 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
          />
        </div>

        <div className="flex gap-3">
          <button
            onClick={sendTelemetry}
            className="px-4 py-2 rounded-lg bg-gray-800 text-white text-sm font-medium hover:bg-gray-700"
          >
            Send Telemetry
          </button>
          <button
            onClick={dispense}
            className="px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-500"
          >
            Dispense 20g
          </button>
        </div>

        <div className="bg-gray-50 rounded-lg p-4 min-h-[200px]">
          <p className="text-xs font-medium text-gray-500 mb-2">Log</p>
          <pre className="text-xs text-gray-700 whitespace-pre-wrap">
            {log.length === 0 ? 'No events yet…' : log.join('\n')}
          </pre>
        </div>
      </main>
    </div>
  );
}
