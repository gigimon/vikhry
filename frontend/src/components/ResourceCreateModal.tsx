import { Plus, X } from 'lucide-react'

interface ResourceCreateModalProps {
  open: boolean
  resourceNames: string[]
  resourceCounts: Record<string, number>
  selectedResourceName: string
  countValue: string
  creating: boolean
  onClose: () => void
  onResourceChange: (resourceName: string) => void
  onCountChange: (count: string) => void
  onCreate: () => void | Promise<void>
}

const numberFormatter = new Intl.NumberFormat('en-US')

export function ResourceCreateModal({
  open,
  resourceNames,
  resourceCounts,
  selectedResourceName,
  countValue,
  creating,
  onClose,
  onResourceChange,
  onCountChange,
  onCreate,
}: ResourceCreateModalProps) {
  if (!open) {
    return null
  }

  const createDisabled = creating || resourceNames.length === 0 || !selectedResourceName
  const selectedCount = resourceCounts[selectedResourceName] ?? 0

  return (
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <section className="modal modal--sm" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
        <header className="modal__header">
          <h2>Create Resources</h2>
          <button className="modal__close" type="button" onClick={onClose}>
            <X size={14} />
          </button>
        </header>

        <div className="modal__content">
          <label className="field field--compact">
            <span className="field__label">Resource name</span>
            <select
              className="field__input"
              value={selectedResourceName}
              onChange={(event) => onResourceChange(event.target.value)}
              disabled={resourceNames.length === 0}
            >
              {resourceNames.length === 0 ? (
                <option value="">No resources available</option>
              ) : (
                resourceNames.map((resourceName) => (
                  <option key={resourceName} value={resourceName}>
                    {resourceName} ({numberFormatter.format(resourceCounts[resourceName] ?? 0)})
                  </option>
                ))
              )}
            </select>
          </label>

          <label className="field field--compact">
            <span className="field__label">Count</span>
            <input
              className="field__input"
              type="number"
              min={1}
              step={1}
              value={countValue}
              onChange={(event) => onCountChange(event.target.value)}
            />
          </label>

          <p className="field__hint">
            Existing: <strong>{numberFormatter.format(selectedCount)}</strong>
            {countValue && Number(countValue) > 0 ? (
              <> → after create: <strong>{numberFormatter.format(selectedCount + Number(countValue))}</strong></>
            ) : null}
          </p>
        </div>

        <footer className="modal__footer">
          <button className="btn" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn--primary" type="button" disabled={createDisabled} onClick={() => void onCreate()}>
            <Plus size={12} />
            <span>{creating ? 'Creating...' : 'Create'}</span>
          </button>
        </footer>
      </section>
    </div>
  )
}
