import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'

import type { NovelOutline } from '../analysis/api'
import {
  downloadOutlineExport,
  type ExportFormat,
  type ExportSection,
} from './api'

const choices: Array<{
  id: ExportSection
  label: string
  description: string
}> = [
  { id: 'overall_summary', label: '总体概述', description: '全书核心剧情概览' },
  { id: 'chapter_outline', label: '章节细纲', description: '按章节范围排列的剧情' },
  { id: 'storylines', label: '故事线', description: '主线与关键发展' },
  { id: 'characters', label: '人物关系', description: '人物、关系与变化' },
  { id: 'worldbuilding', label: '世界观', description: '地点、势力、规则与物品' },
  { id: 'foreshadowing', label: '伏笔', description: '疑似铺垫与远距离关联' },
  { id: 'unresolved_items', label: '未解决项', description: '悬念、冲突和不确定信息' },
]

type ExportPanelProps = {
  title: string
  outline: NovelOutline
}

export function ExportPanel({ title, outline }: ExportPanelProps) {
  const [format, setFormat] = useState<ExportFormat>('docx')
  const [sections, setSections] = useState<ExportSection[]>(() =>
    choices.map((choice) => choice.id),
  )
  const [message, setMessage] = useState<string | null>(null)
  const download = useMutation({
    mutationFn: downloadOutlineExport,
    onMutate: () => setMessage(null),
    onSuccess: (filename) => setMessage(`已生成并下载：${filename}`),
  })

  const toggle = (section: ExportSection) => {
    setSections((current) =>
      current.includes(section)
        ? current.filter((item) => item !== section)
        : [...current, section],
    )
  }

  return (
    <section className="mt-6 overflow-hidden rounded-2xl border border-[#31533f]/18 bg-[#edf2e9]">
      <div className="border-b border-[#31533f]/10 p-5 md:p-6">
        <p className="text-xs font-bold uppercase tracking-[0.16em] text-[#55705e]">Export · 导出细纲</p>
        <div className="mt-2 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <h2 className="font-serif text-2xl font-semibold text-[#17221b]">带走这份整理结果</h2>
            <p className="mt-2 text-sm leading-6 text-black/45">Word 含标题页、目录和分页样式；HTML 是可离线打开和打印的单文件。</p>
          </div>
          <div className="flex rounded-xl border border-black/10 bg-white/65 p-1">
            {(['docx', 'html'] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setFormat(value)}
                className={`rounded-lg px-4 py-2 text-xs font-bold uppercase transition ${format === value ? 'bg-[#1e3227] text-white' : 'text-black/42 hover:text-black/65'}`}
              >
                {value}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="p-5 md:p-6">
        <fieldset>
          <legend className="text-xs font-bold text-black/48">选择导出内容</legend>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {choices.map((choice) => (
              <label key={choice.id} className="flex cursor-pointer gap-3 rounded-xl border border-black/8 bg-white/65 p-3 transition hover:border-[#55705e]/30">
                <input
                  type="checkbox"
                  checked={sections.includes(choice.id)}
                  onChange={() => toggle(choice.id)}
                  className="mt-1 size-4 accent-[#31533f]"
                />
                <span><span className="block text-sm font-semibold text-[#17221b]">{choice.label}</span><span className="mt-1 block text-xs leading-5 text-black/38">{choice.description}</span></span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs leading-5 text-black/38">导出内容由当前页面细纲即时生成，服务端不会保存文件。</p>
          <button
            type="button"
            disabled={sections.length === 0 || download.isPending}
            onClick={() => download.mutate({ title, format, sections, outline })}
            className="shrink-0 rounded-xl bg-[#1e3227] px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-[#294535] disabled:cursor-not-allowed disabled:opacity-45"
          >
            {download.isPending ? '正在生成…' : `导出 ${format.toUpperCase()}`}
          </button>
        </div>
        {sections.length === 0 && <p className="mt-3 text-xs text-amber-700">请至少选择一个导出模块。</p>}
        {download.error instanceof Error && <p className="mt-3 rounded-xl border border-rose-900/10 bg-rose-50 px-4 py-3 text-sm text-rose-800">{download.error.message}</p>}
        {message && <p className="mt-3 rounded-xl border border-emerald-900/10 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{message}</p>}
      </div>
    </section>
  )
}
