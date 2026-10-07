import { Image } from 'expo-image';
import { router, useLocalSearchParams, useNavigation } from 'expo-router';
import { useVideoPlayer, VideoView } from 'expo-video';
import { useEffect, useRef, useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';

import {
  Card,
  ErrorState,
  PrimaryButton,
  SecondaryButton,
  Surface,
} from '@/components';
import { useStartAnalysis } from '@/hooks/use-analyses';
import { useMusicPreferences } from '@/hooks/use-music-preferences';
import { ApiError } from '@/lib/api-client';
import { showMessage } from '@/lib/dialogs';
import { pickMedia } from '@/lib/media-picker';
import { useReelMateTheme } from '@/theme';
import type {
  AnalysisMode,
  SelectedMedia,
  SelectedVideo,
  StoryVocalPreference,
} from '@/types/media';

const formatBytes = (bytes: number) =>
  `${(bytes / 1_000_000).toFixed(bytes > 10_000_000 ? 0 : 1)} MB`;

const formatRoundedTime = (seconds: number) => {
  const rounded = Math.round(seconds);
  return `${Math.floor(rounded / 60)}:${(rounded % 60).toString().padStart(2, '0')}`;
};

function VideoPreview({ video }: { video: SelectedVideo }) {
  const theme = useReelMateTheme();
  const player = useVideoPlayer(video.uri, (instance) => {
    instance.loop = true;
    instance.muted = true;
  });
  return (
    <VideoView
      accessibilityLabel="Selected reel preview"
      contentFit="cover"
      fullscreenOptions={{ enable: true }}
      nativeControls
      player={player}
      style={{
        width: '100%',
        aspectRatio: video.width > video.height ? 16 / 9 : 9 / 13,
        maxHeight: 480,
        borderRadius: theme.radii.lg,
        borderCurve: 'continuous',
        backgroundColor: '#000',
      }}
    />
  );
}

function MediaPreview({ media }: { media: SelectedMedia }) {
  const theme = useReelMateTheme();
  if (media.mode === 'video_coach') return <VideoPreview video={media} />;
  return (
    <Image
      accessibilityLabel="Selected story image preview"
      contentFit="cover"
      source={media.uri}
      style={{
        width: '100%',
        aspectRatio: 9 / 16,
        maxHeight: 560,
        borderRadius: theme.radii.lg,
        backgroundColor: theme.colors.surfaceMuted,
      }}
      transition={180}
    />
  );
}

function VocalChoice({
  label,
  detail,
  selected,
  onPress,
}: {
  label: string;
  detail: string;
  selected: boolean;
  onPress: () => void;
}) {
  const theme = useReelMateTheme();
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ checked: selected }}
      onPress={onPress}
      style={({ pressed }) => ({
        flexGrow: 1,
        flexBasis: 220,
        gap: theme.spacing.xs,
        padding: theme.spacing.lg,
        borderRadius: theme.radii.lg,
        borderCurve: 'continuous',
        borderWidth: selected ? 2 : 1,
        borderColor: selected ? theme.colors.accent : theme.colors.separator,
        backgroundColor: selected
          ? theme.colors.accentSoft
          : pressed
            ? theme.colors.surfaceMuted
            : theme.colors.surfaceRaised,
        opacity: pressed ? 0.8 : 1,
      })}
    >
      <Text
        style={{ color: theme.colors.text, ...theme.typography.bodyStrong }}
      >
        {label}
      </Text>
      <Text
        style={{ color: theme.colors.textMuted, ...theme.typography.caption }}
      >
        {detail}
      </Text>
    </Pressable>
  );
}

export function UploadScreen() {
  const theme = useReelMateTheme();
  const navigation = useNavigation();
  const params = useLocalSearchParams<{ mode?: string }>();
  const mode: AnalysisMode =
    params.mode === 'story_song' ? 'story_song' : 'video_coach';
  const isStory = mode === 'story_song';
  const allowNavigation = useRef(false);
  const mounted = useRef(true);
  const [media, setMedia] = useState<SelectedMedia | null>(null);
  const [vocalOverride, setVocalOverride] =
    useState<StoryVocalPreference | null>(null);
  const [pickerError, setPickerError] = useState<string | null>(null);
  const musicPreferences = useMusicPreferences(isStory);
  const start = useStartAnalysis();
  const activeMedia = media?.mode === mode ? media : null;
  const vocalPreference: StoryVocalPreference =
    vocalOverride ?? musicPreferences.data?.default_vocal_preference ?? 'any';
  const preferenceReady =
    !isStory || vocalOverride !== null || musicPreferences.data !== undefined;

  useEffect(
    () => () => {
      mounted.current = false;
    },
    [],
  );

  useEffect(() => {
    if (!start.isPending) return;
    return navigation.addListener('beforeRemove', (event) => {
      if (allowNavigation.current) return;
      event.preventDefault();
      showMessage(
        'Private upload in progress',
        'Keep this screen open until ReelMate confirms the upload.',
      );
    });
  }, [navigation, start.isPending]);

  const choose = async () => {
    setPickerError(null);
    try {
      const selected = await pickMedia(mode);
      if (selected) setMedia(selected);
    } catch (error) {
      setPickerError(
        error instanceof Error
          ? error.message
          : 'The media could not be selected.',
      );
    }
  };

  const analyze = async () => {
    if (!activeMedia) return;
    if (!preferenceReady) {
      showMessage(
        'Choose a sound type',
        'Wait for your saved default or choose Best overall / Aesthetic · no lyrics.',
      );
      return;
    }
    try {
      const selectedForAnalysis =
        activeMedia.mode === 'story_song'
          ? { ...activeMedia, vocalPreference }
          : activeMedia;
      const analysis = await start.mutateAsync(selectedForAnalysis);
      if (!mounted.current) return;
      allowNavigation.current = true;
      router.replace({
        pathname: '/analysis/[id]',
        params: { id: analysis.analysis_id },
      });
    } catch {
      // The mutation keeps the stable API message visible below.
    }
  };

  const mutationMessage =
    start.error instanceof ApiError
      ? start.error.message
      : start.error instanceof Error
        ? start.error.message
        : null;
  const phaseLabel =
    start.phase === 'creating'
      ? 'Preparing private upload…'
      : start.phase === 'uploading'
        ? 'Uploading securely…'
        : isStory
          ? 'Starting song match…'
          : 'Starting reel analysis…';

  return (
    <ScrollView
      contentInsetAdjustmentBehavior="automatic"
      contentContainerStyle={{
        width: '100%',
        maxWidth: theme.layout.contentMaxWidth,
        alignSelf: 'center',
        padding: theme.spacing.xl,
        paddingBottom: theme.spacing.hero,
        gap: theme.spacing.xxl,
      }}
    >
      <View style={{ gap: theme.spacing.sm }}>
        <Text
          style={{ color: theme.colors.accent, ...theme.typography.eyebrow }}
        >
          {isStory ? 'STORY SONG MATCH' : 'VIDEO COACH'}
        </Text>
        <Text
          selectable
          style={{ color: theme.colors.text, ...theme.typography.display }}
        >
          {isStory ? 'Find the sound in your frame.' : 'Bring the cut.'}
        </Text>
        <Text
          selectable
          style={{ color: theme.colors.textMuted, ...theme.typography.body }}
        >
          {isStory
            ? 'JPEG, PNG, or WebP · under 15 MB · matched by local visual signals'
            : 'MP4 or MOV · up to 90 seconds · under 100 MB'}
        </Text>
      </View>

      {isStory ? (
        <View accessibilityRole="radiogroup" style={{ gap: theme.spacing.md }}>
          <View style={{ gap: theme.spacing.xs }}>
            <Text
              style={{
                color: theme.colors.text,
                ...theme.typography.bodyStrong,
              }}
            >
              What kind of sound?
            </Text>
            <Text
              selectable
              style={{
                color: theme.colors.textMuted,
                ...theme.typography.caption,
              }}
            >
              You can change the default in your Music taste profile.
            </Text>
          </View>
          <View
            style={{
              flexDirection: 'row',
              flexWrap: 'wrap',
              gap: theme.spacing.md,
            }}
          >
            <VocalChoice
              detail="Lyrics or instrumental—whichever fits the image best."
              label="Best overall"
              selected={vocalPreference === 'any'}
              onPress={() => setVocalOverride('any')}
            />
            <VocalChoice
              detail="Only aesthetic tunes with no lyrics."
              label="Aesthetic · no lyrics"
              selected={vocalPreference === 'no_lyrics'}
              onPress={() => setVocalOverride('no_lyrics')}
            />
          </View>
          {musicPreferences.isError && vocalOverride === null ? (
            <ErrorState
              compact
              title="Saved default unavailable"
              message="Choose a sound type above, or retry your private music preferences."
              actionLabel="Retry preferences"
              onAction={() => void musicPreferences.refetch()}
            />
          ) : null}
        </View>
      ) : null}

      {activeMedia ? (
        <Card padding="compact" style={{ gap: theme.spacing.lg }}>
          <MediaPreview media={activeMedia} />
          <View
            style={{
              gap: theme.spacing.xs,
              paddingHorizontal: theme.spacing.sm,
            }}
          >
            <Text
              selectable
              numberOfLines={1}
              style={{
                color: theme.colors.text,
                ...theme.typography.bodyStrong,
              }}
            >
              {activeMedia.filename}
            </Text>
            <Text
              selectable
              style={{
                color: theme.colors.textMuted,
                ...theme.typography.caption,
              }}
            >
              {activeMedia.mode === 'video_coach' &&
              activeMedia.durationSeconds !== null
                ? `${formatRoundedTime(activeMedia.durationSeconds)} · `
                : ''}
              {formatBytes(activeMedia.sizeBytes)} ·{' '}
              {activeMedia.mimeType.split('/')[1].toUpperCase()}
            </Text>
          </View>
          <SecondaryButton
            fullWidth
            disabled={start.isPending}
            label={
              isStory ? 'Choose a different image' : 'Choose a different reel'
            }
            onPress={() => void choose()}
          />
        </Card>
      ) : (
        <Surface
          variant="accent"
          style={{
            minHeight: 320,
            alignItems: 'center',
            justifyContent: 'center',
            gap: theme.spacing.xl,
          }}
        >
          <View
            style={{
              width: 82,
              height: 108,
              borderRadius: theme.radii.lg,
              borderCurve: 'continuous',
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: theme.colors.surfaceRaised,
              transform: [{ rotate: isStory ? '-4deg' : '4deg' }],
            }}
          >
            <Text
              style={{
                color: theme.colors.accent,
                fontSize: 34,
                fontWeight: '900',
              }}
            >
              {isStory ? '♫' : '▶'}
            </Text>
          </View>
          <View style={{ alignItems: 'center', gap: theme.spacing.sm }}>
            <Text
              selectable
              style={{ color: theme.colors.text, ...theme.typography.title }}
            >
              {isStory
                ? 'Choose your story image'
                : 'Choose one finished draft'}
            </Text>
            <Text
              selectable
              style={{
                maxWidth: 440,
                color: theme.colors.textMuted,
                textAlign: 'center',
                ...theme.typography.caption,
              }}
            >
              {isStory
                ? 'ReelMate measures the image mood and ranks matching songs without sending it to a generative AI.'
                : 'ReelMate measures scenes, motion, text, audio, and beat alignment on its own worker.'}
            </Text>
          </View>
          <PrimaryButton
            label="Choose from library"
            onPress={() => void choose()}
          />
        </Surface>
      )}

      {pickerError ? (
        <ErrorState
          compact
          title="Couldn’t use that file"
          message={pickerError}
          actionLabel="Try another"
          onAction={() => void choose()}
        />
      ) : null}
      {mutationMessage ? (
        <ErrorState
          compact
          title="Analysis did not start"
          message={mutationMessage}
          actionLabel="Try again"
          onAction={() => void analyze()}
        />
      ) : null}

      <Card style={{ gap: theme.spacing.md }}>
        <Text
          style={{
            color: theme.colors.textSubtle,
            ...theme.typography.eyebrow,
          }}
        >
          REELMATE&apos;S OWN ENGINE
        </Text>
        <Text
          selectable
          style={{ color: theme.colors.text, ...theme.typography.bodyStrong }}
        >
          No GPT recommendation call. Source media stays private and cleanup is
          durably queued when processing ends.
        </Text>
        <Text
          selectable
          style={{ color: theme.colors.textMuted, ...theme.typography.caption }}
        >
          {isStory
            ? 'Visual features are converted into a mood profile and matched against ReelMate’s versioned song catalogue.'
            : 'Every coaching note comes from measured timestamps, scores, and ReelMate’s versioned local rules.'}
        </Text>
      </Card>

      <PrimaryButton
        fullWidth
        disabled={!activeMedia || !preferenceReady}
        loading={start.isPending}
        label={
          start.isPending
            ? phaseLabel
            : isStory && !preferenceReady
              ? musicPreferences.isError
                ? 'Choose a sound type'
                : 'Loading your music default…'
              : isStory
                ? 'Find matching songs'
                : 'Analyze this reel'
        }
        onPress={() => void analyze()}
      />
    </ScrollView>
  );
}
