/**
 * WatchlistCell Component
 * 
 * Displays a watchlist cell value with:
 * - Visual highlighting for values updated in the last 60 seconds
 * - Tooltip showing "Last updated: <timestamp>" on hover
 * - "Saved" feedback after successful edits
 */

import React, { useState, useEffect } from 'react';

interface WatchlistCellProps {
  value: any;
  fieldName: string;
  fieldUpdatedAt?: Record<string, string>;  // field_updated_at from API
  className?: string;
  children?: React.ReactNode;
  onSave?: () => Promise<void>;
  showSavedFeedback?: boolean;
}

export function WatchlistCell({
  value,
  fieldName,
  fieldUpdatedAt,
  className = '',
  children,
  onSave,
  showSavedFeedback = false,
}: WatchlistCellProps) {
  const [showSaved, setShowSaved] = useState(false);
  const [isRecentlyUpdated, setIsRecentlyUpdated] = useState(false);

  // Check if value was updated in the last 60 seconds
  useEffect(() => {
    if (!fieldUpdatedAt || !fieldUpdatedAt[fieldName]) {
      setIsRecentlyUpdated(false);
      return;
    }

    try {
      const updatedAt = new Date(fieldUpdatedAt[fieldName]);
      const now = new Date();
      const secondsAgo = (now.getTime() - updatedAt.getTime()) / 1000;
      setIsRecentlyUpdated(secondsAgo <= 60 && secondsAgo >= 0);
    } catch (e) {
      setIsRecentlyUpdated(false);
    }
  }, [fieldUpdatedAt, fieldName]);

  // Show "Saved" feedback after successful save
  useEffect(() => {
    if (showSavedFeedback) {
      setShowSaved(true);
      const timer = setTimeout(() => setShowSaved(false), 2000);
      return () => clearTimeout(timer);
    }
  }, [showSavedFeedback]);

  const getLastUpdatedText = (): string => {
    if (!fieldUpdatedAt || !fieldUpdatedAt[fieldName]) {
      return 'Last updated: Never';
    }

    try {
      const updatedAt = new Date(fieldUpdatedAt[fieldName]);
      const now = new Date();
      const secondsAgo = Math.floor((now.getTime() - updatedAt.getTime()) / 1000);
      
      if (secondsAgo < 60) {
        return `Last updated: ${secondsAgo} second${secondsAgo !== 1 ? 's' : ''} ago`;
      } else if (secondsAgo < 3600) {
        const minutesAgo = Math.floor(secondsAgo / 60);
        return `Last updated: ${minutesAgo} minute${minutesAgo !== 1 ? 's' : ''} ago`;
      } else {
        return `Last updated: ${updatedAt.toLocaleString()}`;
      }
    } catch (e) {
      return 'Last updated: Unknown';
    }
  };

  const cellClassName = `
    ${className}
    ${isRecentlyUpdated ? 'watchlist-cell-recently-updated' : ''}
    ${showSaved ? 'watchlist-cell-saved' : ''}
  `.trim();

  return (
    <div
      className={cellClassName}
      title={getLastUpdatedText()}
      style={{
        position: 'relative',
        transition: 'all 0.2s ease',
        ...(isRecentlyUpdated && {
          fontWeight: 'bold',
          backgroundColor: 'rgba(34, 197, 94, 0.1)', // green-500 with opacity
          borderLeft: '2px solid rgb(34, 197, 94)',
          paddingLeft: '4px',
        }),
        ...(showSaved && {
          backgroundColor: 'rgba(59, 130, 246, 0.1)', // blue-500 with opacity
        }),
      }}
    >
      {children || value}
      {showSaved && (
        <span
          style={{
            position: 'absolute',
            top: '-20px',
            right: '0',
            fontSize: '10px',
            color: 'rgb(59, 130, 246)',
            fontWeight: 'bold',
            backgroundColor: 'white',
            padding: '2px 4px',
            borderRadius: '2px',
            boxShadow: '0 1px 2px rgba(0,0,0,0.1)',
            zIndex: 10,
          }}
        >
          ✓ Saved
        </span>
      )}
    </div>
  );
}








