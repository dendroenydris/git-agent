import { describe, expect, it } from 'vitest';

import type { Task, TaskEvent } from './api';
import { applyStepOutputEvent } from './task-events';


const buildTask = (): Task => ({
  id: 'task_1',
  dialog_id: 'dialog_1',
  user_message: 'Run tests',
  status: 'queued',
  approval_status: 'not_required',
  plan_json: {},
  result_json: {},
  current_step_index: 0,
  created_at: '2026-04-20T00:00:00.000Z',
  updated_at: '2026-04-20T00:00:00.000Z',
  steps: [
    {
      id: 'step_1',
      position: 1,
      title: 'Run tests',
      status: 'pending',
      kind: 'shell',
      requires_approval: false,
      created_at: '2026-04-20T00:00:00.000Z',
      updated_at: '2026-04-20T00:00:00.000Z',
      output: null,
      error: null,
    },
  ],
});


describe('applyStepOutputEvent', () => {
  it('appends stdout chunks and promotes pending work to running', () => {
    const event: TaskEvent = {
      type: 'step_output',
      dialog_id: 'dialog_1',
      task_id: 'task_1',
      payload: {
        step_id: 'step_1',
        stream: 'stdout',
        chunk: 'first line',
      },
    };

    const [updatedTask] = applyStepOutputEvent([buildTask()], event) || [];

    expect(updatedTask.status).toBe('running');
    expect(updatedTask.steps[0].status).toBe('running');
    expect(updatedTask.steps[0].output).toContain('first line');
  });

  it('appends stderr chunks using the step position fallback', () => {
    const event: TaskEvent = {
      type: 'step_output',
      dialog_id: 'dialog_1',
      task_id: 'task_1',
      payload: {
        step_position: 1,
        stream: 'stderr',
        chunk: 'boom',
      },
    };

    const [updatedTask] = applyStepOutputEvent([buildTask()], event) || [];

    expect(updatedTask.steps[0].error).toContain('boom');
    expect(updatedTask.steps[0].status).toBe('running');
  });
});
