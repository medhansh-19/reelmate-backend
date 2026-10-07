import type { Session } from '@supabase/supabase-js';
import {
  createContext,
  use,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type PropsWithChildren,
} from 'react';
import { AppState } from 'react-native';

import { appConfig } from '@/config';
import { getSupabaseClient } from '@/lib/supabase';

export type AuthUser = {
  id: string;
  email: string | null;
  displayName: string;
};

type AuthResult = { confirmationRequired: boolean };

type AuthContextValue = {
  configurationIssue: string | null;
  isConfigured: boolean;
  isDemo: boolean;
  isReady: boolean;
  session: Session | null;
  user: AuthUser | null;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  signUp: (email: string, password: string) => Promise<AuthResult>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const demoUser: AuthUser = {
  id: '00000000-0000-4000-8000-000000000001',
  email: 'creator@preview.reelmate.app',
  displayName: 'Preview Creator',
};

const toAuthUser = (session: Session | null): AuthUser | null => {
  const user = session?.user;
  if (!user) return null;
  const displayName =
    typeof user.user_metadata?.display_name === 'string'
      ? user.user_metadata.display_name
      : user.email?.split('@')[0] || 'Creator';
  return { id: user.id, email: user.email ?? null, displayName };
};

export function AuthProvider({ children }: PropsWithChildren) {
  const [isReady, setReady] = useState(
    appConfig.demoMode || !appConfig.servicesConfigured,
  );
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    if (appConfig.demoMode || !appConfig.servicesConfigured) return;
    const supabase = getSupabaseClient();
    if (!supabase) return;
    let active = true;

    void supabase.auth.getSession().then(({ data }) => {
      if (active) {
        setSession(data.session);
        setReady(true);
      }
    });
    const { data } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setReady(true);
    });
    const appState = AppState.addEventListener('change', (state) => {
      if (state === 'active') supabase.auth.startAutoRefresh();
      else supabase.auth.stopAutoRefresh();
    });
    return () => {
      active = false;
      data.subscription.unsubscribe();
      appState.remove();
      supabase.auth.stopAutoRefresh();
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    if (appConfig.demoMode) return;
    const supabase = getSupabaseClient();
    if (!supabase) throw new Error('ReelMate connections are not configured.');
    const { error } = await supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    });
    if (error) throw error;
  }, []);

  const signUp = useCallback(
    async (email: string, password: string): Promise<AuthResult> => {
      if (appConfig.demoMode) return { confirmationRequired: false };
      const supabase = getSupabaseClient();
      if (!supabase)
        throw new Error('ReelMate connections are not configured.');
      const { data, error } = await supabase.auth.signUp({
        email: email.trim(),
        password,
      });
      if (error) throw error;
      return { confirmationRequired: data.session === null };
    },
    [],
  );

  const signOut = useCallback(async () => {
    if (appConfig.demoMode) return;
    const supabase = getSupabaseClient();
    if (!supabase) return;
    const { error } = await supabase.auth.signOut();
    if (error) throw error;
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      configurationIssue: appConfig.configurationIssue,
      isConfigured: appConfig.servicesConfigured,
      isDemo: appConfig.demoMode,
      isReady,
      session,
      user: appConfig.demoMode ? demoUser : toAuthUser(session),
      signIn,
      signOut,
      signUp,
    }),
    [isReady, session, signIn, signOut, signUp],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}

export const useAuth = () => {
  const context = use(AuthContext);
  if (!context) throw new Error('useAuth must be used inside AuthProvider');
  return context;
};
