import React from 'react'

interface Frame {
  id: string
  name: string
  width: number
  height: number
  page: string
  thumbnail_b64?: string
}

interface Props {
  frames: Frame[]
  onSelect: (frame: Frame) => void
}

export function FramePicker({ frames, onSelect }: Props) {
  return (
    <div className="fp-container">
      <h3 className="fp-heading">Select a frame to convert</h3>
      <div className="fp-grid">
        {frames.map((frame) => (
          <div key={frame.id} className="fp-card" onClick={() => onSelect(frame)}>
            <div className="fp-preview">
              {frame.thumbnail_b64 ? (
                <img src={frame.thumbnail_b64} alt={frame.name} className="fp-thumb" />
              ) : (
                <div className="fp-placeholder">
                  <span className="fp-dims">{frame.width}×{frame.height}</span>
                </div>
              )}
            </div>
            <div className="fp-name">{frame.name}</div>
            {frame.page && <div className="fp-page">{frame.page}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}
