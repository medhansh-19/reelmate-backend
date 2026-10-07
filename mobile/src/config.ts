const trimTrailingSlash = (value: string | undefined) =>
  value?.trim().replace(/\/+$/, '') ?? '';

const supabaseUrl = trimTrailingSlash(process.env.EXPO_PUBLIC_SUPABASE_URL);
const supabasePublishableKey =
  process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY?.trim() ?? '';
const apiBaseUrl = trimTrailingSlash(process.env.EXPO_PUBLIC_API_URL);

const looksLikeUrl = (value: string) => {
  if (!value) return false;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || (__DEV__ && url.protocol === 'http:');
  } catch {
    return false;
  }
};

const servicesConfigured =
  looksLikeUrl(supabaseUrl) &&
  supabasePublishableKey.length > 20 &&
  looksLikeUrl(apiBaseUrl);
const explicitlyDemo =
  process.env.EXPO_PUBLIC_DEMO_MODE?.trim().toLowerCase() === 'true';

export const appConfig = Object.freeze({
  supabaseUrl,
  supabasePublishableKey,
  apiBaseUrl,
  servicesConfigured,
  // A fresh clone stays reviewable before provider setup. Production never
  // silently falls back to sample data unless the build explicitly opts in.
  demoMode: explicitlyDemo || (__DEV__ && !servicesConfigured),
  configurationIssue: servicesConfigured
    ? null
    : 'Add this app’s own Supabase URL, publishable key, and ReelMate API URL.',
});
