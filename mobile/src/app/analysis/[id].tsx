import { useLocalSearchParams } from 'expo-router';

import { AuthenticatedAppGate } from '@/components';
import { AnalysisScreen } from '@/screens/analysis';

export default function AnalysisRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return (
    <AuthenticatedAppGate>
      <AnalysisScreen analysisId={id ?? ''} />
    </AuthenticatedAppGate>
  );
}
