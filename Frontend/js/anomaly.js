
/**
 * Smart Water Meter
 * Modul tampilan anomali pemakaian air.
 * Status anomali mengikuti data dari Backend.
 */

(function () {
    const formatNumber = (value) =>
        Number(value ?? 0).toLocaleString("id-ID", {
            maximumFractionDigits: 2
        });

    const escapeHTML = (value) =>
        String(value ?? "").replace(/[&<>"']/g, (char) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        })[char]);

    // Membaca status anomali dari data Backend.
    function isAnomaly(customer) {
        const status = String(customer?.status ?? "")
            .trim()
            .toLowerCase();

        return [
            "anomali",
            "anomaly",
            "abnormal",
            "indikasi anomali"
        ].includes(status);
    }

    // Menampilkan status pada dashboard pelanggan.
    function renderDashboard(customer, element) {
        if (!element) return;

        if (!customer) {
            element.textContent = "Data pelanggan belum tersedia.";
            return;
        }

        const usage = formatNumber(customer.hariIni);
        const average = formatNumber(customer.rata);

        if (isAnomaly(customer)) {
            element.innerHTML = `
                <div class="alert">
                    <strong>⚠️ Indikasi Anomali Pemakaian Air</strong>
                    <p>
                        Pemakaian hari ini: ${usage} m³.
                    </p>
                    <p>
                        Rata-rata pemakaian: ${average} m³.
                    </p>
                    <p>
                        Pemakaian perlu diperiksa lebih lanjut.
                        Periksa kemungkinan kebocoran atau penggunaan
                        air yang tidak biasa.
                    </p>
                    <small>
                        Indikasi anomali bukan konfirmasi kebocoran.
                    </small>
                </div>
            `;
        } else if (
            String(customer.status ?? "").trim().toLowerCase() === "normal"
        ) {
            element.innerHTML = `
                <div class="alert ok">
                    <strong>✓ Pemakaian Air Normal</strong>
                    <p>
                        Belum ada indikasi anomali berdasarkan
                        status yang diterima dari Backend.
                    </p>
                </div>
            `;
        } else {
            element.innerHTML = `
                <div class="alert">
                    <strong>Status Pemakaian Belum Tersedia</strong>
                    <p>
                        Status anomali belum dapat ditentukan.
                        Silakan periksa koneksi API dan data Backend.
                    </p>
                </div>
            `;
        }
    }

    // Menampilkan notifikasi untuk pelanggan atau petugas.
    function renderNotifications(
        element,
        customers,
        currentCustomer,
        isOfficer = false
    ) {
        if (!element) return;

        if (!Array.isArray(customers)) {
            element.textContent = "Data pelanggan tidak valid.";
            return;
        }

        const anomalies = customers.filter((customer) => {
            if (!isAnomaly(customer)) return false;

            // Pelanggan hanya melihat notifikasi miliknya.
            if (!isOfficer) {
                return String(customer.id) ===
                    String(currentCustomer?.id);
            }

            // Petugas dapat melihat seluruh pelanggan yang anomali.
            return true;
        });

        if (anomalies.length === 0) {
            element.innerHTML = `
                <div class="alert ok">
                    <strong>Tidak Ada Indikasi Anomali</strong>
                    <p>
                        Tidak ditemukan notifikasi anomali
                        pada data yang tersedia.
                    </p>
                </div>
            `;
            return;
        }

        element.innerHTML = anomalies.map((customer) => `
            <div class="alert">
                <strong>
                    ⚠️ ${escapeHTML(customer.nama)}
                    (${escapeHTML(customer.id)})
                </strong>

                <p>Alamat: ${escapeHTML(customer.alamat)}</p>

                <p>
                    Pemakaian hari ini:
                    ${formatNumber(customer.hariIni)} m³
                </p>

                <p>
                    Rata-rata pemakaian:
                    ${formatNumber(customer.rata)} m³
                </p>

                <small>
                    Waktu pembacaan:
                    ${escapeHTML(customer.waktu || "Belum tersedia")}
                </small>

                <p>
                    Perlu pemeriksaan lebih lanjut.
                    Notifikasi ini bukan bukti pasti kebocoran.
                </p>
            </div>
        `).join("");
    }

    // Fungsi yang dapat dipanggil dari app.js.
    window.AnomalyUI = {
        isAnomaly,
        renderDashboard,
        renderNotifications
    };
})();
