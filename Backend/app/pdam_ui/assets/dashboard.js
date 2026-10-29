'use strict';
const el = id => document.getElementById(id);
const number = value => Number(value ?? 0).toLocaleString('id-ID', {maximumFractionDigits: 3});
let people = [];

async function api(path, options = {}) {
  const response = await fetch(path, {credentials: 'same-origin', ...options});
  if (response.status === 401) {
    window.location.replace('/pdam/login');
    throw new Error('Sesi berakhir, silakan login ulang.');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request gagal (${response.status})`);
  return data;
}
function cell(value) {
  const td = document.createElement('td');
  td.textContent = String(value ?? '—');
  return td;
}
function appendTextRow(target, columns, emptyMessage) {
  target.replaceChildren();
  if (!columns.length) {
    const tr = document.createElement('tr');
    const td = cell(emptyMessage); td.colSpan = 7;
    tr.append(td); target.append(tr); return;
  }
  columns.forEach(row => target.append(row));
}
function renderCustomers() {
  const q = el('searchCustomer').value.trim().toLocaleLowerCase('id');
  const filtered = people.filter(p =>
    [p.id, p.nama, p.meter, p.alamat].some(v => String(v || '').toLocaleLowerCase('id').includes(q))
  );
  const rows = filtered.map(p => {
    const tr = document.createElement('tr');
    tr.append(cell(p.id), cell(p.nama), cell(p.meter), cell(p.alamat),
      cell(p.punyaPembacaan ? `${number(p.hariIni)} m³` : 'Belum tersedia'));
    const statusCell = document.createElement('td');
    const status = document.createElement('span');
    status.className = 'status ' + (!p.punyaPembacaan ? 'unknown' : p.status === 'anomali' ? 'warning' : 'normal');
    status.textContent = !p.punyaPembacaan ? 'Belum ada data' : p.status === 'anomali' ? 'Indikasi anomali' : 'Normal';
    statusCell.append(status);
    const actionCell = document.createElement('td');
    const action = document.createElement('button');
    action.type = 'button'; action.className = 'text-button'; action.textContent = 'Riwayat';
    action.addEventListener('click', () => openHistory(p.id));
    actionCell.append(action);
    tr.append(statusCell, actionCell);
    return tr;
  });
  appendTextRow(el('customerRows'), rows, 'Tidak ada pelanggan yang cocok.');
}
async function openHistory(customerId) {
  const panel = el('historyPanel');
  panel.hidden = false;
  el('historyTitle').textContent = 'Memuat riwayat...';
  el('historyRows').replaceChildren();
  panel.scrollIntoView({behavior:'smooth', block:'start'});
  try {
    const result = await api(`/api/pdam/pelanggan/${encodeURIComponent(customerId)}/riwayat`);
    el('historyTitle').textContent = `Riwayat • ${result.nama} (${result.id_pelanggan})`;
    const entries = result.riwayat.map(r => {
      const tr = document.createElement('tr');
      tr.append(cell(r.waktu), cell(number(r.meter)), cell(number(r.pemakaian)));
      return tr;
    });
    if (!entries.length) {
      const tr = document.createElement('tr');
      const td = cell('Belum ada pembacaan meter.'); td.colSpan = 3;
      tr.append(td); entries.push(tr);
    }
    el('historyRows').replaceChildren(...entries);
  } catch (e) {
    el('historyTitle').textContent = 'Riwayat gagal dimuat';
    const tr=document.createElement('tr'), td=cell(e.message); td.colSpan=3;
    tr.append(td); el('historyRows').replaceChildren(tr);
  }
}
async function reloadDashboard() {
  const response = await api('/api/pdam/dashboard');
  people = response.pelanggan;
  const s = response.statistik;
  el('officerName').textContent = response.petugas.nama;
  el('totalPelanggan').textContent = number(s.totalPelanggan);
  el('totalMeter').textContent = number(s.totalMeter);
  el('totalAnomali').textContent = number(s.indikasiAnomali);
  el('belumDibaca').textContent = number(s.belumAdaPembacaan);
  renderCustomers();
  const select = el('readingCustomer');
  const previous = select.value;
  select.replaceChildren(new Option('Pilih pelanggan', ''));
  people.forEach(p => select.add(new Option(`${p.id} — ${p.nama}`, p.id)));
  if (people.some(p => p.id === previous)) select.value = previous;
  el('notice').textContent = `Terhubung ke backend. Menampilkan ${people.length} pelanggan dari database.`;
  el('notice').className = 'notice ok';
}
el('searchCustomer').addEventListener('input', renderCustomers);
el('closeHistory').addEventListener('click', () => {el('historyPanel').hidden = true;});
el('logoutButton').addEventListener('click', async () => {
  try {await fetch('/api/logout', {method: 'POST', credentials: 'same-origin'});} finally {
    window.location.replace('/pdam/login');
  }
});
el('readingForm').addEventListener('submit', async event => {
  event.preventDefault();
  const button = el('readingButton');
  const message = el('readingMessage');
  message.textContent = ''; button.disabled = true;
  try {
    const customerId = el('readingCustomer').value;
    const meter = Number(el('meterValue').value);
    if (!customerId || !Number.isFinite(meter) || meter < 0) throw new Error('Pilih pelanggan dan masukkan angka meter yang valid.');
    const result = await api('/api/readings', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id_pelanggan: customerId, meter, waktu: new Date().toISOString()}),
    });
    message.textContent = `${result.message}. Pemakaian sejak pembacaan sebelumnya: ${number(result.pemakaian)} m³.`;
    el('meterValue').value = '';
    await reloadDashboard();
    if (!el('historyPanel').hidden) await openHistory(customerId);
  } catch (e) {message.textContent = e.message || 'Gagal menyimpan pembacaan.';}
  finally {button.disabled = false;}
});
reloadDashboard().catch(e => {
  el('notice').textContent = `Data gagal dimuat: ${e.message}`;
  el('notice').className = 'notice error';
  el('customerRows').replaceChildren();
});

// Hanya petugas yang dapat memanggil endpoint ini; backend menguji role.
el('customerForm').addEventListener('submit', async event => {
  event.preventDefault();
  const button = el('customerSubmit');
  const message = el('customerMessage');
  message.textContent = '';
  button.disabled = true;
  try {
    const payload = {
      id_pelanggan: el('newCustomerId').value.trim(),
      nomor_meter: el('newMeter').value.trim(),
      nama: el('newName').value.trim(),
      alamat: el('newAddress').value.trim(),
    };
    const response = await api('/api/pdam/pelanggan', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    message.textContent = response.message;
    el('customerForm').reset();
    await reloadDashboard();
  } catch (e) { message.textContent = e.message || 'Gagal menyimpan pelanggan.'; }
  finally { button.disabled = false; }
});
