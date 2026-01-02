// GodComet Chrome Extension - Background Script
// Sends browser context to GodComet

let ws = null;
let reconnectInterval = null;
let currentTabInfo = null;

// Connect to GodComet
function connect() {
  try {
    ws = new WebSocket('ws://localhost:8766');
    
    ws.onopen = () => {
      console.log('✅ Connected to GodComet');
      if (reconnectInterval) {
        clearInterval(reconnectInterval);
        reconnectInterval = null;
      }
      
      // Send current tab info immediately after connecting
      sendCurrentTabContext();
    };
    
    ws.onclose = () => {
      console.log('⚠️ Disconnected from GodComet');
      ws = null;
      // Try to reconnect every 5 seconds
      if (!reconnectInterval) {
        reconnectInterval = setInterval(connect, 5000);
      }
    };
    
    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
    
    ws.onmessage = async (event) => {
      try {
        const message = JSON.parse(event.data);
        console.log('Received message:', message);
        
        // If GodComet requests context, send it
        if (message.type === 'getContext') {
          sendCurrentTabContext();
        }
      } catch (error) {
        console.error('Message handling error:', error);
      }
    };
  } catch (error) {
    console.error('Connection error:', error);
  }
}

// Send current tab context to GodComet
async function sendCurrentTabContext() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    
    if (tab && ws && ws.readyState === WebSocket.OPEN) {
      const context = {
        type: 'contextUpdate',
        url: tab.url,
        title: tab.title
      };
      
      currentTabInfo = context;
      
      console.log('📤 Sending context to GodComet:', context);
      ws.send(JSON.stringify(context));
    }
  } catch (error) {
    console.error('Error sending context:', error);
  }
}

// Listen for tab changes
chrome.tabs.onActivated.addListener(async (activeInfo) => {
  console.log('🔄 Tab activated:', activeInfo.tabId);
  // Wait a bit for tab to load
  setTimeout(sendCurrentTabContext, 100);
});

// Listen for tab updates (URL changes, page loads)
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.active) {
    console.log('🔄 Tab updated:', tab.url);
    sendCurrentTabContext();
  }
});

// Listen for window focus changes
chrome.windows.onFocusChanged.addListener((windowId) => {
  if (windowId !== chrome.windows.WINDOW_ID_NONE) {
    console.log('🔄 Window focused:', windowId);
    setTimeout(sendCurrentTabContext, 100);
  }
});

// Send context every 2 seconds (polling for changes)
setInterval(() => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    sendCurrentTabContext();
  }
}, 2000);

// Start connection when extension loads
console.log('🚀 GodComet Chrome Extension starting...');
connect();