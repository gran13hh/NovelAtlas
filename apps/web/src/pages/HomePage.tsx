import { Link } from 'react-router-dom'

import { clearWorkspaceTaskId } from '../features/analysis/workspaceSession'

const outlineStages = [
  ['01', '上传与解析', '读取 TXT，识别章节并允许人工修正文块。'],
  ['02', '逐批概括', '按模型预算组合章节，每批成功后保存进度。'],
  ['03', '分层汇总', '梳理故事线、人物关系、世界观与伏笔。'],
  ['04', '收入书架', '把细纲留在当前浏览器，随时回来阅读。'],
]

export function HomePage() {
  return (
    <>
      <section className="grid border-b border-black/10 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="px-5 py-16 md:px-10 md:py-20 lg:border-r lg:border-black/10 lg:px-16 lg:py-24">
          <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-[#31533f]/20 bg-[#dfe8dc] px-3 py-1.5 text-xs font-semibold text-[#31533f]">
            <span>AI Agent</span><span className="h-3 w-px bg-[#31533f]/25" /><span>长篇小说细纲</span>
          </div>
          <h1 className="max-w-3xl font-serif text-5xl font-semibold leading-[1.04] tracking-[-0.045em] text-[#17221b] md:text-7xl">
            把一部长篇小说，<span className="text-[#55705e]">整理成可回看的详细大纲。</span>
          </h1>
          <p className="mt-7 max-w-2xl text-base leading-8 text-black/58 md:text-lg">
            上传 TXT 后，由 Agent 分批概括重要内容，再逐层汇总故事线、主要人物关系、世界观与伏笔。
          </p>
          <div className="mt-9 flex flex-wrap gap-3">
            <Link to="/books/new" onClick={clearWorkspaceTaskId} className="rounded-xl bg-[#1e3227] px-6 py-3.5 text-sm font-semibold text-white shadow-[0_10px_30px_rgba(30,50,39,0.18)] transition hover:bg-[#294535]">开始整理一本书</Link>
            <Link to="/books" className="rounded-xl border border-black/10 bg-white px-6 py-3.5 text-sm font-semibold text-black/62 shadow-sm transition hover:border-[#55705e]/35 hover:text-[#31533f]">打开我的书架</Link>
          </div>
        </div>

        <aside className="flex min-h-[430px] flex-col justify-between bg-[#24382c] p-6 text-[#e9eee7] md:p-10 lg:p-12">
          <div className="flex items-center justify-between text-xs uppercase tracking-[0.2em] text-white/45"><span>Outline flow</span><span>01 — 04</span></div>
          <div className="my-12 space-y-3">
            {outlineStages.map(([marker, title, description]) => (
              <div key={marker} className="grid grid-cols-[auto_1fr] gap-4 rounded-2xl border border-white/10 bg-white/[0.055] p-4">
                <span className="font-mono text-xs text-[#b7caae]">{marker}</span>
                <div><h2 className="text-base font-semibold tracking-tight">{title}</h2><p className="mt-1.5 text-sm leading-6 text-white/48">{description}</p></div>
              </div>
            ))}
          </div>
          <p className="text-xs leading-5 text-white/35">小说原文只进入后端临时任务；浏览器书架仅保存分析结果。</p>
        </aside>
      </section>

      <section className="grid gap-px bg-black/10 md:grid-cols-3">
        {[
          ['输入', 'TXT 小说正文', '校验编码、识别章节并建立无重叠分析片段'],
          ['概括', '批次 Agent + Skills', '动态组批、逐批保存并支持失败后继续'],
          ['输出', '浏览器细纲书架', '按文件名收录历史细纲，点击即可重新阅读'],
        ].map(([eyebrow, title, description], index) => (
          <article key={eyebrow} className="relative bg-[#f8f7f2] px-6 py-10 md:px-10 md:py-12">
            <div className="mb-8 flex items-center justify-between"><span className="text-xs font-bold uppercase tracking-[0.2em] text-[#55705e]">{eyebrow}</span><span className="font-mono text-xs text-black/25">0{index + 1}</span></div>
            <h2 className="font-serif text-2xl font-semibold tracking-tight">{title}</h2>
            <p className="mt-3 max-w-sm text-sm leading-6 text-black/50">{description}</p>
          </article>
        ))}
      </section>
    </>
  )
}
