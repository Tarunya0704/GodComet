import React, { useState, useEffect } from 'react'
import { CommandBar } from './CommandBar'
import { Results } from './Results'
import { Settings } from './Settings'
import { FigmaWorkflow } from './FigmaWorkflow'
import './styles.css'

export function App() {
  const [view, setView] = useState<'command' | 'results' | 'settings' | 'figma'>('command')
  const [result, setResult] = useState<any>(null)
  const [context, setContext] = useState<any>(null)
  const [figmaUrl, setFigmaUrl] = useState('')

  useEffect(() => {
    // Listen for context updates
    if (window.electron) {
      window.electron.onContext((ctx: any) => {
        setContext(ctx)
      })
    }
  }, [])

  const handleExecute = async (command: string) => {
    if (command.includes('figma.com/design')) {
      setFigmaUrl(command.trim())
      setView('figma')
      return
    }
    try {
      const result = await window.electron.executeCommand(command)
      setResult(result)
      setView('results')
    } catch (error: any) {
      setResult({
        success: false,
        error: error.message
      })
      setView('results')
    }
  }

  const handleBack = () => {
    setView('command')
    setResult(null)
  }

  const handleSettings = () => {
    setView('settings')
  }

  return (
    <div className="app">
      {view === 'command' && (
        <CommandBar
          onExecute={handleExecute}
          onSettings={handleSettings}
          context={context}
        />
      )}
      
      {view === 'results' && (
        <Results
          result={result}
          onBack={handleBack}
        />
      )}
      
      {view === 'settings' && (
        <Settings
          onBack={handleBack}
        />
      )}

      {view === 'figma' && (
        <FigmaWorkflow
          figmaUrl={figmaUrl}
          onBack={() => { setView('command'); setFigmaUrl('') }}
        />
      )}
    </div>
  )
}