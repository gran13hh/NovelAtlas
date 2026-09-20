export const DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

export type UploadConstraints = {
  max_upload_bytes: number
  upload_ttl_seconds: number
  accepted_extensions: string[]
}

export type UploadedDocument = {
  task_id: string
  filename: string
  detected_encoding: string
  size_bytes: number
  character_count: number
  created_at: string
  expires_at: string
}

export async function fetchUploadConstraints(): Promise<UploadConstraints> {
  const response = await fetch('/api/uploads/config')
  if (!response.ok) {
    throw new Error(`Unable to read upload constraints (${response.status})`)
  }
  return response.json() as Promise<UploadConstraints>
}

export async function fetchUpload(taskId: string): Promise<UploadedDocument> {
  const response = await fetch(`/api/uploads/${taskId}`)
  if (response.ok) return response.json() as Promise<UploadedDocument>
  const payload = (await response.json().catch(() => null)) as unknown
  throw new Error(responseDetail(payload, `读取临时任务失败（${response.status}）`))
}

type UploadOptions = {
  signal: AbortSignal
  onProgress: (progress: number) => void
}

function responseDetail(response: unknown, fallback: string): string {
  if (
    typeof response === 'object' &&
    response !== null &&
    'detail' in response &&
    typeof response.detail === 'string'
  ) {
    return response.detail
  }
  return fallback
}

export function uploadTxt(
  file: File,
  { signal, onProgress }: UploadOptions,
): Promise<UploadedDocument> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    const formData = new FormData()
    formData.append('file', file)

    const cleanup = () => signal.removeEventListener('abort', abortRequest)
    const abortRequest = () => request.abort()

    request.open('POST', '/api/uploads')
    request.responseType = 'json'
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100))
      }
    }
    request.onload = () => {
      cleanup()
      if (request.status >= 200 && request.status < 300) {
        onProgress(100)
        resolve(request.response as UploadedDocument)
        return
      }
      reject(
        new Error(
          responseDetail(request.response, `上传失败（${request.status}）`),
        ),
      )
    }
    request.onerror = () => {
      cleanup()
      reject(new Error('无法连接 API，请确认后端已启动'))
    }
    request.onabort = () => {
      cleanup()
      reject(new DOMException('上传已取消', 'AbortError'))
    }

    signal.addEventListener('abort', abortRequest, { once: true })
    request.send(formData)
  })
}

export async function deleteUpload(taskId: string): Promise<void> {
  const response = await fetch(`/api/uploads/${taskId}`, { method: 'DELETE' })
  if (response.ok) {
    return
  }

  const payload = (await response.json().catch(() => null)) as unknown
  throw new Error(responseDetail(payload, `删除失败（${response.status}）`))
}
