export type SourceReference = {
  citation_id: string
  task_id: string
  chapter_id: string
  start_char: number
  end_char: number
  preview: string
}

export type TextChunk = {
  chunk_id: string
  chapter_id: string
  ordinal: number
  token_count: number
  overlap_with_previous_tokens: number
  reference: SourceReference
  content_override: string | null
}

export type TextChunkContent = {
  chunk: TextChunk
  content: string
  original_content: string
  is_edited: boolean
}

export type ParsedChapter = {
  chapter_id: string
  ordinal: number
  title: string
  heading_kind: 'chapter' | 'volume' | 'special' | 'fallback'
  volume_id: string | null
  volume_title: string | null
  heading_start_char: number
  heading_end_char: number
  content_start_char: number
  content_end_char: number
  character_count: number
  token_count: number
  preview: string
  chunk_ids: string[]
}

export type ParsedVolume = {
  volume_id: string
  ordinal: number
  title: string
  heading_start_char: number
  heading_end_char: number
  content_start_char: number
  content_end_char: number
  chapter_ids: string[]
}

export type ParsedDocument = {
  schema_version: 1 | 2
  task_id: string
  filename: string
  tokenizer: string
  character_count: number
  token_count: number
  chapter_count: number
  chunk_count: number
  used_fallback_chapter: boolean
  volumes: ParsedVolume[]
  chapters: ParsedChapter[]
  chunks: TextChunk[]
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

export async function parseDocument(taskId: string): Promise<ParsedDocument> {
  const response = await fetch(`/api/documents/${taskId}/parse`, {
    method: 'POST',
  })
  if (response.ok) {
    return response.json() as Promise<ParsedDocument>
  }

  const payload = (await response.json().catch(() => null)) as unknown
  throw new Error(responseDetail(payload, `解析失败（${response.status}）`))
}

export async function fetchParsedDocument(taskId: string): Promise<ParsedDocument> {
  const response = await fetch(`/api/documents/${taskId}/parse`)
  return parsedResponse(response, `读取解析结果失败（${response.status}）`)
}

async function parsedResponse(
  response: Response,
  fallback: string,
): Promise<ParsedDocument> {
  if (response.ok) {
    return response.json() as Promise<ParsedDocument>
  }
  const payload = (await response.json().catch(() => null)) as unknown
  throw new Error(responseDetail(payload, fallback))
}

export async function fetchChunkContent(
  taskId: string,
  chunkId: string,
): Promise<TextChunkContent> {
  const response = await fetch(`/api/documents/${taskId}/chunks/${chunkId}`)
  if (response.ok) {
    return response.json() as Promise<TextChunkContent>
  }
  const payload = (await response.json().catch(() => null)) as unknown
  throw new Error(responseDetail(payload, `读取文本块失败（${response.status}）`))
}

export async function updateTextChunk(
  taskId: string,
  chunkId: string,
  content: string,
): Promise<ParsedDocument> {
  const response = await fetch(`/api/documents/${taskId}/chunks/${chunkId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  })
  return parsedResponse(response, `保存文本块失败（${response.status}）`)
}

export async function deleteTextChunk(
  taskId: string,
  chunkId: string,
): Promise<ParsedDocument> {
  const response = await fetch(`/api/documents/${taskId}/chunks/${chunkId}`, {
    method: 'DELETE',
  })
  return parsedResponse(response, `删除文本块失败（${response.status}）`)
}
