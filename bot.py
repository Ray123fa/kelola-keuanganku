import telebot
import google.generativeai as genai
from PIL import Image
import io
import re
import pytz
from datetime import datetime
import nltk
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

# Download necessary NLTK data (if not already downloaded)
nltk.download('punkt_tab')

# Mapping kategori
kategori_map = {
    'makan': 'makanan', 'warteg': 'makanan', 'indomaret': 'belanja',
    'bensin': 'transportasi', 'gojek': 'transportasi',
    'listrik': 'tagihan', 'air': 'tagihan'
}

# Define WIB timezone
WIB = pytz.timezone('Asia/Jakarta')

# Function to normalize the date
def normalize_date(date_str=None):
    if date_str:
        try:
            # If a date string is provided, parse it
            parsed_date = datetime.strptime(date_str, '%d %b %Y')  # Example: 16 Apr 2025
            # Convert it to the desired format using WIB timezone
            return parsed_date.astimezone(WIB).strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            print(f"Error parsing date: {e}")
            return datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S')
    else:
        # If no date provided, return the current date and time in WIB format
        return datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S')

def parse_transaksi(text):
    # Extract amount
    jumlah_match = re.search(r'rp[\s.]?([\d.,]+)', text.lower())
    jumlah = int(jumlah_match.group(1).replace('.', '').replace(',', '')) if jumlah_match else 0
    
    # Get the current date and time in WIB
    tanggal = datetime.now(WIB)  # Get current date and time in WIB
    tanggal_str = tanggal.strftime('%Y-%m-%d %H:%M:%S')  # Format date with time as YYYY-MM-DD HH:MM:SS
    
    # Tokenize using NLTK
    tokens = nltk.word_tokenize(text.lower())
    kategori = 'lainnya'

    # Look for categories in the tokens
    for token in tokens:
        for key in kategori_map:
            if key in token:
                kategori = kategori_map[key]
                break
    
    # Extract description (excluding numbers, punctuation, and specific parts of speech)
    deskripsi = ' '.join([token for token in tokens if not token.isdigit() and token not in [',', '.', ':', ';', '!', '?']])
    
    return {
        "deskripsi": deskripsi.strip(),
        "jumlah": jumlah,
        "kategori": kategori,
        "tanggal": tanggal_str
    }

def simpan_transaksi(data: dict, sumber: str = "manual"):
    tahun = data['tanggal'][:4] if data['tanggal'] else "Unknown"
    sheet = get_sheet(tahun)
    sheet.append_row([data['tanggal'], data['deskripsi'], data['jumlah'], data['kategori'], sumber])

@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_text(message):
    hasil = parse_transaksi(message.text)
    simpan_transaksi(hasil, "manual")
    bot.reply_to(message, f"""
    Tercatat:
    - Deskripsi: {hasil['deskripsi']}
    - Jumlah: Rp{hasil['jumlah']:,}
    - Kategori: {hasil['kategori']}
    - Tanggal: {hasil['tanggal'] or 'Tidak ditemukan'}
    """)

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    image = Image.open(io.BytesIO(downloaded_file))

    prompt = (
        "Ambil informasi transaksi keuangan dari gambar struk ini. Fokus pada apa yang dibayar sebagai satu transaksi utuh, "
        "dan gunakan jumlah total yang benar-benar dibayar (setelah diskon, pengiriman, layanan, pengemasan, dll).\n\n"
        "Tampilkan hasil dalam format teks berikut:\n"
        "Deskripsi: <deskripsi menu/barang utama>\n"
        "Jumlah: <total yang dibayar>\n"
        "Kategori: <kategori barang/jasa>\n"
        "Tanggal: <tanggal transaksi>\n\n"
        "Setiap transaksi harus ditampilkan lengkap dengan deskripsi, jumlah, kategori, dan tanggal.\n"
        "Pisahkan setiap transaksi dengan satu baris kosong."
    )
    response = vision_model.generate_content([prompt, image])

    # Print the raw response for debugging
    # print(f"Response from Gemini model: {response.text}")

    try:
        # Check if the response is not empty and does not contain only whitespace
        if not response.text.strip():
            raise ValueError("The response from Gemini model is empty or contains only whitespace.")

        # The response will now be plain text, so just send it as-is
        transactions = response.text.strip().split("\n\n")  # Split by blank lines to separate each transaction

        # Format the response
        formatted_response = "\n\n".join(transactions)

        # Send the formatted response back to the user in plain text
        bot.reply_to(message, f"Hasil dari gambar:\n{formatted_response}")
        
        # Regex patterns for extracting the relevant data
        deskripsi_pattern = r"Deskripsi:\s?(.+)"
        jumlah_pattern = r"Jumlah:\s?Rp([0-9]{1,3}(?:[.,][0-9]{3})*(?:\.\d+)?)"
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
        
        # Extract and normalize the date
        if tanggal_match:
            tanggal_str = tanggal_match.group(1).strip()
            tanggal_normalized = normalize_date(tanggal_str)  # Normalize the date format
        else:
            # If no date is found, use the current date
            tanggal_normalized = normalize_date()

        # Save the transaction data (send only total to sheet)
        simpan_transaksi({"tanggal": tanggal_normalized, "deskripsi": deskripsi, "jumlah": jumlah, "kategori": kategori, "sumber": "gambar"})

    except json.JSONDecodeError as e:
        bot.reply_to(message, f"Error saat memproses gambar: JSON Decode Error: {e}")
    except ValueError as e:
        bot.reply_to(message, f"Error saat memproses gambar: {e}")
    except Exception as e:
        bot.reply_to(message, f"Error saat memproses gambar: {e}")

bot.infinity_polling()
