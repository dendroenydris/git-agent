import { useEffect, useMemo, useState } from 'react';
import {
  FaChevronDown,
  FaChevronRight,
  FaBrain,
  FaTerminal,
  FaEye,
} from 'react-icons/fa';

import type { ReactTraceEntry, Task } from '../lib/api';
import { formatWorkflowStatus, getWorkflowStatusIcon } from '../lib/task-status';

interface TaskWorkflowProps {
  task: Task | null;
  isConnected?: boolean;
  connectionError?: string | null;
  onReconnect?: () => void;
  onApprove?: (approved: boolean) => void;
  isApproving?: boolean;
  onReplan?: (failureMessage: string) => void;
  isReplanning?: boolean;
}

type PanelTab = 'trace' | 'results';

export default function TaskWorkflow({
  task,
  isConnected = false,
  connectionError = null,
  onReconnect,
  onApprove,
  isApproving = false,
  onReplan,
  isReplanning = false,
}: TaskWorkflowProps) {
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set());
  const [expandedTraceEntries, setExpandedTraceEntries] = useState<Set<string>>(new Set());
  const [activeTab, setActiveTab] = useState<PanelTab>('trace');

  const aggregatedOutput = useMemo(() => {
    if (!task) return 'No task selected.';

    const stepLogs = task.steps
      .map((step) => {
        const sections = [`[${step.position}] ${step.title}`];
        if (step.command) sections.push(`$ ${step.command}`);
        if (step.output) sections.push(step.output);
        if (step.error) sections.push(`ERROR: ${step.error}`);
        return sections.join('\n');
      })
      .join('\n\n');

    return stepLogs || 'Task queued. Waiting for planner output...';
  }, [task]);

  const traceEntries = useMemo(() => {
    const rawTrace = task?.plan_json.react_trace;
    if (!Array.isArray(rawTrace)) return [];

    return rawTrace
      .map((entry) => {
        if (!entry || typeof entry !== 'object') return null;
        const item = entry as Partial<ReactTraceEntry>;
        if (
          (item.type !== 'thought' && item.type !== 'act' && item.type !== 'observation') ||
          typeof item.label !== 'string' ||
          typeof item.content !== 'string'
        ) {
          return null;
        }

        return {
          type: item.type,
          label: item.label,
          iteration: typeof item.iteration === 'number' ? item.iteration : null,
          step_position: typeof item.step_position === 'number' ? item.step_position : null,
          title: typeof item.title === 'string' ? item.title : null,
          kind: typeof item.kind === 'string' ? item.kind : null,
          command: typeof item.command === 'string' ? item.command : null,
          status: typeof item.status === 'string' ? item.status : null,
          created_at: typeof item.created_at === 'string' ? item.created_at : null,
          content_truncated: item.content_truncated === true,
          content: item.content,
        } as ReactTraceEntry;
      })
      .filter((entry): entry is ReactTraceEntry => entry !== null);
  }, [task]);

  const repositorySummary =
    typeof task?.plan_json.repository_context?.repository_summary === 'string'
      ? task.plan_json.repository_context.repository_summary
      : '';

  const retrievedSources = useMemo(() => {
    const rawContext = task?.plan_json.repository_context?.retrieved_context;
    if (!Array.isArray(rawContext)) return [];
    const sources = rawContext
      .map((entry) => {
        if (!entry || typeof entry !== 'object') return '';
        const source = (entry as Record<string, unknown>).source;
        return typeof source === 'string' ? source : '';
      })
      .filter((source) => source.length > 0);
    return Array.from(new Set(sources)).slice(0, 8);
  }, [task]);

  const latestFailedStep = useMemo(() => {
    if (!task) return null;
    return [...task.steps].reverse().find((step) => step.status === 'failed') || null;
  }, [task]);

  const latestRunningStep = useMemo(() => {
    if (!task) return null;
    return [...task.steps].reverse().find((step) => step.status === 'running') || null;
  }, [task]);


  // Auto-expand the latest failed step so the recovery action is immediately visible.
  useEffect(() => {
    if (latestFailedStep) {
      setExpandedSteps((prev) => {
        if (prev.has(latestFailedStep.id)) return prev;
        return new Set([...prev, latestFailedStep.id]);
      });
    }
  }, [latestFailedStep]);

  useEffect(() => {
    if (latestRunningStep) {
      setExpandedSteps((prev) => {
        if (prev.has(latestRunningStep.id)) return prev;
        return new Set([...prev, latestRunningStep.id]);
      });
    }
  }, [latestRunningStep]);

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

  const toggleStep = (stepId: string) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev);
      if (next.has(stepId)) next.delete(stepId);
      else next.add(stepId);
      return next;
    });
  };

  const toggleTraceEntry = (traceKey: string) => {
    setExpandedTraceEntries((prev) => {
      const next = new Set(prev);
      if (next.has(traceKey)) next.delete(traceKey);
      else next.add(traceKey);
      return next;
    });
  };

  const buildStepFailureMessage = (step: (typeof task.steps)[number]) => {
    const sections = [`Task failure context for: ${task!.user_message}`];
    sections.push(`Failed subtask: ${step.title}`);
    if (step.command) sections.push(`Command:\n${step.command}`);
    if (step.output) sections.push(`Output:\n${step.output}`);
    if (step.error) sections.push(`Error:\n${step.error}`);
    if (task!.error) sections.push(`Task-level error:\n${task!.error}`);
    return sections.join('\n\n');
  };

  const getTraceIcon = (entryType: ReactTraceEntry['type']) => {
    if (entryType === 'thought') return <FaBrain className="h-4 w-4 text-violet-400" />;
    if (entryType === 'act') return <FaTerminal className="h-4 w-4 text-blue-400" />;
    return <FaEye className="h-4 w-4 text-emerald-400" />;
  };

  if (!task) {
    return (
      <div className="flex h-[calc(100vh-3rem)] items-center justify-center text-sm text-gray-500">
        Select a task to inspect its plan, live trace, and summary.
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-3rem)]">
      <div className="border-b border-mac-border bg-white px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-wide text-gray-500">Selected Task</div>
            <h2 className="mt-1 text-lg font-semibold text-gray-900">{task.user_message}</h2>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-500">
              <span className="rounded-full bg-gray-100 px-2 py-1">{formatWorkflowStatus(task.status)}</span>
              <span>Created {new Date(task.created_at).toLocaleString()}</span>
              {task.completed_at && <span>Completed {new Date(task.completed_at).toLocaleString()}</span>}
            </div>
          </div>
          {!isConnected && connectionError && onReconnect && (
            <button onClick={onReconnect} className="mac-button text-sm">
              Reconnect Stream
            </button>
          )}
        </div>

        {repositorySummary && (
          <div className="mt-4 rounded-lg border border-blue-100 bg-blue-50 p-4 text-sm text-blue-900">
            <div className="font-medium">Repository Context</div>
            <div className="mt-1">{repositorySummary}</div>
            {retrievedSources.length > 0 && (
              <div className="mt-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">
                  Retrieved Sources
                </div>
                <div className="mt-1 flex flex-wrap gap-1">
                  {retrievedSources.map((source) => (
                    <span key={source} className="rounded bg-blue-100 px-2 py-0.5 text-xs text-blue-800">
                      {source}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {task.status === 'waiting_for_human' && (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4">
            <div className="text-sm font-medium text-amber-900">Approval Required</div>
            <div className="mt-1 text-sm text-amber-800">
              The agent planned an execution step that needs operator approval before continuing.
            </div>
            {onApprove && (
              <div className="mt-3 flex gap-3">
                <button
                  onClick={() => onApprove(true)}
                  disabled={isApproving}
                  className="rounded-md bg-amber-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
                >
                  Approve
                </button>
                <button
                  onClick={() => onApprove(false)}
                  disabled={isApproving}
                  className="rounded-md border border-amber-300 bg-white px-3 py-2 text-sm font-medium text-amber-900 disabled:opacity-50"
                >
                  Reject
                </button>
              </div>
            )}
          </div>
        )}

      </div>

      <div className="flex-1 overflow-y-auto p-4 pb-0">
        <div className="space-y-4 mb-4">
          {task.steps.map((step) => (
            <div
              key={step.id}
              className="border border-mac-border rounded-lg bg-white shadow-sm transition-shadow"
            >
              <button
                onClick={() => toggleStep(step.id)}
                className="w-full flex items-center justify-between p-4 text-left focus:outline-none focus:ring-2 focus:ring-mac-hover focus:ring-opacity-50 rounded-t-lg"
              >
                <div className="flex items-center space-x-3">
                  {getWorkflowStatusIcon(step.status)}
                  <div>
                    <div className="text-sm font-medium text-gray-800">
                      {step.position}. {step.title}
                    </div>
                    <div className="text-xs text-gray-500">
                      {step.kind}
                      {step.requires_approval && ' • approval gate'}
                    </div>
                  </div>
                </div>
                {expandedSteps.has(step.id) ? (
                  <FaChevronDown className="w-4 h-4 text-gray-400" />
                ) : (
                  <FaChevronRight className="w-4 h-4 text-gray-400" />
                )}
              </button>

              {expandedSteps.has(step.id) && (
                <div className="border-t border-mac-border px-4 py-4 space-y-3">
                  {step.command && (
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">Command</div>
                      <pre className="mt-1 bg-gray-50 p-3 rounded-md text-sm overflow-x-auto font-mono">
                        {step.command}
                      </pre>
                    </div>
                  )}
                  {step.output && (
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">Output</div>
                      <pre className="mt-1 bg-gray-50 p-3 rounded-md text-sm overflow-x-auto font-mono whitespace-pre-wrap">
                        {step.output}
                      </pre>
                    </div>
                  )}
                  {step.error && (
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-wide text-red-500">Error</div>
                      <pre className="mt-1 bg-red-50 p-3 rounded-md text-sm text-red-700 overflow-x-auto font-mono whitespace-pre-wrap">
                        {step.error}
                      </pre>
                    </div>
                  )}
                  {step.status === 'failed' && onReplan && (
                    <div className="border-t border-red-100 pt-3 mt-1">
                      <div className="text-xs font-medium text-red-700 mb-2">Recovery</div>
                      <button
                        type="button"
                        onClick={() => onReplan(buildStepFailureMessage(step))}
                        disabled={isReplanning}
                        className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                      >
                        {isReplanning ? 'Generating fix step...' : 'Regenerate Next Fix Step'}
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

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
                {traceEntries.map((entry, index) => (
                  (() => {
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
                  })()
                ))}
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
            </div>
          )}
        </div>
      </div>
    </div>
  );
}