import type { Task } from '../../lib/api';
import { formatWorkflowStatus } from '../../lib/task-status';


interface TaskHeaderProps {
  task: Task;
  isConnected: boolean;
  connectionError: string | null;
  onReconnect?: () => void;
  onApprove?: (approved: boolean) => void;
  isApproving: boolean;
  repositorySummary: string;
  retrievedSources: string[];
}


export default function TaskHeader({
  task,
  isConnected,
  connectionError,
  onReconnect,
  onApprove,
  isApproving,
  repositorySummary,
  retrievedSources,
}: TaskHeaderProps) {
  return (
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
  );
}
