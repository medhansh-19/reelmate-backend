import type { SupportedStorage } from '@supabase/supabase-js';

const browserStorage = () =>
  typeof window === 'undefined' ? null : window.localStorage;

export const secureAuthStorage: SupportedStorage = {
  getItem: async (key) => browserStorage()?.getItem(key) ?? null,
  setItem: async (key, value) => browserStorage()?.setItem(key, value),
  removeItem: async (key) => browserStorage()?.removeItem(key),
};
