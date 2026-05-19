import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { App } from './App';

describe('App', () => {
  it('renders the Device Simulator heading', () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: /device simulator/i })).toBeDefined();
  });

  it('renders the send telemetry button', () => {
    render(<App />);
    expect(screen.getByRole('button', { name: /send telemetry/i })).toBeDefined();
  });
});
