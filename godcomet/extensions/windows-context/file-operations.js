/**
 * File Operations for Windows
 * Handles file transfers, copying, moving, deleting
 */

const fs = require('fs').promises;
const path = require('path');
const { exec } = require('child_process');
const util = require('util');
const execPromise = util.promisify(exec);

class FileOperations {
    constructor() {
        console.log('📁 File Operations module loaded');
    }
    
    async transferFiles(source, destination, files = []) {
        try {
            console.log(`📦 Transferring files from ${source} to ${destination}`);
            
            // If no specific files, transfer all from source
            if (files.length === 0) {
                files = await this.getAllFilesInFolder(source);
            }
            
            const results = [];
            for (const file of files) {
                const fileName = path.basename(file);
                const destPath = path.join(destination, fileName);
                
                try {
                    await fs.copyFile(file, destPath);
                    results.push({ file: fileName, success: true });
                    console.log(`✅ Transferred: ${fileName}`);
                } catch (error) {
                    results.push({ file: fileName, success: false, error: error.message });
                    console.error(`❌ Failed: ${fileName}`, error);
                }
            }
            
            return {
                success: true,
                message: `Transferred ${results.filter(r => r.success).length}/${results.length} files`,
                results: results
            };
            
        } catch (error) {
            return { success: false, error: error.message };
        }
    }
    
    async copyFiles(source, destination, files = []) {
        return await this.transferFiles(source, destination, files);
    }
    
    async moveFiles(source, destination, files = []) {
        try {
            console.log(`🚚 Moving files from ${source} to ${destination}`);
            
            if (files.length === 0) {
                files = await this.getAllFilesInFolder(source);
            }
            
            const results = [];
            for (const file of files) {
                const fileName = path.basename(file);
                const destPath = path.join(destination, fileName);
                
                try {
                    await fs.rename(file, destPath);
                    results.push({ file: fileName, success: true });
                    console.log(`✅ Moved: ${fileName}`);
                } catch (error) {
                    results.push({ file: fileName, success: false, error: error.message });
                }
            }
            
            return {
                success: true,
                message: `Moved ${results.filter(r => r.success).length}/${results.length} files`,
                results: results
            };
            
        } catch (error) {
            return { success: false, error: error.message };
        }
    }
    
    async deleteFiles(files) {
        try {
            console.log(`🗑️  Deleting ${files.length} files`);
            
            const results = [];
            for (const file of files) {
                try {
                    await fs.unlink(file);
                    results.push({ file: path.basename(file), success: true });
                    console.log(`✅ Deleted: ${path.basename(file)}`);
                } catch (error) {
                    results.push({ file: path.basename(file), success: false, error: error.message });
                }
            }
            
            return {
                success: true,
                message: `Deleted ${results.filter(r => r.success).length}/${results.length} files`,
                results: results
            };
            
        } catch (error) {
            return { success: false, error: error.message };
        }
    }
    
    async getAllFilesInFolder(folderPath) {
        try {
            const entries = await fs.readdir(folderPath, { withFileTypes: true });
            const files = entries
                .filter(entry => entry.isFile())
                .map(entry => path.join(folderPath, entry.name));
            return files;
        } catch (error) {
            console.error(`Error reading folder: ${folderPath}`, error);
            return [];
        }
    }
    
    async openFolder(folderPath) {
        try {
            await execPromise(`explorer "${folderPath}"`);
            return { success: true, message: `Opened folder: ${folderPath}` };
        } catch (error) {
            return { success: false, error: error.message };
        }
    }
    
    async createFolder(folderPath) {
        try {
            await fs.mkdir(folderPath, { recursive: true });
            return { success: true, message: `Created folder: ${folderPath}` };
        } catch (error) {
            return { success: false, error: error.message };
        }
    }
    
    async getFolderSize(folderPath) {
        try {
            const { stdout } = await execPromise(`powershell "(Get-ChildItem -Path '${folderPath}' -Recurse | Measure-Object -Property Length -Sum).Sum"`);
            const bytes = parseInt(stdout.trim());
            const mb = (bytes / (1024 * 1024)).toFixed(2);
            return { success: true, size: bytes, sizeMB: mb };
        } catch (error) {
            return { success: false, error: error.message };
        }
    }
}

module.exports = FileOperations;