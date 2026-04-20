import { useEffect, useMemo, useState } from 'react';

import {
  buildTerminalPreview,
  normalizeTerminalOutput,
  shouldCollapseTerminalOutput,
} from '../../lib/terminal-output';


interface TerminalOutputPanelProps {
  title: string;
  content: string;
  tone?: 'default' | 'error';
  initiallyExpanded?: boolean;
}


export default function TerminalOutputPanel({
  title,
  content,
  tone = 'default',
  initiallyExpanded = false,
}: TerminalOutputPanelProps) {
  const normalizedContent = useMemo(() => normalizeTerminalOutput(content), [content]);
  const isCollapsible = useMemo(
    () => shouldCollapseTerminalOutput(normalizedContent),
    [normalizedContent]
  );
  const [isExpanded, setIsExpanded] = useState(initiallyExpanded || !isCollapsible);

  useEffect(() => {
    if (!isCollapsible) setIsExpanded(true);
  }, [isCollapsible]);

  useEffect(() => {
    if (initiallyExpanded) setIsExpanded(true);
  }, [initiallyExpanded]);

  const displayContent = isExpanded ? normalizedContent : buildTerminalPreview(normalizedContent);
  const labelClass =
    tone === 'error'
      ? 'text-xs font-semibold uppercase tracking-wide text-red-500'
      : 'text-xs font-semibold uppercase tracking-wide text-gray-500';
  const panelClass =
    tone === 'error'
      ? 'mt-1 rounded-md bg-red-50 p-3 text-sm text-red-700 overflow-x-auto font-mono whitespace-pre-wrap'
      : 'mt-1 rounded-md bg-gray-50 p-3 text-sm overflow-x-auto font-mono whitespace-pre-wrap';

  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <div className={labelClass}>{title}</div>
        {isCollapsible && (
          <button
            type="button"
            onClick={() => setIsExpanded((current) => !current)}
            className="text-xs font-medium text-blue-600 hover:text-blue-700"
          >
            {isExpanded ? 'Collapse' : 'Expand'}
          </button>
        )}
      </div>
      <pre className={panelClass}>{displayContent}</pre>
    </div>
  );
}
