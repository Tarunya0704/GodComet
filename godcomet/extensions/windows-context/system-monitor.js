/**
 * System Monitor for Windows
 * Track running apps, system info
 */

const { exec } = require('child_process');
const util = require('util');
const execPromise = util.promisify(exec);
const os = require('os');

class SystemMonitor {
    constructor() {
        console.log('📊 System Monitor module loaded');
    }
    
    async getRunningApps() {
        try {
            const { stdout } = await execPromise('tasklist /FO CSV /NH');
            
            const lines = stdout.split('\n').filter(line => line.trim());
            const apps = lines.map(line => {
                const parts = line.split(',').map(p => p.replace(/"/g, ''));
                return {
                    name: parts[0],
                    pid: parts[1],
                    memory: parts[4]
                };
            });
            
            // Remove duplicates
            const uniqueApps = {};
            apps.forEach(app => {
                if (!uniqueApps[app.name]) {
                    uniqueApps[app.name] = app;
                }
            });
            
            return {
                success: true,
                apps: Object.values(uniqueApps),
                count: Object.keys(uniqueApps).length
            };
            
        } catch (error) {
            return { success: false, error: error.message };
        }
    }
    
    async getSystemInfo() {
        try {
            const cpuUsage = os.loadavg()[0];
            const totalMem = os.totalmem();
            const freeMem = os.freemem();
            const usedMem = totalMem - freeMem;
            
            const memoryUsagePercent = ((usedMem / totalMem) * 100).toFixed(2);
            
            // Get disk info
            const diskInfo = await this.getDiskInfo();
            
            return {
                success: true,
                data: {
                    platform: os.platform(),
                    arch: os.arch(),
                    hostname: os.hostname(),
                    cpus: os.cpus().length,
                    cpuModel: os.cpus()[0].model,
                    totalMemory: this.formatBytes(totalMem),
                    freeMemory: this.formatBytes(freeMem),
                    usedMemory: this.formatBytes(usedMem),
                    memoryUsage: `${memoryUsagePercent}%`,
                    uptime: this.formatUptime(os.uptime()),
                    disks: diskInfo
                }
            };
            
        } catch (error) {
            return { success: false, error: error.message };
        }
    }
    
    async getDiskInfo() {
        try {
            const psScript = `Get-PSDrive -PSProvider FileSystem | Where-Object {$_.Used -ne $null} | Select-Object Name, @{Name="UsedGB";Expression={[math]::Round($_.Used/1GB,2)}}, @{Name="FreeGB";Expression={[math]::Round($_.Free/1GB,2)}}, @{Name="TotalGB";Expression={[math]::Round(($_.Used + $_.Free)/1GB,2)}} | ConvertTo-Json`;
            
            const { stdout } = await execPromise(`powershell -Command "${psScript}"`);
            const disks = JSON.parse(stdout);
            
            return Array.isArray(disks) ? disks : [disks];
            
        } catch (error) {
            return [];
        }
    }
    
    formatBytes(bytes) {
        const gb = (bytes / (1024 ** 3)).toFixed(2);
        return `${gb} GB`;
    }
    
    formatUptime(seconds) {
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor((seconds % 86400) / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        
        return `${days}d ${hours}h ${minutes}m`;
    }
}

module.exports = SystemMonitor;