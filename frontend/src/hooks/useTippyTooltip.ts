// frontend/src/hooks/useTippyTooltip.ts
'use client';
import { useEffect, useRef } from 'react';

interface TippyOptions {
  content?: string;
  allowHTML?: boolean;
  theme?: string;
  maxWidth?: number;
  placement?: 'top' | 'bottom' | 'left' | 'right' | 'top-start' | 'top-end' | 'bottom-start' | 'bottom-end' | 'left-start' | 'left-end' | 'right-start' | 'right-end';
  delay?: [number, number] | number;
  hideOnClick?: boolean;
  trigger?: string;
  interactive?: boolean;
  appendTo?: () => HTMLElement;
  duration?: [number, number] | number;
  followCursor?: boolean;
  sticky?: boolean;
  popperOptions?: {
    modifiers?: Array<{
      name: string;
      options?: {
        boundary?: string;
        [key: string]: unknown;
      };
    }>;
  };
  [key: string]: unknown;
}

export function useTippyTooltip<T extends HTMLElement = HTMLElement>(html: string, options: TippyOptions = {}) {
  const ref = useRef<T>(null);

  useEffect(() => {
    if (!ref.current || !html) return;

    let instance: ReturnType<typeof import('tippy.js').default>[0] | null = null;

    // Dynamically import tippy.js only on client side
    const loadTippy = async () => {
      const tippyModule = await import('tippy.js');
      const tippy = tippyModule.default;
      
      // Note: CSS imports are handled in global styles or _app.tsx for Next.js
      // Tippy.js will work without explicit CSS import in Next.js

      if (ref.current) {
        instance = tippy(ref.current, {
          content: html,
          allowHTML: true,
          theme: 'dark',
          maxWidth: 360,
          placement: 'top',
          delay: [200, 1000], // 200ms para mostrar, 1000ms para ocultar
          hideOnClick: false,
          trigger: 'mouseenter focus',
          interactive: true,
          appendTo: () => document.body,
          duration: [300, 200], // Animación más suave
          followCursor: false,
          sticky: true, // Mantiene el tooltip visible
          popperOptions: {
            modifiers: [
              {
                name: 'preventOverflow',
                options: {
                  boundary: 'viewport',
                },
              },
            ],
          },
          ...options
        });
      }
    };

    loadTippy().catch(console.error);

    return () => {
      if (instance) {
        instance.destroy();
      }
    };
  }, [html, options]);

  return ref;
}
