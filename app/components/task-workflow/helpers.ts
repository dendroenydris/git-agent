import type { ReactTraceEntry, Task, TaskStep } from '../../lib/api';
import { normalizeTerminalOutput } from '../../lib/terminal-output';


export const buildAggregatedOutput = (task: Task | null): string => {
  if (!task) return 'No task selected.';

  const stepLogs = task.steps
    .map((step) => {
      const sections = [`[${step.position}] ${step.title}`];
      if (step.command) sections.push(`$ ${step.command}`);
      if (step.output) sections.push(normalizeTerminalOutput(step.output));
      if (step.error) sections.push(`ERROR: ${normalizeTerminalOutput(step.error)}`);
      return sections.join('\n');
    })
    .join('\n\n');

  return stepLogs || 'Task queued. Waiting for planner output...';
};


export const parseTraceEntries = (task: Task | null): ReactTraceEntry[] => {
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
};


export const extractRetrievedSources = (task: Task | null): string[] => {
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
};


export const buildStepFailureMessage = (task: Task, step: TaskStep): string => {
  const sections = [`Task failure context for: ${task.user_message}`];
  sections.push(`Failed subtask: ${step.title}`);
  if (step.command) sections.push(`Command:\n${step.command}`);
  if (step.output) sections.push(`Output:\n${normalizeTerminalOutput(step.output)}`);
  if (step.error) sections.push(`Error:\n${normalizeTerminalOutput(step.error)}`);
  if (task.error) sections.push(`Task-level error:\n${task.error}`);
  return sections.join('\n\n');
};
