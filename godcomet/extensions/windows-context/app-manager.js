/**
 * App Manager for Windows
 * Install, launch, close applications
 */

const { exec } = require('child_process');
const util = require('util');
const execPromise = util.promisify(exec);

class AppManager {
    constructor() {
        console.log('🎮 App Manager module loaded');
    }
    
    async installFromStore(appName) {
        try {
            console.log(`📦 Installing ${appName} from Microsoft Store...`);
            
            // Open Microsoft Store with search
            const storeUrl = `ms-windows-store://search/?query=${encodeURIComponent(appName)}`;
            await execPromise(`start ${storeUrl}`);
            
            return {
                success: true,
                message: `Opening Microsoft Store to install: ${appName}`,
                note: 'User must complete installation manually'
            };
            
        } catch (error) {
            return { success: false, error: error.message };
        }
    }
    
    async launchApp(appName) {
        try {
            console.log(`🚀 Launching ${appName}...`);
            
            // Common apps mapping
            const appCommands = {
                'notepad': 'notepad',
                'calculator': 'calc',
                'paint': 'mspaint',
                'wordpad': 'write',
                'cmd': 'cmd',
                'powershell': 'powershell',
                'task manager': 'taskmgr',
                'control panel': 'control',
                'settings': 'ms-settings:',
                'file explorer': 'explorer',
                'microsoft edge': 'msedge',
                'chrome': 'chrome',
                'firefox': 'firefox',
                'vscode': 'code',
                'visual studio code': 'code'
            };
            
            const command = appCommands[appName.toLowerCase()] || `start "" "${appName}"`;
            
            await execPromise(command);
            
            return {
                success: true,
                message: `Launched ${appName}`
            };
            
        } catch (error) {
            return { success: false, error: `Could not launch ${appName}: ${error.message}` };
        }
    }
    
    async closeApp(appName) {
        try {
            console.log(`🛑 Closing ${appName}...`);
            
            // Map app names to process names
            const processMap = {
                'chrome': 'chrome.exe',
                'firefox': 'firefox.exe',
                'edge': 'msedge.exe',
                'notepad': 'notepad.exe',
                'calculator': 'Calculator.exe',
                'vscode': 'Code.exe',
                'visual studio code': 'Code.exe'
            };
            
            const processName = processMap[appName.toLowerCase()] || `${appName}.exe`;
            
            await execPromise(`taskkill /F /IM "${processName}"`);
            
            return {
                success: true,
                message: `Closed ${appName}`
            };
            
        } catch (error) {
            return { success: false, error: `Could not close ${appName}: ${error.message}` };
        }
    }
    
    async isAppRunning(appName) {
        try {
            const processMap = {
                'chrome': 'chrome.exe',
                'firefox': 'firefox.exe',
                'edge': 'msedge.exe',
                'notepad': 'notepad.exe',
                'calculator': 'Calculator.exe',
                'vscode': 'Code.exe'
            };
            
            const processName = processMap[appName.toLowerCase()] || `${appName}.exe`;
            
            const { stdout } = await execPromise(`tasklist /FI "IMAGENAME eq ${processName}"`);
            const isRunning = stdout.includes(processName);
            
            return { success: true, running: isRunning };
            
        } catch (error) {
            return { success: false, error: error.message };
        }
    }
}

module.exports = AppManager;