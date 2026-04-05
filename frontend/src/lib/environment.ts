/**
 * Environment detection and failover logic
 */

export interface EnvironmentConfig {
  apiUrl: string;
  environment: 'local' | 'aws';
  isLocal: boolean;
  isAWS: boolean;
}

class EnvironmentManager {
  private config: EnvironmentConfig;
  private healthCheckInterval: NodeJS.Timeout | null = null;
  private isLocalHealthy: boolean = true;

  constructor() {
    this.config = this.detectEnvironment();
    this.startHealthCheck();
  }

  private detectEnvironment(): EnvironmentConfig {
    // Check if we're running in a browser
    if (typeof window === 'undefined') {
      // Server-side rendering (SSR) - use environment variables
      // Inside Docker, NEXT_PUBLIC_API_URL is set to http://backend-aws:8002/api
      // This allows the Next.js server (running in Docker) to reach the backend via Docker service name
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || '/api';
      const environment = process.env.NEXT_PUBLIC_ENVIRONMENT as 'local' | 'aws' || 'local';
      
      console.log('🔍 Environment detection (SSR):', { apiUrl, environment });
      return {
        apiUrl,
        environment,
        isLocal: environment === 'local',
        isAWS: environment === 'aws'
      };
    }

    // Client-side (browser) - detect based on hostname
    // NOTE: In Next.js, NEXT_PUBLIC_* variables are compiled into the bundle at build time
    // So process.env.NEXT_PUBLIC_API_URL will be available in the browser code
    // If it's set to http://backend-aws:8002/api, we use it (for Docker environments)
    // Otherwise, we detect based on hostname
    const hostname = window.location.hostname;
    const protocol = window.location.protocol; // http: or https:
    const isLocalhost = hostname === 'localhost' || hostname === '127.0.0.1';
    const isHiloVivo = hostname.includes('hilovivo.com') || hostname.includes('hilovivo');
    const isAWS = hostname.includes('47.130.143.159') || hostname.includes('175.41.189.249') || hostname.includes('ec2');

    // Check if NEXT_PUBLIC_API_URL was set at build time (compiled into bundle)
    // This will be '/api' when built with docker-compose.yml frontend-aws settings
    const compiledApiUrl = process.env.NEXT_PUBLIC_API_URL;

    console.log('🔍 Environment detection (client):', { hostname, protocol, isLocalhost, isAWS, isHiloVivo, compiledApiUrl });
    // Always log to help debug
    console.log('[ENV DEBUG] window.location:', { hostname: window.location.hostname, href: window.location.href, protocol: window.location.protocol });

    // Handle relative paths (like '/api') - convert to absolute URL based on current hostname
    if (compiledApiUrl && compiledApiUrl.startsWith('/') && !compiledApiUrl.startsWith('//')) {
      const config = {
        apiUrl: `${protocol}//${hostname}${compiledApiUrl}`,
        environment: (isHiloVivo || isAWS) ? 'aws' as const : 'local' as const,
        isLocal: !isHiloVivo && !isAWS,
        isAWS: isHiloVivo || isAWS
      };
      console.log('✅ Using relative API URL converted to absolute:', config);
      return config;
    }

    // Only use compiledApiUrl if it's a valid, browser-accessible URL (not Docker service name)
    // Docker service names like 'backend-aws' cannot be resolved by browsers
    if (compiledApiUrl && compiledApiUrl.startsWith('http')) {
      try {
        const parsed = new URL(compiledApiUrl);
        // Skip Docker service names - browsers can't resolve them
        const isDockerServiceName = parsed.hostname === 'backend-aws' || parsed.hostname.includes('backend-aws');
        
        if (!isDockerServiceName) {
          const forcedConfig = {
            apiUrl: compiledApiUrl,
            environment: 'aws' as const,
            isLocal: false,
            isAWS: true
          };
          console.log('🔍 Using forced API URL from NEXT_PUBLIC_API_URL:', forcedConfig);
          return forcedConfig;
        } else {
          console.log('🔍 Skipping Docker service name in NEXT_PUBLIC_API_URL, using hostname detection');
        }
      } catch (parseErr) {
        console.warn('Invalid NEXT_PUBLIC_API_URL provided:', compiledApiUrl, parseErr);
      }
    }

    if (isHiloVivo) {
      // Production domain - use relative path /api (works with current domain)
      // Nginx will proxy /api to backend on port 8002
      const config = {
        apiUrl: '/api',  // Relative path - browser will use current domain automatically
        environment: 'aws' as const,
        isLocal: false,
        isAWS: true
      };
      console.log('✅ Using Hilo Vivo domain config (relative /api):', config);
      return config;
    } else if (isLocalhost) {
      // Local browser access (user accessing http://localhost:3000 from their Mac)
      // Use relative /api path to avoid CORS issues - Next.js rewrites will proxy to backend
      // If NEXT_PUBLIC_API_URL was compiled with backend-aws, use it (Docker environment)
      // NOTE: Browsers cannot resolve Docker service names, but if the frontend was built
      // with NEXT_PUBLIC_API_URL=http://backend-aws:8002/api, it means we're in Docker
      // and the Next.js server-side can proxy/rewrite these requests
      const useDockerService = compiledApiUrl && compiledApiUrl.includes('backend-aws');
      
      const config = {
        apiUrl: useDockerService ? compiledApiUrl : '/api',  // Use relative path to avoid CORS
        environment: 'local' as const,
        isLocal: true,
        isAWS: false
      };
      console.log('🔍 Using localhost config (browser):', config, { compiledApiUrl, useDockerService });
      return config;
    } else if (isAWS) {
      // AWS public IP access
      const config = {
        apiUrl: `${protocol}//${hostname}:8002/api`,
        environment: 'aws' as const,
        isLocal: false,
        isAWS: true
      };
      console.log('🔍 Using AWS config:', config);
      return config;
    } else {
      // Fallback: use same hostname as frontend for backend API
      const config = {
        apiUrl: `http://${hostname}:8002/api`,
        environment: 'local' as const,
        isLocal: true,
        isAWS: false
      };
      console.log('🔍 Using fallback config (same hostname):', config);
      return config;
    }
  }

  private async checkLocalHealth(): Promise<boolean> {
    try {
      // Use the current API URL for health check
      const apiUrl = this.config.apiUrl.replace('/api', '');
      const response = await fetch(`${apiUrl}/health`, {
        method: 'GET',
        signal: AbortSignal.timeout(3000) // 3 second timeout
      });
      return response.ok;
    } catch (error) {
      console.log('Local backend health check failed:', error);
      return false;
    }
  }

  private startHealthCheck(): void {
    // Only run health checks in local environment
    if (!this.config.isLocal) return;

    // Temporarily disable health checks to avoid connection issues
    // TODO: Fix health check for containerized environment
    console.log('Health check disabled for containerized environment');
    return;

    const interval = parseInt(process.env.NEXT_PUBLIC_HEALTH_CHECK_INTERVAL || '5000');
    
    this.healthCheckInterval = setInterval(async () => {
      const isHealthy = await this.checkLocalHealth();
      
      if (this.isLocalHealthy !== isHealthy) {
        this.isLocalHealthy = isHealthy;
        console.log(`Local backend health status changed: ${isHealthy ? 'healthy' : 'unhealthy'}`);
        
        // Emit custom event for components to listen to
        window.dispatchEvent(new CustomEvent('environment-health-change', {
          detail: { isLocalHealthy: isHealthy }
        }));
      }
    }, interval);
  }

  public getConfig(): EnvironmentConfig {
    return { ...this.config };
  }

  public getApiUrl(): string {
    // If we're in local environment but local backend is unhealthy, failover to AWS
    // NOTE: This failover is disabled in containerized environments (see startHealthCheck)
    if (this.config.isLocal && !this.isLocalHealthy) {
      console.log('Failing over to AWS backend');
      return 'https://dashboard.hilovivo.com/api';
    }
    
    return this.config.apiUrl;
  }

  public isLocalBackendHealthy(): boolean {
    return this.isLocalHealthy;
  }

  public destroy(): void {
    if (this.healthCheckInterval) {
      clearInterval(this.healthCheckInterval);
      this.healthCheckInterval = null;
    }
  }
}

// Singleton instance
let environmentManager: EnvironmentManager | null = null;

export function getEnvironmentManager(): EnvironmentManager {
  if (!environmentManager) {
    environmentManager = new EnvironmentManager();
  }
  return environmentManager;
}

export function getApiUrl(): string {
  return getEnvironmentManager().getApiUrl();
}

export function getEnvironmentConfig(): EnvironmentConfig {
  return getEnvironmentManager().getConfig();
}

export function isLocalBackendHealthy(): boolean {
  return getEnvironmentManager().isLocalBackendHealthy();
}

/** Same-origin wss:// on HTTPS for /api/ws/prices — see priceStreamWsUrl.ts */
export { getPriceStreamWebSocketUrl, PRICE_STREAM_WS_PATH } from './priceStreamWsUrl';
