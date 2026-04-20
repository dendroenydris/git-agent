import { useEffect, useMemo, useState } from 'react';
import { FaChevronDown, FaChevronRight } from 'react-icons/fa';

import type { Task } from '../../lib/api';
import { getWorkflowStatusIcon } from '../../lib/task-status';
import TerminalOutputPanel from './TerminalOutputPanel';
import { buildStepFailureMessage } from './helpers';


interface TaskStepsPanelProps {
  task: Task;
  onReplan?: (failureMessage: string) => void;
  isReplanning: boolean;
}


export default function TaskStepsPanel({
  task,
  onReplan,
  isReplanning,
}: TaskStepsPanelProps) {
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set());

  const latestFailedStep = useMemo(
    () => [...task.steps].reverse().find((step) => step.status === 'failed') || null,
    [task.steps]
  );
  const latestRunningStep = useMemo(
    () => [...task.steps].reverse().find((step) => step.status === 'running') || null,
    [task.steps]
  );

  useEffect(() => {
    if (!latestFailedStep) return;
    setExpandedSteps((prev) => {
      if (prev.has(latestFailedStep.id)) return prev;
      return new Set([...prev, latestFailedStep.id]);
    });
  }, [latestFailedStep]);

  useEffect(() => {
    if (!latestRunningStep) return;
    setExpandedSteps((prev) => {
      if (prev.has(latestRunningStep.id)) return prev;
      return new Set([...prev, latestRunningStep.id]);
    });
  }, [latestRunningStep]);

  const toggleStep = (stepId: string) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev);
      if (next.has(stepId)) next.delete(stepId);
      else next.add(stepId);
      return next;
    });
  };

  return (
    <div className="flex-1 overflow-y-auto p-4 pb-0">
      <div className="mb-4 space-y-4">
        {task.steps.map((step) => (
          <div
            key={step.id}
            className="rounded-lg border border-mac-border bg-white shadow-sm transition-shadow"
          >
            <button
              onClick={() => toggleStep(step.id)}
              className="w-full rounded-t-lg p-4 text-left focus:outline-none focus:ring-2 focus:ring-mac-hover focus:ring-opacity-50"
            >
              <div className="flex items-center justify-between">
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
                  <FaChevronDown className="h-4 w-4 text-gray-400" />
                ) : (
                  <FaChevronRight className="h-4 w-4 text-gray-400" />
                )}
              </div>
            </button>

            {expandedSteps.has(step.id) && (
              <div className="space-y-3 border-t border-mac-border px-4 py-4">
                {step.command && (
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Command
                    </div>
                    <pre className="mt-1 rounded-md bg-gray-50 p-3 text-sm overflow-x-auto font-mono">
                      {step.command}
                    </pre>
                  </div>
                )}
                {step.output && (
                  <TerminalOutputPanel
                    title="Output"
                    content={step.output}
                    initiallyExpanded={step.status === 'running'}
                  />
                )}
                {step.error && (
                  <TerminalOutputPanel
                    title="Error"
                    content={step.error}
                    tone="error"
                    initiallyExpanded
                  />
                )}
                {step.status === 'failed' && onReplan && (
                  <div className="mt-1 border-t border-red-100 pt-3">
                    <div className="mb-2 text-xs font-medium text-red-700">Recovery</div>
                    <button
                      type="button"
                      onClick={() => onReplan(buildStepFailureMessage(task, step))}
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
  );
}
