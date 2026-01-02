/**
 * GodComet Windows Context Tracker
 * Monitors ALL Windows applications and provides system-wide context
 */

const WebSocket = require('ws');
const activeWin = require('active-win');
const fs = require('fs');
const path = require('path');
const { exec } = require('child_process');
const util = require('util');
const execPromise = util.promisify(exec);

// Import sub-modules
const FileOperations = require('./file-operations');
const AppManager = require('./app-manager');
const SystemMonitor = require('./system-monitor');

class WindowsContextTracker {
    constructor() {
        this.port = 8767; // Different port from VS Code (8765) and Chrome (8766)
        this.wss = null;
        this.currentContext = {
            app: 'Unknown',
            window: 'Unknown',
            executable: 'Unknown',
            path: null,
            selectedFiles: [],
            currentFolder: null,
            systemInfo: {}
        };
        
        this.fileOps = new FileOperations();
        this.appManager = new AppManager();
        this.systemMonitor = new SystemMonitor();
        
        this.contextUpdateInterval = null;
    }
    
    async start() {
        console.log('🖥️  Starting Windows Context Tracker...');
        
        // Start WebSocket server
        this.wss = new WebSocket.Server({ port: this.port });
        
        this.wss.on('connection', (ws) => {
            console.log('✅ GodComet connected to Windows Context Tracker');
            
            // Send current context immediately
            ws.send(JSON.stringify({
                type: 'context',
                data: this.currentContext
            }));
            
            // Handle incoming commands
            ws.on('message', async (message) => {
                try {
                    const data = JSON.parse(message);
                    await this.handleCommand(data, ws);
                } catch (error) {
                    console.error('Error handling message:', error);
                }
            });
            
            ws.on('error', (error) => {
                console.error('WebSocket error:', error);
            });
        });
        
        // Start monitoring active windows
        this.startContextMonitoring();
        
        console.log(`✅ Windows Context Tracker running on port ${this.port}`);
        console.log('📡 Tracking: File Explorer, Desktop, All Apps');
    }
    
    startContextMonitoring() {
        // Update context every 2 seconds
        this.contextUpdateInterval = setInterval(async () => {
            await this.updateContext();
        }, 2000);
    }
    
    async updateContext() {
        try {
            // Get active window using active-win
            const win = await activeWin();
            
            if (!win) {
                this.currentContext.app = 'Desktop';
                this.currentContext.window = 'Windows Desktop';
                this.currentContext.executable = 'explorer.exe';
                this.broadcastContext();
                return;
            }
            
            // Update basic info
            this.currentContext.app = win.owner.name;
            this.currentContext.window = win.title;
            this.currentContext.executable = win.owner.path;
            
            // Special handling for File Explorer
            if (win.owner.name === 'File Explorer' || 
                win.owner.name === 'Windows Explorer' ||
                win.title.includes(':\\')) {
                await this.updateFileExplorerContext(win);
            }
            
            // Special handling for Microsoft Store
            else if (win.owner.name === 'Microsoft Store') {
                this.currentContext.path = 'ms-windows-store://';
            }
            
            // Get system info periodically (every ~20 seconds)
            if (Math.random() < 0.05) {
                this.currentContext.systemInfo = await this.systemMonitor.getSystemInfo();
            }
            
            // Broadcast updated context to all connected clients
            this.broadcastContext();
            
        } catch (error) {
            console.error('Error updating context:', error.message);
        }
    }
    
    async updateFileExplorerContext(win) {
        try {
            // Get current folder from window title
            const folderPath = this.extractFolderFromTitle(win.title);
            this.currentContext.currentFolder = folderPath;
            this.currentContext.path = folderPath;
            
            // Get selected files using PowerShell
            const selectedFiles = await this.getSelectedFiles();
            this.currentContext.selectedFiles = selectedFiles;
            
        } catch (error) {
            console.error('Error updating File Explorer context:', error.message);
        }
    }
    
    extractFolderFromTitle(title) {
        // File Explorer title is usually the folder name or path
        if (title.includes(':\\')) {
            return title; // It's already a path
        }
        
        // Common folder mappings
        const folderMap = {
            'This PC': 'C:\\',
            'Desktop': path.join(process.env.USERPROFILE, 'Desktop'),
            'Documents': path.join(process.env.USERPROFILE, 'Documents'),
            'Downloads': path.join(process.env.USERPROFILE, 'Downloads'),
            'Pictures': path.join(process.env.USERPROFILE, 'Pictures'),
            'Music': path.join(process.env.USERPROFILE, 'Music'),
            'Videos': path.join(process.env.USERPROFILE, 'Videos')
        };
        
        return folderMap[title] || title;
    }
    
    async getSelectedFiles() {
        try {
            // PowerShell script to get selected files in File Explorer
            const psScript = `
                $shell = New-Object -ComObject Shell.Application
                $window = $shell.Windows() | Where-Object {$_.Name -eq "File Explorer"} | Select-Object -First 1
                if ($window) {
                    $selected = $window.Document.SelectedItems()
                    $files = @()
                    foreach ($item in $selected) {
                        $files += $item.Path
                    }
                    if ($files.Count -gt 0) {
                        $files | ConvertTo-Json -Compress
                    } else {
                        "[]"
                    }
                } else {
                    "[]"
                }
            `.replace(/\n/g, ' ').trim();
            
            const { stdout } = await execPromise(`powershell -Command "${psScript}"`);
            const cleaned = stdout.trim() || '[]';
            const files = JSON.parse(cleaned);
            
            return Array.isArray(files) ? files : (files ? [files] : []);
            
        } catch (error) {
            // Silent fail - just return empty array
            return [];
        }
    }
    
    broadcastContext() {
        const message = JSON.stringify({
            type: 'context',
            data: this.currentContext
        });
        
        this.wss.clients.forEach(client => {
            if (client.readyState === WebSocket.OPEN) {
                try {
                    client.send(message);
                } catch (error) {
                    console.error('Error sending context:', error.message);
                }
            }
        });
    }
    
    async handleCommand(data, ws) {
        const { command, params } = data;
        
        console.log(`📥 Received command: ${command}`);
        
        let result;
        
        try {
            switch (command) {
                case 'get_context':
                    result = { success: true, data: this.currentContext };
                    break;
                    
                case 'transfer_files':
                    result = await this.fileOps.transferFiles(
                        params.source, 
                        params.destination, 
                        params.files || []
                    );
                    break;
                    
                case 'copy_files':
                    result = await this.fileOps.copyFiles(
                        params.source, 
                        params.destination, 
                        params.files || []
                    );
                    break;
                    
                case 'move_files':
                    result = await this.fileOps.moveFiles(
                        params.source, 
                        params.destination, 
                        params.files || []
                    );
                    break;
                    
                case 'delete_files':
                    result = await this.fileOps.deleteFiles(params.files || []);
                    break;
                    
                case 'install_app':
                    result = await this.appManager.installFromStore(params.appName);
                    break;
                    
                case 'launch_app':
                    result = await this.appManager.launchApp(params.appName);
                    break;
                    
                case 'close_app':
                    result = await this.appManager.closeApp(params.appName);
                    break;
                    
                case 'get_running_apps':
                    result = await this.systemMonitor.getRunningApps();
                    break;
                    
                case 'get_system_info':
                    result = await this.systemMonitor.getSystemInfo();
                    break;
                    
                case 'open_folder':
                    result = await this.fileOps.openFolder(params.path);
                    break;
                    
                case 'create_folder':
                    result = await this.fileOps.createFolder(params.path);
                    break;
                    
                default:
                    result = { success: false, error: 'Unknown command' };
            }
        } catch (error) {
            console.error(`Command '${command}' failed:`, error);
            result = { success: false, error: error.message };
        }
        
        ws.send(JSON.stringify({
            type: 'command_result',
            command: command,
            result: result
        }));
    }
}

// Start the tracker
const tracker = new WindowsContextTracker();
tracker.start().catch(error => {
    console.error('Failed to start tracker:', error);
    process.exit(1);
});

console.log('🖥️  Windows Context Tracker is running!');
console.log('📡 Monitoring all Windows applications...');