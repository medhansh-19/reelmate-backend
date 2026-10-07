import { router } from 'expo-router';
import { ActivityIndicator, FlatList, Text, View } from 'react-native';

import {
  AnalysisListCard,
  EmptyState,
  ErrorState,
  PreviewModeBanner,
} from '@/components';
import { useAnalyses } from '@/hooks/use-analyses';
import { useAuth } from '@/providers/auth-provider';
import { useReelMateTheme } from '@/theme';

export function LibraryScreen() {
  const theme = useReelMateTheme();
  const { isDemo } = useAuth();
  const query = useAnalyses();
  const items = query.data?.pages.flatMap((page) => page.analyses) ?? [];

  return (
    <FlatList
      contentInsetAdjustmentBehavior="automatic"
      data={items}
      keyExtractor={(item) => item.analysis_id}
      contentContainerStyle={{
        width: '100%',
        maxWidth: theme.layout.contentMaxWidth,
        alignSelf: 'center',
        padding: theme.spacing.xl,
        paddingBottom: theme.spacing.hero,
        gap: theme.spacing.md,
        flexGrow: items.length ? undefined : 1,
      }}
      ListHeaderComponent={
        <View
          style={{ gap: theme.spacing.lg, paddingBottom: theme.spacing.sm }}
        >
          {isDemo ? <PreviewModeBanner /> : null}
          <Text
            selectable
            style={{ color: theme.colors.textMuted, ...theme.typography.body }}
          >
            Reopen video coaching plans and story song matches.
          </Text>
        </View>
      }
      ListEmptyComponent={
        query.isError ? (
          <ErrorState
            title="Couldn’t load your library"
            message={
              query.error instanceof Error
                ? query.error.message
                : 'Check your connection and try again.'
            }
            actionLabel="Try again"
            onAction={() => void query.refetch()}
          />
        ) : query.isPending ? (
          <View
            style={{
              flex: 1,
              alignItems: 'center',
              justifyContent: 'center',
              gap: theme.spacing.md,
            }}
          >
            <ActivityIndicator color={theme.colors.accent} />
            <Text style={{ color: theme.colors.textMuted }}>
              Loading your reels…
            </Text>
          </View>
        ) : (
          <EmptyState
            title="No reels analyzed yet"
            message="Your private ReelMate history will collect here."
            actionLabel="Start your first analysis"
            onAction={() => router.push('/upload')}
          />
        )
      }
      ListFooterComponent={
        query.isFetchingNextPage ? (
          <ActivityIndicator
            color={theme.colors.accent}
            style={{ padding: theme.spacing.xl }}
          />
        ) : null
      }
      onEndReached={() => {
        if (query.hasNextPage && !query.isFetchingNextPage)
          void query.fetchNextPage();
      }}
      onEndReachedThreshold={0.4}
      onRefresh={() => void query.refetch()}
      refreshing={query.isRefetching && !query.isFetchingNextPage}
      renderItem={({ item }) => (
        <AnalysisListCard
          createdAt={item.created_at}
          mode={item.mode}
          status={item.status}
          score={item.score}
          niche={item.niche_detected}
          onPress={() =>
            router.push({
              pathname: '/analysis/[id]',
              params: { id: item.analysis_id },
            })
          }
        />
      )}
    />
  );
}
