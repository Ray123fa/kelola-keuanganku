# Telegram Bot Pencatat Keuangan

Bot Telegram untuk mencatat transaksi keuangan harian melalui:
- Teks manual (NLP)
- Foto struk (Gemini)

Transaksi otomatis disimpan ke Google Spreadsheet berdasarkan tahun.

---

## Fitur
- Tulis: `Makan siang Rp25000 di warteg`
- Kirim foto struk: dibaca otomatis oleh Gemini
- Semua transaksi dicatat ke spreadsheet `Catatan Keuangan`

---

## Setup

### 1. Clone project & install dependencies
```bash
git clone https://github.com/username/project-nama.git
cd project-nama
pip install -r requirements.txt