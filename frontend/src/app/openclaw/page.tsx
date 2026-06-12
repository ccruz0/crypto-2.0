'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

/** Legacy OpenClaw route — redirect to dashboard Jarvis tab. */
export default function OpenClawRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace('/');
  }, [router]);

  return (
    <div className="flex min-h-[40vh] items-center justify-center p-8">
      <p className="text-sm text-gray-600 dark:text-gray-400">
        OpenClaw has been replaced by Jarvis Control Center. Redirecting to the dashboard…
      </p>
    </div>
  );
}
