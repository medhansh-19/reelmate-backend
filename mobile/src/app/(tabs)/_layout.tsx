import { AuthenticatedAppGate } from '@/components';
import AppTabs from '@/components/app-tabs';

export default function TabsLayout() {
  return (
    <AuthenticatedAppGate>
      <AppTabs />
    </AuthenticatedAppGate>
  );
}
