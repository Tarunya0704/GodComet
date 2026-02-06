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
  },

  // ============================================================================
  // WORKFLOW APIs - Real-time Figma-to-Production Pipeline
  // ============================================================================

  // Start a Figma workflow
  startWorkflow: (figmaUrl, projectName) => {
    return ipcRenderer.invoke('start-workflow', figmaUrl, projectName);
  },

  // Get workflow status
  getWorkflowStatus: (workflowId) => {
    return ipcRenderer.invoke('get-workflow-status', workflowId);
  },

  // Approve workflow and continue to deployment
  approveWorkflow: (workflowId) => {
    return ipcRenderer.invoke('approve-workflow', workflowId);
  },

  // Reject workflow and request changes
  rejectWorkflow: (workflowId, requestedChanges) => {
    return ipcRenderer.invoke('reject-workflow', workflowId, requestedChanges);
  },

  // Cancel workflow
  cancelWorkflow: (workflowId) => {
    return ipcRenderer.invoke('cancel-workflow', workflowId);
  },

  // List all workflows
  listWorkflows: () => {
    return ipcRenderer.invoke('list-workflows');
  },

  // Close preview window
  closePreview: () => {
    return ipcRenderer.invoke('close-preview');
  },

  // Listen for workflow progress updates
  onWorkflowProgress: (callback) => {
    ipcRenderer.on('workflow-progress', (event, data) => {
      callback(data);
    });
  },

  // Listen for approval required events
  onApprovalRequired: (callback) => {
    ipcRenderer.on('approval-required', (event, data) => {
      callback(data);
    });
  },

  // Listen for workflow completion
  onWorkflowComplete: (callback) => {
    ipcRenderer.on('workflow-complete', (event, data) => {
      callback(data);
    });
  },

  // Listen for workflow errors
  onWorkflowError: (callback) => {
    ipcRenderer.on('workflow-error', (event, data) => {
      callback(data);
    });
  },

  // Listen for preview data (for preview window)
  onPreviewData: (callback) => {
    ipcRenderer.on('preview-data', (event, data) => {
      callback(data);
    });
  }
});

console.log('✅ Preload script loaded with workflow support');