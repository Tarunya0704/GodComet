"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const ws_1 = __importDefault(require("ws"));
let ws = null;
let statusBarItem;
function activate(context) {
    console.log('GodComet extension activated');
    // Create status bar item
    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBarItem.text = '$(plug) GodComet';
    statusBarItem.tooltip = 'Click to connect to GodComet';
    statusBarItem.command = 'godcomet.connect';
    statusBarItem.show();
    context.subscriptions.push(statusBarItem);
    // Register commands
    context.subscriptions.push(vscode.commands.registerCommand('godcomet.connect', connect));
    context.subscriptions.push(vscode.commands.registerCommand('godcomet.disconnect', disconnect));
    // Auto-connect if enabled
    const config = vscode.workspace.getConfiguration('godcomet');
    if (config.get('autoConnect')) {
        connect();
    }
    // Listen for file changes
    vscode.window.onDidChangeActiveTextEditor((editor) => {
        if (ws && ws.readyState === ws_1.default.OPEN && editor) {
            sendMessage({
                type: 'fileChanged',
                file: editor.document.fileName,
                language: editor.document.languageId
            });
        }
    });
    // Listen for selection changes
    vscode.window.onDidChangeTextEditorSelection((event) => {
        if (ws && ws.readyState === ws_1.default.OPEN) {
            const selection = event.textEditor.document.getText(event.selections[0]);
            if (selection) {
                sendMessage({
                    type: 'selectionChanged',
                    text: selection
                });
            }
        }
    });
}
function connect() {
    const config = vscode.workspace.getConfiguration('godcomet');
    const port = config.get('serverPort', 8765);
    try {
        ws = new ws_1.default(`ws://localhost:${port}`);
        ws.on('open', () => {
            console.log('Connected to GodComet');
            statusBarItem.text = '$(plug) GodComet ✓';
            statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.prominentBackground');
            vscode.window.showInformationMessage('Connected to GodComet');
            // Send initial context
            const editor = vscode.window.activeTextEditor;
            if (editor) {
                sendMessage({
                    type: 'connected',
                    file: editor.document.fileName,
                    language: editor.document.languageId
                });
            }
        });
        ws.on('close', () => {
            console.log('Disconnected from GodComet');
            statusBarItem.text = '$(plug) GodComet';
            statusBarItem.backgroundColor = undefined;
            ws = null;
        });
        ws.on('error', (error) => {
            console.error('WebSocket error:', error);
            vscode.window.showErrorMessage('Failed to connect to GodComet');
        });
        ws.on('message', async (data) => {
            const message = JSON.parse(data.toString());
            const response = await handleMessage(message);
            sendMessage(response);
        });
    }
    catch (error) {
        vscode.window.showErrorMessage(`Connection failed: ${error}`);
    }
}
function disconnect() {
    if (ws) {
        ws.close();
        ws = null;
        statusBarItem.text = '$(plug) GodComet';
        statusBarItem.backgroundColor = undefined;
        vscode.window.showInformationMessage('Disconnected from GodComet');
    }
}
async function handleMessage(message) {
    try {
        switch (message.type) {
            case 'getCurrentFile':
                return getCurrentFile();
            case 'getSelection':
                return getSelection();
            case 'runCommand':
                return await runCommand(message.command, message.args);
            case 'insertText':
                return await insertText(message.text);
            default:
                return { error: 'Unknown message type' };
        }
    }
    catch (error) {
        return { error: error.message };
    }
}
function getCurrentFile() {
    const editor = vscode.window.activeTextEditor;
    if (editor) {
        return {
            file: editor.document.fileName,
            language: editor.document.languageId,
            content: editor.document.getText()
        };
    }
    return { file: null };
}
function getSelection() {
    const editor = vscode.window.activeTextEditor;
    if (editor && editor.selection) {
        return {
            text: editor.document.getText(editor.selection)
        };
    }
    return { text: null };
}
async function runCommand(command, args) {
    try {
        await vscode.commands.executeCommand(command, args);
        return { success: true };
    }
    catch (error) {
        return { success: false, error: error.message };
    }
}
async function insertText(text) {
    const editor = vscode.window.activeTextEditor;
    if (editor) {
        await editor.edit((editBuilder) => {
            editBuilder.insert(editor.selection.active, text);
        });
        return { success: true };
    }
    return { success: false, error: 'No active editor' };
}
function sendMessage(message) {
    if (ws && ws.readyState === ws_1.default.OPEN) {
        ws.send(JSON.stringify(message));
    }
}
function deactivate() {
    if (ws) {
        ws.close();
    }
}
//# sourceMappingURL=extension.js.map