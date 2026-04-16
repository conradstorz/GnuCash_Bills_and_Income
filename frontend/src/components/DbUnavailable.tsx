interface Props { error: string }

export default function DbUnavailable({ error }: Props) {
  return (
    <div className="flex items-center justify-center min-h-screen bg-slate-50">
      <div className="bg-white border border-red-200 rounded-lg p-8 max-w-md w-full shadow">
        <h2 className="text-lg font-semibold text-red-700 mb-2">Database Unavailable</h2>
        <p className="text-slate-600 text-sm mb-4">{error}</p>
        <div className="flex gap-2">
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
          >
            Retry
          </button>
        </div>
      </div>
    </div>
  )
}
