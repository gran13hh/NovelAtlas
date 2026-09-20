const WORKSPACE_TASK_KEY = 'novelatlas.workspace-task.v1'

export function loadWorkspaceTaskId(): string | null {
  try {
    const taskId = window.sessionStorage.getItem(WORKSPACE_TASK_KEY)
    return taskId && /^[0-9a-f]{32}$/.test(taskId) ? taskId : null
  } catch {
    return null
  }
}

export function saveWorkspaceTaskId(taskId: string): void {
  try {
    window.sessionStorage.setItem(WORKSPACE_TASK_KEY, taskId)
  } catch {
    // A blocked session store only disables refresh restoration.
  }
}

export function clearWorkspaceTaskId(): void {
  try {
    window.sessionStorage.removeItem(WORKSPACE_TASK_KEY)
  } catch {
    // Nothing else needs cleanup when browser storage is unavailable.
  }
}
