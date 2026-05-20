'use client';

import { useEffect } from 'react';
import { initRum } from '../../lib/rum';

/**
 * Client component that initializes CloudWatch RUM on mount.
 * Renders nothing — purely a side-effect component.
 */
export function RumInit() {
  useEffect(() => {
    initRum();
  }, []);

  return null;
}
