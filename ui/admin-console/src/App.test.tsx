import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import App from './App';

describe('App', () => {
  beforeEach(() => {
    // Mock fetch to return an empty cats list so the component renders without errors
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: () => Promise.resolve([]),
    }));
  });

  it('renders the Admin Console heading', async () => {
    render(<App />);

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Admin Console');

    // Wait for the fetch to resolve so the component finishes its effect
    await waitFor(() => {
      expect(fetch).toHaveBeenCalled();
    });
  });
});
