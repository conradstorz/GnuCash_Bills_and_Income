import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Layout from './components/Layout'
import DbUnavailable from './components/DbUnavailable'
import BillsQueue from './pages/BillsQueue'
import CashEntry from './pages/CashEntry'
import Vendors from './pages/Vendors'
import Settings from './pages/Settings'
import api from './api/client'

const queryClient = new QueryClient()

function AppInner() {
  const [dbError, setDbError] = useState<string | null>(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    api.get('/db/health').then(res => {
      if (res.data.status !== 'ok') setDbError(res.data.error || 'Database unavailable')
    }).catch(() => {
      setDbError('Could not reach server')
    }).finally(() => setChecking(false))
  }, [])

  if (checking) return null
  if (dbError) return <DbUnavailable error={dbError} />

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/bills" replace />} />
          <Route path="bills" element={<BillsQueue />} />
          <Route path="cash" element={<CashEntry />} />
          <Route path="vendors" element={<Vendors />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppInner />
    </QueryClientProvider>
  )
}
