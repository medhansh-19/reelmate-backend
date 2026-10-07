import { fetch as expoFetch } from 'expo/fetch';
import { File as ExpoFile } from 'expo-file-system';
import { z, type ZodType } from 'zod';

import { appConfig } from '@/config';
import {
  analysisCreatedResponseSchema,
  analysisListResponseSchema,
  analysisStatusResponseSchema,
  analysisSubmitResponseSchema,
  apiErrorEnvelopeSchema,
  musicPreferenceSchema,
  type AnalysisListResponse,
  type AnalysisStatusResponse,
  type AnalysisSubmitResponse,
  type MusicPreference,
  type MusicPreferenceUpdate,
} from '@/lib/api-schemas';
import {
  demoDeleteAnalysis,
  demoCancelAnalysis,
  demoGetAnalysis,
  demoListAnalyses,
  demoRetryAnalysis,
  demoStartAnalysis,
} from '@/lib/demo-api';
import { getAccessToken } from '@/lib/supabase';
import type { SelectedMedia } from '@/types/media';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly retryable: boolean,
    readonly requestId: string | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export type UploadPhase = 'creating' | 'uploading' | 'submitting';

type CreatedAnalysis = z.infer<typeof analysisCreatedResponseSchema>;

// A retry for the same selected file reuses its backend row and can recover a
// submit response that was lost after the server accepted it.
const pendingAnalyses = new Map<string, CreatedAnalysis>();

const endpoint = (path: string) => `${appConfig.apiBaseUrl}/v1${path}`;

const parseError = async (response: Response) => {
  const payload = await response.json().catch(() => null);
  const parsed = apiErrorEnvelopeSchema.safeParse(payload);
  if (parsed.success) {
    return new ApiError(
      parsed.data.error.message,
      response.status,
      parsed.data.error.code,
      parsed.data.error.retryable,
      parsed.data.error.request_id ?? null,
    );
  }
  return new ApiError(
    response.status >= 500
      ? 'ReelMate is temporarily unavailable.'
      : 'The request could not be completed.',
    response.status,
    'UNEXPECTED_RESPONSE',
    response.status >= 500,
  );
};

const authenticatedFetch = async (
  path: string,
  init: RequestInit,
  refresh = false,
) => {
  const token = await getAccessToken({ refresh });
  if (!token)
    throw new ApiError('Sign in to continue.', 401, 'AUTH_REQUIRED', false);
  let response: Response;
  try {
    response = await expoFetch(endpoint(path), {
      ...init,
      headers: {
        Accept: 'application/json',
        ...init.headers,
        Authorization: `Bearer ${token}`,
      },
    });
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(
      'Check your connection and try again.',
      0,
      'NETWORK_ERROR',
      true,
    );
  }
  if (response.status === 401 && !refresh)
    return authenticatedFetch(path, init, true);
  return response;
};

const requestJson = async <T>(
  path: string,
  schema: ZodType<T>,
  init: RequestInit = {},
): Promise<T> => {
  const response = await authenticatedFetch(path, init);
  if (!response.ok) throw await parseError(response);
  const payload: unknown = await response.json();
  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    throw new ApiError(
      'ReelMate returned an incompatible response.',
      502,
      'INVALID_RESPONSE',
      true,
    );
  }
  return parsed.data;
};

export const getAnalysis = async (
  analysisId: string,
  signal?: AbortSignal,
): Promise<AnalysisStatusResponse> => {
  if (appConfig.demoMode) return demoGetAnalysis(analysisId);
  return requestJson(`/analyses/${analysisId}`, analysisStatusResponseSchema, {
    signal,
  });
};

export const listAnalyses = async (
  cursor: string | null,
  signal?: AbortSignal,
): Promise<AnalysisListResponse> => {
  if (appConfig.demoMode) return demoListAnalyses();
  const query = new URLSearchParams({ limit: '20' });
  if (cursor) query.set('cursor', cursor);
  return requestJson(`/analyses?${query}`, analysisListResponseSchema, {
    signal,
  });
};

export const retryAnalysis = async (
  analysisId: string,
): Promise<AnalysisSubmitResponse> => {
  if (appConfig.demoMode) return demoRetryAnalysis(analysisId);
  return requestJson(
    `/analyses/${analysisId}/retry`,
    analysisSubmitResponseSchema,
    {
      method: 'POST',
    },
  );
};

export const cancelAnalysis = async (
  analysisId: string,
): Promise<AnalysisSubmitResponse> => {
  if (appConfig.demoMode) return demoCancelAnalysis(analysisId);
  return requestJson(
    `/analyses/${analysisId}/cancel`,
    analysisSubmitResponseSchema,
    { method: 'POST' },
  );
};

export const deleteAnalysis = async (analysisId: string): Promise<void> => {
  if (appConfig.demoMode) return demoDeleteAnalysis(analysisId);
  const response = await authenticatedFetch(`/analyses/${analysisId}`, {
    method: 'DELETE',
  });
  if (!response.ok) throw await parseError(response);
};

const createAnalysis = async (media: SelectedMedia) => {
  const idempotencyKey = media.idempotencyKey;
  return requestJson('/analyses', analysisCreatedResponseSchema, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey,
    },
    body: JSON.stringify({
      mode: media.mode,
      vocal_preference:
        media.mode === 'story_song' ? media.vocalPreference : 'any',
      filename: media.filename,
      content_type: media.mimeType,
      file_size_bytes: media.sizeBytes,
      idempotency_key: idempotencyKey,
    }),
  });
};

const uploadMedia = async (
  media: SelectedMedia,
  target: CreatedAnalysis['upload'],
) => {
  const headers = new Headers(target.headers);
  // Browsers forbid explicitly setting Content-Length; they still send the
  // exact Blob size that R2 verifies. Native Expo fetch can forward it.
  if (process.env.EXPO_OS === 'web') headers.delete('content-length');
  const body = media.webFile ?? new ExpoFile(media.uri);
  let response: Response;
  try {
    response = await expoFetch(target.url, {
      method: target.method,
      headers,
      body: body as BodyInit,
    });
  } catch {
    throw new ApiError(
      'The private media upload was interrupted.',
      0,
      'UPLOAD_NETWORK_ERROR',
      true,
    );
  }
  if (!response.ok) {
    throw new ApiError(
      'The private media upload failed.',
      response.status,
      'UPLOAD_FAILED',
      true,
    );
  }
};

export const startAnalysis = async (
  media: SelectedMedia,
  onPhase?: (phase: UploadPhase) => void,
): Promise<AnalysisSubmitResponse> => {
  if (appConfig.demoMode) {
    onPhase?.('creating');
    await new Promise((resolve) => setTimeout(resolve, 350));
    onPhase?.('uploading');
    await new Promise((resolve) => setTimeout(resolve, 750));
    onPhase?.('submitting');
    return demoStartAnalysis(
      media.mode,
      media.mode === 'story_song' ? media.vocalPreference : 'any',
      media.mode === 'story_song' ? demoMusicPreference : null,
    );
  }

  onPhase?.('creating');
  const pending = pendingAnalyses.get(media.idempotencyKey);
  if (pending) {
    try {
      const current = await getAnalysis(pending.analysis_id);
      if (current.status !== 'awaiting_upload') {
        pendingAnalyses.delete(media.idempotencyKey);
        return {
          analysis_id: current.analysis_id,
          mode: current.mode,
          vocal_preference: current.vocal_preference,
          status: current.status,
          stage: current.stage,
        };
      }
    } catch {
      // The idempotent create below refreshes an awaiting upload target or
      // returns the original safe API error.
    }
  }

  const created = await createAnalysis(media);
  pendingAnalyses.set(media.idempotencyKey, created);
  let uploadCompleted = false;
  try {
    onPhase?.('uploading');
    await uploadMedia(media, created.upload);
    uploadCompleted = true;
    onPhase?.('submitting');
    try {
      const submitted = await requestJson(
        `/analyses/${created.analysis_id}/submit`,
        analysisSubmitResponseSchema,
        { method: 'POST' },
      );
      pendingAnalyses.delete(media.idempotencyKey);
      return submitted;
    } catch (submitError) {
      const current = await getAnalysis(created.analysis_id).catch(() => null);
      if (current && current.status !== 'awaiting_upload') {
        pendingAnalyses.delete(media.idempotencyKey);
        return {
          analysis_id: current.analysis_id,
          mode: current.mode,
          vocal_preference: current.vocal_preference,
          status: current.status,
          stage: current.stage,
        };
      }
      try {
        const submitted = await requestJson(
          `/analyses/${created.analysis_id}/submit`,
          analysisSubmitResponseSchema,
          { method: 'POST' },
        );
        pendingAnalyses.delete(media.idempotencyKey);
        return submitted;
      } catch {
        throw submitError;
      }
    }
  } catch (error) {
    if (!uploadCompleted) {
      pendingAnalyses.delete(media.idempotencyKey);
      await deleteAnalysis(created.analysis_id).catch(() => undefined);
    }
    throw error;
  }
};

let demoMusicPreference: MusicPreference = {
  preferred_languages: [],
  preferred_moods: [],
  favorite_artists: [],
  favorite_tracks: [],
  default_vocal_preference: 'any',
  profile_version: '1',
  revision: 0,
  updated_at: null,
  onboarding_completed_at: null,
};

export const getMusicPreferences = async (
  signal?: AbortSignal,
): Promise<MusicPreference> => {
  if (appConfig.demoMode) return demoMusicPreference;
  return requestJson('/music-preferences', musicPreferenceSchema, { signal });
};

export const updateMusicPreferences = async (
  preference: MusicPreferenceUpdate,
): Promise<MusicPreference> => {
  if (appConfig.demoMode) {
    const { complete_onboarding: completeOnboarding, ...values } = preference;
    const now = new Date().toISOString();
    demoMusicPreference = {
      ...values,
      profile_version: '1',
      revision: demoMusicPreference.revision + 1,
      updated_at: now,
      onboarding_completed_at: completeOnboarding
        ? (demoMusicPreference.onboarding_completed_at ?? now)
        : demoMusicPreference.onboarding_completed_at,
    };
    return demoMusicPreference;
  }
  return requestJson('/music-preferences', musicPreferenceSchema, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(preference),
  });
};
