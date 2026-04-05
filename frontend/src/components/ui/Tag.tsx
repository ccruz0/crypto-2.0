import React from 'react';

interface TagProps {
  children: React.ReactNode;
  className?: string;
}

const Tag: React.FC<TagProps> = ({ children, className = '' }) => {
  return (
    <span className={`inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-sm text-gray-700 ${className}`}>
      {children}
    </span>
  );
};

export default Tag;






