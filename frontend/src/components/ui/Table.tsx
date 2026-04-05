import React from 'react';

interface TableProps {
  children: React.ReactNode;
  className?: string;
}

const Table: React.FC<TableProps> = ({ children, className = '' }) => {
  return (
    <div className={`overflow-x-auto overflow-y-auto max-h-[80vh] rounded-2xl border shadow-sm bg-white ${className}`}>
      <table className="min-w-full text-sm text-gray-800 border-collapse">
        {children}
      </table>
    </div>
  );
};

export default Table;






