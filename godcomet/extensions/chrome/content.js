// // GodComet Chrome Extension - Content Script

// // Listen for messages from background script
// chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
//   if (message.type === 'getSelection') {
//     sendResponse({ text: window.getSelection().toString() });
//   }
  
//   if (message.type === 'getPageText') {
//     sendResponse({ text: document.body.innerText });
//   }
  
//   if (message.type === 'highlight') {
//     highlightText(message.text);
//     sendResponse({ success: true });
//   }
  
//   return true;
// });

// // Highlight text on page
// function highlightText(text) {
//   const selection = window.find(text);
//   if (selection) {
//     const range = window.getSelection().getRangeAt(0);
//     const span = document.createElement('span');
//     span.style.backgroundColor = 'yellow';
//     range.surroundContents(span);
//   }
// }

// // Send page load event
// window.addEventListener('load', () => {
//   chrome.runtime.sendMessage({
//     type: 'pageLoaded',
//     url: window.location.href,
//     title: document.title
//   });
// });

// GodComet Chrome Extension - Content Script

console.log('✅ GodComet content script loaded');

// Listen for messages from background script
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  console.log('📨 Content script received message:', message);
  
  if (message.type === 'getSelection') {
    const selection = window.getSelection().toString();
    console.log('📋 Selected text:', selection.substring(0, 50));
    sendResponse({ text: selection });
  }
  
  if (message.type === 'getPageText') {
    const text = document.body.innerText;
    console.log('📄 Page text length:', text.length);
    sendResponse({ text: text });
  }
  
  return true;
});

// Notify background script when page loads
window.addEventListener('load', () => {
  console.log('🌐 Page loaded:', window.location.href);
  chrome.runtime.sendMessage({
    type: 'pageLoaded',
    url: window.location.href,
    title: document.title
  });
});

