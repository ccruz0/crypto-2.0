/**
 * Centralized logging utility
 * Replaces console.log/warn/error/debug with a structured logging system
 */

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

const LOG_LEVELS: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

// Get log level from environment or default to 'info' in production
const getLogLevel = (): LogLevel => {
  if (typeof window === 'undefined') return 'info';
  const envLevel = (window as { __LOG_LEVEL__?: LogLevel }).__LOG_LEVEL__;
  if (envLevel && LOG_LEVELS[envLevel] !== undefined) return envLevel;
  
  // In production, default to 'warn' to reduce noise
  // In development, default to 'debug'
  return process.env.NODE_ENV === 'production' ? 'warn' : 'debug';
};

const currentLogLevel = getLogLevel();
const currentLogLevelValue = LOG_LEVELS[currentLogLevel];

// Error suppression for handled errors (to avoid spam)
const HANDLED_ERROR_SUPPRESSION_MS = 30000;
const handledErrorTimestamps = new Map<string, number>();

interface Logger {
  debug: (message: string, ...args: unknown[]) => void;
  info: (message: string, ...args: unknown[]) => void;
  warn: (message: string, ...args: unknown[]) => void;
  error: (message: string, ...args: unknown[]) => void;
  logHandledError: (key: string, message: string, error: unknown, level?: 'warn' | 'error') => void;
}

const shouldLog = (level: LogLevel): boolean => {
  return LOG_LEVELS[level] >= currentLogLevelValue;
};

const formatMessage = (level: LogLevel, message: string): string => {
  const timestamp = new Date().toISOString();
  const prefix = `[${timestamp}] [${level.toUpperCase()}]`;
  return `${prefix} ${message}`;
};

export const logger: Logger = {
  debug: (message: string, ...args: unknown[]) => {
    if (shouldLog('debug')) {
      console.debug(formatMessage('debug', message), ...args);
    }
  },

  info: (message: string, ...args: unknown[]) => {
    if (shouldLog('info')) {
      console.info(formatMessage('info', message), ...args);
    }
  },

  warn: (message: string, ...args: unknown[]) => {
    if (shouldLog('warn')) {
      console.warn(formatMessage('warn', message), ...args);
    }
  },

  error: (message: string, ...args: unknown[]) => {
    if (shouldLog('error')) {
      console.error(formatMessage('error', message), ...args);
    }
  },

  logHandledError: (
    key: string,
    message: string,
    error: unknown,
    level: 'warn' | 'error' = 'warn'
  ): void => {
    const now = Date.now();
    const lastLoggedAt = handledErrorTimestamps.get(key) ?? 0;
    if (now - lastLoggedAt < HANDLED_ERROR_SUPPRESSION_MS) {
      return;
    }
    handledErrorTimestamps.set(key, now);

    const formattedMessage = formatMessage(level, message);
    if (error instanceof Error) {
      logger[level](formattedMessage, { name: error.name, message: error.message, stack: error.stack });
    } else {
      logger[level](formattedMessage, error);
    }
  },
};

// Export default logger
export default logger;



