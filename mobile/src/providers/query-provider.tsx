import NetInfo from '@react-native-community/netinfo';
import {
  focusManager,
  onlineManager,
  QueryClient,
  QueryClientProvider,
} from '@tanstack/react-query';
import { useEffect, type PropsWithChildren } from 'react';
import { AppState } from 'react-native';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 10 * 60_000,
      retry: 1,
      refetchOnReconnect: true,
    },
    mutations: { retry: 0 },
  },
});

function QueryLifecycle() {
  useEffect(
    () =>
      onlineManager.setEventListener((setOnline) =>
        NetInfo.addEventListener((state) =>
          setOnline(Boolean(state.isConnected)),
        ),
      ),
    [],
  );

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => {
      focusManager.setFocused(state === 'active');
    });
    return () => subscription.remove();
  }, []);

  return null;
}

export function QueryProvider({ children }: PropsWithChildren) {
  return (
    <QueryClientProvider client={queryClient}>
      <QueryLifecycle />
      {children}
    </QueryClientProvider>
  );
}

export const resetQueryCache = () => queryClient.clear();
