import React, { useState, useEffect } from 'react'
import { FramePicker } from './FramePicker'
import { SectionSelector } from './SectionSelector'

interface Props {
  figmaUrl: string
  onBack: () => void
}

type Step = 'loading-frames' | 'pick-frame' | 'loading-sections' | 'pick-sections' | 'generating' | 'done'

export function FigmaWorkflow({ figmaUrl, onBack }: Props) {
  const [step, setStep] = useState<Step>('loading-frames')
  const [frames, setFrames] = useState<any[]>([])
  const [sections, setSections] = useState<any[]>([])
  const [selectedFrame, setSelectedFrame] = useState<any>(null)
  const [selectedSections, setSelectedSections] = useState<string[]>([])
  const [progress, setProgress] = useState('')
  const [deployUrl, setDeployUrl] = useState('')
  const [error, setError] = useState('')

  const API = 'http://localhost:8001'

  useEffect(() => {
    fetchFrames()
  }, [])

  const fetchFrames = async () => {
    try {
      const res = await fetch(`${API}/workflow/frames`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ figma_url: figmaUrl })
      })
      const data = await res.json()
      setFrames(data.frames || [])
      setStep('pick-frame')
    } catch (e: any) {
      setError(e.message)
    }
  }

  const handleFrameSelect = async (frame: any) => {
    setSelectedFrame(frame)
    setStep('loading-sections')
    try {
      const res = await fetch(`${API}/workflow/sections`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ figma_url: figmaUrl, frame_id: frame.id })
      })
      const data = await res.json()
      const secs = data.sections || []
      setSections(secs)
      setSelectedSections(secs.map((s: any) => s.id))
      setStep('pick-sections')
    } catch (e: any) {
      setError(e.message)
    }
  }

  const handleGenerate = async () => {
    setStep('generating')
    setProgress('Starting conversion...')

    const ws = new WebSocket('ws://localhost:8002')
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data)
      if (msg.type === 'step_update') {
        setProgress(msg.data?.message || msg.data?.step_name || '')
      }
      if (msg.type === 'workflow_complete') {
        setDeployUrl(msg.data?.vercel_url || '')
        setStep('done')
        ws.close()
      }
    }

    try {
      await fetch(`${API}/workflow/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ figma_url: figmaUrl, frame_id: selectedFrame.id })
      })
    } catch (e: any) {
      setError(e.message)
    }
  }

  return (
    <div className="fw-container">
      <div className="fw-header">
        <button className="fw-back-btn" onClick={onBack}>← Back</button>
        <h2 className="fw-title">Figma to Website</h2>
      </div>

      {error && <div className="fw-error">{error}</div>}

      {step === 'loading-frames' && (
        <div className="fw-loading">
          <div className="fw-spinner">⚡</div>
          <p>Loading frames...</p>
        </div>
      )}

      {step === 'pick-frame' && (
        <FramePicker frames={frames} onSelect={handleFrameSelect} />
      )}

      {step === 'loading-sections' && (
        <div className="fw-loading">
          <div className="fw-spinner">⚡</div>
          <p>Analyzing {selectedFrame?.name}...</p>
        </div>
      )}

      {step === 'pick-sections' && (
        <SectionSelector
          sections={sections}
          selected={selectedSections}
          onToggle={(id) => {
            setSelectedSections(prev =>
              prev.includes(id) ? prev.filter(s => s !== id) : [...prev, id]
            )
          }}
          onGenerate={handleGenerate}
          frameName={selectedFrame?.name}
        />
      )}

      {step === 'generating' && (
        <div className="fw-loading">
          <div className="fw-spinner">⚡</div>
          <p className="fw-progress">{progress}</p>
        </div>
      )}

      {step === 'done' && (
        <div className="fw-done">
          <div className="fw-done-icon">✅</div>
          <h3>Deployed!</h3>
          {deployUrl && (
            <a className="fw-deploy-url" href={deployUrl} target="_blank" rel="noreferrer">
              {deployUrl}
            </a>
          )}
          <button className="fw-generate-btn" onClick={onBack}>Convert Another</button>
        </div>
      )}
    </div>
  )
}
