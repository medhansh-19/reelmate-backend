import { AuthenticatedAppGate } from '@/components';
import { UploadScreen } from '@/screens/upload';

export default function UploadRoute() {
  return (
    <AuthenticatedAppGate>
      <UploadScreen />
    </AuthenticatedAppGate>
  );
}
