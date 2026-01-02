// import { useState, useEffect } from 'react'
// import { Sparkles, Loader2, Check } from 'lucide-react'

// export function CommandBar() {
//   const [command, setCommand] = useState('')
//   const [isExecuting, setIsExecuting] = useState(false)
//   const [result, setResult] = useState<any>(null)
//   const [context, setContext] = useState<any>(null)

//   useEffect(() => {
//     // Listen for context
//     window.electron.onContext((ctx: any) => {
//       setContext(ctx)
//     })
//   }, [])

//   const handleExecute = async () => {
//     if (!command.trim()) return

//     setIsExecuting(true)
//     setResult(null)

//     try {
//       const result = await window.electron.executeCommand(command)
//       setResult(result)
//     } catch (error: any) {
//       setResult({
//         success: false,
//         error: error.message
//       })
//     } finally {
//       setIsExecuting(false)
//     }
//   }

//   const handleKeyDown = (e: React.KeyboardEvent) => {
//     if (e.key === 'Enter' && !e.shiftKey) {
//       e.preventDefault()
//       handleExecute()
//     }
//     if (e.key === 'Escape') {
//       window.electron.hideWindow()
//     }
//   }

//   return (
//     <div className="w-full h-full bg-white dark:bg-gray-900 rounded-2xl shadow-2xl overflow-hidden">
//       {/* Header */}
//       <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
//         <div className="flex items-center justify-between">
//           <div className="flex items-center space-x-2">
//             <Sparkles className="w-5 h-5 text-blue-600" />
//             <span className="font-bold text-lg">GodComet</span>
//           </div>
//           {context && (
//             <div className="text-sm text-gray-500">
//               📍 {context.app} {context.file && `- ${context.file}`}
//             </div>
//           )}
//         </div>
//       </div>

//       {/* Command Input */}
//       <div className="p-6">
//         <textarea
//           value={command}
//           onChange={(e) => setCommand(e.target.value)}
//           onKeyDown={handleKeyDown}
//           placeholder="What would you like to do?"
//           className="w-full px-4 py-3 border-2 border-gray-200 dark:border-gray-700 rounded-lg resize-none focus:border-blue-500 focus:outline-none dark:bg-gray-800"
//           rows={3}
//           autoFocus
//         />
//         <button
//           onClick={handleExecute}
//           disabled={isExecuting}
//           className="mt-4 w-full bg-blue-600 text-white py-3 rounded-lg font-semibold hover:bg-blue-700 transition disabled:opacity-50"
//         >
//           {isExecuting ? (
//             <>
//               <Loader2 className="w-5 h-5 inline mr-2 animate-spin" />
//               Executing...
//             </>
//           ) : (
//             <>
//               <Sparkles className="w-5 h-5 inline mr-2" />
//               Execute
//             </>
//           )}
//         </button>
//       </div>

//       {/* Results */}
//       {result && (
//         <div className="px-6 pb-6">
//           <div className={`p-4 rounded-lg ${
//             result.success 
//               ? 'bg-green-50 border-2 border-green-200' 
//               : 'bg-red-50 border-2 border-red-200'
//           }`}>
//             <div className="flex items-center mb-2">
//               {result.success ? (
//                 <Check className="w-5 h-5 text-green-600 mr-2" />
//               ) : (
//                 <span className="text-red-600 mr-2">❌</span>
//               )}
//               <span className="font-semibold">{result.message}</span>
//             </div>
//             {result.actions && (
//               <div className="mt-3 space-y-2">
//                 {result.actions.map((action: any, i: number) => (
//                   <div key={i} className="text-sm text-gray-600">
//                     ✓ {action.description}
//                   </div>
//                 ))}
//               </div>
//             )}
//           </div>
//         </div>
//       )}
//     </div>
//   )
// }

import React, { useState, useEffect, useRef } from 'react'

interface CommandBarProps {
  onExecute: (command: string) => void
  onSettings: () => void
  context: any
}

export function CommandBar({ onExecute, onSettings, context }: CommandBarProps) {
  const [command, setCommand] = useState('')
  const [isExecuting, setIsExecuting] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    // Auto-focus input
    inputRef.current?.focus()
  }, [])

  const handleExecute = async () => {
    if (!command.trim() || isExecuting) return

    setIsExecuting(true)
    try {
      await onExecute(command)
    } finally {
      setIsExecuting(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleExecute()
    }
    if (e.key === 'Escape') {
      window.electron?.hideWindow()
    }
  }

  return (
    <div className="command-bar">
      {/* Header */}
      <div className="header">
        <div className="title">
          <span className="icon">🚀</span>
          <span>GodComet</span>
        </div>
        <button className="settings-btn" onClick={onSettings}>
          ⚙️
        </button>
      </div>

      {/* Context */}
      {context && (
        <div className="context">
          <span className="context-label">📍</span>
          <span className="context-text">
            {context.app}
            {context.file && ` - ${context.file}`}
            {context.url && ` - ${context.url}`}
          </span>
        </div>
      )}

      {/* Input */}
      <div className="input-container">
        <textarea
          ref={inputRef}
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="What would you like to do?"
          rows={3}
          disabled={isExecuting}
        />
      </div>

      {/* Actions */}
      <div className="actions">
        <button
          className="execute-btn"
          onClick={handleExecute}
          disabled={!command.trim() || isExecuting}
        >
          {isExecuting ? (
            <>
              <span className="spinner">⚡</span>
              Executing...
            </>
          ) : (
            <>
              <span>✨</span>
              Execute
            </>
          )}
        </button>
      </div>

      {/* Tips */}
      <div className="tips">
        <div className="tip">💡 Press Enter to execute, Esc to close</div>
      </div>
    </div>
  )
}