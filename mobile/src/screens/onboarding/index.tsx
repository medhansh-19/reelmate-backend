import * as Haptics from 'expo-haptics';
import { Redirect, router, useLocalSearchParams } from 'expo-router';
import { useRef, useState } from 'react';
import {
  KeyboardAvoidingView,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from 'react-native';
import Animated, {
  FadeInLeft,
  FadeInRight,
  FadeOut,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { PrimaryButton, ReelMateWordmark, StatePanel } from '@/components';
import {
  useMusicPreferences,
  useUpdateMusicPreferences,
} from '@/hooks/use-music-preferences';
import type {
  MusicLanguage,
  MusicMood,
  MusicPreference,
  StoryVocalPreference,
} from '@/lib/api-schemas';
import { useAuth } from '@/providers/auth-provider';
import { brandColors, useReelMateTheme } from '@/theme';

const TOTAL_STEPS = 4;

const LANGUAGE_OPTIONS: {
  value: MusicLanguage;
  label: string;
  detail: string;
}[] = [
  { value: 'English', label: 'English', detail: 'Global pop & indie' },
  { value: 'Hindi', label: 'Hindi', detail: 'Bollywood & indie' },
  { value: 'Punjabi', label: 'Punjabi', detail: 'Pop, hip-hop & folk' },
  {
    value: 'Instrumental',
    label: 'Instrumental',
    detail: 'No lyrics · ambient & cinematic',
  },
];

const MOOD_OPTIONS: { value: MusicMood; label: string }[] = [
  { value: 'dreamy', label: 'Dreamy' },
  { value: 'joyful', label: 'Joyful' },
  { value: 'romantic', label: 'Romantic' },
  { value: 'calm', label: 'Calm' },
  { value: 'energetic', label: 'Energetic' },
  { value: 'bold', label: 'Bold' },
  { value: 'moody', label: 'Moody' },
  { value: 'nostalgic', label: 'Nostalgic' },
];

const ARTIST_SUGGESTIONS = [
  'Anuv Jain',
  'A.R. Rahman',
  'Arijit Singh',
  'Diljit Dosanjh',
  'Prateek Kuhad',
  'Karan Aujla',
  'Billie Eilish',
  'Taylor Swift',
  'The Weeknd',
  'Coldplay',
  'Ludovico Einaudi',
  'Yiruma',
  'Hans Zimmer',
  'The xx',
  'Tycho',
  'Joe Hisaishi',
] as const;

const suggestionKeys = new Set(
  ARTIST_SUGGESTIONS.map((artist) => artist.toLocaleLowerCase()),
);

const commaValues = (value: string) =>
  value
    .split(',')
    .map((item) => item.trim().replace(/\s+/g, ' '))
    .filter(Boolean);

const uniqueValues = (values: string[]) => {
  const seen = new Set<string>();
  return values.filter((value) => {
    const key = value.toLocaleLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
};

function ChoicePill({
  label,
  selected,
  onPress,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
}) {
  const theme = useReelMateTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected }}
      onPress={onPress}
      style={({ pressed }) => ({
        minHeight: 46,
        justifyContent: 'center',
        paddingHorizontal: theme.spacing.lg,
        paddingVertical: theme.spacing.md,
        borderRadius: theme.radii.round,
        borderCurve: 'continuous',
        borderWidth: 1.5,
        borderColor: selected ? theme.colors.accent : theme.colors.separator,
        backgroundColor: selected
          ? theme.colors.accentSoft
          : pressed
            ? theme.colors.surfaceMuted
            : theme.colors.surface,
        opacity: pressed ? 0.78 : 1,
        transform: [{ scale: pressed ? 0.98 : 1 }],
      })}
    >
      <Text
        style={{
          color: selected ? theme.colors.accent : theme.colors.text,
          ...theme.typography.bodyStrong,
        }}
      >
        {selected ? '✓  ' : ''}
        {label}
      </Text>
    </Pressable>
  );
}

function ChoiceCard({
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
      accessibilityRole="button"
      accessibilityState={{ selected }}
      onPress={onPress}
      style={({ pressed }) => ({
        flexGrow: 1,
        flexBasis: 150,
        minHeight: 112,
        gap: theme.spacing.sm,
        padding: theme.spacing.lg,
        justifyContent: 'space-between',
        borderRadius: theme.radii.lg,
        borderCurve: 'continuous',
        borderWidth: selected ? 2 : 1,
        borderColor: selected ? theme.colors.accent : theme.colors.separator,
        backgroundColor: selected
          ? theme.colors.accentSoft
          : pressed
            ? theme.colors.surfaceMuted
            : theme.colors.surface,
        opacity: pressed ? 0.82 : 1,
        transform: [{ scale: pressed ? 0.985 : 1 }],
      })}
    >
      <View
        accessibilityElementsHidden
        style={{
          width: 24,
          height: 24,
          alignItems: 'center',
          justifyContent: 'center',
          borderRadius: 12,
          borderWidth: 1.5,
          borderColor: selected ? theme.colors.accent : theme.colors.outline,
          backgroundColor: selected
            ? theme.colors.accent
            : theme.colors.surfaceRaised,
        }}
      >
        {selected ? (
          <Text style={{ color: brandColors.ink, fontWeight: '900' }}>✓</Text>
        ) : null}
      </View>
      <View style={{ gap: 2 }}>
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
      </View>
    </Pressable>
  );
}

function VocalCard({
  title,
  detail,
  selected,
  onPress,
}: {
  title: string;
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
        flexDirection: 'row',
        alignItems: 'center',
        gap: theme.spacing.lg,
        padding: theme.spacing.xl,
        borderRadius: theme.radii.lg,
        borderCurve: 'continuous',
        borderWidth: selected ? 2 : 1,
        borderColor: selected ? theme.colors.accent : theme.colors.separator,
        backgroundColor: selected
          ? theme.colors.accentSoft
          : pressed
            ? theme.colors.surfaceMuted
            : theme.colors.surface,
        opacity: pressed ? 0.82 : 1,
      })}
    >
      <View
        accessibilityElementsHidden
        style={{
          width: 26,
          height: 26,
          borderRadius: 13,
          borderWidth: 2,
          borderColor: selected ? theme.colors.accent : theme.colors.outline,
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {selected ? (
          <View
            style={{
              width: 14,
              height: 14,
              borderRadius: 7,
              backgroundColor: theme.colors.accent,
            }}
          />
        ) : null}
      </View>
      <View style={{ flex: 1, gap: theme.spacing.xs }}>
        <Text
          style={{ color: theme.colors.text, ...theme.typography.bodyStrong }}
        >
          {title}
        </Text>
        <Text
          style={{ color: theme.colors.textMuted, ...theme.typography.caption }}
        >
          {detail}
        </Text>
      </View>
    </Pressable>
  );
}

function StepHeading({
  eyebrow,
  title,
  message,
}: {
  eyebrow: string;
  title: string;
  message: string;
}) {
  const theme = useReelMateTheme();
  return (
    <View style={{ gap: theme.spacing.md }}>
      <Text style={{ color: theme.colors.accent, ...theme.typography.eyebrow }}>
        {eyebrow}
      </Text>
      <Text
        accessibilityRole="header"
        selectable
        style={{ color: theme.colors.text, ...theme.typography.display }}
      >
        {title}
      </Text>
      <Text
        selectable
        style={{ color: theme.colors.textMuted, ...theme.typography.body }}
      >
        {message}
      </Text>
    </View>
  );
}

function OnboardingFlow({
  initial,
  editing,
}: {
  initial: MusicPreference;
  editing: boolean;
}) {
  const theme = useReelMateTheme();
  const insets = useSafeAreaInsets();
  const updatePreferences = useUpdateMusicPreferences();
  const scrollRef = useRef<ScrollView>(null);
  const [step, setStep] = useState(0);
  const [direction, setDirection] = useState<1 | -1>(1);
  const [languages, setLanguages] = useState(initial.preferred_languages);
  const [moods, setMoods] = useState(initial.preferred_moods);
  const [selectedArtists, setSelectedArtists] = useState(
    initial.favorite_artists.filter((artist) =>
      suggestionKeys.has(artist.toLocaleLowerCase()),
    ),
  );
  const [customArtists, setCustomArtists] = useState(
    initial.favorite_artists
      .filter((artist) => !suggestionKeys.has(artist.toLocaleLowerCase()))
      .join(', '),
  );
  const [tracks, setTracks] = useState(initial.favorite_tracks.join(', '));
  const [vocalPreference, setVocalPreference] = useState<StoryVocalPreference>(
    initial.default_vocal_preference,
  );
  const [error, setError] = useState<string | null>(null);

  const toggleLanguage = (value: MusicLanguage) => {
    setLanguages((current) =>
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    );
  };

  const toggleMood = (value: MusicMood) => {
    setMoods((current) =>
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    );
  };

  const toggleArtist = (artist: string) => {
    setError(null);
    if (selectedArtists.includes(artist)) {
      setSelectedArtists((current) =>
        current.filter((item) => item !== artist),
      );
      return;
    }
    const nextArtists = uniqueValues([
      ...selectedArtists,
      artist,
      ...commaValues(customArtists),
    ]);
    if (nextArtists.length > 12) {
      setError('Choose at most 12 favorite artists.');
      return;
    }
    setSelectedArtists((current) => [...current, artist]);
  };

  const goToStep = (nextStep: number) => {
    setError(null);
    setDirection(nextStep > step ? 1 : -1);
    setStep(nextStep);
    scrollRef.current?.scrollTo({ y: 0, animated: true });
    if (process.env.EXPO_OS === 'ios') {
      void Haptics.selectionAsync();
    }
  };

  const finish = async () => {
    setError(null);
    const favoriteArtists = uniqueValues([
      ...selectedArtists,
      ...commaValues(customArtists),
    ]);
    const favoriteTracks = uniqueValues(commaValues(tracks));

    if (favoriteArtists.length > 12 || favoriteTracks.length > 12) {
      setError('Keep at most 12 favorite artists and 12 favorite tracks.');
      return;
    }
    if (favoriteArtists.some((artist) => artist.length > 100)) {
      setError('Keep each artist name at 100 characters or fewer.');
      return;
    }
    if (favoriteTracks.some((track) => track.length > 150)) {
      setError('Keep each track name at 150 characters or fewer.');
      return;
    }

    try {
      await updatePreferences.mutateAsync({
        preferred_languages: languages,
        preferred_moods: moods,
        favorite_artists: favoriteArtists,
        favorite_tracks: favoriteTracks,
        default_vocal_preference: vocalPreference,
        complete_onboarding: true,
      });
      if (process.env.EXPO_OS === 'ios') {
        void Haptics.notificationAsync(
          Haptics.NotificationFeedbackType.Success,
        );
      }
      router.replace(editing ? '/profile' : '/coach');
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : 'Your music profile could not be saved. Try again.',
      );
    }
  };

  const inputStyle = {
    minHeight: 52,
    color: theme.colors.text,
    backgroundColor: theme.colors.surface,
    borderColor: theme.colors.separator,
    borderWidth: 1,
    borderRadius: theme.radii.md,
    borderCurve: 'continuous' as const,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
    ...theme.typography.body,
  };

  return (
    <KeyboardAvoidingView
      behavior={process.env.EXPO_OS === 'ios' ? 'padding' : undefined}
      style={{ flex: 1, backgroundColor: theme.colors.background }}
    >
      <View
        style={{
          paddingTop: insets.top + theme.spacing.md,
          paddingHorizontal: theme.spacing.xl,
          paddingBottom: theme.spacing.md,
          backgroundColor: theme.colors.background,
          borderBottomWidth: 1,
          borderBottomColor: theme.colors.separator,
        }}
      >
        <View
          style={{
            width: '100%',
            maxWidth: theme.layout.readingMaxWidth,
            alignSelf: 'center',
            gap: theme.spacing.lg,
          }}
        >
          <View
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: theme.spacing.lg,
            }}
          >
            <ReelMateWordmark size="compact" />
            <Pressable
              accessibilityRole="button"
              disabled={updatePreferences.isPending}
              onPress={() =>
                editing ? router.replace('/profile') : void finish()
              }
              hitSlop={12}
              style={({ pressed }) => ({ opacity: pressed ? 0.55 : 1 })}
            >
              <Text
                style={{
                  color: theme.colors.textMuted,
                  ...theme.typography.caption,
                  fontWeight: '700',
                }}
              >
                {editing ? 'Cancel' : 'Skip setup'}
              </Text>
            </Pressable>
          </View>

          <View
            accessibilityRole="progressbar"
            accessibilityValue={{ min: 1, max: TOTAL_STEPS, now: step + 1 }}
            style={{ gap: theme.spacing.sm }}
          >
            <View
              style={{
                flexDirection: 'row',
                justifyContent: 'space-between',
              }}
            >
              <Text
                style={{
                  color: theme.colors.text,
                  ...theme.typography.caption,
                }}
              >
                Your music profile
              </Text>
              <Text
                style={{
                  color: theme.colors.textMuted,
                  ...theme.typography.caption,
                }}
              >
                {step + 1} of {TOTAL_STEPS}
              </Text>
            </View>
            <View style={{ flexDirection: 'row', gap: theme.spacing.xs }}>
              {Array.from({ length: TOTAL_STEPS }, (_, index) => (
                <View
                  key={index}
                  style={{
                    flex: 1,
                    height: 4,
                    borderRadius: theme.radii.round,
                    backgroundColor:
                      index <= step
                        ? theme.colors.accent
                        : theme.colors.surfaceMuted,
                  }}
                />
              ))}
            </View>
          </View>
        </View>
      </View>

      <ScrollView
        ref={scrollRef}
        contentInsetAdjustmentBehavior="automatic"
        keyboardShouldPersistTaps="handled"
        style={{ flex: 1 }}
        contentContainerStyle={{
          flexGrow: 1,
          width: '100%',
          maxWidth: theme.layout.readingMaxWidth,
          alignSelf: 'center',
          paddingHorizontal: theme.spacing.xl,
          paddingTop: theme.spacing.xxxl,
          paddingBottom: theme.spacing.xxxl,
        }}
      >
        <Animated.View
          key={step}
          entering={(direction === 1 ? FadeInRight : FadeInLeft).duration(220)}
          exiting={FadeOut.duration(120)}
          style={{ flex: 1, gap: theme.spacing.xxxl }}
        >
          {step === 0 ? (
            <>
              <StepHeading
                eyebrow="Start with the sounds"
                title="What feels like you?"
                message="Pick every language or format you reach for. Your image still stays in charge of the final match."
              />
              <View
                style={{
                  flexDirection: 'row',
                  flexWrap: 'wrap',
                  gap: theme.spacing.md,
                }}
              >
                {LANGUAGE_OPTIONS.map((option) => (
                  <ChoiceCard
                    key={option.value}
                    label={option.label}
                    detail={option.detail}
                    selected={languages.includes(option.value)}
                    onPress={() => toggleLanguage(option.value)}
                  />
                ))}
              </View>
            </>
          ) : null}

          {step === 1 ? (
            <>
              <StepHeading
                eyebrow="Set the mood"
                title="What should your stories feel like?"
                message="Choose as many as you like. These become gentle ranking signals, not rigid filters."
              />
              <View
                style={{
                  flexDirection: 'row',
                  flexWrap: 'wrap',
                  gap: theme.spacing.md,
                }}
              >
                {MOOD_OPTIONS.map((option) => (
                  <ChoicePill
                    key={option.value}
                    label={option.label}
                    selected={moods.includes(option.value)}
                    onPress={() => toggleMood(option.value)}
                  />
                ))}
              </View>
            </>
          ) : null}

          {step === 2 ? (
            <>
              <StepHeading
                eyebrow="Add a few anchors"
                title="Who is already in your rotation?"
                message="A few favorites help ReelMate break close matches without needing your Spotify history. Everything here is optional."
              />
              <View style={{ gap: theme.spacing.xxl }}>
                <View
                  style={{
                    flexDirection: 'row',
                    flexWrap: 'wrap',
                    gap: theme.spacing.sm,
                  }}
                >
                  {ARTIST_SUGGESTIONS.map((artist) => (
                    <ChoicePill
                      key={artist}
                      label={artist}
                      selected={selectedArtists.includes(artist)}
                      onPress={() => toggleArtist(artist)}
                    />
                  ))}
                </View>

                <View style={{ gap: theme.spacing.sm }}>
                  <Text
                    style={{
                      color: theme.colors.text,
                      ...theme.typography.bodyStrong,
                    }}
                  >
                    Anyone else?
                  </Text>
                  <TextInput
                    accessibilityLabel="Other favorite artists separated by commas"
                    autoCapitalize="words"
                    maxLength={600}
                    onChangeText={setCustomArtists}
                    placeholder="Add artists, separated by commas"
                    placeholderTextColor={theme.colors.textSubtle}
                    returnKeyType="next"
                    style={inputStyle}
                    value={customArtists}
                  />
                </View>

                <View style={{ gap: theme.spacing.sm }}>
                  <Text
                    style={{
                      color: theme.colors.text,
                      ...theme.typography.bodyStrong,
                    }}
                  >
                    Songs you always come back to
                  </Text>
                  <TextInput
                    accessibilityLabel="Favorite tracks separated by commas"
                    maxLength={900}
                    onChangeText={setTracks}
                    placeholder="Experience, Husn, Lover Taylor Swift"
                    placeholderTextColor={theme.colors.textSubtle}
                    returnKeyType="done"
                    style={inputStyle}
                    value={tracks}
                  />
                  <Text
                    selectable
                    style={{
                      color: theme.colors.textMuted,
                      ...theme.typography.caption,
                    }}
                  >
                    Separate names with commas. Add an artist when a title is
                    common.
                  </Text>
                </View>
              </View>
            </>
          ) : null}

          {step === 3 ? (
            <>
              <StepHeading
                eyebrow="Choose your default"
                title="How should each search begin?"
                message="You can switch this for any image before uploading it."
              />
              <View
                accessibilityRole="radiogroup"
                style={{ gap: theme.spacing.md }}
              >
                <VocalCard
                  title="Best match overall"
                  detail="Mix lyrical songs and aesthetic instrumentals, whichever fits the image best."
                  selected={vocalPreference === 'any'}
                  onPress={() => setVocalPreference('any')}
                />
                <VocalCard
                  title="Aesthetic · no lyrics"
                  detail="Start with piano, ambient, cinematic, and other tune-first options."
                  selected={vocalPreference === 'no_lyrics'}
                  onPress={() => setVocalPreference('no_lyrics')}
                />
              </View>
              <View
                style={{
                  gap: theme.spacing.sm,
                  padding: theme.spacing.lg,
                  borderRadius: theme.radii.md,
                  borderCurve: 'continuous',
                  backgroundColor: theme.colors.highlightSoft,
                }}
              >
                <Text
                  style={{
                    color: theme.colors.text,
                    ...theme.typography.bodyStrong,
                  }}
                >
                  Image first. Your taste second.
                </Text>
                <Text
                  selectable
                  style={{
                    color: theme.colors.textMuted,
                    ...theme.typography.caption,
                  }}
                >
                  ReelMate measures the image locally, then uses these choices
                  only to personalize close recommendations. No GPT or
                  listening-history import is involved.
                </Text>
              </View>
            </>
          ) : null}
        </Animated.View>
      </ScrollView>

      <View
        style={{
          paddingHorizontal: theme.spacing.xl,
          paddingTop: theme.spacing.md,
          paddingBottom: Math.max(insets.bottom, theme.spacing.lg),
          borderTopWidth: 1,
          borderTopColor: theme.colors.separator,
          backgroundColor: theme.colors.backgroundElevated,
        }}
      >
        <View
          style={{
            width: '100%',
            maxWidth: theme.layout.readingMaxWidth,
            alignSelf: 'center',
            gap: theme.spacing.md,
          }}
        >
          {error ? (
            <Text
              accessibilityRole="alert"
              selectable
              style={{
                color: theme.colors.danger,
                ...theme.typography.caption,
              }}
            >
              {error}
            </Text>
          ) : null}
          <PrimaryButton
            fullWidth
            label={
              step === TOTAL_STEPS - 1
                ? editing
                  ? 'Save music profile'
                  : 'Build my music profile'
                : 'Continue'
            }
            loading={updatePreferences.isPending}
            onPress={() =>
              step === TOTAL_STEPS - 1 ? void finish() : goToStep(step + 1)
            }
          />
          <View
            style={{
              minHeight: 24,
              flexDirection: 'row',
              justifyContent: step > 0 ? 'space-between' : 'center',
              alignItems: 'center',
            }}
          >
            {step > 0 ? (
              <Pressable
                accessibilityRole="button"
                disabled={updatePreferences.isPending}
                hitSlop={12}
                onPress={() => goToStep(step - 1)}
                style={({ pressed }) => ({ opacity: pressed ? 0.55 : 1 })}
              >
                <Text
                  style={{
                    color: theme.colors.textMuted,
                    ...theme.typography.caption,
                  }}
                >
                  Back
                </Text>
              </Pressable>
            ) : null}
            {step < TOTAL_STEPS - 1 ? (
              <Pressable
                accessibilityRole="button"
                disabled={updatePreferences.isPending}
                hitSlop={12}
                onPress={() => goToStep(step + 1)}
                style={({ pressed }) => ({ opacity: pressed ? 0.55 : 1 })}
              >
                <Text
                  style={{
                    color: theme.colors.textMuted,
                    ...theme.typography.caption,
                  }}
                >
                  Skip for now
                </Text>
              </Pressable>
            ) : null}
          </View>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

export function MusicOnboardingScreen() {
  const theme = useReelMateTheme();
  const auth = useAuth();
  const preferences = useMusicPreferences(Boolean(auth.user));
  const { edit } = useLocalSearchParams<{ edit?: string | string[] }>();
  const editing = Array.isArray(edit) ? edit.includes('1') : edit === '1';

  if (!auth.user) return <Redirect href="/sign-in" />;

  if (
    preferences.isPending ||
    (preferences.isError && !preferences.data) ||
    !preferences.data
  ) {
    return (
      <ScrollView
        contentInsetAdjustmentBehavior="automatic"
        contentContainerStyle={{
          flexGrow: 1,
          justifyContent: 'center',
          padding: theme.spacing.xl,
        }}
      >
        <StatePanel
          compact
          kind={preferences.isError ? 'error' : 'setup'}
          title={
            preferences.isError
              ? 'Could not start your music profile'
              : 'Preparing your music profile'
          }
          message={
            preferences.isError
              ? 'Check your connection and try loading your private preferences again.'
              : 'One moment…'
          }
          actionLabel={preferences.isError ? 'Try again' : undefined}
          onAction={
            preferences.isError ? () => void preferences.refetch() : undefined
          }
        />
      </ScrollView>
    );
  }

  if (preferences.data.onboarding_completed_at && !editing) {
    return <Redirect href="/coach" />;
  }

  return (
    <OnboardingFlow
      key={`${preferences.data.revision}-${editing ? 'edit' : 'new'}`}
      editing={editing}
      initial={preferences.data}
    />
  );
}
