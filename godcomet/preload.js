const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods to renderer
contextBridge.exposeInMainWorld('api', {
  // Execute command
  executeCommand: (command) => {
    return ipcRenderer.invoke('execute-command', command);
  },
  
  // Get current context
  getCurrentContext: () => {
    return ipcRenderer.invoke('get-current-context');
  },
  
  // Hide window
  hideWindow: () => {
    return ipcRenderer.invoke('hide-window');
  },
  
  // Get settings
  getSettings: () => {
    return ipcRenderer.invoke('get-settings');
  },
  
  // Get integration status
  getIntegrationStatus: () => {
    return ipcRenderer.invoke('get-integration-status');
  },
  
  // Save settings
  saveSettings: (settings) => {
    return ipcRenderer.invoke('save-settings', settings);
  },
  
  // Configure integration
  configureIntegration: (name, config) => {
    return ipcRenderer.invoke('configure-integration', name, config);
  },
  
  // Listen for context updates
  onContext: (callback) => {
    ipcRenderer.on('context-update', (event, context) => {
      callback(context);
    });
  }
});

console.log('✅ Preload script loaded');