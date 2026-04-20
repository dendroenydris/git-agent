import { useEffect, useState } from 'react';
import { FaChevronDown, FaChevronRight } from 'react-icons/fa';

import type { ReactTraceEntry, Task } from '../../lib/api';
import { getTraceIcon } from './trace-icons';


interface TaskBottomPanelProps {
  task: Task;
  isOpen: boolean;
  traceEntries: ReactTraceEntry[];
  aggregatedOutput: string;
}

type PanelTab = 'trace' | 'results';


export default function TaskBottomPanel({
  task,
  isOpen,
  traceEntries,
  aggregatedOutput,
}: TaskBottomPanelProps) {
  const [activeTab, setActiveTab] = useState<PanelTab>('trace');
  const [expandedTraceEntries, setExpandedTraceEntries] = useState<Set<string>>(new Set());

  useEffect(() => {
    setExpandedTraceEntries((prev) => {
      const next = new Set(prev);
      traceEntries.forEach((entry, index) => {
        const traceKey = `${entry.label}-${index}`;
        if (entry.type !== 'thought') next.add(traceKey);
      });
      return next;
    });
  }, [traceEntries]);

  const toggleTraceEntry = (traceKey: string) => {
    setExpandedTraceEntries((prev) => {
      const next = new Set(prev);
      if (next.has(traceKey)) next.delete(traceKey);
      else next.add(traceKey);
      return next;
    });
  };

  if (!isOpen) return null;

  const taskGraph = task.plan_json.task_graph;
  const graphNodes = Array.isArray(taskGraph?.nodes) ? taskGraph.nodes : [];
  const worktreePath = typeof taskGraph?.worktree_path === 'string' ? taskGraph.worktree_path : null;

  return (
    <div className="h-80 border-t border-mac-border bg-[#111827] text-gray-100 flex flex-col">
      <div className="flex border-b border-gray-700">
        <button
          type="button"
          onClick={() => setActiveTab('trace')}
          className={`px-4 py-2 text-sm font-medium ${
            activeTab === 'trace'
              ? 'text-white bg-[#1f2937] border-b-2 border-blue-500'
              : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          Trace
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('results')}
          className={`px-4 py-2 text-sm font-medium ${
            activeTab === 'results'
              ? 'text-white bg-[#1f2937] border-b-2 border-blue-500'
              : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          Summary
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 font-mono text-sm">
        {activeTab === 'trace' ? (
          traceEntries.length > 0 ? (
            <div className="space-y-3">
              {traceEntries.map((entry, index) => {
                const traceKey = `${entry.label}-${index}`;
                const isExpanded = expandedTraceEntries.has(traceKey);

                return (
                  <div
                    key={traceKey}
                    className="rounded-lg border border-gray-800 bg-[#0f172a]"
                  >
                    <button
                      type="button"
                      onClick={() => toggleTraceEntry(traceKey)}
                      className="flex w-full items-center justify-between gap-3 p-3 text-left"
                    >
                      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-gray-400">
                        {getTraceIcon(entry.type)}
                        <span>{entry.label}</span>
                        {entry.title && <span className="text-gray-500 normal-case">· {entry.title}</span>}
                        {typeof entry.step_position === 'number' && (
                          <span className="rounded bg-slate-800 px-2 py-0.5 text-[10px] normal-case text-slate-300">
                            step {entry.step_position}
                          </span>
                        )}
                        {entry.status && (
                          <span className="rounded bg-gray-800 px-2 py-0.5 text-[10px] normal-case text-gray-300">
                            {entry.status}
                          </span>
                        )}
                        {entry.content_truncated && (
                          <span className="rounded bg-amber-900/40 px-2 py-0.5 text-[10px] normal-case text-amber-300">
                            truncated
                          </span>
                        )}
                      </div>
                      {isExpanded ? (
                        <FaChevronDown className="h-3.5 w-3.5 text-gray-500" />
                      ) : (
                        <FaChevronRight className="h-3.5 w-3.5 text-gray-500" />
                      )}
                    </button>
                    {isExpanded && (
                      <div className="border-t border-gray-800 px-3 py-3">
                        {entry.created_at && (
                          <div className="mb-2 text-xs text-gray-500">
                            {new Date(entry.created_at).toLocaleString()}
                          </div>
                        )}
                        <pre className="whitespace-pre-wrap text-gray-200">{entry.content}</pre>
                        {entry.command && (
                          <pre className="mt-2 whitespace-pre-wrap rounded bg-[#111827] p-2 text-blue-300">
                            {entry.command}
                          </pre>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <pre className="whitespace-pre-wrap text-gray-300">{aggregatedOutput}</pre>
          )
        ) : (
          <div className="space-y-4">
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-400">Planner Intent</div>
              <pre className="mt-2 whitespace-pre-wrap text-gray-200">
                {JSON.stringify(task.plan_json.intent || {}, null, 2)}
              </pre>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-400">Workflow Summary</div>
              <pre className="mt-2 whitespace-pre-wrap text-gray-200">
                {task.summary || 'Summary will appear when the workflow completes.'}
              </pre>
            </div>
            {worktreePath && (
              <div>
                <div className="text-xs uppercase tracking-wide text-gray-400">Worktree</div>
                <pre className="mt-2 whitespace-pre-wrap text-gray-200">{worktreePath}</pre>
              </div>
            )}
            {graphNodes.length > 0 && (
              <div>
                <div className="text-xs uppercase tracking-wide text-gray-400">Task Graph</div>
                <pre className="mt-2 whitespace-pre-wrap text-gray-200">
                  {JSON.stringify(
                    {
                      status: taskGraph?.status || 'pending',
                      active_node_id: taskGraph?.active_node_id || null,
                      nodes: graphNodes.map((node) => ({
                        id: node.id,
                        agent: node.agent,
                        title: node.title,
                        status: node.status,
                        depends_on: node.depends_on,
                        tool_name: node.tool_name,
                      })),
                    },
                    null,
                    2
                  )}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
