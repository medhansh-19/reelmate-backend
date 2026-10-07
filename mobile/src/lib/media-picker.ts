import { File as ExpoFile } from 'expo-file-system';
import * as ImagePicker from 'expo-image-picker';

import type {
  AnalysisMode,
  SelectedImage,
  SelectedMedia,
  SelectedVideo,
  SupportedImageMime,
  SupportedVideoMime,
} from '@/types/media';

const MAX_VIDEO_BYTES = 100_000_000;
const MAX_IMAGE_BYTES = 15_000_000;
const MAX_DURATION_SECONDS = 90;

const createUploadAttemptKey = () =>
  `mobile-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;

const videoMime = (
  mime: string | null | undefined,
  name: string,
): SupportedVideoMime | null => {
  const normalized = mime?.toLowerCase();
  if (normalized === 'video/mp4') return 'video/mp4';
  if (normalized === 'video/quicktime') return 'video/quicktime';
  if (name.toLowerCase().endsWith('.mov')) return 'video/quicktime';
  if (name.toLowerCase().endsWith('.mp4')) return 'video/mp4';
  return null;
};

const imageMime = (
  mime: string | null | undefined,
  name: string,
): SupportedImageMime | null => {
  const normalized = mime?.toLowerCase();
  if (normalized === 'image/jpeg') return 'image/jpeg';
  if (normalized === 'image/png') return 'image/png';
  if (normalized === 'image/webp') return 'image/webp';
  const lower = name.toLowerCase();
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg';
  if (lower.endsWith('.png')) return 'image/png';
  if (lower.endsWith('.webp')) return 'image/webp';
  return null;
};

export const pickMedia = async (
  mode: AnalysisMode,
): Promise<SelectedMedia | null> => {
  if (mode === 'video_coach' && process.env.EXPO_OS === 'ios') {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted)
      throw new Error('Allow photo-library access to choose a reel.');
  }

  const pending =
    process.env.EXPO_OS === 'android'
      ? await ImagePicker.getPendingResultAsync()
      : null;
  if (pending && 'code' in pending)
    throw new Error('Android could not restore the previously selected media.');
  const result =
    pending && !pending.canceled
      ? pending
      : await ImagePicker.launchImageLibraryAsync(
          mode === 'video_coach'
            ? {
                mediaTypes: ['videos'],
                allowsEditing: false,
                allowsMultipleSelection: false,
                quality: 1,
                videoExportPreset: ImagePicker.VideoExportPreset.Passthrough,
              }
            : {
                mediaTypes: ['images'],
                allowsEditing: true,
                allowsMultipleSelection: false,
                aspect: [9, 16],
                quality: 0.9,
              },
        );
  if (result.canceled) return null;

  const asset = result.assets[0];
  const guessedName =
    asset.fileName ||
    asset.uri.split('/').pop() ||
    (mode === 'video_coach' ? 'reel.mp4' : 'story.jpg');
  const localFile = asset.file ?? new ExpoFile(asset.uri);
  const sizeBytes = asset.fileSize ?? localFile.size;
  if (!sizeBytes || sizeBytes <= 0)
    throw new Error('The selected media could not be read.');
  const base = {
    idempotencyKey: createUploadAttemptKey(),
    uri: asset.uri,
    sizeBytes,
    width: asset.width,
    height: asset.height,
    webFile: asset.file,
  };

  if (mode === 'story_song') {
    const mimeType = imageMime(asset.mimeType, guessedName);
    if (!mimeType)
      throw new Error(
        'Choose a JPEG, PNG, or WebP image. HEIC should be cropped/exported first.',
      );
    if (sizeBytes > MAX_IMAGE_BYTES)
      throw new Error('Choose an image smaller than 15 MB.');
    const extension =
      mimeType === 'image/jpeg'
        ? 'jpg'
        : mimeType === 'image/png'
          ? 'png'
          : 'webp';
    const filename = guessedName.toLowerCase().endsWith(`.${extension}`)
      ? guessedName
      : `story-${Date.now()}.${extension}`;
    const selected: SelectedImage = {
      ...base,
      mode,
      mimeType,
      filename,
      durationSeconds: null,
      vocalPreference: 'any',
    };
    return selected;
  }

  const mimeType = videoMime(asset.mimeType, guessedName);
  if (!mimeType) throw new Error('Choose an MP4 or MOV video.');
  if (sizeBytes > MAX_VIDEO_BYTES)
    throw new Error('Choose a video smaller than 100 MB.');
  const durationSeconds = asset.duration == null ? null : asset.duration / 1000;
  if (durationSeconds !== null && durationSeconds > MAX_DURATION_SECONDS)
    throw new Error('Choose a reel that is 90 seconds or shorter.');
  const extension = mimeType === 'video/mp4' ? 'mp4' : 'mov';
  const filename = guessedName.toLowerCase().endsWith(`.${extension}`)
    ? guessedName
    : `reel-${Date.now()}.${extension}`;
  const selected: SelectedVideo = {
    ...base,
    mode,
    mimeType,
    filename,
    durationSeconds,
  };
  return selected;
};
