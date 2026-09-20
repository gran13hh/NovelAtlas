import type { NovelOutline } from '../analysis/api'

export type ExportFormat = 'docx' | 'html'
export type ExportSection =
  | 'overall_summary'
  | 'chapter_outline'
  | 'storylines'
  | 'characters'
  | 'worldbuilding'
  | 'foreshadowing'
  | 'unresolved_items'

export type OutlineExportRequest = {
  title: string
  format: ExportFormat
  sections: ExportSection[]
  outline: NovelOutline
}

function responseDetail(payload: unknown, fallback: string): string {
  if (typeof payload !== 'object' || payload === null || !('detail' in payload)) {
    return fallback
  }
  if (typeof payload.detail === 'string') return payload.detail
  return fallback
}

function responseFilename(response: Response, format: ExportFormat): string {
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  if (encoded) {
    try {
      return decodeURIComponent(encoded)
    } catch {
      // Fall back to a controlled filename when a proxy changes the header.
    }
  }
  return `NovelAtlas-全书细纲.${format}`
}

export async function downloadOutlineExport(
  request: OutlineExportRequest,
): Promise<string> {
  const response = await fetch('/api/exports/outline', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as unknown
    throw new Error(responseDetail(payload, `导出失败（${response.status}）`))
  }

  const filename = responseFilename(response, request.format)
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
  return filename
}
