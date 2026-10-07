import 'react-native-url-polyfill/auto';

import {
  createClient,
  processLock,
  type SupabaseClient,
} from '@supabase/supabase-js';

import { appConfig } from '@/config';
import { secureAuthStorage } from '@/lib/secure-auth-storage';

let client: SupabaseClient | null = null;

export const getSupabaseClient = () => {
  if (!appConfig.servicesConfigured) return null;
  client ??= createClient(
    appConfig.supabaseUrl,
    appConfig.supabasePublishableKey,
    {
      auth: {
        storage: secureAuthStorage,
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: false,
        lock: processLock,
      },
    },
  );
  return client;
};

export const getAccessToken = async ({
  refresh = false,
}: { refresh?: boolean } = {}) => {
  const supabase = getSupabaseClient();
  if (!supabase) return null;
  if (refresh) {
    const { data, error } = await supabase.auth.refreshSession();
    if (error) throw error;
    return data.session?.access_token ?? null;
  }
  const { data, error } = await supabase.auth.getSession();
  if (error) throw error;
  return data.session?.access_token ?? null;
};
