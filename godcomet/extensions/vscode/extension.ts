// import * as vscode from 'vscode';
// import WebSocket from 'ws';

// let ws: WebSocket | null = null;
// let statusBarItem: vscode.StatusBarItem;

// export function activate(context: vscode.ExtensionContext) {
//     console.log('GodComet extension activated');

//     // Create status bar item
//     statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
//     statusBarItem.text = '$(plug) GodComet';
//     statusBarItem.tooltip = 'Click to connect to GodComet';
//     statusBarItem.command = 'godcomet.connect';
//     statusBarItem.show();
//     context.subscriptions.push(statusBarItem);

//     // Register commands
//     context.subscriptions.push(
//         vscode.commands.registerCommand('godcomet.connect', connect)
//     );
//     context.subscriptions.push(
//         vscode.commands.registerCommand('godcomet.disconnect', disconnect)
//     );

//     // Auto-connect if enabled
//     const config = vscode.workspace.getConfiguration('godcomet');
//     if (config.get('autoConnect')) {
//         connect();
//     }

//     // Listen for file changes
//     vscode.window.onDidChangeActiveTextEditor((editor) => {
//         if (ws && ws.readyState === WebSocket.OPEN && editor) {
//             sendMessage({
//                 type: 'fileChanged',
//                 file: editor.document.fileName,
//                 language: editor.document.languageId
//             });
//         }
//     });

//     // Listen for selection changes
//     vscode.window.onDidChangeTextEditorSelection((event) => {
//         if (ws && ws.readyState === WebSocket.OPEN) {
//             const selection = event.textEditor.document.getText(event.selections[0]);
//             if (selection) {
//                 sendMessage({
//                     type: 'selectionChanged',
//                     text: selection
//                 });
//             }
//         }
//     });
// }

// function connect() {
//     const config = vscode.workspace.getConfiguration('godcomet');
//     const port = config.get('serverPort', 8765);

//     try {
//         ws = new WebSocket(`ws://localhost:${port}`);

//         ws.on('open', () => {
//             console.log('Connected to GodComet');
//             statusBarItem.text = '$(plug) GodComet ✓';
//             statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.prominentBackground');
//             vscode.window.showInformationMessage('Connected to GodComet');

//             // Send initial context
//             const editor = vscode.window.activeTextEditor;
//             if (editor) {
//                 sendMessage({
//                     type: 'connected',
//                     file: editor.document.fileName,
//                     language: editor.document.languageId
//                 });
//             }
//         });

//         ws.on('close', () => {
//             console.log('Disconnected from GodComet');
//             statusBarItem.text = '$(plug) GodComet';
//             statusBarItem.backgroundColor = undefined;
//             ws = null;
//         });

//         ws.on('error', (error) => {
//             console.error('WebSocket error:', error);
//             vscode.window.showErrorMessage('Failed to connect to GodComet');
//         });

//         ws.on('message', async (data) => {
//             const message = JSON.parse(data.toString());
//             const response = await handleMessage(message);
//             sendMessage(response);
//         });

//     } catch (error) {
//         vscode.window.showErrorMessage(`Connection failed: ${error}`);
//     }
// }

// function disconnect() {
//     if (ws) {
//         ws.close();
//         ws = null;
//         statusBarItem.text = '$(plug) GodComet';
//         statusBarItem.backgroundColor = undefined;
//         vscode.window.showInformationMessage('Disconnected from GodComet');
//     }
// }

// async function handleMessage(message: any): Promise<any> {
//     try {
//         switch (message.type) {
//             case 'getCurrentFile':
//                 return getCurrentFile();

//             case 'getSelection':
//                 return getSelection();

//             case 'runCommand':
//                 return await runCommand(message.command, message.args);

//             case 'insertText':
//                 return await insertText(message.text);

//             default:
//                 return { error: 'Unknown message type' };
//         }
//     } catch (error: any) {
//         return { error: error.message };
//     }
// }

// function getCurrentFile() {
//     const editor = vscode.window.activeTextEditor;
//     if (editor) {
//         return {
//             file: editor.document.fileName,
//             language: editor.document.languageId,
//             content: editor.document.getText()
//         };
//     }
//     return { file: null };
// }

// function getSelection() {
//     const editor = vscode.window.activeTextEditor;
//     if (editor && editor.selection) {
//         return {
//             text: editor.document.getText(editor.selection)
//         };
//     }
//     return { text: null };
// }

// async function runCommand(command: string, args?: any) {
//     try {
//         await vscode.commands.executeCommand(command, args);
//         return { success: true };
//     } catch (error: any) {
//         return { success: false, error: error.message };
//     }
// }

// async function insertText(text: string) {
//     const editor = vscode.window.activeTextEditor;
//     if (editor) {
//         await editor.edit((editBuilder) => {
//             editBuilder.insert(editor.selection.active, text);
//         });
//         return { success: true };
//     }
//     return { success: false, error: 'No active editor' };
// }

// function sendMessage(message: any) {
//     if (ws && ws.readyState === WebSocket.OPEN) {
//         ws.send(JSON.stringify(message));
//     }
// }

// export function deactivate() {
//     if (ws) {
//         ws.close();
//     }
// }

import * as vscode from 'vscode';
import WebSocket from 'ws';

let ws: WebSocket | null = null;
let statusBarItem: vscode.StatusBarItem;
let reconnectTimer: NodeJS.Timeout | null = null;
let isConnecting = false;

export function activate(context: vscode.ExtensionContext) {
    console.log('🚀 GodComet VS Code extension activated');

    // Create status bar item
    statusBarItem = vscode.window.createStatusBarItem(
        vscode.StatusBarAlignment.Right, 
        100
    );
    statusBarItem.text = '$(plug) GodComet';
    statusBarItem.tooltip = 'GodComet: Click to connect';
    statusBarItem.command = 'godcomet.connect';
    statusBarItem.show();
    context.subscriptions.push(statusBarItem);

    // Register commands
    context.subscriptions.push(
        vscode.commands.registerCommand('godcomet.connect', () => {
            connect();
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('godcomet.disconnect', () => {
            disconnect();
        })
    );

    // Auto-connect after 2 seconds
    setTimeout(() => {
        connect();
    }, 2000);

    // Send context when active editor changes
    context.subscriptions.push(
        vscode.window.onDidChangeActiveTextEditor((editor) => {
            if (editor) {
                sendContextUpdate();
            }
        })
    );

    // Send context when selection changes
    context.subscriptions.push(
        vscode.window.onDidChangeTextEditorSelection(() => {
            sendContextUpdate();
        })
    );

    // Send context every 5 seconds if connected
    setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            sendContextUpdate();
        }
    }, 5000);
}

function connect() {
    if (isConnecting) {
        return;
    }

    if (ws && ws.readyState === WebSocket.OPEN) {
        console.log('Already connected');
        return;
    }

    isConnecting = true;
    const port = 8765;

    try {
        console.log(`Connecting to ws://localhost:${port}...`);
        ws = new WebSocket(`ws://localhost:${port}`);

        ws.on('open', () => {
            console.log('✅ Connected to GodComet');
            isConnecting = false;
            
            statusBarItem.text = '$(plug) GodComet ✓';
            statusBarItem.tooltip = 'GodComet: Connected';
            statusBarItem.backgroundColor = new vscode.ThemeColor(
                'statusBarItem.prominentBackground'
            );

            vscode.window.showInformationMessage('✅ GodComet connected');

            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }

            // Send initial context
            setTimeout(() => {
                sendContextUpdate();
            }, 500);

            // Send context every second for first 5 seconds
            let initialUpdates = 0;
            const initialTimer = setInterval(() => {
                sendContextUpdate();
                initialUpdates++;
                if (initialUpdates >= 5) {
                    clearInterval(initialTimer);
                }
            }, 1000);
        });

        ws.on('close', () => {
            console.log('⚠️  Disconnected from GodComet');
            isConnecting = false;
            
            statusBarItem.text = '$(plug) GodComet';
            statusBarItem.tooltip = 'GodComet: Disconnected';
            statusBarItem.backgroundColor = undefined;
            
            ws = null;

            // Auto-reconnect after 5 seconds
            if (!reconnectTimer) {
                reconnectTimer = setTimeout(() => {
                    reconnectTimer = null;
                    connect();
                }, 5000);
            }
        });

        ws.on('error', (error) => {
            console.error('WebSocket error:', error.message);
            isConnecting = false;
        });

        ws.on('message', async (data: Buffer) => {
            try {
                const message = JSON.parse(data.toString());
                
                if (message.type === 'getContext') {
                    // Send context immediately
                    const context = await getContext();
                    if (ws && ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify(context));
                    }
                }
            } catch (error: any) {
                console.error('Message error:', error.message);
            }
        });

    } catch (error: any) {
        console.error('Connection failed:', error.message);
        isConnecting = false;
        vscode.window.showErrorMessage(`GodComet connection failed: ${error.message}`);
    }
}

function disconnect() {
    if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
    }

    if (ws) {
        ws.close();
        ws = null;
        statusBarItem.text = '$(plug) GodComet';
        statusBarItem.tooltip = 'GodComet: Disconnected';
        statusBarItem.backgroundColor = undefined;
        vscode.window.showInformationMessage('GodComet disconnected');
    }
}

function sendContextUpdate() {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        return;
    }

    const editor = vscode.window.activeTextEditor;
    
    if (!editor) {
        return;
    }

    const context = {
        type: 'contextUpdate',
        file: editor.document.fileName,
        language: editor.document.languageId,
        selectedText: editor.document.getText(editor.selection) || null,
        lineCount: editor.document.lineCount,
        cursorLine: editor.selection.active.line + 1,
        cursorColumn: editor.selection.active.character + 1
    };

    try {
        ws.send(JSON.stringify(context));
        console.log('📤 Context sent:', context.file);
    } catch (error: any) {
        console.error('Send error:', error.message);
    }
}

async function getContext() {
    const editor = vscode.window.activeTextEditor;

    if (!editor) {
        return {
            type: 'context',
            file: null,
            language: null,
            selectedText: null,
            lineCount: 0,
            cursorLine: 0,
            cursorColumn: 0
        };
    }

    return {
        type: 'context',
        file: editor.document.fileName,
        language: editor.document.languageId,
        selectedText: editor.document.getText(editor.selection) || null,
        lineCount: editor.document.lineCount,
        cursorLine: editor.selection.active.line + 1,
        cursorColumn: editor.selection.active.character + 1
    };
}

export function deactivate() {
    if (reconnectTimer) {
        clearTimeout(reconnectTimer);
    }
    if (ws) {
        ws.close();
    }
}