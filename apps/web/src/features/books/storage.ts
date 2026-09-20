import type {
  AnalysisPlan,
  AnalysisTaskManifest,
  BatchSummaryRecord,
  FinalOutlineRecord,
} from '../analysis/api'
import type { UploadedDocument } from '../upload/api'

const DATABASE_NAME = 'novelatlas-library'
const DATABASE_VERSION = 1
const BOOK_STORE = 'books'

export type ShelfBookStage =
  | 'uploaded'
  | 'parsed'
  | 'planned'
  | AnalysisTaskManifest['status']

export type ShelfBook = {
  version: 1
  id: string
  task_id: string
  title: string
  created_at: string
  updated_at: string
  source_expires_at: string
  stage: ShelfBookStage
  chapter_count: number | null
  chunk_count: number | null
  plan: AnalysisPlan | null
  manifest: AnalysisTaskManifest | null
  summaries: BatchSummaryRecord[]
  outline: FinalOutlineRecord | null
}

function openLibrary(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (!('indexedDB' in window)) {
      reject(new Error('当前浏览器不支持 IndexedDB，无法保存书架。'))
      return
    }

    const request = window.indexedDB.open(DATABASE_NAME, DATABASE_VERSION)
    request.onerror = () => reject(request.error ?? new Error('无法打开浏览器书架。'))
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(BOOK_STORE)) {
        request.result.createObjectStore(BOOK_STORE, { keyPath: 'id' })
      }
    }
    request.onsuccess = () => resolve(request.result)
  })
}

async function transactStore<T>(
  mode: IDBTransactionMode,
  operation: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const database = await openLibrary()
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(BOOK_STORE, mode)
    const request = operation(transaction.objectStore(BOOK_STORE))
    let result: T
    request.onsuccess = () => {
      result = request.result
    }
    request.onerror = () => reject(request.error ?? new Error('浏览器书架操作失败。'))
    transaction.oncomplete = () => {
      database.close()
      resolve(result)
    }
    transaction.onerror = () => {
      database.close()
      reject(transaction.error ?? new Error('浏览器书架写入失败。'))
    }
    transaction.onabort = () => database.close()
  })
}

export function createShelfBook(uploaded: UploadedDocument): ShelfBook {
  return {
    version: 1,
    id: uploaded.task_id,
    task_id: uploaded.task_id,
    title: uploaded.filename,
    created_at: uploaded.created_at,
    updated_at: uploaded.created_at,
    source_expires_at: uploaded.expires_at,
    stage: 'uploaded',
    chapter_count: null,
    chunk_count: null,
    plan: null,
    manifest: null,
    summaries: [],
    outline: null,
  }
}

export async function listShelfBooks(): Promise<ShelfBook[]> {
  const books = await transactStore<ShelfBook[]>('readonly', (store) => store.getAll())
  return books.sort(
    (left, right) =>
      new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime(),
  )
}

export async function getShelfBook(id: string): Promise<ShelfBook | null> {
  const book = await transactStore<ShelfBook | undefined>('readonly', (store) =>
    store.get(id),
  )
  return book ?? null
}

export async function saveShelfBook(book: ShelfBook): Promise<void> {
  await transactStore<IDBValidKey>('readwrite', (store) => store.put(book))
}

export async function removeShelfBook(id: string): Promise<void> {
  await transactStore<undefined>('readwrite', (store) => store.delete(id))
}
