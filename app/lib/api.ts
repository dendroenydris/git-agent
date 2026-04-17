import axios from 'axios';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

export type TaskStatus =
  | 'queued'
  | 'running'
  | 'waiting_for_human'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type ApprovalStatus = 'not_required' | 'pending' | 'approved' | 'rejected';
export type StepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'waiting_for_human';
export type ApprovalMode = 'all-allow' | 'allow-allowlist' | 'no';

export interface GitHubRepo {
  owner: string;
  name: string;
  branch?: string;
}

export interface AgentMessage {
  id: string;
  type: 'user' | 'agent' | 'system';
  content: string;
  created_at: string;
  task_id?: string | null;
  summary?: string | null;
  metadata_json?: Record<string, unknown>;
}

export interface Dialog {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: AgentMessage[];
  repo?: GitHubRepo | null;
}

export interface TaskStep {
  id: string;
  position: number;
  title: string;
  status: StepStatus;
  kind: string;
  command?: string | null;
  output?: string | null;
  error?: string | null;
  requires_approval: boolean;
  metadata_json?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ReactTraceEntry {
  type: 'thought' | 'act' | 'observation';
  label: string;
  iteration?: number | null;
  step_position?: number | null;
  title?: string | null;
  kind?: string | null;
  command?: string | null;
  status?: string | null;
  created_at?: string | null;
  content_truncated?: boolean;
  content: string;
}

export interface Task {
  id: string;
  dialog_id: string;
  repository_id?: string | null;
  user_message: string;
  status: TaskStatus;
  approval_status: ApprovalStatus;
  plan_json: {
    intent?: Record<string, unknown>;
    repository_context?: Record<string, unknown>;
    steps?: Array<Record<string, unknown>>;
    planner_iterations?: Array<Record<string, unknown>>;
    react_trace?: ReactTraceEntry[];
  };
  result_json: {
    results?: Array<{
      step: string;
      success: boolean;
      output: string;
      error?: string | null;
      metadata?: Record<string, unknown>;
    }>;
  };
  summary?: string | null;
  error?: string | null;
  current_step_index: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  steps: TaskStep[];
}

export interface RepositoryIndex {
  id: string;
  repository_id: string;
  status: string;
  commit_sha?: string | null;
  vectorstore_path: string;
  total_files: number;
  total_chunks: number;
  summary?: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ChatAccepted {
  mode: 'task';
  task_id: string;
  dialog_id: string;
  status: TaskStatus;
}

export interface ChatAnswered {
  mode: 'answer';
  dialog_id: string;
  status: 'completed';
  answer: string;
}

export type ChatResponse = ChatAccepted | ChatAnswered;

export interface HealthResponse {
  status: string;
  redis: string;
  database: string;
  version: string;
}

export interface AppSettings {
  approval_mode: ApprovalMode;
}

export interface TaskEvent {
  type: 'task_created' | 'task_updated' | 'message_added' | 'approval_required' | 'step_output' | 'error';
  dialog_id?: string;
  task_id?: string;
  message_id?: string;
  payload: Record<string, unknown>;
}

export const healthCheck = async (): Promise<HealthResponse> => {
  const response = await apiClient.get('/health');
  return response.data;
};

export const getAppSettings = async (): Promise<AppSettings> => {
  const response = await apiClient.get('/api/settings');
  return response.data;
};

export const updateAppSettings = async (approvalMode: ApprovalMode): Promise<AppSettings> => {
  const response = await apiClient.put('/api/settings', { approval_mode: approvalMode });
  return response.data;
};

export const createDialog = async (repo: GitHubRepo): Promise<Dialog> => {
  const response = await apiClient.post('/api/dialogs', repo);
  return response.data;
};

export const getDialogs = async (): Promise<Dialog[]> => {
  const response = await apiClient.get('/api/dialogs');
  return response.data;
};

export const getDialog = async (dialogId: string): Promise<Dialog> => {
  const response = await apiClient.get(`/api/dialogs/${dialogId}`);
  return response.data;
};

export const submitChat = async (dialogId: string, message: string): Promise<ChatResponse> => {
  const response = await apiClient.post(`/api/dialogs/${dialogId}/chat`, { message });
  return response.data;
};

export const getTask = async (taskId: string): Promise<Task> => {
  const response = await apiClient.get(`/api/tasks/${taskId}`);
  return response.data;
};

export const getTasks = async (dialogId?: string): Promise<Task[]> => {
  const response = await apiClient.get('/api/tasks', {
    params: dialogId ? { dialog_id: dialogId } : undefined,
  });
  return response.data;
};

export const approveTask = async (
  taskId: string,
  approved: boolean,
  reason?: string
): Promise<{ task_id: string; status: TaskStatus; approval_status: ApprovalStatus }> => {
  const response = await apiClient.post(`/api/tasks/${taskId}/approval`, {
    approved,
    reason,
  });
  return response.data;
};

export const replanTask = async (
  taskId: string,
  failureMessage: string
): Promise<{ task_id: string; status: TaskStatus; approval_status: ApprovalStatus }> => {
  const response = await apiClient.post(`/api/tasks/${taskId}/replan`, {
    failure_message: failureMessage,
  });
  return response.data;
};

export const indexRepository = async (dialogId: string): Promise<RepositoryIndex> => {
  const response = await apiClient.post(`/api/repositories/${dialogId}/index`);
  return response.data;
};

export const getAvailableTools = async (): Promise<{ tools: Array<Record<string, unknown>> }> => {
  const response = await apiClient.get('/api/tools');
  return response.data;
};

export const formatTimestamp = (timestamp?: string | null): string => {
  if (!timestamp) return '';
  return new Date(timestamp).toLocaleString();
};

export const createUserMessage = (content: string): { type: 'user_message'; content: string } => ({
  type: 'user_message',
  content,
});

export default apiClient;