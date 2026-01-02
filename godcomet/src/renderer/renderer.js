const commandInput = document.getElementById('commandInput');
const progressSection = document.getElementById('progressSection');
const progressFill = document.getElementById('progressFill');
const progressPercentage = document.getElementById('progressPercentage');
const progressSteps = document.getElementById('progressSteps');
const resultSection = document.getElementById('resultSection');
const resultIcon = document.getElementById('resultIcon');
const resultTitle = document.getElementById('resultTitle');
const resultContent = document.getElementById('resultContent');
const resultActions = document.getElementById('resultActions');

// Context elements
const contextApp = document.getElementById('contextApp');
const contextFile = document.getElementById('contextFile');
const contextAppPill = document.getElementById('contextAppPill');
const contextFilePill = document.getElementById('contextFilePill');

// Panels
const historyPanel = document.getElementById('historyPanel');
const workflowPanel = document.getElementById('workflowPanel');
const historyList = document.getElementById('historyList');

let currentContext = {};
let commandHistory = JSON.parse(localStorage.getItem('commandHistory') || '[]');

// Update context display periodically
setInterval(async () => {
    try {
        const context = await window.api.getCurrentContext();
        updateContextDisplay(context);
        currentContext = context;
    } catch (error) {
        console.error('Failed to get context:', error);
    }
}, 2000);

function updateContextDisplay(context) {
    // Update app
    contextApp.textContent = context.app || 'Unknown';
    
    // Update file
    if (context.file) {
        const fileName = context.file.split('\\').pop();
        contextFile.textContent = fileName;
        contextFile.title = context.file;
        contextFilePill.style.display = 'flex';
    } else {
        contextFile.textContent = 'No file';
        contextFilePill.style.display = 'none';
    }
}

// Command input handling
commandInput.addEventListener('keydown', async (e) => {
    if (e.key === 'Enter') {
        await executeCommand();
    } else if (e.key === 'Escape') {
        window.api.hideWindow();
    }
});

// Quick actions
document.querySelectorAll('.quick-action').forEach(btn => {
    btn.addEventListener('click', () => {
        commandInput.value = btn.dataset.command;
        executeCommand();
    });
});

async function executeCommand() {
    const command = commandInput.value.trim();
    if (!command) return;

    // Hide previous results
    hideResult();
    
    // Show progress
    showProgress('Processing command...', 0);

    try {
        const result = await window.api.executeCommand(command);

        hideProgress();

        if (result.success) {
            showResult('success', 'Success', result.message, result.data);
            
            // Save to history
            saveToHistory(command, result.message);
        } else {
            showResult('error', 'Error', result.error || result.message);
        }

        // Clear input
        commandInput.value = '';

    } catch (error) {
        hideProgress();
        showResult('error', 'Error', error.message);
    }
}

function showProgress(message, percent) {
    progressSection.classList.remove('hidden');
    progressFill.style.width = `${percent}%`;
    progressPercentage.textContent = `${Math.round(percent)}%`;
    resultSection.classList.add('hidden');
}

function hideProgress() {
    progressSection.classList.add('hidden');
    progressSteps.innerHTML = '';
}

function showResult(type, title, message, data = null) {
    resultSection.classList.remove('hidden');
    resultSection.className = `result-section ${type}`;
    
    // Set icon and title
    if (type === 'success') {
        resultIcon.textContent = '✅';
        resultTitle.textContent = title;
    } else {
        resultIcon.textContent = '❌';
        resultTitle.textContent = title;
    }
    
    // Set content
    resultContent.textContent = message;
    
    // Add action buttons if data has URLs
    resultActions.innerHTML = '';
    if (data) {
        if (data.vercel_url) {
            const btn = document.createElement('a');
            btn.className = 'result-action';
            btn.href = data.vercel_url;
            btn.textContent = '🌐 Open Website';
            btn.target = '_blank';
            resultActions.appendChild(btn);
        }
        if (data.github_url) {
            const btn = document.createElement('a');
            btn.className = 'result-action';
            btn.href = data.github_url;
            btn.textContent = '📦 View on GitHub';
            btn.target = '_blank';
            resultActions.appendChild(btn);
        }
    }
}

function hideResult() {
    resultSection.classList.add('hidden');
}

function saveToHistory(command, result) {
    commandHistory.unshift({
        command,
        result: result.substring(0, 100),
        timestamp: Date.now()
    });
    
    // Keep only last 50
    commandHistory = commandHistory.slice(0, 50);
    localStorage.setItem('commandHistory', JSON.stringify(commandHistory));
}

// History button
document.getElementById('historyBtn').addEventListener('click', () => {
    togglePanel(historyPanel);
    renderHistory();
});

document.getElementById('closeHistory').addEventListener('click', () => {
    historyPanel.classList.add('hidden');
});

function renderHistory() {
    if (commandHistory.length === 0) {
        historyList.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">📜</span>
                <p>No history yet</p>
            </div>
        `;
        return;
    }
    
    historyList.innerHTML = commandHistory.map(item => `
        <div class="history-item" data-command="${item.command}">
            <div class="history-command">${item.command}</div>
            <div class="history-time">${new Date(item.timestamp).toLocaleString()}</div>
        </div>
    `).join('');
    
    // Add click handlers
    historyList.querySelectorAll('.history-item').forEach(item => {
        item.addEventListener('click', () => {
            commandInput.value = item.dataset.command;
            historyPanel.classList.add('hidden');
            commandInput.focus();
        });
    });
}

// Workflow button
document.getElementById('workflowBtn').addEventListener('click', () => {
    togglePanel(workflowPanel);
});

document.getElementById('closeWorkflow').addEventListener('click', () => {
    workflowPanel.classList.add('hidden');
});

// Workflow cards
document.querySelectorAll('.workflow-card').forEach(card => {
    card.addEventListener('click', () => {
        const workflow = card.dataset.workflow;
        commandInput.value = `execute workflow ${workflow}`;
        workflowPanel.classList.add('hidden');
        commandInput.focus();
    });
});

function togglePanel(panel) {
    const isHidden = panel.classList.contains('hidden');
    
    // Close all panels
    historyPanel.classList.add('hidden');
    workflowPanel.classList.add('hidden');
    
    // Open requested panel
    if (isHidden) {
        panel.classList.remove('hidden');
    }
}

// Close result button
document.getElementById('closeResult').addEventListener('click', () => {
    hideResult();
});

// Focus input on load
setTimeout(() => {
    commandInput.focus();
}, 100);

// Global keyboard shortcuts
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        // Close panels first
        if (!historyPanel.classList.contains('hidden') || 
            !workflowPanel.classList.contains('hidden')) {
            historyPanel.classList.add('hidden');
            workflowPanel.classList.add('hidden');
        } else {
            // Close window
            window.api.hideWindow();
        }
    }
});