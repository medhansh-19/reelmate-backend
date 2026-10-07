import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { useState } from 'react';

import { terminalStatuses } from '@/lib/api-schemas';
import {
  cancelAnalysis,
  deleteAnalysis,
  getAnalysis,
  listAnalyses,
  retryAnalysis,
  startAnalysis,
  type UploadPhase,
} from '@/lib/api-client';
import type { SelectedMedia } from '@/types/media';
import { useAuth } from '@/providers/auth-provider';

export const analysisKeys = {
  all: (userId: string) => ['analyses', userId] as const,
  detail: (userId: string, analysisId: string) =>
    ['analyses', userId, 'detail', analysisId] as const,
  list: (userId: string) => ['analyses', userId, 'list'] as const,
};

export const useAnalysis = (analysisId: string) => {
  const { user } = useAuth();
  const userId = user?.id ?? 'signed-out';
  return useQuery({
    queryKey: analysisKeys.detail(userId, analysisId),
    queryFn: ({ signal }) => getAnalysis(analysisId, signal),
    enabled: Boolean(user && analysisId),
    refetchInterval: (query) => {
      if (query.state.status === 'error') return false;
      const status = query.state.data?.status;
      if (!status || terminalStatuses.has(status)) return false;
      return 1_500;
    },
  });
};

export const useAnalyses = () => {
  const { user } = useAuth();
  const userId = user?.id ?? 'signed-out';
  return useInfiniteQuery({
    queryKey: analysisKeys.list(userId),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => listAnalyses(pageParam, signal),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    refetchInterval: (query) => {
      const analyses = query.state.data?.pages.flatMap((page) => page.analyses);
      return analyses?.some((item) => !terminalStatuses.has(item.status))
        ? 3_000
        : false;
    },
    enabled: Boolean(user),
  });
};

export const useStartAnalysis = () => {
  const { user } = useAuth();
  const userId = user?.id ?? 'signed-out';
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<UploadPhase>('creating');
  const mutation = useMutation({
    mutationFn: (media: SelectedMedia) => startAnalysis(media, setPhase),
    onSuccess: (analysis) => {
      void queryClient.invalidateQueries({
        queryKey: analysisKeys.list(userId),
      });
      queryClient.setQueryData(
        analysisKeys.detail(userId, analysis.analysis_id),
        undefined,
      );
    },
  });
  return { ...mutation, phase };
};

export const useRetryAnalysis = () => {
  const { user } = useAuth();
  const userId = user?.id ?? 'signed-out';
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: retryAnalysis,
    onSuccess: (analysis) => {
      void queryClient.invalidateQueries({
        queryKey: analysisKeys.detail(userId, analysis.analysis_id),
      });
      void queryClient.invalidateQueries({
        queryKey: analysisKeys.list(userId),
      });
    },
  });
};

export const useCancelAnalysis = () => {
  const { user } = useAuth();
  const userId = user?.id ?? 'signed-out';
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: cancelAnalysis,
    onSuccess: (analysis) => {
      void queryClient.invalidateQueries({
        queryKey: analysisKeys.detail(userId, analysis.analysis_id),
      });
      void queryClient.invalidateQueries({
        queryKey: analysisKeys.list(userId),
      });
    },
  });
};

export const useDeleteAnalysis = () => {
  const { user } = useAuth();
  const userId = user?.id ?? 'signed-out';
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteAnalysis,
    onSuccess: (_data, analysisId) => {
      queryClient.removeQueries({
        queryKey: analysisKeys.detail(userId, analysisId),
      });
      void queryClient.invalidateQueries({
        queryKey: analysisKeys.list(userId),
      });
    },
  });
};
