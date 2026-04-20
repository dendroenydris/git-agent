import type { Task, TaskEvent } from './api';
import { appendTerminalChunk } from './terminal-output';


export const applyStepOutputEvent = (
  tasks: Task[] | undefined,
  event: TaskEvent
): Task[] | undefined => {
  if (!tasks || event.type !== 'step_output' || !event.task_id) return tasks;

  const stepId = typeof event.payload.step_id === 'string' ? event.payload.step_id : null;
  const stepPosition =
    typeof event.payload.step_position === 'number' ? event.payload.step_position : null;
  const stream = event.payload.stream === 'stderr' ? 'stderr' : 'stdout';
  const chunk = typeof event.payload.chunk === 'string' ? event.payload.chunk : '';
  if (!chunk || (!stepId && stepPosition === null)) return tasks;

  return tasks.map((task) => {
    if (task.id !== event.task_id) return task;

    return {
      ...task,
      status: task.status === 'queued' ? 'running' : task.status,
      steps: task.steps.map((step) => {
        const matchesStep =
          (stepId !== null && step.id === stepId) ||
          (stepPosition !== null && step.position === stepPosition);
        if (!matchesStep) return step;

        if (stream === 'stderr') {
          return {
            ...step,
            status: step.status === 'pending' ? 'running' : step.status,
            error: appendTerminalChunk(step.error, chunk),
          };
        }

        return {
          ...step,
          status: step.status === 'pending' ? 'running' : step.status,
          output: appendTerminalChunk(step.output, chunk),
        };
      }),
    };
  });
};
