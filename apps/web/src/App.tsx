import { useQuery } from '@tanstack/react-query'
import { NavLink, Route, Routes } from 'react-router-dom'

import { ModelGatewayPanel } from './features/models/ModelGatewayPanel'
import { BookDetailPage } from './pages/BookDetailPage'
import { BookshelfPage } from './pages/BookshelfPage'
import { HomePage } from './pages/HomePage'
import { NewBookPage } from './pages/NewBookPage'

type HealthResponse = {
  status: 'ok'
  service: string
  version: string
}

async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch('/api/health')
  if (!response.ok) throw new Error(`API health check failed with ${response.status}`)
  return response.json() as Promise<HealthResponse>
}

const navigation = [
  { to: '/', label: '主页面', end: true },
  { to: '/books', label: '我的书架', end: false },
  { to: '/settings', label: '模型配置', end: true },
]

function App() {
  const health = useQuery({
    queryKey: ['api-health'],
    queryFn: fetchHealth,
    retry: 1,
    refetchInterval: 30_000,
  })
  const apiState = health.isPending
    ? { label: '正在连接 API', tone: 'bg-amber-400' }
    : health.isError
      ? { label: 'API 未启动', tone: 'bg-rose-400' }
      : { label: `API 已连接 · v${health.data.version}`, tone: 'bg-emerald-400' }

  return (
    <main className="min-h-screen overflow-hidden bg-[#f3f1ea] text-[#191a17]">
      <div className="pointer-events-none fixed inset-0 opacity-45 [background-image:radial-gradient(#b9b5a7_0.7px,transparent_0.7px)] [background-size:18px_18px]" />
      <div className="relative mx-auto min-h-screen max-w-[1440px] border-x border-black/10 bg-[#f8f7f2]/95">
        <header className="relative border-b border-black/10 bg-[#f8f7f2]/95 px-5 py-4 md:px-10">
          <div className="flex items-center justify-between gap-4">
            <NavLink to="/" className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-xl bg-[#1e3227] font-mono text-sm font-bold tracking-tight text-[#e7efdf] shadow-[0_6px_20px_rgba(30,50,39,0.2)]">NA</span>
              <div className="hidden lg:block">
                <p className="font-serif text-lg font-semibold leading-none tracking-tight">NovelAtlas</p>
                <p className="mt-1 text-[10px] font-medium uppercase tracking-[0.22em] text-black/45">Narrative Intelligence</p>
              </div>
            </NavLink>

            <div className="hidden items-center gap-2 rounded-full border border-black/10 bg-white/70 px-3 py-2 text-xs font-medium text-black/60 shadow-sm lg:flex">
              <span className={`size-2 rounded-full ${apiState.tone}`} />
              <span>{apiState.label}</span>
            </div>
          </div>

          <nav aria-label="主导航" className="mt-4 flex gap-1 overflow-x-auto rounded-xl bg-black/[0.035] p-1 sm:absolute sm:top-4 sm:left-1/2 sm:mt-0 sm:-translate-x-1/2">
            {navigation.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-lg px-4 py-2.5 text-sm font-semibold transition ${
                    isActive
                      ? 'bg-white text-[#1e3227] shadow-sm'
                      : 'text-black/45 hover:text-black/70'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </header>

        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/books" element={<BookshelfPage />} />
          <Route path="/books/new" element={<NewBookPage />} />
          <Route path="/books/:bookId" element={<BookDetailPage />} />
          <Route path="/settings" element={<ModelGatewayPanel />} />
          <Route path="*" element={<HomePage />} />
        </Routes>

        <footer className="flex flex-col gap-2 border-t border-black/10 px-5 py-6 text-xs text-black/42 md:flex-row md:items-center md:justify-between md:px-10">
          <span>NovelAtlas · AI Agent 长篇小说细纲工作台</span>
          <span>本地优先 · 浏览器书架 · 批次可恢复</span>
        </footer>
      </div>
    </main>
  )
}

export default App
