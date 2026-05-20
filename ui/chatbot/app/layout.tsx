import type { Metadata } from 'next';
import './globals.css';
import { RumInit } from './components/RumInit';

export const metadata: Metadata = {
  title: 'Cat Care Chatbot',
  description: 'Split-screen comparison of LangGraph vs Strands agents',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh">
      <body>
        <RumInit />
        {children}
      </body>
    </html>
  );
}
