import { NextRequest, NextResponse } from 'next/server';
import { isInternalApiProxyPath } from '@/lib/internalApiProxy';
import { getBackendApiKey, getBackendBaseUrl } from '@/lib/internalApiProxyServer';

async function proxyToBackend(
  request: NextRequest,
  pathSegments: string[],
): Promise<NextResponse> {
  const path = pathSegments.join('/');
  if (!isInternalApiProxyPath(path)) {
    return NextResponse.json({ detail: 'Path not allowed' }, { status: 403 });
  }

  const backendUrl = `${getBackendBaseUrl()}/api/${path}`;
  const apiKey = getBackendApiKey();
  const body = await request.text();

  let upstream: Response;
  try {
    upstream = await fetch(backendUrl, {
      method: 'POST',
      headers: {
        'Content-Type': request.headers.get('content-type') || 'application/json',
        'x-api-key': apiKey,
      },
      body: body || undefined,
      cache: 'no-store',
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      { detail: `Backend unreachable: ${message}` },
      { status: 502 },
    );
  }

  const responseBody = await upstream.text();
  return new NextResponse(responseBody, {
    status: upstream.status,
    headers: {
      'Content-Type': upstream.headers.get('content-type') || 'application/json',
      'Cache-Control': 'no-store',
    },
  });
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  return proxyToBackend(request, path);
}
