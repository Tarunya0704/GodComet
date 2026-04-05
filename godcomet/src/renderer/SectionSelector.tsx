import React from 'react'

interface Section {
  id: string
  name: string
  width: number
  height: number
  is_template: boolean
  instance_count: number
  thumbnail_b64: string
}

interface Props {
  sections: Section[]
  selected: string[]
  onToggle: (id: string) => void
  onGenerate: () => void
  frameName: string
}

export function SectionSelector({ sections, selected, onToggle, onGenerate, frameName }: Props) {
  return (
    <div className="ss-container">
      <h3 className="ss-heading">Sections in "{frameName}"</h3>
      <p className="ss-hint">Uncheck sections you don't want to convert</p>
      <div className="ss-list">
        {sections.map((section) => (
          <div key={section.id} className="ss-item">
            <input
              type="checkbox"
              className="ss-checkbox"
              checked={selected.includes(section.id)}
              onChange={() => onToggle(section.id)}
            />
            {section.thumbnail_b64 && (
              <img src={section.thumbnail_b64} alt={section.name} className="ss-thumb" />
            )}
            <div className="ss-info">
              <div className="ss-name">
                {section.name}
                {section.is_template && (
                  <span className="ss-badge">×{section.instance_count}</span>
                )}
              </div>
              <div className="ss-dims">{section.width}×{section.height}</div>
            </div>
          </div>
        ))}
      </div>
      <button
        className="fw-generate-btn"
        onClick={onGenerate}
        disabled={selected.length === 0}
      >
        Generate {selected.length} section{selected.length !== 1 ? 's' : ''}
      </button>
    </div>
  )
}
