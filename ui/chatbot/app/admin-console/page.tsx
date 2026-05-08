'use client';

import { useEffect, useState } from 'react';

type Cat = { cat_id: string; name?: string; nickname?: string; breed?: string; color?: string; birthday?: string };

export default function AdminConsole() {
  const [cats, setCats] = useState<Cat[]>([]);
  const [form, setForm] = useState({ cat_id: '', name: '', breed: '' });
  const [selected, setSelected] = useState<string | null>(null);
  const [feedings, setFeedings] = useState<any[]>([]);
  const [alerts, setAlerts] = useState<any[]>([]);

  async function refresh() {
    const r = await fetch('/api/proxy/cats');
    setCats(await r.json());
  }

  useEffect(() => { refresh(); }, []);

  async function createCat() {
    await fetch('/api/proxy/cats', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    });
    setForm({ cat_id: '', name: '', breed: '' });
    refresh();
  }

  async function openCat(catId: string) {
    setSelected(catId);
    const [f, a] = await Promise.all([
      fetch(`/api/proxy/feedings?cat_id=${catId}`).then((r) => r.json()),
      fetch(`/api/proxy/health/${catId}/alerts`).then((r) => r.json()),
    ]);
    setFeedings(f);
    setAlerts(a);
  }

  return (
    <div className="min-h-screen bg-white text-gray-900">
      <header className="flex items-center gap-3 px-6 py-4 border-b border-gray-200">
        <span className="text-lg">🏠</span>
        <h1 className="text-base font-semibold">Admin Console</h1>
        <a href="/" className="ml-auto text-xs text-gray-400 hover:text-gray-600">← Chatbot</a>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8 space-y-8">
        {/* Cat list */}
        <section>
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Cats</h2>
          <div className="space-y-2">
            {cats.map((c) => (
              <div
                key={c.cat_id}
                className="flex items-center gap-3 p-3 rounded-lg border border-gray-200 hover:bg-gray-50 cursor-pointer"
                onClick={() => openCat(c.cat_id)}
              >
                <span className="text-lg">🐱</span>
                <div>
                  <p className="text-sm font-medium">{c.name ?? c.cat_id}</p>
                  <p className="text-xs text-gray-500">{c.breed} {c.color && `· ${c.color}`}</p>
                </div>
                <span className="ml-auto text-xs text-gray-400">{c.cat_id}</span>
              </div>
            ))}
            {cats.length === 0 && <p className="text-sm text-gray-400">No cats registered</p>}
          </div>
        </section>

        {/* Create cat */}
        <section>
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Create a Cat</h2>
          <div className="grid grid-cols-[auto_1fr] gap-3 items-center max-w-md">
            <label className="text-sm text-gray-600">cat_id</label>
            <input value={form.cat_id} onChange={(e) => setForm({ ...form, cat_id: e.target.value })} className="px-3 py-2 rounded-lg border border-gray-300 text-sm" />
            <label className="text-sm text-gray-600">name</label>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="px-3 py-2 rounded-lg border border-gray-300 text-sm" />
            <label className="text-sm text-gray-600">breed</label>
            <input value={form.breed} onChange={(e) => setForm({ ...form, breed: e.target.value })} className="px-3 py-2 rounded-lg border border-gray-300 text-sm" />
          </div>
          <button onClick={createCat} className="mt-3 px-4 py-2 rounded-lg bg-gray-800 text-white text-sm font-medium hover:bg-gray-700">
            Create
          </button>
        </section>

        {/* Detail view */}
        {selected && (
          <section className="space-y-4">
            <h2 className="text-sm font-semibold text-gray-700">Details — {selected}</h2>

            <div>
              <h3 className="text-xs font-medium text-gray-500 mb-1">Feedings</h3>
              <pre className="bg-gray-50 rounded-lg p-3 text-xs overflow-auto max-h-60">
                {JSON.stringify(feedings, null, 2)}
              </pre>
            </div>

            <div>
              <h3 className="text-xs font-medium text-gray-500 mb-1">Health Alerts</h3>
              <pre className="bg-gray-50 rounded-lg p-3 text-xs overflow-auto max-h-60">
                {JSON.stringify(alerts, null, 2)}
              </pre>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
