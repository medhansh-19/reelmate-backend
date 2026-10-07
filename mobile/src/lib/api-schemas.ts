import { z } from 'zod';

export const analysisStatusSchema = z.enum([
  'awaiting_upload',
  'queued',
  'processing',
  'completed',
  'failed',
  'cancelled',
  'expired',
]);

export const analysisStageSchema = z.enum([
  'awaiting_upload',
  'queued',
  'validating',
  'extracting',
  'scoring',
  'generating_feedback',
  'completed',
  'failed',
  'cancelled',
  'expired',
]);

export const analysisModeSchema = z.enum(['video_coach', 'story_song']);
export const storyVocalPreferenceSchema = z.enum(['any', 'no_lyrics']);

export const feedbackItemSchema = z.object({
  type: z.enum(['hook', 'pacing', 'audio', 'text', 'strength']),
  start_seconds: z.number().nonnegative(),
  end_seconds: z.number().nonnegative(),
  message: z.string(),
  action: z.string(),
  evidence: z.string(),
  severity: z.enum(['high', 'medium', 'low']),
});

export const videoAnalysisResultSchema = z
  .object({
    schema_version: z.string(),
    mode: z.literal('video_coach'),
    score: z.number().int().min(5).max(95),
    score_label: z.literal('reel_readiness'),
    score_experimental: z.boolean(),
    confidence: z.number().min(0).max(1),
    sub_scores: z.object({
      hook: z.number().int().min(0).max(100),
      pacing: z.number().int().min(0).max(100),
      av_sync: z.number().int().min(0).max(100).nullable(),
      text: z.number().int().min(0).max(100),
      trend: z.null(),
    }),
    niche_detected: z.string().nullable(),
    niche_confidence: z.number().min(0).max(1).nullable(),
    feedback: z.array(feedbackItemSchema).min(3).max(5),
    feedback_source: z.literal('local_signal_engine'),
    pipeline_summary: z.record(z.string(), z.unknown()),
    versions: z.object({
      pipeline: z.string(),
      score: z.string(),
      prompt: z.string(),
      model: z.string(),
    }),
    usage: z.object({
      model_input_tokens: z.number().int().nonnegative(),
      model_output_tokens: z.number().int().nonnegative(),
      estimated_model_cost_usd: z.number().nonnegative().nullable(),
      estimated_total_cost_usd: z.number().nonnegative().nullable(),
      pricing_status: z.enum(['metered', 'no_model_call', 'unknown']),
      pricing_version: z.string(),
      cost_limit_exceeded: z.boolean(),
      external_api_used: z.literal(false),
    }),
    personalization: z
      .object({
        submission_count: z.number().int().nonnegative(),
        inferred_niche: z.string().nullable(),
        niche_confidence: z.number().min(0).max(1).nullable(),
        editing_style: z.string().nullable(),
        editing_style_confidence: z.number().min(0).max(1).nullable(),
        typical_energy: z.string().nullable(),
        typical_energy_confidence: z.number().min(0).max(1).nullable(),
        recurring_issue_codes: z.array(z.string()),
        profile_version: z.string(),
        is_repeat_user: z.boolean(),
        previous_score: z.number().int().nullable(),
        score_delta: z.number().int().nullable(),
        improvement_noted: z.boolean(),
      })
      .passthrough(),
  })
  .passthrough();

const moodSchema = z.enum([
  'calm',
  'energetic',
  'romantic',
  'joyful',
  'moody',
  'dreamy',
  'bold',
  'nostalgic',
]);

export const storySongResultSchema = z
  .object({
    schema_version: z.literal('3'),
    mode: z.literal('story_song'),
    requested_vocal_preference: storyVocalPreferenceSchema,
    score: z.number().int().min(5).max(95),
    confidence: z.number().min(0).max(1),
    image_summary: z.object({
      width: z.number().int().positive(),
      height: z.number().int().positive(),
      brightness: z.number().min(0).max(1),
      saturation: z.number().min(0).max(1),
      contrast: z.number().min(0).max(1),
      warmth: z.number().min(0).max(1),
      colorfulness: z.number().min(0).max(1),
      edge_density: z.number().min(0).max(1),
      center_activity: z.number().min(0).max(1),
      face_count: z.number().int().nonnegative(),
      face_prominence: z.number().min(0).max(1),
      dominant_colors: z.array(z.string()).min(1).max(3),
      visual_tags: z.array(z.string()).min(1).max(6),
      mood_profile: z.record(moodSchema, z.number().min(0).max(1)),
    }),
    recommendations: z
      .array(
        z.object({
          song_id: z.string(),
          title: z.string(),
          artist: z.string(),
          language: z.string(),
          match_score: z.number().int().min(0).max(100),
          bpm: z.number().int().positive().nullable(),
          energy: z.enum(['low', 'medium', 'high']),
          vocal_type: z.enum([
            'none',
            'vocal_texture',
            'sparse_lyrics',
            'full_lyrics',
          ]),
          has_lyrics: z.boolean(),
          aesthetic_tags: z.array(z.string()).min(1).max(4),
          matched_moods: z.array(moodSchema).min(1).max(3),
          why: z.string(),
          search_query: z.string(),
        }),
      )
      .min(3)
      .max(5),
    personalization: z.object({
      applied: z.boolean(),
      source: z.enum(['first_party', 'none']),
      signals_provided: z.array(
        z.enum([
          'preferred_languages',
          'preferred_moods',
          'favorite_artists',
          'favorite_tracks',
        ]),
      ),
      signals_used: z.array(
        z.enum([
          'preferred_languages',
          'preferred_moods',
          'favorite_artists',
          'favorite_tracks',
        ]),
      ),
      profile_version: z.string().nullable(),
      profile_revision: z.number().int().positive().nullable(),
      profile_updated_at: z.string().datetime({ offset: true }).nullable(),
      resolution: z.enum(['processing_start', 'none']),
      spotify_data_used: z.literal(false),
    }),
    versions: z.object({
      pipeline: z.string(),
      ranking_model: z.string(),
      catalog: z.string(),
    }),
    privacy: z.object({
      external_api_used: z.literal(false),
      source_included_in_result: z.literal(false),
      source_cleanup: z.literal('durable_outbox'),
    }),
  })
  .superRefine((result, context) => {
    const songIds = new Set<string>();
    result.recommendations.forEach((recommendation, index) => {
      if (songIds.has(recommendation.song_id)) {
        context.addIssue({
          code: 'custom',
          message: 'Story recommendations must have unique song IDs.',
          path: ['recommendations', index, 'song_id'],
        });
      }
      songIds.add(recommendation.song_id);

      const shouldHaveLyrics = recommendation.vocal_type !== 'none';
      if (recommendation.has_lyrics !== shouldHaveLyrics) {
        context.addIssue({
          code: 'custom',
          message: 'Vocal metadata is inconsistent.',
          path: ['recommendations', index, 'has_lyrics'],
        });
      }
      if (
        (recommendation.vocal_type === 'none') !==
        (recommendation.language === 'Instrumental')
      ) {
        context.addIssue({
          code: 'custom',
          message: 'Instrumental language is inconsistent with vocal type.',
          path: ['recommendations', index, 'language'],
        });
      }
      if (
        result.requested_vocal_preference === 'no_lyrics' &&
        recommendation.has_lyrics
      ) {
        context.addIssue({
          code: 'custom',
          message: 'No-lyrics results cannot contain lyrical songs.',
          path: ['recommendations', index],
        });
      }
    });

    if (
      result.personalization.applied !==
      result.personalization.signals_used.length > 0
    ) {
      context.addIssue({
        code: 'custom',
        message: 'Personalization disclosure is inconsistent.',
        path: ['personalization', 'applied'],
      });
    }
    const provided = new Set(result.personalization.signals_provided);
    if (
      result.personalization.signals_used.some(
        (signal) => !provided.has(signal),
      )
    ) {
      context.addIssue({
        code: 'custom',
        message: 'Used preference signals must have been provided.',
        path: ['personalization', 'signals_used'],
      });
    }
  });

export const analysisResultSchema = z.discriminatedUnion('mode', [
  videoAnalysisResultSchema,
  storySongResultSchema,
]);

export const analysisStatusResponseSchema = z.object({
  analysis_id: z.string().uuid(),
  mode: analysisModeSchema,
  vocal_preference: storyVocalPreferenceSchema,
  status: analysisStatusSchema,
  stage: analysisStageSchema,
  retryable: z.boolean(),
  failure_code: z.string().nullable(),
  result: analysisResultSchema.nullable(),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
});

export const analysisListItemSchema = z.object({
  analysis_id: z.string().uuid(),
  mode: analysisModeSchema,
  vocal_preference: storyVocalPreferenceSchema,
  status: analysisStatusSchema,
  stage: analysisStageSchema,
  score: z.number().int().min(5).max(95).nullable(),
  niche_detected: z.string().nullable(),
  created_at: z.string().datetime({ offset: true }),
});

export const analysisListResponseSchema = z.object({
  analyses: z.array(analysisListItemSchema),
  next_cursor: z.string().nullable(),
});

export const analysisCreatedResponseSchema = z.object({
  analysis_id: z.string().uuid(),
  mode: analysisModeSchema,
  vocal_preference: storyVocalPreferenceSchema,
  status: analysisStatusSchema,
  upload: z.object({
    url: z.string().url(),
    method: z.literal('PUT'),
    headers: z.record(z.string(), z.string()),
    expires_at: z.string().datetime({ offset: true }),
  }),
});

export const analysisSubmitResponseSchema = z.object({
  analysis_id: z.string().uuid(),
  mode: analysisModeSchema,
  vocal_preference: storyVocalPreferenceSchema,
  status: analysisStatusSchema,
  stage: analysisStageSchema,
});

export const apiErrorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    retryable: z.boolean(),
    request_id: z.string().nullable().optional(),
  }),
});

export const musicLanguageSchema = z.enum([
  'English',
  'Hindi',
  'Punjabi',
  'Instrumental',
]);

export const musicMoodSchema = z.enum([
  'calm',
  'energetic',
  'romantic',
  'joyful',
  'moody',
  'dreamy',
  'bold',
  'nostalgic',
]);

export const musicPreferenceSchema = z.object({
  preferred_languages: z.array(musicLanguageSchema).max(4),
  preferred_moods: z.array(musicMoodSchema).max(8),
  favorite_artists: z.array(z.string().min(1).max(100)).max(12),
  favorite_tracks: z.array(z.string().min(1).max(150)).max(12),
  default_vocal_preference: storyVocalPreferenceSchema,
  profile_version: z.string(),
  revision: z.number().int().nonnegative(),
  updated_at: z.string().datetime({ offset: true }).nullable(),
  onboarding_completed_at: z.string().datetime({ offset: true }).nullable(),
});

export type AnalysisResult = z.infer<typeof analysisResultSchema>;
export type VideoAnalysisResult = z.infer<typeof videoAnalysisResultSchema>;
export type StorySongResult = z.infer<typeof storySongResultSchema>;
export type AnalysisMode = z.infer<typeof analysisModeSchema>;
export type StoryVocalPreference = z.infer<typeof storyVocalPreferenceSchema>;
export type MusicLanguage = z.infer<typeof musicLanguageSchema>;
export type MusicMood = z.infer<typeof musicMoodSchema>;
export type MusicPreference = z.infer<typeof musicPreferenceSchema>;
export type MusicPreferenceUpdate = Pick<
  MusicPreference,
  | 'preferred_languages'
  | 'preferred_moods'
  | 'favorite_artists'
  | 'favorite_tracks'
  | 'default_vocal_preference'
> & {
  complete_onboarding?: boolean;
};
export type AnalysisStatus = z.infer<typeof analysisStatusSchema>;
export type AnalysisStage = z.infer<typeof analysisStageSchema>;
export type AnalysisStatusResponse = z.infer<
  typeof analysisStatusResponseSchema
>;
export type AnalysisListItem = z.infer<typeof analysisListItemSchema>;
export type AnalysisListResponse = z.infer<typeof analysisListResponseSchema>;
export type AnalysisCreatedResponse = z.infer<
  typeof analysisCreatedResponseSchema
>;
export type AnalysisSubmitResponse = z.infer<
  typeof analysisSubmitResponseSchema
>;

export const terminalStatuses = new Set<AnalysisStatus>([
  'completed',
  'failed',
  'cancelled',
  'expired',
]);
