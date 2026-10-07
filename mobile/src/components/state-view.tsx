import type { ReactNode } from 'react';
import { Text, View, type ViewStyle } from 'react-native';

import { PrimaryButton, SecondaryButton } from './app-button';
import { ReelMateMark } from './brand-mark';
import { Card } from './surface';

import { useReelMateTheme } from '@/theme';

export type StateKind = 'empty' | 'error' | 'setup';

export type StatePanelProps = {
  kind?: StateKind;
  title: string;
  message: string;
  actionLabel?: string;
  onAction?: () => void;
  actionLoading?: boolean;
  secondaryActionLabel?: string;
  onSecondaryAction?: () => void;
  visual?: ReactNode;
  compact?: boolean;
  style?: ViewStyle;
};

function StateGlyph({ kind }: { kind: StateKind }) {
  const theme = useReelMateTheme();
  const glyph = kind === 'error' ? '!' : kind === 'setup' ? '↗' : '+';
  const foreground =
    kind === 'error' ? theme.colors.danger : theme.colors.accent;
  const background =
    kind === 'error' ? theme.colors.dangerSoft : theme.colors.accentSoft;

  if (kind === 'empty') return <ReelMateMark decorative size={54} />;

  return (
    <View
      accessibilityElementsHidden
      style={{
        width: 54,
        height: 54,
        borderRadius: 18,
        borderCurve: 'continuous',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: background,
      }}
    >
      <Text
        style={{
          color: foreground,
          fontSize: 24,
          lineHeight: 28,
          fontWeight: '900',
        }}
      >
        {glyph}
      </Text>
    </View>
  );
}

export function StatePanel({
  kind = 'empty',
  title,
  message,
  actionLabel,
  onAction,
  actionLoading = false,
  secondaryActionLabel,
  onSecondaryAction,
  visual,
  compact = false,
  style,
}: StatePanelProps) {
  const theme = useReelMateTheme();

  return (
    <Card
      accessibilityLiveRegion={kind === 'error' ? 'assertive' : 'none'}
      accessibilityRole={
        actionLabel && onAction
          ? undefined
          : kind === 'error'
            ? 'alert'
            : 'summary'
      }
      padding={compact ? 'regular' : 'generous'}
      style={[{ alignItems: 'center', gap: theme.spacing.lg }, style]}
    >
      {visual ?? <StateGlyph kind={kind} />}
      <View
        style={{
          maxWidth: theme.layout.readingMaxWidth,
          alignItems: 'center',
          gap: theme.spacing.sm,
        }}
      >
        <Text
          accessibilityRole="header"
          selectable
          style={{
            color: theme.colors.text,
            textAlign: 'center',
            ...theme.typography.title,
          }}
        >
          {title}
        </Text>
        <Text
          selectable
          style={{
            color: theme.colors.textMuted,
            textAlign: 'center',
            ...theme.typography.body,
          }}
        >
          {message}
        </Text>
      </View>
      {actionLabel && onAction ? (
        <View
          style={{
            width: compact ? '100%' : undefined,
            flexDirection: compact ? 'column' : 'row',
            gap: theme.spacing.sm,
          }}
        >
          <PrimaryButton
            fullWidth={compact}
            label={actionLabel}
            loading={actionLoading}
            onPress={onAction}
          />
          {secondaryActionLabel && onSecondaryAction ? (
            <SecondaryButton
              fullWidth={compact}
              label={secondaryActionLabel}
              onPress={onSecondaryAction}
            />
          ) : null}
        </View>
      ) : null}
    </Card>
  );
}

export function EmptyState(props: Omit<StatePanelProps, 'kind'>) {
  return <StatePanel {...props} kind="empty" />;
}

export function ErrorState(props: Omit<StatePanelProps, 'kind'>) {
  return <StatePanel {...props} kind="error" />;
}

export function SetupState(props: Omit<StatePanelProps, 'kind'>) {
  return <StatePanel {...props} kind="setup" />;
}
