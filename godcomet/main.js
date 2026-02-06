// const { app, BrowserWindow, globalShortcut, ipcMain } = require('electron');
// const path = require('path');
// const axios = require('axios');
// const WebSocket = require('ws');
// const UniversalContextDetector = require('./lib/context-detector');

// const BACKEND_URL = 'http://127.0.0.1:8001';
// const contextDetector = new UniversalContextDetector();

// let mainWindow = null;
// let vscodeWS = null;
// let chromeWS = null;
// let vscodeServer = null;
// let chromeServer = null;

// // Store latest context from extensions
// let latestVSCodeContext = {
//   file: null,
//   language: null,
//   selectedText: null,
//   lineCount: 0
// };

// let latestChromeContext = {
//   url: null,
//   title: null
// };

// // Start WebSocket servers for extensions
// function startWebSocketServers() {
//   // VS Code WebSocket Server (port 8765)
//   vscodeServer = new WebSocket.Server({ port: 8765 });
  
//   vscodeServer.on('connection', (ws) => {
//     console.log('✅ VS Code extension connected');
//     vscodeWS = ws;
    
//     ws.on('close', () => {
//       console.log('⚠️  VS Code extension disconnected');
//       vscodeWS = null;
//       latestVSCodeContext = { file: null, language: null, selectedText: null, lineCount: 0 };
//     });

//     ws.on('message', (data) => {
//       try {
//         const message = JSON.parse(data.toString());
        
//         // Store context updates automatically
//         if (message.type === 'contextUpdate' || message.type === 'context') {
//           latestVSCodeContext = {
//             file: message.file || null,
//             language: message.language || null,
//             selectedText: message.selectedText || null,
//             lineCount: message.lineCount || 0,
//             cursorLine: message.cursorLine || 0,
//             cursorColumn: message.cursorColumn || 0
//           };
//           console.log('📝 VS Code context updated:', latestVSCodeContext.file);
          
//           // Notify renderer of context update
//           if (mainWindow && mainWindow.webContents) {
//             mainWindow.webContents.send('context-update', latestVSCodeContext);
//           }
//         }

//         // Respond to context requests
//         if (message.type === 'getContext') {
//           ws.send(JSON.stringify({
//             type: 'contextResponse',
//             ...latestVSCodeContext
//           }));
//         }
//       } catch (error) {
//         console.error('VS Code message error:', error.message);
//       }
//     });

//     // Request initial context
//     setTimeout(() => {
//       if (ws.readyState === WebSocket.OPEN) {
//         ws.send(JSON.stringify({ type: 'getContext' }));
//       }
//     }, 1000);
//   });

//   console.log('🔌 VS Code WebSocket server on port 8765');

//   // Chrome WebSocket Server (port 8766)
//   chromeServer = new WebSocket.Server({ port: 8766 });
  
//   chromeServer.on('connection', (ws) => {
//     console.log('✅ Chrome extension connected');
//     chromeWS = ws;
    
//     ws.on('close', () => {
//       console.log('⚠️  Chrome extension disconnected');
//       chromeWS = null;
//       latestChromeContext = { url: null, title: null };
//     });

//     ws.on('message', (data) => {
//       try {
//         const message = JSON.parse(data.toString());
        
//         if (message.type === 'contextUpdate' || message.type === 'context') {
//           latestChromeContext = {
//             url: message.url || null,
//             title: message.title || null
//           };
//           console.log('📝 Chrome context updated:', latestChromeContext.url);
          
//           // Notify renderer of context update
//           if (mainWindow && mainWindow.webContents) {
//             mainWindow.webContents.send('context-update', latestChromeContext);
//           }
//         }
//       } catch (error) {
//         console.error('Chrome message error:', error.message);
//       }
//     });
//   });

//   console.log('🔌 Chrome WebSocket server on port 8766');
// }

// async function getCurrentContext() {
//   try {
//     // Use universal context detector
//     const fullContext = await contextDetector.getFullContext();
    
//     // Merge with VS Code extension context if available
//     if (latestVSCodeContext.file) {
//       fullContext.file = latestVSCodeContext.file;
//       fullContext.language = latestVSCodeContext.language;
//       fullContext.selectedText = latestVSCodeContext.selectedText || fullContext.selectedText;
//       fullContext.app = 'VSCode';
//       fullContext.lineCount = latestVSCodeContext.lineCount;
//       fullContext.cursorLine = latestVSCodeContext.cursorLine;
//       fullContext.cursorColumn = latestVSCodeContext.cursorColumn;
//     }
    
//     // Merge with Chrome extension context if available
//     if (latestChromeContext.url) {
//       fullContext.url = latestChromeContext.url;
//       fullContext.browserTab = latestChromeContext.title;
//       fullContext.app = 'Chrome';
//     }
    
//     console.log('📍 Full context detected:', {
//       app: fullContext.app,
//       file: fullContext.file,
//       url: fullContext.url,
//       hasSelection: !!fullContext.selectedText
//     });
    
//     return fullContext;
//   } catch (error) {
//     console.error('Context detection error:', error);
//     return {
//       app: 'Unknown',
//       timestamp: Date.now()
//     };
//   }
// }

// function createWindow() {
//   mainWindow = new BrowserWindow({
//     width: 900,
//     height: 600,
//     frame: false,
//     transparent: false, // ✅ Changed from true - solid background
//     backgroundColor: '#0a0a0f', // ✅ Solid background color
//     alwaysOnTop: true,
//     resizable: false,
//     skipTaskbar: true,
//     show: false,
//     webPreferences: {
//       nodeIntegration: false,
//       contextIsolation: true,
//       preload: path.join(__dirname, 'preload.js')
//     }
//   });

//   mainWindow.loadFile(path.join(__dirname, 'src/renderer/index.html'));

//   mainWindow.on('blur', () => {
//     mainWindow.hide();
//   });

//   mainWindow.on('ready-to-show', () => {
//     console.log('✅ Window loaded');
//   });
  
//   // Open DevTools in development
//   // mainWindow.webContents.openDevTools();
// }

// function showWindow() {
//   if (!mainWindow) {
//     createWindow();
//   }
//   mainWindow.show();
//   mainWindow.focus();
// }

// app.whenReady().then(() => {
//   console.log('🚀 GodComet starting...');
  
//   // Start WebSocket servers first
//   startWebSocketServers();
  
//   // Test backend connection
//   testBackendConnection();
  
//   createWindow();

//   // Register hotkey
//   const hotkey = process.platform === 'darwin' ? 'Command+Space' : 'Control+Space';
//   const registered = globalShortcut.register(hotkey, () => {
//     console.log('\n⚡ Hotkey pressed!\n');
//     showWindow();
//   });

//   if (registered) {
//     console.log(`✅ Hotkey: ${hotkey}`);
//   } else {
//     console.log('❌ Hotkey registration failed');
//   }

//   // ============================================================================
//   // IPC HANDLERS - ALL FEATURES SUPPORTED
//   // ============================================================================

//   // Execute command with full context
//   ipcMain.handle('execute-command', async (event, command) => {
//     try {
//       console.log(`\n🎯 Executing: ${command}`);
      
//       // Get full context
//       const context = await getCurrentContext();
//       console.log('📍 Context:', JSON.stringify({
//         app: context.app,
//         file: context.file,
//         url: context.url,
//         hasSelection: !!context.selectedText
//       }, null, 2));
      
//       // Send to backend with context
//       const response = await axios.post(`${BACKEND_URL}/execute`, {
//         command,
//         context: context
//       }, {
//         timeout: 120000 // 2 minute timeout for long operations
//       });
      
//       console.log('✅ Command executed successfully\n');
//       return response.data;
      
//     } catch (error) {
//       console.error('❌ Error:', error.message);
      
//       if (error.code === 'ECONNREFUSED') {
//         return {
//           success: false,
//           error: 'Backend server not running. Start: cd backend && python brain.py'
//         };
//       }
      
//       if (error.code === 'ECONNABORTED') {
//         return {
//           success: false,
//           error: 'Command timed out. Try a simpler command or check backend logs.'
//         };
//       }
      
//       return {
//         success: false,
//         error: error.message
//       };
//     }
//   });

//   // Get current context
//   ipcMain.handle('get-current-context', async (event) => {
//     try {
//       const context = await getCurrentContext();
//       return context;
//     } catch (error) {
//       console.error('Failed to get context:', error);
//       return {
//         app: 'Unknown',
//         timestamp: Date.now()
//       };
//     }
//   });

//   // Hide window
//   ipcMain.handle('hide-window', () => {
//     if (mainWindow) {
//       mainWindow.hide();
//       return { success: true };
//     }
//     return { success: false };
//   });

//   // Get settings
//   ipcMain.handle('get-settings', async () => {
//     return {
//       hotkey: hotkey,
//       theme: 'dark',
//       autoStart: false,
//       notifications: true,
//       contextDetection: true,
//       vsCodeIntegration: !!vscodeWS,
//       chromeIntegration: !!chromeWS
//     };
//   });

//   // Save settings
//   ipcMain.handle('save-settings', async (event, settings) => {
//     console.log('💾 Saving settings:', settings);
//     // TODO: Implement settings persistence
//     return { success: true };
//   });

//   // Get integration status
//   ipcMain.handle('get-integration-status', async () => {
//     return {
//       vscode: { 
//         enabled: true, 
//         configured: !!vscodeWS,
//         status: vscodeWS ? 'connected' : 'disconnected',
//         contextAvailable: !!latestVSCodeContext.file
//       },
//       chrome: { 
//         enabled: true, 
//         configured: !!chromeWS,
//         status: chromeWS ? 'connected' : 'disconnected',
//         contextAvailable: !!latestChromeContext.url
//       },
//       slack: { 
//         enabled: false, 
//         configured: false,
//         status: 'not_configured'
//       },
//       github: { 
//         enabled: true, 
//         configured: true,
//         status: 'ready'
//       },
//       jira: { 
//         enabled: true, 
//         configured: true,
//         status: 'ready'
//       },
//       vercel: {
//         enabled: true,
//         configured: true,
//         status: 'ready'
//       },
//       aws: {
//         enabled: true,
//         configured: true,
//         status: 'ready'
//       },
//       figma: {
//         enabled: true,
//         configured: true,
//         status: 'ready'
//       }
//     };
//   });

//   // Configure integration
//   ipcMain.handle('configure-integration', async (event, name, config) => {
//     console.log(`⚙️  Configuring ${name}:`, config);
//     // TODO: Implement integration configuration
//     return { success: true };
//   });
// });

// async function testBackendConnection() {
//   try {
//     const response = await axios.get(`${BACKEND_URL}/health`, { timeout: 5000 });
//     console.log('✅ Backend connected:', response.data.status);
//     return true;
//   } catch (error) {
//     console.error('❌ Backend connection failed');
//     console.error('💡 Start backend: cd backend && python brain.py');
//     return false;
//   }
// }

// app.on('will-quit', () => {
//   console.log('👋 Shutting down...');
//   globalShortcut.unregisterAll();
//   if (vscodeServer) vscodeServer.close();
//   if (chromeServer) chromeServer.close();
// });

// app.on('window-all-closed', () => {
//   if (process.platform !== 'darwin') {
//     app.quit();
//   }
// });

// app.on('activate', () => {
//   if (BrowserWindow.getAllWindows().length === 0) {
//     createWindow();
//   }
// });

// console.log('✅ Main process loaded');


const { app, BrowserWindow, globalShortcut, ipcMain } = require('electron');
const path = require('path');
const axios = require('axios');
const WebSocket = require('ws');
const UniversalContextDetector = require('./lib/context-detector');

const BACKEND_URL = 'http://127.0.0.1:8001';
const contextDetector = new UniversalContextDetector();

let mainWindow = null;
let previewWindow = null; // NEW: Preview window for Figma comparison
let vscodeWS = null;
let chromeWS = null;
let windowsWS = null; // ⭐ NEW: Windows context WebSocket
let workflowWS = null; // NEW: Workflow WebSocket for real-time updates
let vscodeServer = null;
let chromeServer = null;

// Store latest context from extensions
let latestVSCodeContext = {
  file: null,
  language: null,
  selectedText: null,
  lineCount: 0
};

let latestChromeContext = {
  url: null,
  title: null
};

// ⭐ NEW: Windows context
let latestWindowsContext = {
  app: 'Unknown',
  window: 'Unknown',
  currentFolder: null,
  selectedFiles: [],
  systemInfo: {}
};

// Start WebSocket servers for extensions
function startWebSocketServers() {
  // VS Code WebSocket Server (port 8765)
  vscodeServer = new WebSocket.Server({ port: 8765 });
  
  vscodeServer.on('connection', (ws) => {
    console.log('✅ VS Code extension connected');
    vscodeWS = ws;
    
    ws.on('close', () => {
      console.log('⚠️  VS Code extension disconnected');
      vscodeWS = null;
      latestVSCodeContext = { file: null, language: null, selectedText: null, lineCount: 0 };
    });

    ws.on('message', (data) => {
      try {
        const message = JSON.parse(data.toString());
        
        // Store context updates automatically
        if (message.type === 'contextUpdate' || message.type === 'context') {
          latestVSCodeContext = {
            file: message.file || null,
            language: message.language || null,
            selectedText: message.selectedText || null,
            lineCount: message.lineCount || 0,
            cursorLine: message.cursorLine || 0,
            cursorColumn: message.cursorColumn || 0
          };
          console.log('📝 VS Code context updated:', latestVSCodeContext.file);
          
          // Notify renderer of context update
          if (mainWindow && mainWindow.webContents) {
            mainWindow.webContents.send('context-update', latestVSCodeContext);
          }
        }

        // Respond to context requests
        if (message.type === 'getContext') {
          ws.send(JSON.stringify({
            type: 'contextResponse',
            ...latestVSCodeContext
          }));
        }
      } catch (error) {
        console.error('VS Code message error:', error.message);
      }
    });

    // Request initial context
    setTimeout(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'getContext' }));
      }
    }, 1000);
  });

  console.log('🔌 VS Code WebSocket server on port 8765');

  // Chrome WebSocket Server (port 8766)
  chromeServer = new WebSocket.Server({ port: 8766 });
  
  chromeServer.on('connection', (ws) => {
    console.log('✅ Chrome extension connected');
    chromeWS = ws;
    
    ws.on('close', () => {
      console.log('⚠️  Chrome extension disconnected');
      chromeWS = null;
      latestChromeContext = { url: null, title: null };
    });

    ws.on('message', (data) => {
      try {
        const message = JSON.parse(data.toString());
        
        if (message.type === 'contextUpdate' || message.type === 'context') {
          latestChromeContext = {
            url: message.url || null,
            title: message.title || null
          };
          console.log('📝 Chrome context updated:', latestChromeContext.url);
          
          // Notify renderer of context update
          if (mainWindow && mainWindow.webContents) {
            mainWindow.webContents.send('context-update', latestChromeContext);
          }
        }
      } catch (error) {
        console.error('Chrome message error:', error.message);
      }
    });
  });

  console.log('🔌 Chrome WebSocket server on port 8766');
}

// ⭐ NEW: Connect to Windows Context Tracker
function connectToWindowsContext() {
  console.log('🔌 Connecting to Windows Context Tracker...');
  
  windowsWS = new WebSocket('ws://localhost:8767');
  
  windowsWS.on('open', () => {
    console.log('✅ Windows Context Tracker connected');
  });
  
  windowsWS.on('message', (data) => {
    try {
      const message = JSON.parse(data.toString());
      
      if (message.type === 'context') {
        latestWindowsContext = message.data;
        console.log('🖥️  Windows context:', latestWindowsContext.app, '-', latestWindowsContext.window);
        
        // Notify renderer
        if (mainWindow && mainWindow.webContents) {
          mainWindow.webContents.send('windows-context-update', latestWindowsContext);
        }
      }
    } catch (error) {
      console.error('Windows context message error:', error);
    }
  });
  
  windowsWS.on('close', () => {
    console.log('⚠️  Windows Context Tracker disconnected - will retry in 5s');
    windowsWS = null;
    latestWindowsContext = { app: 'Unknown', window: 'Unknown', currentFolder: null, selectedFiles: [] };
    
    // Retry connection after 5 seconds
    setTimeout(connectToWindowsContext, 5000);
  });
  
  windowsWS.on('error', (error) => {
    console.error('❌ Windows Context Tracker error:', error.message);
    console.log('💡 Make sure to start: node extensions/windows-context/index.js');
  });
}

// NEW: Connect to Workflow WebSocket server for real-time updates
function connectToWorkflowServer() {
  console.log('🔌 Connecting to Workflow WebSocket server...');

  workflowWS = new WebSocket('ws://localhost:8002');

  workflowWS.on('open', () => {
    console.log('✅ Workflow WebSocket server connected');
  });

  workflowWS.on('message', (data) => {
    try {
      const message = JSON.parse(data.toString());

      // Forward to renderer
      if (mainWindow && mainWindow.webContents) {
        if (message.type === 'progress') {
          mainWindow.webContents.send('workflow-progress', message);
          console.log(`📊 Workflow ${message.workflow_id}: ${message.data?.step} (${message.data?.progress}%)`);
        }

        if (message.type === 'approval_required') {
          mainWindow.webContents.send('approval-required', message);
          console.log(`🔔 Approval required for workflow: ${message.workflow_id}`);
          // Show preview window
          createPreviewWindow(message.preview);
        }

        if (message.type === 'complete') {
          mainWindow.webContents.send('workflow-complete', message);
          console.log(`✅ Workflow ${message.workflow_id} complete!`);
          if (previewWindow) {
            previewWindow.webContents.send('workflow-complete', message);
          }
        }

        if (message.type === 'error') {
          mainWindow.webContents.send('workflow-error', message);
          console.log(`❌ Workflow ${message.workflow_id} error: ${message.error?.message}`);
        }
      }
    } catch (error) {
      console.error('Workflow message error:', error);
    }
  });

  workflowWS.on('close', () => {
    console.log('⚠️  Workflow WebSocket disconnected - will retry in 5s');
    workflowWS = null;
    setTimeout(connectToWorkflowServer, 5000);
  });

  workflowWS.on('error', (error) => {
    console.error('❌ Workflow WebSocket error:', error.message);
    console.log('💡 Make sure backend is running: cd backend && python brain.py');
  });
}

// NEW: Create preview window for Figma vs Generated comparison
function createPreviewWindow(previewData) {
  if (previewWindow) {
    previewWindow.focus();
    previewWindow.webContents.send('preview-data', previewData);
    return;
  }

  previewWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    frame: true,
    title: 'GodComet Preview - Figma vs Generated',
    backgroundColor: '#0a0a0f',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    }
  });

  previewWindow.loadFile(path.join(__dirname, 'src/renderer/preview.html'));

  previewWindow.on('ready-to-show', () => {
    previewWindow.show();
    previewWindow.webContents.send('preview-data', previewData);
  });

  previewWindow.on('closed', () => {
    previewWindow = null;
  });
}

async function getCurrentContext() {
  try {
    // Use universal context detector
    const fullContext = await contextDetector.getFullContext();
    
    // Merge with VS Code extension context if available
    if (latestVSCodeContext.file) {
      fullContext.file = latestVSCodeContext.file;
      fullContext.language = latestVSCodeContext.language;
      fullContext.selectedText = latestVSCodeContext.selectedText || fullContext.selectedText;
      fullContext.app = 'VSCode';
      fullContext.lineCount = latestVSCodeContext.lineCount;
      fullContext.cursorLine = latestVSCodeContext.cursorLine;
      fullContext.cursorColumn = latestVSCodeContext.cursorColumn;
    }
    
    // Merge with Chrome extension context if available
    if (latestChromeContext.url) {
      fullContext.url = latestChromeContext.url;
      fullContext.browserTab = latestChromeContext.title;
      fullContext.app = 'Chrome';
    }
    
    // ⭐ NEW: Merge with Windows context
    if (latestWindowsContext.app && latestWindowsContext.app !== 'Unknown') {
      // Only override if not already set by VS Code or Chrome
      if (!fullContext.app || fullContext.app === 'Unknown') {
        fullContext.app = latestWindowsContext.app;
      }
      fullContext.window = latestWindowsContext.window;
      fullContext.currentFolder = latestWindowsContext.currentFolder;
      fullContext.selectedFiles = latestWindowsContext.selectedFiles;
      fullContext.systemInfo = latestWindowsContext.systemInfo;
    }
    
    console.log('📍 Full context detected:', {
      app: fullContext.app,
      file: fullContext.file,
      url: fullContext.url,
      folder: fullContext.currentFolder,
      selectedFiles: fullContext.selectedFiles?.length || 0,
      hasSelection: !!fullContext.selectedText
    });
    
    return fullContext;
  } catch (error) {
    console.error('Context detection error:', error);
    return {
      app: 'Unknown',
      timestamp: Date.now()
    };
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 900,
    height: 600,
    frame: false,
    transparent: false,
    backgroundColor: '#0a0a0f',
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    }
  });

  mainWindow.loadFile(path.join(__dirname, 'src/renderer/index.html'));

  mainWindow.on('blur', () => {
    mainWindow.hide();
  });

  mainWindow.on('ready-to-show', () => {
    console.log('✅ Window loaded');
  });
  
  // Open DevTools in development
  // mainWindow.webContents.openDevTools();
}

function showWindow() {
  if (!mainWindow) {
    createWindow();
  }
  mainWindow.show();
  mainWindow.focus();
}

app.whenReady().then(() => {
  console.log('🚀 GodComet starting...');
  
  // Start WebSocket servers for extensions
  startWebSocketServers();
  
  // ⭐ NEW: Connect to Windows Context Tracker
  connectToWindowsContext();

  // NEW: Connect to Workflow WebSocket server
  connectToWorkflowServer();

  // Test backend connection
  testBackendConnection();
  
  createWindow();

  // Register hotkey
  const hotkey = process.platform === 'darwin' ? 'Command+Space' : 'Control+Space';
  const registered = globalShortcut.register(hotkey, () => {
    console.log('\n⚡ Hotkey pressed!\n');
    showWindow();
  });

  if (registered) {
    console.log(`✅ Hotkey: ${hotkey}`);
  } else {
    console.log('❌ Hotkey registration failed');
  }

  // ============================================================================
  // IPC HANDLERS - ALL FEATURES SUPPORTED + WINDOWS AUTOMATION
  // ============================================================================

  // Execute command with full context
  ipcMain.handle('execute-command', async (event, command) => {
    try {
      console.log(`\n🎯 Executing: ${command}`);

      // Check if command contains a Figma URL
      const figmaUrlMatch = command.match(/(?:https?:\/\/)?(?:www\.)?figma\.com\/(?:file|design|proto)\/([a-zA-Z0-9]+)/i);

      if (figmaUrlMatch) {
        // Extract Figma URL
        let figmaUrl = figmaUrlMatch[0];
        if (!figmaUrl.startsWith('http')) {
          figmaUrl = 'https://' + figmaUrl;
        }

        console.log(`🎨 Detected Figma URL: ${figmaUrl}`);
        console.log('🚀 Starting Figma-to-Production workflow...');

        // Extract project name from command or generate one
        const projectNameMatch = command.match(/(?:name|project|called?)\s+["\']?([a-zA-Z0-9_-]+)["\']?/i);
        const projectName = projectNameMatch ? projectNameMatch[1] : null;

        // Start workflow via workflow endpoint
        const response = await axios.post(`${BACKEND_URL}/workflow/start`, {
          figma_url: figmaUrl,
          project_name: projectName
        }, {
          timeout: 30000
        });

        console.log('✅ Workflow started:', response.data.workflow_id);

        return {
          success: true,
          message: `Figma workflow started! ID: ${response.data.workflow_id}`,
          data: {
            workflow_id: response.data.workflow_id,
            project_name: response.data.project_name,
            figma_url: figmaUrl
          },
          actions: [
            { type: 'workflow_started', description: 'Converting Figma design to production code', status: 'running' }
          ],
          isWorkflow: true
        };
      }

      // Get full context (including Windows)
      const context = await getCurrentContext();
      console.log('📍 Context:', JSON.stringify({
        app: context.app,
        file: context.file,
        url: context.url,
        folder: context.currentFolder,
        selectedFiles: context.selectedFiles?.length || 0,
        hasSelection: !!context.selectedText
      }, null, 2));

      // Send to backend with context
      const response = await axios.post(`${BACKEND_URL}/execute`, {
        command,
        context: context
      }, {
        timeout: 120000 // 2 minute timeout
      });

      console.log('✅ Command executed successfully\n');
      return response.data;
      
    } catch (error) {
      console.error('❌ Error:', error.message);
      
      if (error.code === 'ECONNREFUSED') {
        return {
          success: false,
          error: 'Backend server not running. Start: cd backend && python brain.py'
        };
      }
      
      if (error.code === 'ECONNABORTED') {
        return {
          success: false,
          error: 'Command timed out. Try a simpler command or check backend logs.'
        };
      }
      
      return {
        success: false,
        error: error.message
      };
    }
  });

  // Get current context
  ipcMain.handle('get-current-context', async (event) => {
    try {
      const context = await getCurrentContext();
      return context;
    } catch (error) {
      console.error('Failed to get context:', error);
      return {
        app: 'Unknown',
        timestamp: Date.now()
      };
    }
  });

  // Hide window
  ipcMain.handle('hide-window', () => {
    if (mainWindow) {
      mainWindow.hide();
      return { success: true };
    }
    return { success: false };
  });

  // Get settings
  ipcMain.handle('get-settings', async () => {
    return {
      hotkey: hotkey,
      theme: 'dark',
      autoStart: false,
      notifications: true,
      contextDetection: true,
      vsCodeIntegration: !!vscodeWS,
      chromeIntegration: !!chromeWS,
      windowsIntegration: !!windowsWS // ⭐ NEW
    };
  });

  // Save settings
  ipcMain.handle('save-settings', async (event, settings) => {
    console.log('💾 Saving settings:', settings);
    // TODO: Implement settings persistence
    return { success: true };
  });

  // Get integration status
  ipcMain.handle('get-integration-status', async () => {
    return {
      vscode: { 
        enabled: true, 
        configured: !!vscodeWS,
        status: vscodeWS ? 'connected' : 'disconnected',
        contextAvailable: !!latestVSCodeContext.file
      },
      chrome: { 
        enabled: true, 
        configured: !!chromeWS,
        status: chromeWS ? 'connected' : 'disconnected',
        contextAvailable: !!latestChromeContext.url
      },
      windows: { // ⭐ NEW
        enabled: true,
        configured: !!windowsWS,
        status: windowsWS ? 'connected' : 'disconnected',
        contextAvailable: latestWindowsContext.app !== 'Unknown'
      },
      slack: { 
        enabled: false, 
        configured: false,
        status: 'not_configured'
      },
      github: { 
        enabled: true, 
        configured: true,
        status: 'ready'
      },
      jira: { 
        enabled: true, 
        configured: true,
        status: 'ready'
      },
      vercel: {
        enabled: true,
        configured: true,
        status: 'ready'
      },
      aws: {
        enabled: true,
        configured: true,
        status: 'ready'
      },
      figma: {
        enabled: true,
        configured: true,
        status: 'ready'
      }
    };
  });

  // Configure integration
  ipcMain.handle('configure-integration', async (event, name, config) => {
    console.log(`⚙️  Configuring ${name}:`, config);
    // TODO: Implement integration configuration
    return { success: true };
  });

  // ============================================================================
  // WORKFLOW IPC HANDLERS - Real-time Figma-to-Production Pipeline
  // ============================================================================

  // Start a Figma workflow
  ipcMain.handle('start-workflow', async (event, figmaUrl, projectName) => {
    try {
      console.log(`🚀 Starting workflow for: ${figmaUrl}`);

      const response = await axios.post(`${BACKEND_URL}/workflow/start`, {
        figma_url: figmaUrl,
        project_name: projectName
      }, { timeout: 30000 });

      return response.data;
    } catch (error) {
      console.error('Failed to start workflow:', error.message);
      return {
        success: false,
        error: error.message
      };
    }
  });

  // Get workflow status
  ipcMain.handle('get-workflow-status', async (event, workflowId) => {
    try {
      const response = await axios.get(`${BACKEND_URL}/workflow/${workflowId}`, { timeout: 10000 });
      return response.data;
    } catch (error) {
      console.error('Failed to get workflow status:', error.message);
      return { error: error.message };
    }
  });

  // Approve workflow
  ipcMain.handle('approve-workflow', async (event, workflowId) => {
    try {
      console.log(`✅ Approving workflow: ${workflowId}`);

      // Send via WebSocket for faster response
      if (workflowWS && workflowWS.readyState === WebSocket.OPEN) {
        workflowWS.send(JSON.stringify({
          type: 'approval_response',
          workflow_id: workflowId,
          approved: true
        }));
      }

      // Also call REST endpoint
      const response = await axios.post(`${BACKEND_URL}/workflow/${workflowId}/approve`, {}, { timeout: 30000 });
      return response.data;
    } catch (error) {
      console.error('Failed to approve workflow:', error.message);
      return { success: false, error: error.message };
    }
  });

  // Reject workflow
  ipcMain.handle('reject-workflow', async (event, workflowId, requestedChanges) => {
    try {
      console.log(`❌ Rejecting workflow: ${workflowId}`);

      // Send via WebSocket
      if (workflowWS && workflowWS.readyState === WebSocket.OPEN) {
        workflowWS.send(JSON.stringify({
          type: 'approval_response',
          workflow_id: workflowId,
          approved: false,
          requested_changes: requestedChanges || []
        }));
      }

      // Also call REST endpoint
      const response = await axios.post(`${BACKEND_URL}/workflow/${workflowId}/reject`, {
        approved: false,
        requested_changes: requestedChanges || []
      }, { timeout: 30000 });

      return response.data;
    } catch (error) {
      console.error('Failed to reject workflow:', error.message);
      return { success: false, error: error.message };
    }
  });

  // Cancel workflow
  ipcMain.handle('cancel-workflow', async (event, workflowId) => {
    try {
      console.log(`🛑 Cancelling workflow: ${workflowId}`);

      if (workflowWS && workflowWS.readyState === WebSocket.OPEN) {
        workflowWS.send(JSON.stringify({
          type: 'cancel',
          workflow_id: workflowId
        }));
      }

      const response = await axios.delete(`${BACKEND_URL}/workflow/${workflowId}`, { timeout: 10000 });
      return response.data;
    } catch (error) {
      console.error('Failed to cancel workflow:', error.message);
      return { success: false, error: error.message };
    }
  });

  // List workflows
  ipcMain.handle('list-workflows', async () => {
    try {
      const response = await axios.get(`${BACKEND_URL}/workflows`, { timeout: 10000 });
      return response.data;
    } catch (error) {
      console.error('Failed to list workflows:', error.message);
      return { workflows: [], error: error.message };
    }
  });

  // Close preview window
  ipcMain.handle('close-preview', () => {
    if (previewWindow) {
      previewWindow.close();
      previewWindow = null;
    }
    return { success: true };
  });
});

async function testBackendConnection() {
  try {
    const response = await axios.get(`${BACKEND_URL}/health`, { timeout: 5000 });
    console.log('✅ Backend connected:', response.data.status);
    return true;
  } catch (error) {
    console.error('❌ Backend connection failed');
    console.error('💡 Start backend: cd backend && python brain.py');
    return false;
  }
}

app.on('will-quit', () => {
  console.log('👋 Shutting down...');
  globalShortcut.unregisterAll();
  if (vscodeServer) vscodeServer.close();
  if (chromeServer) chromeServer.close();
  if (windowsWS) windowsWS.close();
  if (workflowWS) workflowWS.close(); // NEW: Close workflow WebSocket
  if (previewWindow) previewWindow.close(); // NEW: Close preview window
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

console.log('✅ Main process loaded');