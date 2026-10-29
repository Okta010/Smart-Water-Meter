'use strict';
const form = document.getElementById('officerLogin');
const button = document.getElementById('loginButton');
const error = document.getElementById('loginError');
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  error.textContent = '';
  button.disabled = true;
  try {
    const response = await fetch('/api/login', {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        identifier: document.getElementById('identifier').value.trim(),
        password: document.getElementById('password').value,
      }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || 'Login gagal.');
    if (result.role !== 'pdam') {
      await fetch('/api/logout', {method:'POST', credentials:'same-origin'});
      throw new Error('Akun ini bukan akun petugas PDAM.');
    }
    window.location.assign('/pdam/dashboard');
  } catch (e) {
    error.textContent = e.message || 'Backend tidak dapat dihubungi.';
  } finally {
    button.disabled = false;
  }
});
