// StudyBuddy Global Utilities

// ── TOAST NOTIFICATIONS ───────────────────────────────────────────────────────
function initToastContainer() {
  if (!document.getElementById('toast-container')) {
    const container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }
}

function showToast(message, type = 'info') {
  initToastContainer();
  const container = document.getElementById('toast-container');
  
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  
  let icon = 'ℹ️';
  if (type === 'success') icon = '✅';
  if (type === 'error') icon = '❌';
  if (type === 'warning') icon = '⚠️';

  toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
  
  container.appendChild(toast);
  
  setTimeout(() => {
    toast.classList.add('hiding');
    toast.addEventListener('animationend', () => toast.remove());
  }, 3000);
}

// ── FETCH WRAPPER ────────────────────────────────────────────────────────────
async function apiFetch(url, options = {}) {
  try {
    const response = await fetch(url, options);
    
    // If not OK, attempt to parse JSON error, otherwise throw status text
    if (!response.ok) {
      let errorMsg = response.statusText;
      try {
        const errData = await response.json();
        if (errData.error) errorMsg = errData.error;
      } catch (e) { }
      throw new Error(errorMsg);
    }
    
    // If returning JSON
    const contentType = response.headers.get("content-type");
    if (contentType && contentType.indexOf("application/json") !== -1) {
      return await response.json();
    }
    
    // Fallback text
    return await response.text();
  } catch (error) {
    showToast(error.message || 'Network error occurred', 'error');
    throw error;
  }
}

// ── DARK/LIGHT MODE TOGGLE ────────────────────────────────────────────────────
function initTheme() {
  const savedTheme = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', savedTheme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
}

document.addEventListener('DOMContentLoaded', initTheme);
