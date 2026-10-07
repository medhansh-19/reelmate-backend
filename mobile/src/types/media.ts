export type AnalysisMode = 'video_coach' | 'story_song';
export type StoryVocalPreference = 'any' | 'no_lyrics';
export type SupportedVideoMime = 'video/mp4' | 'video/quicktime';
export type SupportedImageMime = 'image/jpeg' | 'image/png' | 'image/webp';
export type SupportedMediaMime = SupportedVideoMime | SupportedImageMime;

type SelectedMediaBase = {
  idempotencyKey: string;
  uri: string;
  filename: string;
  sizeBytes: number;
  width: number;
  height: number;
  webFile?: Blob;
};

export type SelectedVideo = SelectedMediaBase & {
  mode: 'video_coach';
  mimeType: SupportedVideoMime;
  durationSeconds: number | null;
};

export type SelectedImage = SelectedMediaBase & {
  mode: 'story_song';
  mimeType: SupportedImageMime;
  durationSeconds: null;
  vocalPreference: StoryVocalPreference;
};

export type SelectedMedia = SelectedVideo | SelectedImage;
