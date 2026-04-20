import { useMemo } from 'react';

import type { Task } from '../lib/api';
import TaskBottomPanel from './task-workflow/TaskBottomPanel';
import TaskHeader from './task-workflow/TaskHeader';
import TaskStepsPanel from './task-workflow/TaskStepsPanel';
import {
  buildAggregatedOutput,
  extractRetrievedSources,
  parseTraceEntries,
} from './task-workflow/helpers';

interface TaskWorkflowProps {
  task: Task | null;
  isConnected?: boolean;
  isTerminalOpen?: boolean;
  connectionError?: string | null;
  onReconnect?: () => void;
  onApprove?: (approved: boolean) => void;
  isApproving?: boolean;
  onReplan?: (failureMessage: string) => void;
  isReplanning?: boolean;
}

export default function TaskWorkflow({
  task,
  isConnected = false,
  isTerminalOpen = true,
  connectionError = null,
  onReconnect,
  onApprove,
  isApproving = false,
  onReplan,
  isReplanning = false,
}: TaskWorkflowProps) {
  const aggregatedOutput = useMemo(() => buildAggregatedOutput(task), [task]);
  const traceEntries = useMemo(() => parseTraceEntries(task), [task]);
  const retrievedSources = useMemo(() => extractRetrievedSources(task), [task]);
  const repositorySummary =
    typeof task?.plan_json.repository_context?.repository_summary === 'string'
      ? task.plan_json.repository_context.repository_summary
      : '';

  if (!task) {
    return (
      <div className="flex h-[calc(100vh-3rem)] items-center justify-center text-sm text-gray-500">
        Select a task to inspect its plan, live trace, and summary.
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-3rem)]">
      <TaskHeader
        task={task}
        isConnected={isConnected}
        connectionError={connectionError}
        onReconnect={onReconnect}
        onApprove={onApprove}
        isApproving={isApproving}
        repositorySummary={repositorySummary}
        retrievedSources={retrievedSources}
      />
      <TaskStepsPanel
        task={task}
        onReplan={onReplan}
        isReplanning={isReplanning}
      />
      <TaskBottomPanel
        task={task}
        isOpen={isTerminalOpen}
        traceEntries={traceEntries}
        aggregatedOutput={aggregatedOutput}
      />
    </div>
  );
}