import React from 'react';
import { palette } from '@/theme/palette';

interface BadgeProps {
  variant: 'success' | 'danger' | 'warning' | 'neutral';
  children: React.ReactNode;
  className?: string;
}

const Badge: React.FC<BadgeProps> = ({ variant, children, className = '' }) => {
  const baseClasses = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs border';
  const variantClasses = {
    success: palette.badge.success,
    danger: palette.badge.danger,
    warning: palette.badge.warning,
    neutral: palette.badge.neutral,
  };

  return (
    <span className={`${baseClasses} ${variantClasses[variant]} ${className}`}>
      {children}
    </span>
  );
};

export default Badge;




