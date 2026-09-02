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
}

export type ParsedChapter = {
  chapter_id: string
  ordinal: number
  title: string
  heading_kind: 'chapter' | 'volume' | 'special' | 'fallback'
  heading_start_char: number
  heading_end_char: number
  content_start_char: number
  content_end_char: number
  character_count: number
  token_count: number
  preview: string
  chunk_ids: string[]
}

export type ParsedDocument = {
  schema_version: 1
  task_id: string
  filename: string
  tokenizer: string
  character_count: number
  token_count: number
  chapter_count: number
  chunk_count: number
  used_fallback_chapter: boolean
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
