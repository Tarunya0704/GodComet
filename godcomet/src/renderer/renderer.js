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

    // Intercept Figma URLs — show the frame/section picker instead of auto-starting
    const figmaMatch = command.match(/https?:\/\/(?:www\.)?figma\.com\/(?:file|design|proto)\/[a-zA-Z0-9][^\s]*/i);
    if (figmaMatch) {
        commandInput.value = '';
        showFigmaPicker(figmaMatch[0]);
        return;
    }

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
        // Dismiss picker first if open
        if (!document.getElementById('figmaPicker').classList.contains('hidden')) {
            hideFigmaPicker();
            return;
        }
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

// ============================================================
// FIGMA PICKER — frame → section → generate flow
// ============================================================

const figmaPickerEl   = document.getElementById('figmaPicker');
const pickerBack      = document.getElementById('pickerBack');
const pickerTitle     = document.getElementById('pickerTitle');
const pickerClose     = document.getElementById('pickerClose');
const pickerLoading   = document.getElementById('pickerLoading');
const frameGrid       = document.getElementById('frameGrid');
const sectionList     = document.getElementById('sectionList');
const pickerFooter    = document.getElementById('pickerFooter');
const selectAllChk    = document.getElementById('selectAllSections');
const generateBtn     = document.getElementById('generateBtn');

let _pickerFigmaUrl = '';
let _pickerFrameId  = '';

pickerClose.addEventListener('click', hideFigmaPicker);
pickerBack.addEventListener('click', () => showFrameStep());

selectAllChk.addEventListener('change', () => {
    document.querySelectorAll('.section-chk').forEach(chk => {
        chk.checked = selectAllChk.checked;
    });
});

generateBtn.addEventListener('click', async () => {
    const checked = [...document.querySelectorAll('.section-chk:checked')].map(c => c.dataset.id);
    if (!checked.length) return;
    // Capture before hideFigmaPicker clears them
    const figmaUrl = _pickerFigmaUrl;
    const frameId  = _pickerFrameId;
    generateBtn.disabled = true;
    generateBtn.textContent = '⏳ Starting…';
    hideFigmaPicker();
    await startWorkflowFromPicker(figmaUrl, frameId, checked);
    generateBtn.disabled = false;
    generateBtn.textContent = '✨ Generate';
});

function hideFigmaPicker() {
    figmaPickerEl.classList.add('hidden');
    _pickerFigmaUrl = '';
    _pickerFrameId  = '';
}

function setPickerLoading(msg = 'Loading…') {
    pickerLoading.querySelector('span').textContent = msg;
    pickerLoading.classList.remove('hidden');
    frameGrid.classList.add('hidden');
    sectionList.classList.add('hidden');
    pickerFooter.classList.add('hidden');
}

function setPickerError(msg) {
    pickerLoading.classList.add('hidden');
    frameGrid.classList.add('hidden');
    sectionList.classList.add('hidden');
    pickerFooter.classList.add('hidden');
    // Reuse frameGrid div to show error
    frameGrid.innerHTML = `<div class="picker-error">⚠️ ${msg}</div>`;
    frameGrid.classList.remove('hidden');
}

async function showFigmaPicker(figmaUrl) {
    _pickerFigmaUrl = figmaUrl;
    figmaPickerEl.classList.remove('hidden');
    showFrameStep();
}

async function showFrameStep() {
    _pickerFrameId = '';
    pickerBack.classList.add('hidden');
    pickerTitle.textContent = 'Select Frame';
    pickerFooter.classList.add('hidden');
    sectionList.classList.add('hidden');
    sectionList.innerHTML = '';
    setPickerLoading('Fetching frames from Figma…');

    let frames;
    try {
        const res = await fetch('http://localhost:8001/workflow/frames', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ figma_url: _pickerFigmaUrl })
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        frames = data.frames || [];
    } catch (err) {
        setPickerError(err.message || 'Could not load frames');
        return;
    }

    if (!frames.length) {
        setPickerError('No frames found in this file');
        return;
    }

    pickerLoading.classList.add('hidden');
    frameGrid.innerHTML = frames.map(f => `
        <div class="frame-card" data-id="${f.id}">
            <div class="frame-icon">🖼</div>
            <div class="frame-name" title="${f.name}">${f.name}</div>
            <div class="frame-dims">${f.width} × ${f.height}px</div>
            ${f.page ? `<div class="frame-page">${f.page}</div>` : ''}
        </div>
    `).join('');
    frameGrid.classList.remove('hidden');

    frameGrid.querySelectorAll('.frame-card').forEach(card => {
        card.addEventListener('click', () => showSectionStep(card.dataset.id));
    });
}

async function showSectionStep(frameId) {
    _pickerFrameId = frameId;
    pickerBack.classList.remove('hidden');
    pickerTitle.textContent = 'Select Sections';
    frameGrid.classList.add('hidden');
    setPickerLoading('Loading sections…');

    let sections;
    try {
        const res = await fetch('http://localhost:8001/workflow/sections', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ figma_url: _pickerFigmaUrl, frame_id: frameId })
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        sections = data.sections || [];
    } catch (err) {
        setPickerError(err.message || 'Could not load sections');
        return;
    }

    if (!sections.length) {
        setPickerError('No sections detected in this frame');
        return;
    }

    pickerLoading.classList.add('hidden');
    sectionList.innerHTML = sections.map(s => {
        const badge = s.is_template ? `<span class="section-badge">×${s.instance_count}</span>` : '';
        const thumb = s.thumbnail_b64
            ? `<img class="section-thumb" src="${s.thumbnail_b64}" alt="">`
            : `<div class="section-thumb-placeholder">🧩</div>`;
        return `
            <div class="section-card">
                <input type="checkbox" class="section-chk" data-id="${s.id}" checked>
                ${thumb}
                <div class="section-info">
                    <div class="section-name">${s.name}</div>
                    <div class="section-meta">${s.width} × ${s.height}px${s.is_template ? ' · template' : ''}</div>
                </div>
                ${badge}
            </div>
        `;
    }).join('');
    sectionList.classList.remove('hidden');

    // "Select all" reflects real state
    selectAllChk.checked = true;
    sectionList.querySelectorAll('.section-chk').forEach(chk => {
        chk.addEventListener('change', () => {
            const all = [...document.querySelectorAll('.section-chk')];
            selectAllChk.checked = all.every(c => c.checked);
        });
    });

    pickerFooter.classList.remove('hidden');
}

async function startWorkflowFromPicker(figmaUrl, frameId, sectionIds) {
    hideResult();
    showProgress('Starting workflow…', 5);

    // Connect WebSocket for live progress updates
    let ws;
    try {
        ws = new WebSocket('ws://localhost:8002');
        ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                if (msg.type === 'step_update') {
                    const step = msg.data || {};
                    const pct = step.progress ?? (step.step_index != null
                        ? Math.round((step.step_index / (step.total_steps || 10)) * 90) + 5
                        : null);
                    showProgress(step.message || step.step_name || 'Working…', pct ?? 50);
                    // Add step to progress list
                    if (step.step_name) {
                        const li = document.createElement('div');
                        li.className = 'progress-step';
                        li.textContent = `• ${step.step_name}`;
                        progressSteps.appendChild(li);
                    }
                } else if (msg.type === 'workflow_complete') {
                    hideProgress();
                    const d = msg.data || {};
                    showResult('success', 'Deployed!', d.vercel_url || 'Workflow complete', d);
                    saveToHistory(figmaUrl, d.workflow_id || 'Workflow');
                    ws.close();
                } else if (msg.type === 'workflow_error') {
                    hideProgress();
                    showResult('error', 'Error', (msg.data || {}).error || 'Workflow failed');
                    ws.close();
                }
            } catch (_) {}
        };
        ws.onerror = () => {}; // progress only; HTTP call below handles real errors
    } catch (_) {}

    try {
        const res = await fetch('http://localhost:8001/workflow/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ figma_url: figmaUrl, frame_id: frameId })
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        // Show workflow ID immediately; WS will update as steps complete
        showProgress(`Workflow ${data.workflow_id || ''} running…`, 10);
        saveToHistory(figmaUrl, `Workflow ${data.workflow_id || ''}`);
    } catch (err) {
        hideProgress();
        showResult('error', 'Error', err.message);
        if (ws) ws.close();
    }
}