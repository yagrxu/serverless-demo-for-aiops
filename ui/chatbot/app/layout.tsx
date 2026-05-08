import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Cat Care Chatbot',
  description: 'Split-screen comparison of LangGraph vs Strands agents',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh">
      <body>{children}</body>
    </html>
  );
}
