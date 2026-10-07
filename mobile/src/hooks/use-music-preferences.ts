import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getMusicPreferences, updateMusicPreferences } from '@/lib/api-client';
import type { MusicPreferenceUpdate } from '@/lib/api-schemas';
import { useAuth } from '@/providers/auth-provider';

const musicPreferenceKey = (userId: string) =>
  ['music-preferences', userId] as const;

export const useMusicPreferences = (enabled = true) => {
  const { user } = useAuth();
  const userId = user?.id ?? 'signed-out';
  return useQuery({
    queryKey: musicPreferenceKey(userId),
    queryFn: ({ signal }) => getMusicPreferences(signal),
    enabled: enabled && Boolean(user),
  });
};

export const useUpdateMusicPreferences = () => {
  const { user } = useAuth();
  const userId = user?.id ?? 'signed-out';
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (preference: MusicPreferenceUpdate) =>
      updateMusicPreferences(preference),
    onSuccess: (preference) => {
      queryClient.setQueryData(musicPreferenceKey(userId), preference);
    },
  });
};
