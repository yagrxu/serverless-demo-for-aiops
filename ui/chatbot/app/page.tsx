'use client';

import { useState } from 'react';
import ChatPanel, { Msg } from './components/ChatPanel';
import { getSessionId, SESSION_HEADER } from '@/lib/session';

interface InvokeResponse {
  langgraph?: string;
  strands?: string;
  error?: string;
}

interface ModelEntry {
  id: string;
  display_name: string;
  tier: string;
}

// Inline the registry — avoids a fetch in dev and works in Docker
const MODELS: ModelEntry[] = [
  { id: "claude-haiku-4-5", display_name: "Claude Haiku 4.5", tier: "frontier" },
  { id: "claude-sonnet-4-5", display_name: "Claude Sonnet 4.5", tier: "frontier" },
  { id: "nova-pro", display_name: "Nova Pro", tier: "mid" },
  { id: "llama-3-3-70b", display_name: "Llama 3.3 70B", tier: "weak" },
];

export default function Home() {
  const [input, setInput] = useState('');
  const [modelId, setModelId] = useState('');
  const [promptVersion, setPromptVersion] = useState('');
  const [lgMsgs, setLgMsgs] = useState<Msg[]>([]);
  const [stMsgs, setStMsgs] = useState<Msg[]>([]);
  const [lgBusy, setLgBusy] = useState(false);
  const [stBusy, setStBusy] = useState(false);

  async function send() {
    if (!input.trim()) return;
    const msg = input;
    const ts = Date.now();
    setInput('');

    const userMsg: Msg = { role: 'user', text: msg, ts };
    setLgMsgs((p) => [...p, userMsg]);
    setStMsgs((p) => [...p, userMsg]);

    setLgBusy(true);
    setStBusy(true);

    const payload: Record<string, unknown> = { message: msg, agent: 'both' };
    const trimmedModel = modelId.trim();
    const trimmedVersion = promptVersion.trim();
    if (trimmedModel) payload.model_id = trimmedModel;
    if (trimmedVersion) payload.prompt_version = parseInt(trimmedVersion, 10) || null;

    try {
      const res = await fetch('/api/invoke', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          [SESSION_HEADER]: getSessionId(),
        },
        body: JSON.stringify(payload),
      });
      const data: InvokeResponse = await res.json();

      if (data.langgraph) {
        setLgMsgs((p) => [...p, { role: 'bot', text: data.langgraph!, ts: Date.now() }]);
      }
      if (data.strands) {
        setStMsgs((p) => [...p, { role: 'bot', text: data.strands!, ts: Date.now() }]);
      }
    } catch (e: any) {
      const errMsg = `Error: ${e.message}`;
      setLgMsgs((p) => [...p, { role: 'bot', text: errMsg, ts: Date.now() }]);
      setStMsgs((p) => [...p, { role: 'bot', text: errMsg, ts: Date.now() }]);
    } finally {
      setLgBusy(false);
      setStBusy(false);
    }
  }

  return (
    <div className="h-screen flex flex-col bg-white text-gray-900">
      {/* top bar */}
      <header className="flex items-center justify-between px-6 py-3 border-b border-gray-200 bg-white">
        <div className="flex items-center gap-3">
          <span className="text-lg">🐱</span>
          <h1 className="text-base font-semibold tracking-tight">
            Cat Care Agent Comparison
          </h1>
          <nav className="ml-6 flex gap-4 text-xs text-gray-400">
            <a href="/device-simulator" className="hover:text-gray-600">Device Simulator</a>
            <a href="/admin-console" className="hover:text-gray-600">Admin Console</a>
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => {
              setLgMsgs([]);
              setStMsgs([]);
            }}
            className="text-xs text-gray-400 hover:text-gray-600 transition-colors px-2 py-1"
          >
            Clear
          </button>
        </div>
      </header>

      {/* split panels */}
      <div className="flex-1 flex min-h-0 divide-x divide-gray-200">
        <div className="w-1/2 flex flex-col min-h-0">
          <ChatPanel
            agent="langgraph"
            messages={lgMsgs}
            busy={lgBusy}
            accent="bg-indigo-50 text-indigo-900"
          />
        </div>
        <div className="w-1/2 flex flex-col min-h-0">
          <ChatPanel
            agent="strands"
            messages={stMsgs}
            busy={stBusy}
            accent="bg-emerald-50 text-emerald-900"
          />
        </div>
      </div>

      {/* shared input */}
      <div className="border-t border-gray-200 bg-gray-50/80 px-6 py-4">
        <div className="max-w-3xl mx-auto">
          <div className="flex gap-3">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && send()}
              disabled={lgBusy && stBusy}
              placeholder="问问你的猫咪… 例如「锅锅最近吃了什么」「烤烤健康状况怎么样」"
              className="flex-1 px-4 py-2.5 rounded-xl border border-gray-300 text-sm
                         placeholder:text-gray-400
                         focus:outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400
                         disabled:opacity-50 transition-shadow"
            />
            <button
              onClick={send}
              disabled={lgBusy && stBusy}
              className="px-5 py-2.5 rounded-xl bg-gray-800 text-white text-sm font-medium
                         hover:bg-gray-700 active:bg-gray-900
                         disabled:opacity-50 disabled:cursor-not-allowed
                         transition-colors"
            >
              Send
            </button>
          </div>
          <div className="mt-2 flex items-center gap-3">
            <label className="text-xs text-gray-500">Model:</label>
            <select
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
              className="px-3 py-1.5 rounded-lg border border-gray-200 text-xs
                         focus:outline-none focus:ring-1 focus:ring-indigo-500/30 bg-white"
            >
              <option value="">Default (Haiku 4.5)</option>
              {MODELS.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.display_name} ({m.tier})
                </option>
              ))}
            </select>
            <label className="text-xs text-gray-500 ml-2">Prompt ver:</label>
            <input
              value={promptVersion}
              onChange={(e) => setPromptVersion(e.target.value)}
              placeholder="latest"
              className="w-20 px-3 py-1.5 rounded-lg border border-gray-200 text-xs
                         placeholder:text-gray-400
                         focus:outline-none focus:ring-1 focus:ring-indigo-500/30"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
