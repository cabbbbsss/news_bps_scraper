# 📰 News Scraper - BPS Provinsi Gorontalo

Aplikasi komprehensif untuk pengumpulan, analisis, dan klasifikasi berita dari sumber-sumber Gorontalo menggunakan Streamlit. Mendukung scraping web, ekstraksi PDF dengan AI, dan klasifikasi BPS otomatis.

## ✨ Fitur Utama

### 🔍 Web Scraping
- **8 Media Gorontalo**: GOSULUT.ID, Gorontalo Post, Habari.id, Rakyat Gorontalo, GoPOS.id, Antara News, Berita Pemda Gorontalo, CoolTurnesia
- **Database Integration**: Pencarian artikel dari database MySQL
- **Filter Canggih**: Tanggal, keyword, sumber berita

### 📄 PDF Processing
- **AI-Powered Extraction**: Ekstraksi artikel dari PDF koran menggunakan Azure OpenAI
- **Multi-page Support**: Deteksi artikel yang bersambung antar halaman
- **BPS Auto-classification**: Klasifikasi kategori BPS otomatis untuk setiap artikel
- **Source Detection**: Identifikasi sumber koran dari header PDF

### 📊 Analytics & Visualization
- **BPS Category Analysis**: Distribusi artikel berdasarkan kategori BPS (A1, B, C1, dll.)
- **Interactive Charts**: Visualisasi data dengan Altair
- **File Summary**: Ringkasan per-file PDF dengan statistik lengkap
- **Export Capabilities**: Download dalam format CSV

### 🔧 Advanced Features
- **BPS Classification**: Otomatis klasifikasi artikel ke kategori BPS KBLI
- **Duplicate Handling**: Sistem pencegahan duplikasi artikel
- **Responsive UI**: Interface yang adaptif untuk desktop dan mobile

## 🚀 Instalasi & Setup

### 1. Clone Repository
```bash
git clone <repository-url>
cd news_scraper_bps_modification
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Setup Environment Variables
**Direkomendasikan**: Gunakan environment variables untuk konfigurasi aman:

```bash
# Database Configuration
export DB_HOST="your_mysql_host"
export DB_USER="your_username"
export DB_PASSWORD="your_secure_password"
export DB_NAME="news_database"

# Azure OpenAI (untuk PDF processing)
export AZURE_OPENAI_ENDPOINT="https://your-endpoint.openai.azure.com/"
export AZURE_OPENAI_API_KEY="your_api_key"
export AZURE_OPENAI_API_VERSION="2024-12-01-preview"
export AZURE_OPENAI_DEPLOYMENT_NAME="gpt-4o"
```

### 4. Setup Database Schema
Jalankan scraper untuk auto-create database dan tabel:
```bash
python scraper.py
```

Atau setup manual:
```sql
-- Database akan otomatis dibuat saat pertama kali menjalankan scraper
-- Tabel news_articles akan dibuat dengan kolom BPS otomatis
```

### 5. Jalankan Aplikasi
```bash
streamlit run app_streamlit.py
```

## 📋 Dependencies

### Core Dependencies
- **streamlit**: Web framework dan UI
- **pandas**: Data manipulation dan analysis
- **pymysql**: MySQL database connector
- **altair**: Data visualization

### Web Scraping Dependencies
- **requests**: HTTP client untuk scraping
- **beautifulsoup4**: HTML parsing

### PDF Processing Dependencies
- **langchain**: AI-powered text processing framework
- **langchain-community**: Community integrations
- **langchain-openai**: Azure OpenAI integration
- **pydantic**: Data validation dan models
- **PyMuPDF**: PDF text extraction
- **python-dotenv**: Environment variables

## 🔧 Konfigurasi

### Database Schema
Aplikasi menggunakan MySQL dengan tabel `news_articles`:

```sql
CREATE TABLE news_articles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    date DATE,
    title TEXT,
    contents LONGTEXT,
    reporter VARCHAR(255),
    sources VARCHAR(255),
    links TEXT,
    impact TEXT,
    sector VARCHAR(255),
    sentiment VARCHAR(50),
    kategori_bps VARCHAR(10),        -- Kategori BPS (A1, B, C1, dll.)
    kategori_bps_detail TEXT,        -- Deskripsi lengkap kategori BPS
    UNIQUE KEY unique_title (title(255))
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

**Kolom BPS akan ditambahkan otomatis** saat pertama kali menjalankan scraper.

### Environment Variables
```bash
# Required
DB_HOST=your_mysql_server
DB_USER=your_username
DB_PASSWORD=your_password
DB_NAME=news_database

# Optional (untuk PDF processing)
AZURE_OPENAI_ENDPOINT=https://your-endpoint.openai.azure.com/
AZURE_OPENAI_API_KEY=your_api_key
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
```

## 🎯 Cara Penggunaan

### Mode Web Scraping
1. **Cek Status Database**: Lihat status koneksi di header aplikasi
2. **Jika Database Online**: Pilih filter tanggal/keyword/sumber, klik "Search Articles"
3. **Filter BPS**: Gunakan dropdown untuk filter berdasarkan kategori BPS

### Mode PDF Processing
1. **Upload Files**: Upload satu atau multiple file PDF koran
2. **AI Extraction**: Sistem akan mengekstrak artikel menggunakan Azure OpenAI
3. **BPS Classification**: Artikel otomatis diklasifikasi ke kategori BPS
4. **Review Results**: Lihat summary per-file dan artikel yang diekstrak
5. **Export Data**: Download hasil dalam format CSV

### Fitur Analytics
- **BPS Category Distribution**: Lihat distribusi artikel per kategori BPS
- **File Summaries**: Ringkasan lengkap untuk setiap file PDF
- **Interactive Charts**: Visualisasi data dengan filter dinamis
- **Article Details**: Lihat konten lengkap dan klasifikasi BPS

## ⚠️ Catatan Penting

- **Dual Mode**: Aplikasi mendukung web scraping dan PDF extraction
- **BPS Classification**: Semua artikel otomatis diklasifikasi ke kategori BPS
- **Security**: Gunakan environment variables untuk konfigurasi sensitif
- **Azure OpenAI**: Diperlukan untuk fitur PDF extraction dengan AI

## 🛠️ Troubleshooting

### Database Issues
```bash
# Test koneksi database
python test_mysql_connection.py

# Setup ulang schema database
python scraper.py  # Akan membuat tabel dan kolom BPS otomatis
```

### PDF Processing Issues
```bash
# Install dependencies PDF
pip install langchain langchain-community langchain-text-splitters langchain-openai pydantic PyMuPDF python-dotenv

# Setup environment variables Azure OpenAI
export AZURE_OPENAI_ENDPOINT="https://your-endpoint.openai.azure.com/"
export AZURE_OPENAI_API_KEY="your_api_key"
```

### Scraping Issues
```bash
# Test koneksi ke media
python -c "import requests; print(requests.get('https://gosulut.id').status_code)"

# Jalankan scraper manual
python scraper.py
```

### Common Errors
- **Database connection failed**: Periksa credentials dan network connectivity
- **PDF extraction disabled**: Install dependencies dan setup Azure OpenAI
- **Module not found**: Install ulang dari requirements.txt
- **Scraping failed**: Periksa koneksi internet dan struktur website

## 📊 Struktur Project

```
news_scraper_bps_modification/
├── app_streamlit.py                 # Main Streamlit application
├── scraper.py                       # Main scraping orchestrator
├── langchain_extract.py             # AI-powered PDF extraction
├── requirements.txt                 # Python dependencies
├── config.ini.example              # Configuration template
├── README.md                       # Documentation
├── category.txt                    # Scraper URL configurations
├── runtime.txt                     # Scraping schedule
├── clean_dup.py                    # Database cleanup utility
├── test_mysql_connection.py        # Database connection test
├── scraper_*.py                    # Individual media scrapers
├── __pycache__/                    # Python cache (auto-generated)
└── .venv/                          # Virtual environment (optional)
```

## 🤝 Contributing

1. Fork repository
2. Create feature branch
3. Commit changes
4. Push to branch
5. Create Pull Request

## 📄 License

This project is licensed under the MIT License.

---

**Badan Pusat Statistik Provinsi Gorontalo** 🏛️