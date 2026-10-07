import { LinearGradient } from 'expo-linear-gradient';
import { router } from 'expo-router';
import { useState } from 'react';
import {
  KeyboardAvoidingView,
  ScrollView,
  Text,
  TextInput,
  View,
} from 'react-native';

import {
  Card,
  PrimaryButton,
  ReelMateWordmark,
  SecondaryButton,
} from '@/components';
import { useAuth } from '@/providers/auth-provider';
import { brandColors, useReelMateTheme } from '@/theme';

export function AuthScreen() {
  const theme = useReelMateTheme();
  const { signIn, signUp } = useAuth();
  const [mode, setMode] = useState<'sign-in' | 'sign-up'>('sign-in');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    setNotice(null);
    if (!email.includes('@')) {
      setError('Enter a valid email address.');
      return;
    }
    if (password.length < 8) {
      setError('Use at least eight characters for your password.');
      return;
    }
    setBusy(true);
    try {
      if (mode === 'sign-in') {
        await signIn(email, password);
        router.replace('/');
      } else {
        const result = await signUp(email, password);
        if (result.confirmationRequired) {
          setNotice('Check your inbox to confirm the account, then sign in.');
          setMode('sign-in');
        } else {
          router.replace('/');
        }
      }
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Authentication failed.',
      );
    } finally {
      setBusy(false);
    }
  };

  const inputStyle = {
    minHeight: 52,
    color: theme.colors.text,
    backgroundColor: theme.colors.surfaceMuted,
    borderRadius: theme.radii.md,
    borderCurve: 'continuous' as const,
    paddingHorizontal: theme.spacing.lg,
    fontSize: 16,
    borderWidth: 1,
    borderColor: theme.colors.separator,
  };

  return (
    <KeyboardAvoidingView
      behavior={process.env.EXPO_OS === 'ios' ? 'padding' : undefined}
      style={{ flex: 1, backgroundColor: theme.colors.background }}
    >
      <ScrollView
        contentInsetAdjustmentBehavior="automatic"
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{
          flexGrow: 1,
          justifyContent: 'center',
          alignItems: 'center',
          padding: theme.spacing.xl,
          gap: theme.spacing.xxxl,
        }}
      >
        <LinearGradient
          colors={[brandColors.coral, '#FF9677', brandColors.lime]}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={{
            position: 'absolute',
            top: -170,
            right: -140,
            width: 360,
            height: 360,
            borderRadius: 360,
            opacity: theme.isDark ? 0.18 : 0.24,
          }}
        />
        <View style={{ width: '100%', maxWidth: 440, gap: theme.spacing.lg }}>
          <ReelMateWordmark size="large" />
          <Text
            selectable
            style={{ color: theme.colors.text, ...theme.typography.display }}
          >
            Better edits before you post.
          </Text>
          <Text
            selectable
            style={{ color: theme.colors.textMuted, ...theme.typography.body }}
          >
            Private, evidence-based coaching for hooks, pacing, audio, and
            on-screen text.
          </Text>
        </View>

        <Card
          padding="generous"
          style={{ width: '100%', maxWidth: 440, gap: theme.spacing.lg }}
        >
          <View style={{ gap: theme.spacing.xs }}>
            <Text
              selectable
              style={{ color: theme.colors.text, ...theme.typography.title }}
            >
              {mode === 'sign-in'
                ? 'Welcome back'
                : 'Create your creator profile'}
            </Text>
            <Text
              selectable
              style={{
                color: theme.colors.textMuted,
                ...theme.typography.caption,
              }}
            >
              Your media stays private and is durably queued for deletion when
              processing ends.
            </Text>
          </View>
          <TextInput
            accessibilityLabel="Email address"
            autoCapitalize="none"
            autoComplete="email"
            keyboardType="email-address"
            placeholder="Email address"
            placeholderTextColor={theme.colors.textSubtle}
            value={email}
            onChangeText={setEmail}
            style={inputStyle}
          />
          <TextInput
            accessibilityLabel="Password"
            autoCapitalize="none"
            autoComplete={
              mode === 'sign-in' ? 'current-password' : 'new-password'
            }
            placeholder="Password"
            placeholderTextColor={theme.colors.textSubtle}
            secureTextEntry
            value={password}
            onChangeText={setPassword}
            onSubmitEditing={() => void submit()}
            style={inputStyle}
          />
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
          {notice ? (
            <Text
              selectable
              style={{
                color: theme.colors.success,
                ...theme.typography.caption,
              }}
            >
              {notice}
            </Text>
          ) : null}
          <PrimaryButton
            fullWidth
            loading={busy}
            label={mode === 'sign-in' ? 'Sign in' : 'Create account'}
            onPress={() => void submit()}
          />
          <SecondaryButton
            fullWidth
            disabled={busy}
            label={
              mode === 'sign-in'
                ? 'I need an account'
                : 'I already have an account'
            }
            onPress={() => {
              setError(null);
              setMode(mode === 'sign-in' ? 'sign-up' : 'sign-in');
            }}
          />
        </Card>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
