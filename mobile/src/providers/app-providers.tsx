import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, type PropsWithChildren } from 'react';

import { AuthProvider, useAuth } from '@/providers/auth-provider';
import { QueryProvider } from '@/providers/query-provider';

function AuthScopedQueryCache({ children }: PropsWithChildren) {
  const { isReady, user } = useAuth();
  const queryClient = useQueryClient();
  const previousUserId = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    if (!isReady) return;
    const nextUserId = user?.id ?? null;
    if (
      previousUserId.current !== undefined &&
      previousUserId.current !== nextUserId
    ) {
      queryClient.clear();
    }
    previousUserId.current = nextUserId;
  }, [isReady, queryClient, user?.id]);

  return children;
}

export function AppProviders({ children }: PropsWithChildren) {
  return (
    <QueryProvider>
      <AuthProvider>
        <AuthScopedQueryCache>{children}</AuthScopedQueryCache>
      </AuthProvider>
    </QueryProvider>
  );
}
