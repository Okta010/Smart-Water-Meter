
const $ = (id) => document.getElementById(id);

const fmt = (value) => {
    const number = Number(value);

    return Number.isFinite(number)
        ? number.toLocaleString('id-ID', {
            maximumFractionDigits: 2
        })
        : '0';
};

const safe = (value) =>
    String(value ?? '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    })[char]);

function showError(message) {
    const errorBox = $('error');

    if (errorBox) {
        errorBox.textContent = message;
    } else {
        console.error(message);
    }
}

async function logout() {
    try {
        await window.api.logout();
    } catch (error) {
        console.error('Gagal mengakhiri sesi:', error);
    } finally {
        sessionStorage.removeItem('role');
        location.href = 'index.html';
    }
}

function chart(id, labels, values) {
    const canvas = $(id);

    if (!canvas || typeof Chart === 'undefined') {
        return;
    }

    new Chart(canvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: 'Pemakaian (m³)',
                data: values,
                backgroundColor: '#168bb6',
                borderRadius: 6
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'm³'
                    }
                }
            }
        }
    });
}

async function init() {
    const page = document.body.dataset.page;

    // REGISTRASI PELANGGAN
    if (page === 'register') {
        const form = $('registerForm');

        if (!form) return;

        form.addEventListener('submit', async (event) => {
            event.preventDefault();

            const errorBox = $('error');
            const successBox = $('success');

            if (errorBox) errorBox.textContent = '';
            if (successBox) successBox.textContent = '';

            const password = $('registerPassword').value;
            const confirmation = $('confirmPassword').value;

            if (password !== confirmation) {
                showError('Konfirmasi password tidak cocok.');
                return;
            }

            const button = form.querySelector(
                'button[type="submit"]'
            );

            if (button) button.disabled = true;

            try {
                await window.api.register({
                    id_pelanggan: $('customerId').value.trim(),
                    nomor_meter: $('meterId').value.trim(),
                    nama: $('fullName').value.trim(),
                    alamat: $('address').value.trim(),
                    password: password
                });

                if (successBox) {
                    successBox.textContent =
                        'Registrasi berhasil. Silakan login menggunakan ID Pelanggan dan password.';
                }

                form.reset();
            } catch (error) {
                showError(error.message);
            } finally {
                if (button) button.disabled = false;
            }
        });

        return;
    }

    // LOGIN KHUSUS PELANGGAN
    if (page === 'login') {
        const form = $('loginForm');

        if (!form) return;

        form.addEventListener('submit', async (event) => {
            event.preventDefault();

            const errorBox = $('error');

            if (errorBox) errorBox.textContent = '';

            const identifier = $('identifier').value.trim();
            const password = $('password').value;
            const button = form.querySelector(
                'button[type="submit"]'
            );

            if (button) button.disabled = true;

            try {
                const account = await window.api.login(
                    identifier,
                    password
                );

                // Halaman Frontend hanya untuk pelanggan.
                if (account.role !== 'pelanggan') {
                    try {
                        await window.api.logout();
                    } catch (error) {
                        console.error(error);
                    }

                    sessionStorage.removeItem('role');

                    showError(
                        'Halaman ini khusus pelanggan. Petugas PDAM silakan menggunakan portal PDAM di http://127.0.0.1:8001/pdam/login.'
                    );

                    return;
                }

                sessionStorage.setItem('role', 'pelanggan');

                location.href = 'dashboard-pelanggan.html';
            } catch (error) {
                showError(error.message || 'Login gagal. Periksa ID dan password.');
            } finally {
                if (button) button.disabled = false;
            }
        });

        return;
    }

    // HALAMAN YANG HANYA BOLEH DIAKSES PELANGGAN
    const protectedPages = [
        'pelanggan',
        'riwayat',
        'notifikasi'
    ];

    if (!protectedPages.includes(page)) {
        return;
    }

    let account;

    try {
        account = await window.api.me();

        if (account.role !== 'pelanggan') {
            sessionStorage.removeItem('role');
            location.href = 'index.html';
            return;
        }

        sessionStorage.setItem('role', 'pelanggan');
    } catch (error) {
        sessionStorage.removeItem('role');
        location.href = 'index.html';
        return;
    }

    document.querySelectorAll('[data-logout]').forEach((button) => {
        button.addEventListener('click', logout);
    });

    try {
        let people = [];
        let history = [];
        let mine = null;

        // Ambil data pelanggan untuk dashboard dan notifikasi.
        if (page === 'pelanggan' || page === 'notifikasi') {
            const result = await window.api.pelanggan();

            people = Array.isArray(result) ? result : [];

            mine =
                people.find(
                    (person) =>
                        String(person.id) === String(account.id)
                ) ||
                people[0] ||
                null;
        }

        // Ambil riwayat jika diperlukan.
        if (page === 'pelanggan' || page === 'riwayat') {
            const result = await window.api.riwayat();

            history = Array.isArray(result) ? result : [];
        }

        // DASHBOARD PELANGGAN
        if (page === 'pelanggan') {
            if ($('name')) {
                $('name').textContent =
                    mine?.nama || account.nama || 'Pelanggan';
            }

            if ($('usage')) {
                $('usage').textContent =
                    mine ? `${fmt(mine.hariIni)} m³` : '0 m³';
            }

            if ($('average')) {
                $('average').textContent =
                    mine ? `${fmt(mine.rata)} m³` : '0 m³';
            }

            if ($('meter')) {
                $('meter').textContent = history.length
                    ? `${fmt(history[history.length - 1].meter)} m³`
                    : 'Belum ada data';
            }

            if ($('warning')) {
                if (!mine) {
                    $('warning').textContent =
                        'Data pelanggan belum tersedia.';
                } else if (mine.status === 'anomali') {
                    $('warning').innerHTML = `
                        <strong>Indikasi anomali pemakaian air</strong>
                        <p>
                            Pemakaian tercatat ${fmt(mine.hariIni)} m³,
                            lebih tinggi dari rata-rata
                            ${fmt(mine.rata)} m³.
                            Periksa kemungkinan kebocoran.
                            Ini bukan konfirmasi kebocoran.
                        </p>
                    `;
                } else {
                    $('warning').textContent =
                        'Pemakaian terpantau normal.';
                }
            }

            chart(
                'usageChart',
                history.map((item) =>
                    String(item.tanggal || '').slice(5)
                ),
                history.map((item) => Number(item.pemakaian) || 0)
            );
        }

        // RIWAYAT PEMBACAAN METER
        if (page === 'riwayat') {
            if ($('historyRows')) {
                $('historyRows').innerHTML = history.length
                    ? history.slice().reverse().map((item) => `
                        <tr>
                            <td>${safe(item.tanggal)}</td>
                            <td>${fmt(item.meter)} m³</td>
                            <td>${fmt(item.pemakaian)} m³</td>
                        </tr>
                    `).join('')
                    : `
                        <tr>
                            <td colspan="3">
                                Belum ada data pembacaan meter.
                            </td>
                        </tr>
                    `;
            }

            chart(
                'historyChart',
                history.map((item) =>
                    String(item.tanggal || '').slice(5)
                ),
                history.map((item) => Number(item.pemakaian) || 0)
            );
        }

        // NOTIFIKASI PELANGGAN
        if (page === 'notifikasi') {
            const alerts = $('alerts');

            if (alerts) {
                if (mine && mine.status === 'anomali') {
                    alerts.innerHTML = `
                        <div class="alert">
                            <strong>
                                Indikasi anomali pemakaian air
                            </strong>
                            <p>${safe(mine.nama)}</p>
                            <p>
                                Pemakaian tercatat ${fmt(mine.hariIni)} m³;
                                rata-rata ${fmt(mine.rata)} m³.
                            </p>
                            <small>
                                Pembacaan: ${safe(mine.waktu || '-')}
                            </small>
                            <p>
                                Periksa kondisi meter dan instalasi air.
                                Indikasi ini belum membuktikan adanya kebocoran.
                            </p>
                        </div>
                    `;
                } else {
                    alerts.innerHTML =
                        '<p>Tidak ada indikasi anomali pemakaian air.</p>';
                }
            }
        }
    } catch (error) {
        showError(error.message || 'Gagal mengambil data dari server.');
        console.error(error);
    }
}

document.addEventListener('DOMContentLoaded', init);
