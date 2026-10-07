import type {
  AnalysisListItem,
  AnalysisListResponse,
  AnalysisResult,
  AnalysisStage,
  AnalysisStatus,
  AnalysisStatusResponse,
  AnalysisSubmitResponse,
  MusicPreference,
  StorySongResult,
} from '@/lib/api-schemas';
import type { AnalysisMode, StoryVocalPreference } from '@/types/media';

type DemoJob = {
  createdAt: number;
  mode: AnalysisMode;
  vocalPreference: StoryVocalPreference;
  musicPreference: MusicPreference | null;
  cancelled?: boolean;
  deleted?: boolean;
};

const demoJobs = new Map<string, DemoJob>();
const deletedSeedIds = new Set<string>();

const sampleResult: AnalysisResult = {
  schema_version: '1',
  mode: 'video_coach',
  score: 82,
  score_label: 'reel_readiness',
  score_experimental: true,
  confidence: 0.91,
  sub_scores: { hook: 91, pacing: 74, av_sync: 86, text: 77, trend: null },
  niche_detected: 'fitness',
  niche_confidence: 0.86,
  feedback_source: 'local_signal_engine',
  feedback: [
    {
      type: 'strength',
      start_seconds: 0,
      end_seconds: 2.4,
      severity: 'low',
      message: 'The opening movement creates an immediate visual question.',
      action: 'Keep this first shot and preserve its quick reveal.',
      evidence:
        'Motion is strongest in the first two seconds and the subject is already visible.',
    },
    {
      type: 'pacing',
      start_seconds: 7.2,
      end_seconds: 10.8,
      severity: 'medium',
      message:
        'The middle demonstration holds longer than the rest of the edit.',
      action: 'Trim about one second or add a closer crop at the key movement.',
      evidence:
        'This is the longest measured clip while the surrounding cuts are faster.',
    },
    {
      type: 'text',
      start_seconds: 3.1,
      end_seconds: 5.6,
      severity: 'medium',
      message:
        'The benefit text is readable, but it arrives after the visual promise.',
      action:
        'Move the benefit line into the first two seconds and keep it above the bottom UI zone.',
      evidence:
        'Readable text appears after the hook window and the overlay sits low in frame.',
    },
    {
      type: 'audio',
      start_seconds: 11.3,
      end_seconds: 13.2,
      severity: 'low',
      message: 'The final cut lands slightly away from the nearest beat.',
      action: 'Nudge the ending cut earlier by roughly two frames.',
      evidence:
        'The measured scene change is offset from the nearest detected beat.',
    },
  ],
  pipeline_summary: {
    duration_seconds: 18.4,
    has_audio: true,
    niche: 'fitness',
    audio: { energy: 'high' },
    scenes: { cuts_count: 10, average_clip_length_seconds: 1.84 },
  },
  versions: {
    pipeline: 'pipeline-v1',
    score: 'score-v1',
    prompt: 'feedback-v1',
    model: 'preview-model',
  },
  usage: {
    model_input_tokens: 1380,
    model_output_tokens: 312,
    estimated_model_cost_usd: 0.003252,
    estimated_total_cost_usd: null,
    pricing_status: 'metered',
    pricing_version: 'preview',
    cost_limit_exceeded: false,
    external_api_used: false,
  },
  personalization: {
    submission_count: 4,
    inferred_niche: 'fitness',
    niche_confidence: 0.75,
    editing_style: 'fast-cut',
    editing_style_confidence: 0.75,
    typical_energy: 'high',
    typical_energy_confidence: 1,
    recurring_issue_codes: [],
    profile_version: '1',
    is_repeat_user: true,
    previous_score: 76,
    score_delta: 6,
    improvement_noted: true,
  },
};

const sampleStoryResult: StorySongResult = {
  schema_version: '3',
  mode: 'story_song',
  requested_vocal_preference: 'any',
  score: 91,
  confidence: 0.87,
  image_summary: {
    width: 1080,
    height: 1920,
    brightness: 0.71,
    saturation: 0.62,
    contrast: 0.48,
    warmth: 0.68,
    colorfulness: 0.7,
    edge_density: 0.24,
    center_activity: 0.42,
    face_count: 1,
    face_prominence: 0.28,
    dominant_colors: ['gold', 'orange', 'blue'],
    visual_tags: ['portrait', 'bright', 'colorful', 'warm', 'vertical'],
    mood_profile: {
      calm: 0.31,
      energetic: 0.35,
      romantic: 0.45,
      joyful: 0.46,
      moody: 0.2,
      dreamy: 0.4,
      bold: 0.29,
      nostalgic: 0.33,
    },
  },
  recommendations: [
    {
      song_id: 'golden-hour-jvke',
      title: 'golden hour',
      artist: 'JVKE',
      language: 'English',
      match_score: 94,
      bpm: 94,
      energy: 'medium',
      vocal_type: 'full_lyrics',
      has_lyrics: true,
      aesthetic_tags: ['sunset', 'romantic', 'warm'],
      matched_moods: ['romantic', 'dreamy'],
      why: "Matches the image's romantic and dreamy profile, supported by its portrait, bright visual signals.",
      search_query: 'golden hour JVKE',
    },
    {
      song_id: 'heeriye-jasleen-royal',
      title: 'Heeriye',
      artist: 'Jasleen Royal feat. Arijit Singh',
      language: 'Hindi',
      match_score: 91,
      bpm: 105,
      energy: 'medium',
      vocal_type: 'full_lyrics',
      has_lyrics: true,
      aesthetic_tags: ['romantic', 'warm', 'portrait'],
      matched_moods: ['romantic', 'joyful'],
      why: "Matches the image's romantic and joyful profile, supported by its warm, colorful visual signals.",
      search_query: 'Heeriye Jasleen Royal Arijit Singh',
    },
    {
      song_id: 'experience-ludovico-einaudi',
      title: 'Experience',
      artist: 'Ludovico Einaudi',
      language: 'Instrumental',
      match_score: 88,
      bpm: null,
      energy: 'medium',
      vocal_type: 'none',
      has_lyrics: false,
      aesthetic_tags: ['cinematic', 'dreamy', 'travel'],
      matched_moods: ['dreamy', 'calm'],
      why: "Matches the image's dreamy and calm profile, supported by its warm, bright visual signals. It has no lyrics, leaving space for the image.",
      search_query: 'Experience Ludovico Einaudi',
    },
    {
      song_id: 'river-flows-in-you-yiruma',
      title: 'River Flows in You',
      artist: 'Yiruma',
      language: 'Instrumental',
      match_score: 86,
      bpm: null,
      energy: 'low',
      vocal_type: 'none',
      has_lyrics: false,
      aesthetic_tags: ['romantic', 'soft', 'portrait'],
      matched_moods: ['romantic', 'calm'],
      why: "Matches the image's romantic and calm profile, supported by its portrait, warm visual signals. It has no lyrics, leaving space for the image.",
      search_query: 'River Flows in You Yiruma',
    },
    {
      song_id: 'intro-the-xx',
      title: 'Intro',
      artist: 'The xx',
      language: 'Instrumental',
      match_score: 84,
      bpm: null,
      energy: 'medium',
      vocal_type: 'none',
      has_lyrics: false,
      aesthetic_tags: ['night', 'minimal', 'cinematic'],
      matched_moods: ['dreamy', 'moody'],
      why: "Matches the image's dreamy and moody profile, supported by its colorful, portrait visual signals. It has no lyrics, leaving space for the image.",
      search_query: 'Intro The xx',
    },
  ],
  personalization: {
    applied: true,
    source: 'first_party',
    signals_provided: ['preferred_languages', 'preferred_moods'],
    signals_used: ['preferred_languages', 'preferred_moods'],
    profile_version: '1',
    profile_revision: 1,
    profile_updated_at: '2026-08-09T12:00:00.000Z',
    resolution: 'processing_start',
    spotify_data_used: false,
  },
  versions: {
    pipeline: 'story-vision-v1',
    ranking_model: 'visual-song-mmr-v2',
    catalog: 'reelmate-curated-catalog-2026-08-v2',
  },
  privacy: {
    external_api_used: false,
    source_included_in_result: false,
    source_cleanup: 'durable_outbox',
  },
};

const storyResultForPreference = (
  preference: StoryVocalPreference,
  musicPreference: MusicPreference | null,
): StorySongResult => ({
  ...sampleStoryResult,
  requested_vocal_preference: preference,
  recommendations:
    preference === 'no_lyrics'
      ? sampleStoryResult.recommendations.filter(
          (recommendation) => !recommendation.has_lyrics,
        )
      : sampleStoryResult.recommendations,
  personalization: {
    applied: false,
    source:
      musicPreference &&
      (musicPreference.preferred_languages.length > 0 ||
        musicPreference.preferred_moods.length > 0 ||
        musicPreference.favorite_artists.length > 0 ||
        musicPreference.favorite_tracks.length > 0)
        ? 'first_party'
        : 'none',
    signals_provided: musicPreference
      ? [
          ...(musicPreference.preferred_languages.length > 0
            ? (['preferred_languages'] as const)
            : []),
          ...(musicPreference.preferred_moods.length > 0
            ? (['preferred_moods'] as const)
            : []),
          ...(musicPreference.favorite_artists.length > 0
            ? (['favorite_artists'] as const)
            : []),
          ...(musicPreference.favorite_tracks.length > 0
            ? (['favorite_tracks'] as const)
            : []),
        ]
      : [],
    signals_used: [],
    profile_version: musicPreference?.profile_version ?? null,
    profile_revision:
      musicPreference && musicPreference.revision > 0
        ? musicPreference.revision
        : null,
    profile_updated_at: musicPreference?.updated_at ?? null,
    resolution: musicPreference ? 'processing_start' : 'none',
    spotify_data_used: false,
  },
});

const seedItems: AnalysisListItem[] = [
  {
    analysis_id: '10000000-0000-4000-8000-000000000001',
    mode: 'story_song',
    vocal_preference: 'any',
    status: 'completed',
    stage: 'completed',
    score: 91,
    niche_detected: null,
    created_at: new Date(Date.now() - 2 * 86_400_000).toISOString(),
  },
  {
    analysis_id: '10000000-0000-4000-8000-000000000002',
    mode: 'video_coach',
    vocal_preference: 'any',
    status: 'completed',
    stage: 'completed',
    score: 76,
    niche_detected: 'fitness',
    created_at: new Date(Date.now() - 8 * 86_400_000).toISOString(),
  },
];

const makeId = () => {
  const random = Math.random()
    .toString(16)
    .slice(2)
    .padEnd(12, '0')
    .slice(0, 12);
  return `20000000-0000-4000-8000-${random}`;
};

const jobState = (
  job: DemoJob,
): { status: AnalysisStatus; stage: AnalysisStage } => {
  if (job.cancelled) return { status: 'cancelled', stage: 'cancelled' };
  const elapsed = Date.now() - job.createdAt;
  if (elapsed < 1_500) return { status: 'queued', stage: 'queued' };
  if (elapsed < 4_000) return { status: 'processing', stage: 'validating' };
  if (elapsed < 7_000) return { status: 'processing', stage: 'extracting' };
  if (elapsed < 9_000) return { status: 'processing', stage: 'scoring' };
  if (job.mode === 'story_song')
    return { status: 'completed', stage: 'completed' };
  if (elapsed < 12_000)
    return { status: 'processing', stage: 'generating_feedback' };
  return { status: 'completed', stage: 'completed' };
};

export const demoStartAnalysis = async (
  mode: AnalysisMode,
  vocalPreference: StoryVocalPreference = 'any',
  musicPreference: MusicPreference | null = null,
): Promise<AnalysisSubmitResponse> => {
  const id = makeId();
  demoJobs.set(id, {
    createdAt: Date.now(),
    mode,
    vocalPreference,
    musicPreference:
      mode === 'story_song' && musicPreference
        ? {
            ...musicPreference,
            preferred_languages: [...musicPreference.preferred_languages],
            preferred_moods: [...musicPreference.preferred_moods],
            favorite_artists: [...musicPreference.favorite_artists],
            favorite_tracks: [...musicPreference.favorite_tracks],
          }
        : null,
  });
  return {
    analysis_id: id,
    mode,
    vocal_preference: vocalPreference,
    status: 'queued',
    stage: 'queued',
  };
};

export const demoGetAnalysis = async (
  analysisId: string,
): Promise<AnalysisStatusResponse> => {
  const now = new Date().toISOString();
  if (
    !deletedSeedIds.has(analysisId) &&
    (analysisId === seedItems[0].analysis_id ||
      analysisId === seedItems[1].analysis_id)
  ) {
    return {
      analysis_id: analysisId,
      mode: seedItems.find((item) => item.analysis_id === analysisId)!.mode,
      vocal_preference: seedItems.find(
        (item) => item.analysis_id === analysisId,
      )!.vocal_preference,
      status: 'completed',
      stage: 'completed',
      retryable: false,
      failure_code: null,
      result:
        analysisId === seedItems[0].analysis_id
          ? sampleStoryResult
          : { ...sampleResult, score: 76 },
      created_at: seedItems.find((item) => item.analysis_id === analysisId)!
        .created_at,
      updated_at: now,
    };
  }
  const job = demoJobs.get(analysisId);
  if (!job || job.deleted)
    throw new Error('This preview analysis no longer exists.');
  const state = jobState(job);
  return {
    analysis_id: analysisId,
    mode: job.mode,
    vocal_preference: job.vocalPreference,
    ...state,
    retryable: false,
    failure_code: null,
    result:
      state.status === 'completed'
        ? job.mode === 'story_song'
          ? storyResultForPreference(job.vocalPreference, job.musicPreference)
          : sampleResult
        : null,
    created_at: new Date(job.createdAt).toISOString(),
    updated_at: now,
  };
};

export const demoListAnalyses = async (): Promise<AnalysisListResponse> => {
  const jobs: AnalysisListItem[] = [...demoJobs.entries()]
    .filter(([, job]) => !job.deleted)
    .map(([analysisId, job]) => {
      const state = jobState(job);
      return {
        analysis_id: analysisId,
        mode: job.mode,
        vocal_preference: job.vocalPreference,
        ...state,
        score:
          state.status === 'completed'
            ? job.mode === 'story_song'
              ? sampleStoryResult.score
              : sampleResult.score
            : null,
        niche_detected:
          state.status === 'completed' && job.mode === 'video_coach'
            ? sampleResult.niche_detected
            : null,
        created_at: new Date(job.createdAt).toISOString(),
      };
    });
  return {
    analyses: [
      ...jobs,
      ...seedItems.filter((item) => !deletedSeedIds.has(item.analysis_id)),
    ].sort((a, b) => b.created_at.localeCompare(a.created_at)),
    next_cursor: null,
  };
};

export const demoDeleteAnalysis = async (analysisId: string) => {
  const job = demoJobs.get(analysisId);
  if (job) job.deleted = true;
  if (seedItems.some((item) => item.analysis_id === analysisId))
    deletedSeedIds.add(analysisId);
};

export const demoCancelAnalysis = async (
  analysisId: string,
): Promise<AnalysisSubmitResponse> => {
  const job = demoJobs.get(analysisId);
  if (!job || job.deleted)
    throw new Error('This preview analysis no longer exists.');
  job.cancelled = true;
  return {
    analysis_id: analysisId,
    mode: job.mode,
    vocal_preference: job.vocalPreference,
    status: 'cancelled',
    stage: 'cancelled',
  };
};

export const demoRetryAnalysis = async (
  analysisId: string,
): Promise<AnalysisSubmitResponse> => {
  const job = demoJobs.get(analysisId);
  if (!job)
    throw new Error('Only newly created preview analyses can be retried.');
  job.createdAt = Date.now();
  job.cancelled = false;
  return {
    analysis_id: analysisId,
    mode: job.mode,
    vocal_preference: job.vocalPreference,
    status: 'queued',
    stage: 'queued',
  };
};
