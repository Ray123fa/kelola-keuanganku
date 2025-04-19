import telebot
import google.generativeai as genai
from PIL import Image
import io
import re
import pytz
from datetime import datetime
import os
from dotenv import load_dotenv
from auth import get_sheet
import json

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
genai.configure(api_key=GEMINI_API_KEY)
vision_model = genai.GenerativeModel('gemini-1.5-flash')

# Define WIB timezone
WIB = pytz.timezone('Asia/Jakarta')

def simpan_transaksi(data: dict):
    tahun = data['tanggal'][:4] if data['tanggal'] else "Unknown"
    sheet = get_sheet(tahun)
    sheet.append_row([data['tanggal'], data['deskripsi'], data['jumlah'], data['kategori']])

def format_tanggal(line: str, last_seen_date: str):
    # Regex untuk mencocokkan format tanggal yang opsional diikuti dengan waktu
    date_match = re.match(r"(\d{1,2})\s([a-zA-Z]+)\s(\d{2,4})(?:\s(\d{1,2}):(\d{2}))?", line.strip())

    if date_match:
        # Ambil hasil dari regex
        day, month_name, year, hour, minute = date_match.groups()

        # Map bulan ke nomor bulan
        month_map = {
            "Januari": "01", "Februari": "02", "Maret": "03", "April": "04", "Mei": "05", "Juni": "06",
            "Juli": "07", "Agustus": "08", "September": "09", "Oktober": "10", "November": "11", "Desember": "12",
            "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "Mei": "05", "Jun": "06",
            "Jul": "07", "Agu": "08", "Sep": "09", "Okt": "10", "Nov": "11", "Des": "12"
        }

        # Periksa apakah bulan ditemukan dan setel bulan
        month = month_map.get(month_name.capitalize(), "01")

        # Jika tahun hanya dua digit, tambahkan 20 di depannya
        if len(year) == 2:
            year = "20" + year

        # Tentukan jam dan menit, jika tidak ada waktu, gunakan "00:00"
        hour = hour if hour else "00"
        minute = minute if minute else "00"

        # Formatkan tanggal menjadi YYYY-MM-DD HH:MM:SS
        return f"{year}-{month}-{day.zfill(2)} {hour}:{minute}:00"
    
    # Jika tidak ada kecocokan, kembalikan tanggal terakhir yang diketahui
    return last_seen_date

def extract_transaction_data(formatted_response: str):
    # Regex patterns for extracting the relevant data
    deskripsi_pattern = r"Deskripsi:\s?(.+)"
    jumlah_pattern = r"Jumlah:\s?Rp([0-9]{1,3}(?:\.[0-9]{3})*(?:,\d+)?)"
    kategori_pattern = r"Kategori:\s?(.+)"
    tanggal_pattern = r"Tanggal:\s?(.+)"

    # Extract the relevant data using regex
    deskripsi_match = re.search(deskripsi_pattern, formatted_response)
    jumlah_match = re.search(jumlah_pattern, formatted_response)
    kategori_match = re.search(kategori_pattern, formatted_response)
    tanggal_match = re.search(tanggal_pattern, formatted_response)

    # Initialize extracted data
    deskripsi = deskripsi_match.group(1) if deskripsi_match else "Unknown"
    jumlah = int(jumlah_match.group(1).replace('.', '').replace(',', '')) if jumlah_match else 0
    kategori = kategori_match.group(1) if kategori_match else "Unknown"
    tanggal = tanggal_match.group(1) if tanggal_match else None

    return deskripsi, jumlah, kategori, tanggal

@bot.message_handler(commands=['keluar'])
def handle_text(message):
    # Ambil teks transaksi setelah command
    transaction_text = message.text[len("/keluar"):].strip()
    transactions = [line.strip() for line in transaction_text.split("\n") if line.strip()]

    if not transactions:
        bot.reply_to(message, "Tidak ada transaksi yang dapat diproses.")
        return

    current_time = datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S')
    last_seen_date = None

    # Bangun prompt batch dengan deskripsi tanggal seperti versi sebelumnya
    prompt = (
        "Berikut adalah daftar transaksi:\n\n"
        + "\n".join(transactions) +
        "\n\nPerlu diperhatikan bahwa penulisan harga dalam transaksi bisa menggunakan berbagai format, seperti:\n"
        "- 15rb atau 15k berarti 15000\n"
        "- 1,5rb / 1,5k / 1.5rb / 1.5k berarti 1500\n"
        "- 1jt berarti 1000000\n"
        "- 1,5jt / 1.5jt berarti 1500000\n"
        "- 1,25jt / 1.25jt berarti 1250000\n"
        "Konversikan seluruh bentuk harga tersebut ke dalam angka bulat penuh dalam satuan Rupiah.\n\n"
        "Perlu diperhatikan pula bahwa tanggal yang tertera dalam transaksi dapat ditulis dalam berbagai format, seperti:\n"
        "- 13 April 2025\n"
        "- 13 Apr 2025\n"
        "- 13 april 2025\n"
        "- 13 apr 2025\n"
        "- 13 April 25\n"
        "- 13 Apr 25\n"
        "- 13 april 25\n"
        "- 13 apr 25\n"
        "Konversikan semua format di atas ke dalam format akhir: tahun(4 digit)-bulan(2 digit)-tanggal jam(24 jam):menit:detik, seperti 2025-04-13 00:00:00.\n"
        "Jika tidak disebutkan jam dan menit, gunakan '00:00:00'.\n"
        "Jika tidak ada tanggal, gunakan tanda '-' untuk menandakan tanggal tidak tersedia.\n"
        "Jika tanggal disebutkan di awal, gunakan tanggal tersebut untuk transaksi berikutnya yang tidak memiliki tanggal. Jika tidak ada sama sekali, tetap gunakan '-'>\n\n"
        "Tampilkan hasil dalam format teks berikut:\n"
        "Deskripsi: <jumlah barang (seperti 1x atau 2x) dan deskripsi barang utama>\n"
        "Jumlah: Rp<total yang dibayar, pisahkan dengan titik untuk ribuan dan koma untuk desimal, tanpa spasi setelah 'Rp'>\n"
        "Kategori: <kategori barang/jasa>\n"
        "Tanggal: <tanggal transaksi>\n\n"
        "Pisahkan setiap transaksi dengan satu baris kosong.\n\n"
        "Setiap baris transaksi mewakili satu transaksi berbeda, meskipun memiliki nama atau deskripsi yang sama. Jangan pernah menggabungkan transaksi yang berbeda waktu atau tanggal."
    )

    try:
        response = vision_model.generate_content([prompt])
    except Exception as e:
        bot.reply_to(message, f"Gagal menghubungi Gemini API:\n{e}")
        return

    if not response or not response.text.strip():
        bot.reply_to(message, "Tidak ada respons dari Gemini.")
        return

    formatted_items = []
    results = response.text.strip().split("\n\n")

    for item in results:
        if not item.strip():
            continue

        deskripsi, jumlah, kategori, tanggal = extract_transaction_data(item)

        # Atur tanggal jika kosong
        if tanggal == '-' and last_seen_date is not None:
            tanggal = last_seen_date
        elif tanggal == '-' and last_seen_date is None:
            tanggal = current_time
        else:
            last_seen_date = tanggal

        # Validasi & simpan
        if deskripsi not in ['-', None, 'Unknown'] and kategori not in ['-', None, 'Unknown']:
            formatted_price = f"Rp{int(jumlah):,}".replace(",", ".")
            formatted_result = f"- Deskripsi: {deskripsi}\n- Jumlah: {formatted_price}\n- Kategori: {kategori}\n- Tanggal: {tanggal}\n"
            formatted_items.append(formatted_result)

            simpan_transaksi({
                "tanggal": tanggal,
                "deskripsi": deskripsi,
                "jumlah": jumlah,
                "kategori": kategori
            })

    if formatted_items:
        bot.reply_to(message, f"Pengeluaran tercatat\n\n{'\n'.join(formatted_items)}")
    else:
        bot.reply_to(message, "Tidak ada transaksi valid yang berhasil dicatat.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    image = Image.open(io.BytesIO(downloaded_file))
    
    current_time = datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S')
    last_seen_date = None

    prompt = (
        "Ambil informasi transaksi keuangan dari gambar struk ini. Fokus pada apa yang dibayar sebagai satu transaksi utuh, "
        "dan gunakan jumlah total yang benar-benar dibayar (setelah diskon, pengiriman, layanan, pengemasan, dll).\n\n"
        "\n\nPerlu diperhatikan bahwa penulisan harga dalam transaksi bisa menggunakan berbagai format, seperti:\n"
        "- 15rb atau 15k berarti 15000\n"
        "- 1,5rb / 1,5k / 1.5rb / 1.5k berarti 1500\n"
        "- 1jt berarti 1000000\n"
        "- 1,5jt / 1.5jt berarti 1500000\n"
        "- 1,25jt / 1.25jt berarti 1250000\n"
        "Konversikan seluruh bentuk harga tersebut ke dalam angka bulat penuh dalam satuan Rupiah.\n\n"
        "Perlu diperhatikan pula bahwa tanggal yang tertera dalam transaksi dapat ditulis dalam berbagai format, seperti:\n"
        "- 13 April 2025\n"
        "- 13 Apr 2025\n"
        "- 13 april 2025\n"
        "- 13 apr 2025\n"
        "- 13 April 25\n"
        "- 13 Apr 25\n"
        "- 13 april 25\n"
        "- 13 apr 25\n"
        "Konversikan semua format di atas ke dalam format akhir: tahun(4 digit)-bulan(2 digit)-tanggal jam(24 jam):menit:detik, seperti 2025-04-13 00:00:00.\n"
        "Jika tidak disebutkan jam dan menit, gunakan '00:00:00'.\n"
        "Jika tidak ada tanggal, gunakan tanda '-' untuk menandakan tanggal tidak tersedia.\n"
        "Jika tanggal disebutkan di awal, gunakan tanggal tersebut untuk transaksi berikutnya yang tidak memiliki tanggal. Jika tidak ada sama sekali, tetap gunakan '-'>\n\n"
        "Tampilkan hasil dalam format teks berikut:\n"
        "Deskripsi: <deskripsi menu/barang utama>\n"
        "Jumlah: Rp<total yang dibayar, pisahkan dengan titik untuk ribuan dan koma untuk desimal, tanpa spasi setelah 'Rp'>\n"
        "Kategori: <kategori barang/jasa>\n"
        "Tanggal: <tanggal transaksi, gunakan format tahun(4digit)-bulan(2digit)-tanggal jam(24jam):menit:detik, seperti 2025-02-16 14:53:33>\n\n"
        "Setiap transaksi harus ditampilkan lengkap dengan deskripsi, jumlah, kategori, dan tanggal.\n"
        "Pisahkan setiap transaksi dengan satu baris kosong."
    )

    try:
        response = vision_model.generate_content([prompt, image])
        if not response.text.strip():
            raise ValueError("Respon dari Gemini kosong atau tidak dikenali sebagai transaksi.")

        transactions = response.text.strip().split("\n\n")
        formatted_items = []
        valid_transaction_found = False  # << flag tambahan

        for item in transactions:
            if not item.strip():
                continue

            deskripsi, jumlah, kategori, tanggal = extract_transaction_data(item)

            if tanggal == '-' and last_seen_date is not None:
                tanggal = last_seen_date
            elif tanggal == '-' and last_seen_date is None:
                tanggal = current_time
            else:
                last_seen_date = tanggal

            if deskripsi not in ['-', None, 'Unknown'] and kategori not in ['-', None, 'Unknown'] and jumlah > 0:
                valid_transaction_found = True
                formatted_price = f"Rp{int(jumlah):,}".replace(",", ".")
                formatted_item = (
                    f"- Deskripsi: {deskripsi}\n"
                    f"- Jumlah: {formatted_price}\n"
                    f"- Kategori: {kategori}\n"
                    f"- Tanggal: {tanggal}"
                )
                formatted_items.append(formatted_item)

                simpan_transaksi({
                    "tanggal": tanggal,
                    "deskripsi": deskripsi,
                    "jumlah": jumlah,
                    "kategori": kategori
                })

        if valid_transaction_found:
            bot.reply_to(message, f"Berikut adalah informasi transaksi dari struk yang diberikan\n\n{'\n\n'.join(formatted_items)}")
        else:
            bot.reply_to(message, "Struk yang diberikan tidak berisi transaksi yang dapat dikenali atau dicatat.")

    except json.JSONDecodeError as e:
        bot.reply_to(message, f"Error saat memproses gambar: JSON Decode Error: {e}")
    except ValueError as e:
        bot.reply_to(message, f"Error saat memproses gambar: {e}")
    except Exception as e:
        bot.reply_to(message, f"Error saat memproses gambar: {e}")

print("Bot is running...")
bot.infinity_polling()