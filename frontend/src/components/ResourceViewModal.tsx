import { X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { fetchResourceItems } from '../api/dashboardApi'
import type { ResourceItemsResponse } from '../api/dashboardApi'

interface ResourceViewModalProps {
  open: boolean
  resourceName: string
  onClose: () => void
}

export function ResourceViewModal({ open, resourceName, onClose }: ResourceViewModalProps) {
  const [data, setData] = useState<ResourceItemsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!resourceName) return
    setLoading(true)
    setError(null)
    try {
      const result = await fetchResourceItems(resourceName)
      setData(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load resource items')
    } finally {
      setLoading(false)
    }
  }, [resourceName])

  useEffect(() => {
    if (open && resourceName) {
      void load()
    }
    if (!open) {
      setData(null)
      setError(null)
    }
  }, [open, resourceName, load])

  if (!open) return null

  const items = data?.items ?? []
  const columnKeys = items.length > 0
    ? Array.from(new Set(items.flatMap((item) => Object.keys(item))))
    : []

  // Put resource_id first if present
  const orderedKeys = columnKeys.includes('resource_id')
    ? ['resource_id', ...columnKeys.filter((k) => k !== 'resource_id')]
    : columnKeys

  return (
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <section
        className="modal modal--lg"
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="modal__header">
          <h2>
            {resourceName}
            {data ? <span className="resource-view-count">{data.total} items</span> : null}
          </h2>
          <button className="modal__close" type="button" onClick={onClose}>
            <X size={14} />
          </button>
        </header>

        <div className="modal__content resource-view-content">
          {loading ? (
            <p className="resource-view-placeholder">Loading...</p>
          ) : error ? (
            <p className="resource-view-placeholder resource-view-placeholder--error">{error}</p>
          ) : items.length === 0 ? (
            <p className="resource-view-placeholder">No resource items found.</p>
          ) : (
            <div className="resource-view-table-wrap">
              <table className="resource-view-table">
                <thead>
                  <tr>
                    {orderedKeys.map((key) => (
                      <th key={key}>{key}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map((item, idx) => (
                    <tr key={String(item.resource_id ?? idx)}>
                      {orderedKeys.map((key) => (
                        <td key={key}>{formatCellValue(item[key])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <footer className="modal__footer">
          <button className="btn" type="button" onClick={onClose}>
            Close
          </button>
        </footer>
      </section>
    </div>
  )
}

function formatCellValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
