import { useState } from 'react'

type StructuredEditorProps = {
  label: string
  value: unknown
  isSaving: boolean
  onSave: (value: unknown) => Promise<void>
}

export function StructuredEditor({
  label,
  value,
  isSaving,
  onSave,
}: StructuredEditorProps) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(() => JSON.stringify(value, null, 2))
  const [error, setError] = useState<string | null>(null)

  const save = async () => {
    setError(null)
    try {
      const parsed = JSON.parse(draft) as unknown
      await onSave(parsed)
      setOpen(false)
    } catch (saveError) {
      setError(
        saveError instanceof SyntaxError
          ? 'JSON 格式有误，请检查逗号、引号和括号。'
          : saveError instanceof Error
            ? saveError.message
            : '保存失败，请稍后重试',
      )
    }
  }

  return (
    <div className="mt-4 border-t border-black/8 pt-4">
      <button
        type="button"
        onClick={() => {
          if (!open) setDraft(JSON.stringify(value, null, 2))
          setOpen((current) => !current)
        }}
        className="text-xs font-semibold text-[#31533f] hover:underline"
      >
        {open ? '收起结构化编辑器' : label}
      </button>
      {open && (
        <div className="mt-3 rounded-xl border border-[#31533f]/15 bg-[#f3f1ea] p-3">
          <p className="text-xs leading-5 text-amber-800/75">
            可以修改文字和数组内容，但请保留字段名及 sources 来源字段；后端会重新校验。
          </p>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            disabled={isSaving}
            rows={16}
            spellCheck={false}
            aria-label={label}
            className="mt-3 w-full resize-y rounded-lg border border-black/10 bg-white px-3 py-3 font-mono text-xs leading-5 text-[#17221b] outline-none focus:border-[#55705e] focus:ring-3 focus:ring-[#55705e]/10"
          />
          {error && (
            <p className="mt-2 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-800">
              {error}
            </p>
          )}
          <div className="mt-3 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setDraft(JSON.stringify(value, null, 2))
                setError(null)
              }}
              disabled={isSaving}
              className="rounded-lg border border-black/10 bg-white px-3 py-2 text-xs font-semibold text-black/55"
            >
              撤销编辑
            </button>
            <button
              type="button"
              onClick={save}
              disabled={isSaving}
              className="rounded-lg bg-[#1e3227] px-4 py-2 text-xs font-semibold text-white disabled:opacity-50"
            >
              {isSaving ? '正在保存…' : '校验并保存'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
