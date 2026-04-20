import { FaBrain, FaEye, FaTerminal } from 'react-icons/fa';

import type { ReactTraceEntry } from '../../lib/api';


export const getTraceIcon = (entryType: ReactTraceEntry['type']) => {
  if (entryType === 'thought') return <FaBrain className="h-4 w-4 text-violet-400" />;
  if (entryType === 'act') return <FaTerminal className="h-4 w-4 text-blue-400" />;
  return <FaEye className="h-4 w-4 text-emerald-400" />;
};
