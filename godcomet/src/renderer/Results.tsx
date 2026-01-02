import React from 'react'

interface ResultsProps {
  result: any
  onBack: () => void
}

export function Results({ result, onBack }: ResultsProps) {
  const isSuccess = result?.success

  return (
    <div className="results">
      {/* Header */}
      <div className="header">
        <button className="back-btn" onClick={onBack}>
          ← Back
        </button>
        <div className="title">
          {isSuccess ? '✅ Success' : '❌ Failed'}
        </div>
      </div>

      {/* Message */}
      <div className={`message ${isSuccess ? 'success' : 'error'}`}>
        {result?.message || 'Unknown result'}
      </div>

      {/* Data */}
      {result?.data && (
        <div className="data-section">
          <h3>Details</h3>
          <div className="data-content">
            {/* URLs */}
            {result.data.url && (
              <div className="data-item">
                <span className="label">🔗 URL:</span>
                <a href={result.data.url} target="_blank" rel="noopener noreferrer">
                  {result.data.url}
                </a>
              </div>
            )}

            {result.data.vercel_url && (
              <div className="data-item highlight">
                <span className="label">🌐 Live Website:</span>
                <a href={result.data.vercel_url} target="_blank" rel="noopener noreferrer">
                  {result.data.vercel_url}
                </a>
              </div>
            )}

            {result.data.github_url && (
              <div className="data-item">
                <span className="label">📦 GitHub:</span>
                <a href={result.data.github_url} target="_blank" rel="noopener noreferrer">
                  {result.data.github_url}
                </a>
              </div>
            )}

            {result.data.repo_url && (
              <div className="data-item">
                <span className="label">📦 Repository:</span>
                <a href={result.data.repo_url} target="_blank" rel="noopener noreferrer">
                  {result.data.repo_url}
                </a>
              </div>
            )}

            {/* Paths */}
            {result.data.local_path && (
              <div className="data-item">
                <span className="label">📁 Local:</span>
                <span>{result.data.local_path}</span>
              </div>
            )}

            {/* Documents */}
            {result.data.word_document && (
              <div className="data-item">
                <span className="label">📄 Word:</span>
                <span>{result.data.word_document}</span>
              </div>
            )}

            {result.data.powerpoint && (
              <div className="data-item">
                <span className="label">📊 PowerPoint:</span>
                <span>{result.data.powerpoint}</span>
              </div>
            )}

            {/* Project Info */}
            {result.data.project_name && (
              <div className="data-item">
                <span className="label">🏷️ Project:</span>
                <span>{result.data.project_name}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Actions */}
      {result?.actions && result.actions.length > 0 && (
        <div className="actions-section">
          <h3>Actions Performed</h3>
          <div className="actions-list">
            {result.actions.map((action: any, i: number) => (
              <div key={i} className="action-item">
                <span className="action-icon">
                  {action.status === 'completed' ? '✓' : '•'}
                </span>
                <span className="action-text">{action.description}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Error */}
      {result?.error && (
        <div className="error-section">
          <h3>Error Details</h3>
          <pre className="error-text">{result.error}</pre>
        </div>
      )}

      {/* Execution Time */}
      {result?.executionTime && (
        <div className="stats">
          ⏱️ Completed in {result.executionTime.toFixed(2)}s
        </div>
      )}
    </div>
  )
}