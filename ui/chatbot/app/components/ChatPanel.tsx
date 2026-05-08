'use client';

import { useEffect, useRef } from 'react';

export type Msg = { role: 'user' | 'bot'; text: string; ts: number };
export type AgentType = 'langgraph' | 'strands';

interface ChatPanelProps {
  agent: AgentType;
  messages: Msg[];
  busy: boolean;
  accent: string;
}

export default function ChatPanel({ agent, messages, busy, accent }: ChatPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, busy]);

  const label = agent === 'langgraph' ? 'LangGraph' : 'Strands';
  const dotColor = agent === 'langgraph' ? 'bg-indigo-500' : 'bg-emerald-500';

  return (
    <div className="flex flex-col h-full min-w-0">
      {/* header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-200 bg-gray-50/80">
        <span className={`w-2.5 h-2.5 rounded-full ${dotColor}`} />
        <span className="font-semibold text-sm text-gray-700">{label}</span>
      </div>

      {/* messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.length === 0 && (
          <p className="text-gray-400 text-sm italic">
            Send a message to start chatting with {label}…
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
                m.role === 'user'
                  ? 'bg-gray-800 text-white rounded-br-md'
                  : `${accent} rounded-bl-md`
              }`}
            >
              {m.text}
            </div>
          </div>
        ))}
        {busy && (
          <div className="flex justify-start">
            <div className={`${accent} rounded-2xl rounded-bl-md px-4 py-2.5 text-sm`}>
              <span className="inline-flex gap-1">
                <span className="animate-bounce">·</span>
                <span className="animate-bounce [animation-delay:0.15s]">·</span>
                <span className="animate-bounce [animation-delay:0.3s]">·</span>
              </span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
