import React, { useState, useEffect } from 'react'

interface SettingsProps {
  onBack: () => void
}

export function Settings({ onBack }: SettingsProps) {
  const [settings, setSettings] = useState<any>({
    hotkey: 'Command+Space',
    theme: 'auto',
    autoStart: true,
    notifications: true
  })

  const [integrations, setIntegrations] = useState<any>({})

  useEffect(() => {
    // Load settings
    loadSettings()
    loadIntegrations()
  }, [])

  const loadSettings = async () => {
    try {
      const saved = await window.electron.getSettings()
      if (saved) {
        setSettings(saved)
      }
    } catch (error) {
      console.error('Failed to load settings:', error)
    }
  }

  const loadIntegrations = async () => {
    try {
      const status = await window.electron.getIntegrationStatus()
      setIntegrations(status)
    } catch (error) {
      console.error('Failed to load integrations:', error)
    }
  }

  const handleSave = async () => {
    try {
      await window.electron.saveSettings(settings)
      alert('Settings saved!')
    } catch (error) {
      alert('Failed to save settings')
    }
  }

  const handleConfigureIntegration = (name: string) => {
    const config = prompt(`Enter ${name} configuration (JSON):`)
    if (config) {
      try {
        const parsed = JSON.parse(config)
        window.electron.configureIntegration(name, parsed)
        loadIntegrations()
      } catch (error) {
        alert('Invalid JSON')
      }
    }
  }

  return (
    <div className="settings">
      {/* Header */}
      <div className="header">
        <button className="back-btn" onClick={onBack}>
          ← Back
        </button>
        <div className="title">⚙️ Settings</div>
      </div>

      <div className="settings-content">
        {/* General Settings */}
        <section>
          <h2>General</h2>
          
          <div className="setting-item">
            <label>Hotkey</label>
            <input
              type="text"
              value={settings.hotkey}
              onChange={(e) => setSettings({ ...settings, hotkey: e.target.value })}
            />
          </div>

          <div className="setting-item">
            <label>Theme</label>
            <select
              value={settings.theme}
              onChange={(e) => setSettings({ ...settings, theme: e.target.value })}
            >
              <option value="light">Light</option>
              <option value="dark">Dark</option>
              <option value="auto">Auto</option>
            </select>
          </div>

          <div className="setting-item">
            <label>
              <input
                type="checkbox"
                checked={settings.autoStart}
                onChange={(e) => setSettings({ ...settings, autoStart: e.target.checked })}
              />
              Start on system startup
            </label>
          </div>

          <div className="setting-item">
            <label>
              <input
                type="checkbox"
                checked={settings.notifications}
                onChange={(e) => setSettings({ ...settings, notifications: e.target.checked })}
              />
              Enable notifications
            </label>
          </div>
        </section>

        {/* Integrations */}
        <section>
          <h2>Integrations</h2>
          
          {Object.entries(integrations).map(([name, status]: [string, any]) => (
            <div key={name} className="integration-item">
              <div className="integration-info">
                <span className="integration-name">{name}</span>
                <span className={`integration-status ${status.configured ? 'configured' : 'not-configured'}`}>
                  {status.configured ? '✓ Configured' : '⚠️ Not Configured'}
                </span>
              </div>
              <button
                className="configure-btn"
                onClick={() => handleConfigureIntegration(name)}
              >
                Configure
              </button>
            </div>
          ))}
        </section>

        {/* Actions */}
        <div className="settings-actions">
          <button className="save-btn" onClick={handleSave}>
            💾 Save Settings
          </button>
        </div>
      </div>
    </div>
  )
}