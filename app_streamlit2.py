import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError
import pandas as pd
from datetime import datetime, timedelta
from urllib.parse import urlparse
from Sastrawi.Stemmer.StemmerFactory import StemmerFactory
import re
import configparser
from pathlib import Path
import tempfile
import os
import altair as alt
import threading
import time

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional

# BPS Category Mapping (KBLI - Klasifikasi Baku Lapangan Usaha Indonesia)
BPS_CATEGORIES = {
    'A1': 'Pertanian (Tanaman Pangan, Hortikultura, Perkebunan), Peternakan, Perburuan dan Jasa Pertanian',
    'A2': 'Kehutanan dan Penebangan Kayu',
    'A3': 'Perikanan',
    'B': 'Pertambangan dan Penggalian',
    'C1': 'Industri Makanan dan Minuman',
    'C2': 'Industri Pengolahan',
    'C3': 'Industri Tekstil dan Pakaian Jadi',
    'C4': 'Industri Elektronika',
    'C5': 'Industri Kertas/barang dari Kertas',
    'D': 'Pengadaan Listrik, Gas',
    'E': 'Pengadaan Air',
    'F': 'Konstruksi',
    'G1': 'PERDAGANGAN, REPARASI DAN PERAWATAN MOBIL DAN SEPEDA MOTOR',
    'G2': 'PERDAGANGAN ECERAN BERBAGAI MACAM BARANG DI TOKO, SUPERMARKET/MINIMARKET',
    'G3': 'PERDAGANGAN ECERAN KAKI LIMA DAN LOS PASAR',
    'H1': 'Angkutan Darat',
    'H2': 'Angkutan Laut',
    'H3': 'Angkutan Udara',
    'I1': 'Akomodasi Hotel dan Pondok Wisata',
    'I2': 'Penyediaan Makanan dan Minuman (Kedai, Restoran, dsb)',
    'J': 'Informasi dan Komunikasi',
    'K': 'Jasa Keuangan',
    'L': 'Real Estate',
    'MN': 'Jasa Perusahaan',
    'O': 'Administrasi Pemerintahan, Pertahanan dan Jaminan Sosial Wajib',
    'P': 'Jasa Pendidikan',
    'Q': 'Jasa Kesehatan dan Kegiatan Sosial',
    'RSTU': 'Jasa lainnya',
    'UMUM': 'UMUM'
}

# Initialize session state IMMEDIATELY - before any usage
if 'scraper_mode' not in st.session_state:
    st.session_state.scraper_mode = "Web Scraper"  # Default mode
if 'last_rendered_mode' not in st.session_state:
    st.session_state.last_rendered_mode = st.session_state.scraper_mode
if 'query_results' not in st.session_state:
    st.session_state.query_results = []
if 'filtered_df' not in st.session_state:
    st.session_state.filtered_df = None
if 'last_query' not in st.session_state:
    st.session_state.last_query = None
if 'pdf_articles' not in st.session_state:
    st.session_state.pdf_articles = []
if 'pdf_filtered_df' not in st.session_state:
    st.session_state.pdf_filtered_df = None
if 'pdf_extraction_status' not in st.session_state:
    st.session_state.pdf_extraction_status = "idle"
if 'onboarding_completed' not in st.session_state:
    st.session_state.onboarding_completed = False
if 'mobile_view' not in st.session_state:
    st.session_state.mobile_view = False
if 'db_connection_status' not in st.session_state:
    st.session_state.db_connection_status = "checking..."
if 'db_connection_last_check' not in st.session_state:
    st.session_state.db_connection_last_check = None
if 'db_status_placeholder' not in st.session_state:
    st.session_state.db_status_placeholder = None
if 'fallback_articles' not in st.session_state:
    st.session_state.fallback_articles = []
if 'fallback_media' not in st.session_state:
    st.session_state.fallback_media = None
if 'fallback_filters' not in st.session_state:
    st.session_state.fallback_filters = {}

@st.cache_data(ttl=60)
def check_db_connection():
    """Check database connection status."""
    try:
        conn = get_mysql_conn()
        if conn:
            conn.close()
            return "Connected"
        return "Disconnected"
    except Exception as e:
        return "Error"


def update_db_status():
    now = time.time()
    last_check = st.session_state.get('db_connection_last_check')
    if last_check is None or now - last_check > 30:
        st.session_state.db_connection_status = check_db_connection()
        st.session_state.db_connection_last_check = now

def show_db_status():
    update_db_status()
    status = st.session_state.db_connection_status
    
    if status == "Connected":
        st.markdown('<p class="status-connected">🟢 Connected</p>', unsafe_allow_html=True)
    elif status == "Disconnected":
        st.markdown('<p class="status-error">🔴 Disconnected</p>', unsafe_allow_html=True)
    elif status == "Error":
        st.markdown('<p class="status-error">🔴 Error</p>', unsafe_allow_html=True)
    else:
        st.markdown('<p class="status-error">⌛ Checking...</p>', unsafe_allow_html=True)

@st.cache_data
def classify_bps_category(content_text, extracted_category=None):
    """
    Enhanced BPS category classification function
    Uses content analysis with expanded keyword patterns
    """
    if not content_text and not extracted_category:
        return 'UMUM'

    # First validate if extracted_category is already a valid BPS code
    if extracted_category and validate_bps_category(extracted_category) != 'UMUM':
        return validate_bps_category(extracted_category)

    # Combine content and extracted category for analysis
    analysis_text = ""
    if content_text:
        analysis_text += str(content_text).lower() + " "
    if extracted_category:
        analysis_text += str(extracted_category).lower()

    # Enhanced BPS category classification with expanded keywords
    # A1: Pertanian, Tanaman Pangan, Hortikultura, Perkebunan, Peternakan, Perburuan, Jasa Pertanian
    if any(word in analysis_text for word in [
        'pertanian', 'tanaman', 'padi', 'jagung', 'beras', 'palawija', 'hortikultura',
        'perkebunan', 'sawit', 'kelapa', 'kakao', 'kopi', 'teh', 'cengkeh', 'petani',
        'panen', 'pupuk', 'bibit', 'kehutanan', 'kayu', 'hutan', 'kehutanan',
        'peternakan', 'ternak', 'sapi', 'ayam', 'kambing', 'perburuan', 'buruan'
    ]):
        return 'A1'

    # A2: Kehutanan dan Penebangan Kayu
    elif any(word in analysis_text for word in [
        'kehutanan', 'penebangan', 'kayu', 'hutan', 'rimba', 'hutan lindung',
        'pengelolaan hutan', 'kayu lapis', 'kayu gergajian'
    ]):
        return 'A2'

    # A3: Perikanan
    elif any(word in analysis_text for word in [
        'perikanan', 'ikan', 'nelayan', 'laut', 'tambak', 'kolam', 'budidaya ikan',
        'perikanan tangkap', 'udang', 'kepiting', 'cumi', 'gurita'
    ]):
        return 'A3'

    # B: Pertambangan dan Penggalian
    elif any(word in analysis_text for word in [
        'tambang', 'mining', 'galian', 'minerba', 'emas', 'tembaga', 'nikel',
        'batubara', 'minyak', 'gas', 'panas bumi', 'pertambangan', 'miner'
    ]):
        return 'B'

    # C1: Industri Makanan dan Minuman
    elif any(word in analysis_text for word in [
        'makanan', 'minuman', 'kuliner', 'mamin', 'industri makanan', 'pengolahan makanan',
        'roti', 'kue', 'susu', 'keju', 'yogurt', 'minuman ringan', 'jus', 'teh botol'
    ]):
        return 'C1'

    # C2: Industri Pengolahan
    elif any(word in analysis_text for word in [
        'industri', 'pengolahan', 'manufaktur', 'pabrik', 'produksi', 'industri kimia',
        'industri logam', 'industri plastik', 'industri karet', 'industri semen'
    ]):
        return 'C2'

    # C3: Industri Tekstil dan Pakaian Jadi
    elif any(word in analysis_text for word in [
        'tekstil', 'pakaian', 'konveksi', 'garmen', 'baju', 'kaos', 'celana',
        'kain', 'benang', 'spinning', 'weaving', 'garment'
    ]):
        return 'C3'

    # C4: Industri Elektronika
    elif any(word in analysis_text for word in [
        'elektronik', 'teknologi', 'gadget', 'komputer', 'handphone', 'hp', 'smartphone',
        'laptop', 'elektronika', 'semikonduktor', 'chip', 'elektronik konsumen'
    ]):
        return 'C4'

    # C5: Industri Kertas/barang dari Kertas
    elif any(word in analysis_text for word in [
        'kertas', 'printing', 'media', 'publikasi', 'koran', 'majalah', 'buku',
        'karton', 'tisu', 'printing press', 'percetakan'
    ]):
        return 'C5'

    # D: Pengadaan Listrik, Gas
    elif any(word in analysis_text for word in [
        'listrik', 'gas', 'energi', 'pln', 'kelistrikan', 'pembangkit', 'transmisi',
        'distribusi', 'tenaga listrik', 'gas alam', 'lng'
    ]):
        return 'D'

    # E: Pengadaan Air
    elif any(word in analysis_text for word in [
        'air', 'sanitasi', 'pdam', 'bersih', 'pengolahan air', 'air minum',
        'sanitasi lingkungan', 'drainase', 'pengelolaan air'
    ]):
        return 'E'

    # F: Konstruksi
    elif any(word in analysis_text for word in [
        'konstruksi', 'bangunan', 'jalan', 'infrastruktur', 'jembatan', 'gedung',
        'proyek konstruksi', 'developer', 'kontraktor', 'sipil'
    ]):
        return 'F'

    # G1: Perdagangan, Reparasi dan Perawatan Mobil dan Sepeda Motor
    elif any(word in analysis_text for word in [
        'otomotif', 'mobil', 'motor', 'sepeda motor', 'dealer', 'showroom',
        'bengkel', 'reparasi', 'service', 'sparepart', 'aksesoris kendaraan'
    ]):
        return 'G1'

    # G2: Perdagangan Eceran Berbagai Macam Barang di Toko, Supermarket/Minimarket
    elif any(word in analysis_text for word in [
        'toko', 'supermarket', 'minimarket', 'retail', 'eceran', 'department store',
        'mall', 'pusat perbelanjaan', 'ritel modern'
    ]):
        return 'G2'

    # G3: Perdagangan Eceran Kaki Lima dan Los Pasar
    elif any(word in analysis_text for word in [
        'los pasar', 'kaki lima', 'pedagang', 'pasar tradisional', 'warung',
        'pedagang keliling', 'pasar rakyat', 'retail tradisional'
    ]):
        return 'G3'

    # H1: Angkutan Darat
    elif any(word in analysis_text for word in [
        'darat', 'bus', 'angkot', 'transportasi', 'angkutan', 'logistik', 'trucking',
        'ekspedisi', 'kurir', 'delivery', 'ojek', 'taxi', 'angkot'
    ]):
        return 'H1'

    # H2: Angkutan Laut
    elif any(word in analysis_text for word in [
        'laut', 'kapal', 'pelabuhan', 'maritim', 'shipping', 'kontainer',
        'barang laut', 'perkapalan', 'pelayaran', 'marina'
    ]):
        return 'H2'
    # H3: Angkutan Udara
    elif any(word in analysis_text for word in [
        'udara', 'pesawat', 'bandara', 'aviasi', 'penerbangan', 'airport',
        'maskapai', 'airline', 'cargo udara', 'angkutan udara'
    ]):
        return 'H3'

    # I1: Akomodasi Hotel dan Pondok Wisata
    elif any(word in analysis_text for word in [
        'hotel', 'wisata', 'akomodasi', 'hospitality', 'penginapan', 'villa',
        'resort', 'homestay', 'pondok wisata', 'pariwisata'
    ]):
        return 'I1'

    # I2: Penyediaan Makanan dan Minuman (Kedai, Restoran, dsb)
    elif any(word in analysis_text for word in [
        'restoran', 'kedai', 'makan', 'fnb', 'food and beverage', 'kafe',
        'warung makan', 'rumah makan', 'food court', 'kuliner'
    ]):
        return 'I2'

    # J: Informasi dan Komunikasi
    elif any(word in analysis_text for word in [
        'komunikasi', 'internet', 'telekomunikasi', 'telekom', 'telepon',
        'seluler', 'provider', 'operator', 'broadband', 'fiber optik'
    ]):
        return 'J'

    # K: Jasa Keuangan
    elif any(word in analysis_text for word in [
        'keuangan', 'bank', 'asuransi', 'finance', 'perbankan', 'leasing',
        'kredit', 'pinjaman', 'tabungan', 'investasi', 'sekuritas'
    ]):
        return 'K'

    # L: Real Estate
    elif any(word in analysis_text for word in [
        'real estate', 'properti', 'perumahan', 'developer', 'real estat',
        'property', 'apartemen', 'perumahan', 'landed house'
    ]):
        return 'L'

    # MN: Jasa Perusahaan
    elif any(word in analysis_text for word in [
        'perusahaan', 'bisnis', 'jasa', 'korporasi', 'konsultan', 'akuntan',
        'legal', 'hukum', 'notaris', 'management consultant'
    ]):
        return 'MN'

    # O: Administrasi Pemerintahan, Pertahanan dan Jaminan Sosial Wajib
    elif any(word in analysis_text for word in [
        'pemerintah', 'pemda', 'bupati', 'dinas', 'kementerian', 'pemerintah daerah',
        'administrasi', 'birokrasi', 'pelayanan publik', 'pemerintahan'
    ]):
        return 'O'

    # P: Jasa Pendidikan
    elif any(word in analysis_text for word in [
        'pendidikan', 'sekolah', 'siswa', 'guru', 'universitas', 'kampus',
        'pendidikan tinggi', 'sd', 'smp', 'sma', 'smk', 'kursus', 'pelatihan'
    ]):
        return 'P'

    # Q: Jasa Kesehatan dan Kegiatan Sosial
    elif any(word in analysis_text for word in [
        'kesehatan', 'rumah sakit', 'dokter', 'medis', 'klinik', 'puskesmas',
        'bidan', 'perawat', 'farmasi', 'apotek', 'rs', 'hospital'
    ]):
        return 'Q'

    # RSTU: Jasa lainnya
    elif any(word in analysis_text for word in [
        'jasa', 'servis', 'bisnis', 'usaha', 'konsultasi', 'perdagangan',
        'entertainment', 'hiburan', 'olahraga', 'seni', 'budaya'
    ]):
        return 'RSTU'

    # Default fallback
    else:
        return 'UMUM'


# Backward compatibility
@st.cache_data
def map_to_bps_category(extracted_category):
    """Enhanced BPS category mapping with validation"""
    # First validate the extracted category
    validated_cat = validate_bps_category(extracted_category)

    # If it's a valid BPS code, return it directly
    if validated_cat != 'UMUM':
        return validated_cat

    # Otherwise, try content-based classification
    return classify_bps_category("", extracted_category)

try:
    import pymysql
    PYMYSQL_AVAILABLE = True
except ImportError:
    PYMYSQL_AVAILABLE = False
    st.error("❌ pymysql package not found. Please install with: pip install pymysql")
    st.stop()

# Azure OpenAI config placeholder (will be updated after reading config.ini)
azure_config = {
    "endpoint": "",
    "api_key": "",
    "api_version": "2024-02-01",
    "deployment_name": "gpt-4"
}

# Import langchain extract functionality
try:
    from langchain_extract import NewspaperExtractor
    LANGCHAIN_AVAILABLE = True

except ImportError as e:
    LANGCHAIN_AVAILABLE = False
    AZURE_OPENAI_AVAILABLE = False
    missing_modules = []
    error_msg = str(e)

    # Check for common missing modules
    if "dotenv" in error_msg:
        missing_modules.append("python-dotenv")
    if "langchain_community" in error_msg:
        missing_modules.append("langchain-community")
    if "langchain_text_splitters" in error_msg:
        missing_modules.append("langchain-text-splitters")
    if "langchain_core" in error_msg:
        missing_modules.append("langchain-core")
    if "langchain_openai" in error_msg:
        missing_modules.append("langchain-openai")
    if "pydantic" in error_msg:
        missing_modules.append("pydantic")
    if "PyMuPDF" in error_msg or "fitz" in error_msg:
        missing_modules.append("PyMuPDF")

    if missing_modules:
        st.warning(f"⚠️ PDF extraction disabled. Missing packages: {', '.join(missing_modules)}")
        st.info("**Install required packages:**")
        st.code("pip install langchain langchain-community langchain-text-splitters langchain-openai pydantic PyMuPDF python-dotenv", language="bash")
        st.info("**Note:** PDF extraction requires Azure OpenAI API access and proper configuration in config.ini")
    else:
        st.warning(f"⚠️ PDF extraction disabled. Import error: {error_msg}")

except Exception as e:
    LANGCHAIN_AVAILABLE = False
    AZURE_OPENAI_AVAILABLE = False
    st.warning(f"⚠️ PDF extraction disabled. Error: {str(e)}")

# Azure OpenAI availability will be checked after azure_config is updated below
    # Note: AI features will use fallback method if Azure OpenAI is not configured
    # This is silent - no need to show info message as fallback works fine

# Note: csv_utils not available, using simplified approach

# ---------- LOAD CONFIG ----------
def get_secret(key, fallback=''):
    # 1. Streamlit Cloud
    try:
        if key in st.secrets:
            return st.secrets[key]
    except StreamlitSecretNotFoundError:
        pass
    
    # 2. .env
    val = os.getenv(key)
    if val:
        return val
    
    # 3. config.ini (dev)
    try:
        if config.has_option("DEFAULT", key):
            return config.get("DEFAULT", key)
    except:
        pass

    return fallback


BASE_DIR = Path(__file__).parent
config_path = BASE_DIR / "config.ini"

# Load config.ini if it exists (optional for deployment)
config = configparser.ConfigParser()
if config_path.exists():
    config.read(config_path)

# ---------- HELPER FUNCTIONS ----------
VALID_BPS_CODES = ['A1', 'A2', 'A3', 'B', 'C1', 'C2', 'C3', 'C4', 'C5',
                   'D', 'E', 'F', 'G1', 'G2', 'G3', 'H1', 'H2', 'H3',
                   'I1', 'I2', 'J', 'K', 'L', 'MN', 'O', 'P', 'Q', 'RSTU', 'UMUM']

def validate_bps_category(category):
    """Validate and normalize BPS category codes"""
    if not category:
        return 'UMUM'

    # Convert to uppercase and check if valid
    cat_upper = str(category).upper().strip()

    # Handle common variations
    if cat_upper in VALID_BPS_CODES:
        return cat_upper

    # Handle cases where model adds extra text (e.g., "A1 - Pertanian")
    for code in VALID_BPS_CODES:
        if cat_upper.startswith(code) or cat_upper.endswith(code):
            return code

    # If invalid, return UMUM
    return 'UMUM'

def halaman_to_numeric(halaman_val):
    """Convert halaman value to numeric (handle both int and string formats)"""
    try:
        if isinstance(halaman_val, str):
            # Handle formats like "1,3" or "1-2"
            if ',' in halaman_val:
                pages = [int(p.strip()) for p in halaman_val.split(',')]
                return sum(pages) / len(pages)  # Average of pages
            elif '-' in halaman_val:
                start, end = [int(p.strip()) for p in halaman_val.split('-')]
                return (start + end) / 2  # Midpoint
            else:
                return int(halaman_val)
        else:
            return int(halaman_val)
    except (ValueError, AttributeError):
        return 1  # Default fallback

# Database configuration (environment variables first, config.ini as fallback)
db_config = {
    "host": get_secret("DB_HOST", "localhost"),
    "user": get_secret("DB_USER", "root"),
    "password": get_secret("DB_PASSWORD", ""),
    "database": get_secret("DB_NAME", "news_database"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

# Azure OpenAI configuration for AI-powered features
# Environment variables first, config.ini as fallback for development
azure_config.update({
    "endpoint": get_secret("AZURE_OPENAI_ENDPOINT", ""),
    "api_key": get_secret("AZURE_OPENAI_API_KEY", ""),
    "api_version": get_secret("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
    "deployment_name": get_secret("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")
})

# Check Azure OpenAI configuration after config is loaded
AZURE_OPENAI_AVAILABLE = bool(
    LANGCHAIN_AVAILABLE and
    azure_config["endpoint"] and
    azure_config["api_key"]
)

def show_connection_error(error_code, error_msg, host):
    """Show user-friendly connection error messages with solutions."""
    if error_code == 2003:  # Can't connect to MySQL server
        st.error("🔌 **Connection Failed**")
        with st.expander("🔍 **Troubleshooting Guide**", expanded=True):
            st.write("**What happened:** Cannot reach the MySQL server")
            st.write("**Possible causes:**")
            st.markdown("- 🖥️ MySQL server is not running")
            st.markdown("- 🌐 Network connectivity issues")
            st.markdown("- 🛡️ Firewall blocking the connection")
            st.markdown("- 🔌 Wrong server address or port")

            st.write("**Solutions:**")
            st.code(f"ping {host}", language="bash")
            st.code("netstat -an | find \"3306\"", language="bash")
            st.info("💡 **Check:** Ensure MySQL service is running and port 3306 is open")

    elif error_code == 1045:  # Access denied
        st.error("🔐 **Access Denied**")
        with st.expander("🔑 **Authentication Issues**", expanded=True):
            st.write("**What happened:** Invalid username or password")
            st.write("**Check these settings in `config.ini`:**")
            st.code("""
DB_HOST = your_mysql_host
DB_USER = your_username
DB_PASSWORD = your_password
DB_NAME = your_database_name
            """, language="ini")
            st.info("💡 **Tip:** Ensure the MySQL user has access to the specified database")

    elif error_code == 1049:  # Unknown database
        st.error("📁 **Database Not Found**")
        with st.expander("🗄️ **Database Issues**", expanded=True):
            st.write("**What happened:** The specified database doesn't exist")
            st.write("**Check in `config.ini`:**")
            st.code("DB_NAME = news_database", language="ini")
            st.info("💡 **Tip:** Create the database first or check the database name")

    else:
        st.error(f"⚠️ **Connection Error ({error_code})**")
        with st.expander("🐛 **Technical Details**", expanded=False):
            st.code(f"Error: {error_msg}")
            st.info("💡 **Tip:** Check MySQL logs for more detailed error information")

def get_mysql_conn():
    """Get MySQL database connection with enhanced error handling."""
    try:
        # Add connection timeout and retry logic
        db_config_with_timeout = db_config.copy()
        db_config_with_timeout.update({
            'connect_timeout': 10,  # 10 second timeout
            'read_timeout': 10,
            'write_timeout': 10,
        })

        conn = pymysql.connect(**db_config_with_timeout)

        # Test the connection
        cursor = conn.cursor()
        cursor.execute("SELECT 1 as test")
        cursor.fetchone()
        cursor.close()

        return conn

    except pymysql.err.OperationalError as e:
        error_code = e.args[0] if e.args else None
        host = db_config.get('host', 'localhost')
        show_connection_error(error_code, str(e), host)

        st.warning("🔄 **Continuing with limited functionality** - Some features may not be available")
        return None

    except Exception as e:
        st.error("🚨 **Unexpected Error**")
        with st.expander("🐛 **Error Details**", expanded=False):
            st.code(f"Error: {str(e)}")
            st.info("💡 **Tip:** This might be a configuration or network issue")
        return None

st.set_page_config(
    page_title="News Scraper - BPS Gorontalo",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Session state is now initialized at the very beginning of the file

# Custom CSS for responsive design
st.markdown("""
<style>
/* Responsive design improvements */
@media (max-width: 768px) {
    .stMetric {
        margin-bottom: 1rem;
    }
    .stColumns > div {
        margin-bottom: 1rem;
    }
}

/* Better spacing for mobile */
@media (max-width: 640px) {
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
        font-size: 1.2em !important;
    }
    .stButton button {
        width: 100% !important;
    }
}

/* Improve metric cards */
.stMetric {
    background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
    padding: 1rem;
    border-radius: 10px;
    border: 1px solid #e1e8ed;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

/* Better table styling */
.stDataFrame {
    border-radius: 10px;
    overflow: hidden;
}

/* Improve button styling */
.stButton button {
    border-radius: 8px;
    font-weight: 500;
    transition: all 0.3s ease;
}

.stButton button:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 8px rgba(0,0,0,0.2);
}

/* Better expander styling */
.stExpander {
    border-radius: 8px;
    border: 1px solid #e1e8ed;
    margin-bottom: 0.5rem;
}

/* Status indicators */
.status-connected {
    color: #28a745;
    font-weight: bold;
}

.status-error {
    color: #dc3545;
    font-weight: bold;
}

.status-warning {
    color: #ffc107;
    font-weight: bold;
}

/* Progress bar styling */
.stProgress > div > div > div {
    background: linear-gradient(90deg, #28a745, #20c997);
}

/* Sidebar improvements */
.sidebar .stExpander {
    margin-bottom: 0.5rem;
}

/* Header styling */
.header-section {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    padding: 1.5rem;
    border-radius: 12px;
    color: white;
    margin-bottom: 1.5rem;
}

/* Card styling for metrics */
.metric-card {
    background: white;
    padding: 1.5rem;
    border-radius: 12px;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    border: 1px solid #e1e8ed;
    transition: transform 0.3s ease;
}

.metric-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 12px rgba(0, 0, 0, 0.15);
}
</style>
""", unsafe_allow_html=True)

# Enhanced Header Design with Responsive Layout
st.markdown('<div class="header-section">', unsafe_allow_html=True)

# Responsive header layout
if st.session_state.get('mobile_view', False):
    # Mobile layout - stacked
    st.title("📰 News Scraper")
    st.subheader("BPS Provinsi Gorontalo")
    st.caption("Sistem Analisis Berita untuk Kebutuhan Statistik")

    col1, col2 = st.columns(2)
    with col1:
        # Database Connection Status - Display cached status, update in background if needed
        show_db_status()

    with col2:
        # Current Mode Indicator
        mode_icon = "🔍" if st.session_state.scraper_mode == "Web Scraper" else "📄"
        mode_label = "Web Mode" if st.session_state.scraper_mode == "Web Scraper" else "PDF Mode"
        st.metric(f"{mode_icon} {mode_label}", st.session_state.scraper_mode)

else:
    # Desktop layout - horizontal
    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        st.title("📰 News Scraper")
        st.subheader("BPS Provinsi Gorontalo")
        st.caption("Sistem Analisis Berita untuk Kebutuhan Statistik")

    with col2:
        # Database Connection Status - Display cached status (updated by mobile layout)
        show_db_status()

    with col3:
        # Current Mode Indicator
        mode_icon = "🔍" if st.session_state.scraper_mode == "Web Scraper" else "📄"
        mode_label = "Web Mode" if st.session_state.scraper_mode == "Web Scraper" else "PDF Mode"
        st.metric(
            f"{mode_icon} {mode_label}",
            st.session_state.scraper_mode,
            help=f"Currently using {st.session_state.scraper_mode} mode"
        )

st.markdown('</div>', unsafe_allow_html=True)

# Onboarding Flow for New Users
if not st.session_state.onboarding_completed:
    st.divider()

    with st.container():
        st.markdown("""
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 2rem; border-radius: 15px; margin-bottom: 2rem;">
            <h2 style="color: white; margin-bottom: 1rem;">🎉 Welcome to News Scraper BPS!</h2>
            <p style="font-size: 1.1em; margin-bottom: 1.5rem;">Your powerful tool for news analysis and data extraction</p>
        </div>
        """, unsafe_allow_html=True)

        # Feature highlights
        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("""
            ### 🔍 Web Scraper
            - Search articles from news database
            - Filter by date range and keywords
            - Advanced analytics and visualizations
            """)

        with col2:
            st.markdown("""
            ### 📄 PDF Scraper
            - Extract articles from newspaper PDFs
            - AI-powered content analysis
            - BPS category classification
            """)

        with col3:
            st.markdown("""
            ### 📊 Analytics
            - Real-time statistics
            - Interactive visualizations
            - Export capabilities
            """)

        st.divider()

        # Quick start guide
        st.subheader("🚀 Quick Start Guide")

        with st.expander("📋 Step-by-Step Setup", expanded=True):
            st.markdown("""
            **1. Configure Database** (in `config.ini`)
            ```ini
            DB_HOST = your_mysql_server
            DB_USER = your_username
            DB_PASSWORD = your_password
            DB_NAME = news_database
            ```

            **2. Set up Azure OpenAI** (for PDF processing)
            ```ini
            AZURE_OPENAI_ENDPOINT = your_endpoint
            AZURE_OPENAI_API_KEY = your_api_key
            ```

            **3. Choose Your Mode**
            - **Web Scraper**: Query existing articles
            - **PDF Scraper**: Extract from newspaper files

            **4. Start Analyzing!**
            - Use filters to find relevant articles
            - Export results for further analysis
            """)

        # Skip onboarding option
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            if st.button("🎯 Get Started!", type="primary", use_container_width=True):
                st.session_state.onboarding_completed = True
                st.rerun()

st.divider()

# Quick Stats Overview with Responsive Cards
# try:
#     db_stats = get_database_stats()
#     if db_stats["date_range"] != "No connection":
#         # Responsive layout - stack on mobile, horizontal on desktop
#         if st.session_state.get('mobile_view', False):
#             # Mobile: 2 columns, stacked rows
#             col1, col2 = st.columns(2)
#             with col1:
#                 st.markdown('<div class="metric-card">', unsafe_allow_html=True)
#                 st.metric("📊 Total Articles", f"{db_stats['total_articles']:,}")
#                 st.markdown('</div>', unsafe_allow_html=True)
#             with col2:
#                 st.markdown('<div class="metric-card">', unsafe_allow_html=True)
#                 st.metric("📅 Date Range", db_stats["date_range"])
#                 st.markdown('</div>', unsafe_allow_html=True)

#             col3, col4 = st.columns(2)
#             with col3:
#                 st.markdown('<div class="metric-card">', unsafe_allow_html=True)
#                 # Count only non-empty sources
#                 unique_sources = [s for s in db_stats["sources"].keys() if s and s.strip()]
#                 st.metric("📰 News Sources", len(unique_sources))
#                 st.markdown('</div>', unsafe_allow_html=True)
#             with col4:
#                 st.markdown('<div class="metric-card">', unsafe_allow_html=True)
#                 # Get latest date
#                 try:
#                     conn = get_mysql_conn()
#                     if conn:
#                         cursor = conn.cursor()
#                         cursor.execute("SELECT MAX(date) AS latest_date FROM news_articles")
#                         latest_row = cursor.fetchone() or {}
#                         latest_raw = latest_row.get("latest_date")
#                         if hasattr(latest_raw, "strftime"):
#                             latest_date = latest_raw.strftime("%Y-%m-%d")
#                         else:
#                             latest_date = str(latest_raw) if latest_raw else "N/A"
#                         cursor.close()
#                         conn.close()
#                     else:
#                         latest_date = "N/A"
#                 except:
#                     latest_date = "Error"
#                 st.metric("🕒 Last Updated", latest_date)
#                 st.markdown('</div>', unsafe_allow_html=True)
#         else:
#             # Desktop: 4 columns in a row
#             col1, col2, col3, col4 = st.columns(4)
#             with col1:
#                 st.markdown('<div class="metric-card">', unsafe_allow_html=True)
#                 st.metric("📊 Total Articles", f"{db_stats['total_articles']:,}")
#                 st.markdown('</div>', unsafe_allow_html=True)
#             with col2:
#                 st.markdown('<div class="metric-card">', unsafe_allow_html=True)
#                 st.metric("📅 Date Range", db_stats["date_range"])
#                 st.markdown('</div>', unsafe_allow_html=True)
#             with col3:
#                 st.markdown('<div class="metric-card">', unsafe_allow_html=True)
#                 # Count only non-empty sources
#                 unique_sources = [s for s in db_stats["sources"].keys() if s and s.strip()]
#                 st.metric("📰 News Sources", len(unique_sources))
#                 st.markdown('</div>', unsafe_allow_html=True)
#             with col4:
#                 st.markdown('<div class="metric-card">', unsafe_allow_html=True)
#                 # Get latest date
#                 try:
#                     conn = get_mysql_conn()
#                     if conn:
#                         cursor = conn.cursor()
#                         cursor.execute("SELECT MAX(date) AS latest_date FROM news_articles")
#                         latest_row = cursor.fetchone() or {}
#                         latest_raw = latest_row.get("latest_date")
#                         if hasattr(latest_raw, "strftime"):
#                             latest_date = latest_raw.strftime("%Y-%m-%d")
#                         else:
#                             latest_date = str(latest_raw) if latest_raw else "N/A"
#                         cursor.close()
#                         conn.close()
#                     else:
#                         latest_date = "N/A"
#                 except:
#                     latest_date = "Error"
#                 st.metric("🕒 Last Updated", latest_date)
#                 st.markdown('</div>', unsafe_allow_html=True)
# except:
#     st.info("📊 Database stats will load shortly...")

# st.divider()

# Initialize session state
if 'query_results' not in st.session_state:
    st.session_state.query_results = []
if 'filtered_df' not in st.session_state:
    st.session_state.filtered_df = None
if 'last_query' not in st.session_state:
    st.session_state.last_query = None

# PDF extraction session state
if 'pdf_articles' not in st.session_state:
    st.session_state.pdf_articles = []
if 'pdf_filtered_df' not in st.session_state:
    st.session_state.pdf_filtered_df = None
if 'pdf_extraction_status' not in st.session_state:
    st.session_state.pdf_extraction_status = "idle"

# Note: Session state is now initialized at the top of the file

# Check if there's active data (optimized calculation)
has_active_data = (
    (st.session_state.query_results and len(st.session_state.query_results) > 0) or
    (st.session_state.pdf_filtered_df is not None and not st.session_state.pdf_filtered_df.empty) or
    st.session_state.pdf_extraction_status == "processing"
)

# Show warning banner if there's active data
if has_active_data:
    mode_name = "Web Scraper" if st.session_state.query_results else "PDF Scraper"
    st.error(f"""
    🚨 **Mode Lock Active: {mode_name}**

    Anda sedang menggunakan data aktif. Peralihan mode dinonaktifkan untuk mencegah kehilangan data.
    Selesaikan penggunaan data saat ini sebelum berganti ke mode lain.
    """)

# Show different descriptions based on mode
if st.session_state.scraper_mode == "Web Scraper":
    st.markdown("🔍 **Web Scraper Mode**: Query and analyze articles from news websites stored in the database with advanced filtering.")
elif st.session_state.scraper_mode == "PDF Scraper":
    st.markdown("📄 **PDF Scraper Mode**: Extract and analyze articles from PDF newspapers.")

# Database connection helper
@st.cache_data(ttl=600, show_spinner=False)  # Cache for 10 minutes, no spinner
def get_database_stats():
    """Get basic statistics from the database."""
    conn = get_mysql_conn()
    if not conn:
        return {"total_articles": 0, "date_range": "No connection", "sources": {}}

    try:
        cursor = conn.cursor()

        # Get total articles count
        cursor.execute("SELECT COUNT(*) AS total_count FROM news_articles")
        total_row = cursor.fetchone() or {}
        total_count = total_row.get("total_count", 0)

        # Get date range
        cursor.execute("SELECT MIN(date) AS min_date, MAX(date) AS max_date FROM news_articles")
        date_row = cursor.fetchone() or {}
        date_min, date_max = date_row.get("min_date"), date_row.get("max_date")
        # Format dates to short string
        def _fmt_date(d):
            if d is None:
                return None
            return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
        date_min_fmt, date_max_fmt = _fmt_date(date_min), _fmt_date(date_max)

        # Get source counts (exclude NULL and empty strings)
        cursor.execute("SELECT sources, COUNT(*) AS cnt FROM news_articles WHERE sources IS NOT NULL AND sources != '' GROUP BY sources")
        source_rows = cursor.fetchall() or []
        source_counts = {row.get("sources", "unknown"): row.get("cnt", 0) for row in source_rows if row.get("sources")}

        cursor.close()
        conn.close()

        return {
            "total_articles": total_count,
            "date_range": f"{date_min_fmt} to {date_max_fmt}" if date_min_fmt else "No data",
            "sources": source_counts
        }
    except Exception as e:
        if conn:
            try:
                conn.close()
            except:
                pass
        return {"total_articles": 0, "date_range": f"Error: {str(e)}", "sources": {}}

# Database diagnostics moved to sidebar for better organization

# KBLI Category Reference
with st.expander("📋 Referensi Kode Kategori KBLI (BPS)", expanded=False):
    st.markdown("""
    **Klasifikasi Baku Lapangan Usaha Indonesia (KBLI)** yang digunakan dalam sistem:

    ### **A. PERTANIAN, KEHUTANAN DAN PERIKANAN**
    - **A1**: Pertanian (Tanaman Pangan, Hortikultura, Perkebunan), Peternakan, Perburuan dan Jasa Pertanian
    - **A2**: Kehutanan dan Penebangan Kayu
    - **A3**: Perikanan

    ### **B. PERTAMBANGAN DAN PENGGALIAN**
    - **B**: Pertambangan dan Penggalian

    ### **C. INDUSTRI PENGOLAHAN**
    - **C1**: Industri Makanan dan Minuman
    - **C2**: Industri Pengolahan
    - **C3**: Industri Tekstil dan Pakaian Jadi
    - **C4**: Industri Elektronika
    - **C5**: Industri Kertas/barang dari Kertas

    ### **D. PENGADAAN LISTRIK, GAS, UAP/AIR PANAS DAN UDARA DINGIN**
    - **D**: Pengadaan Listrik, Gas

    ### **E. PENGELOLAAN AIR, PENGELOLAAN AIR LIMBAH, PENGELOLAAN DAN DAUR ULANG SAMPAH**
    - **E**: Pengadaan Air

    ### **F. KONSTRUKSI**
    - **F**: Konstruksi

    ### **G. PERDAGANGAN BESAR DAN ECERAN; REPARASI DAN PERAWATAN MOBIL DAN SEPEDA MOTOR**
    - **G1**: PERDAGANGAN, REPARASI DAN PERAWATAN MOBIL DAN SEPEDA MOTOR
    - **G2**: PERDAGANGAN ECERAN BERBAGAI MACAM BARANG DI TOKO, SUPERMARKET/MINIMARKET
    - **G3**: PERDAGANGAN ECERAN KAKI LIMA DAN LOS PASAR

    ### **H. PENGANGKUTAN DAN PERGUDANGAN**
    - **H1**: Angkutan Darat
    - **H2**: Angkutan Laut
    - **H3**: Angkutan Udara

    ### **I. PENYEDIAAN AKOMODASI DAN PENYEDIAAN MAKANAN MINUMAN**
    - **I1**: Akomodasi Hotel dan Pondok Wisata
    - **I2**: Penyediaan Makanan dan Minuman (Kedai, Restoran, dsb)

    ### **J. INFORMASI DAN KOMUNIKASI**
    - **J**: Informasi dan Komunikasi

    ### **K. KEGIATAN KEUANGAN DAN ASURANSI**
    - **K**: Jasa Keuangan

    ### **L. REAL ESTATE**
    - **L**: Real Estate

    ### **M. KEGIATAN JASA LAINNYA**
    - **MN**: Jasa Perusahaan
    - **O**: Administrasi Pemerintahan, Pertahanan dan Jaminan Sosial Wajib
    - **P**: Jasa Pendidikan
    - **Q**: Jasa Kesehatan dan Kegiatan Sosial
    - **RSTU**: Jasa lainnya

    ### **UMUM**
    - **UMUM**: Kategori umum/tidak terklasifikasi
    """)

# Database overview - only show in Web Scraper mode
if st.session_state.scraper_mode == "Web Scraper":
    st.subheader("📊 Database Overview")

    # Allow manual refresh of cached stats
    if st.button("🔄 Refresh Database Stats", key="refresh_db_stats"):
        get_database_stats.clear()

    db_stats = get_database_stats()

    if db_stats["date_range"] == "No connection":
        # Database connection failed
        col1, col2 = st.columns(2)
        with col1:
            st.error("❌ **Database Connection Failed**")
            st.info(f"Cannot connect to MySQL server at {db_config.get('host', 'localhost')}")
        with col2:
            st.warning("🔄 **App running in offline mode**")
            st.info("Some features may not be available")
    else:
        # Database connection successful
        def kpi_card(title, value, icon=""):
            st.markdown(f"""
            <div style="
                padding:12px 16px;
                border-radius:12px;
                background-color:#f0f2f6;
                height:100%;
                display:flex;
                flex-direction:column;
                justify-content:center;                
            ">
                <div style="font-size:18px; color:#555;">{icon} {title}</div>
                <div style="font-size:26px; font-weight:600; margin-top:4px;">
                    {value}
                </div>
            </div>
            """, unsafe_allow_html=True)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            kpi_card("Total Articles", db_stats["total_articles"], "📰")
        with col2:
            st.markdown(f"""
            <div style="
                padding:12px 16px;
                border-radius:10px;
                background-color:#f0f2f6;
                height:100px;
                display:flex;
                flex-direction:column;
                justify-content:center;
            ">
                <div style="font-size:18px; color:#555;">
                    📅 Date Range
                </div>
                <div style="font-size:22px; font-weight:600; margin-top:6px;">
                    {db_stats["date_range"]}
                </div>
            </div>            
            """, unsafe_allow_html=True)
        with col3:
            # Count only non-empty sources
            unique_sources = [s for s in db_stats["sources"].keys() if s and s.strip()]
            kpi_card("News Sources", len(unique_sources), "🌍")
        with col4:
            # Try to get the most recent date
            try:
                conn = get_mysql_conn()
                if conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT MAX(date) AS latest_date FROM news_articles")
                    latest_row = cursor.fetchone() or {}
                    latest_raw = latest_row.get("latest_date")
                    if hasattr(latest_raw, "strftime"):
                        latest_date = latest_raw.strftime("%d %b %Y")
                    else:
                        latest_date = str(latest_raw) if latest_raw else "N/A"
                    cursor.close()
                    conn.close()
                else:
                    latest_date = "N/A"
            except Exception as e:
                latest_date = "Error"
            
            kpi_card("Last Updated", latest_date, "⏱️")

        # col1, col2, col3, col4 = st.columns(4)
        # with col1:
        #     st.metric("Total Articles", db_stats["total_articles"])
        # with col2:
        #     st.metric("Date Range", db_stats["date_range"])
        # with col3:
        #     # Count only non-empty sources
        #     unique_sources = [s for s in db_stats["sources"].keys() if s and s.strip()]
        #     st.metric("News Sources", len(unique_sources), help="Total unique news sources in database (excluding empty/NULL)")
        # with col4:
        #     # Try to get the most recent date
        #     try:
        #         conn = get_mysql_conn()
        #         if conn:
        #             cursor = conn.cursor()
        #             cursor.execute("SELECT MAX(date) AS latest_date FROM news_articles")
        #             latest_row = cursor.fetchone() or {}
        #             latest_raw = latest_row.get("latest_date")
        #             if hasattr(latest_raw, "strftime"):
        #                 latest_date = latest_raw.strftime("%Y-%m-%d")
        #             else:
        #                 latest_date = str(latest_raw) if latest_raw is not None else None
        #             cursor.close()
        #             conn.close()
        #             st.metric("Last Updated", latest_date or "N/A")
        #         else:
        #             st.metric("Last Updated", "N/A")
        #     except Exception as e:
        #         st.metric("Last Updated", "Error")

# Enhanced Sidebar Design
with st.sidebar:
    # Header Section
    st.header("🎯 Navigation")

    # Mode Selection with better UX
    st.subheader("📊 Scraper Mode")

    # Mode indicator
    if st.session_state.scraper_mode == "Web Scraper":
        st.info("🔍 **Web Scraper Active**\n\nQuery & analyze articles from news database")
    else:
        st.info("📄 **PDF Scraper Active**\n\nExtract articles from PDF newspapers")

    # Mode selection
    scraper_mode = st.radio(
        "Switch Mode:",
        ["Web Scraper", "PDF Scraper"],
        index=0 if st.session_state.scraper_mode == "Web Scraper" else 1,
        help="Choose between web scraping from news websites or PDF newspaper extraction",
        disabled=has_active_data,
        label_visibility="collapsed"
    )

    # Mode Lock Warning
    if has_active_data:
        st.warning("""
        🔒 **Mode Lock Active**

        Complete your current session before switching modes to avoid data loss.

        **Quick Actions:**
        • Download your results
        • Clear data to reset
        """)

    st.divider()

# Update session state if mode changed (optimized with forced re-render)
if scraper_mode != st.session_state.scraper_mode:
    old_mode = st.session_state.scraper_mode
    st.session_state.scraper_mode = scraper_mode

    # Smart reset: only reset states relevant to the mode being switched FROM
    if old_mode == "Web Scraper" and scraper_mode == "PDF Scraper":
        # Switching FROM Web TO PDF: reset Web-related states only
        st.session_state.query_results = []
        st.session_state.filtered_df = None
        st.session_state.last_query = None
    elif old_mode == "PDF Scraper" and scraper_mode == "Web Scraper":
        # Switching FROM PDF TO Web: reset PDF-related states only
        st.session_state.pdf_articles = []
        st.session_state.pdf_filtered_df = None
        st.session_state.pdf_extraction_status = "idle"

    # Update last rendered mode
    st.session_state.last_rendered_mode = scraper_mode

    # Force re-render to ensure mode switch takes effect immediately
    st.rerun()

    # Show success message for mode switch
    st.success(f"✅ Switched to {scraper_mode} mode")

# Initialize variables with default values
start_date = datetime.now().date() - timedelta(days=30)
end_date = datetime.now().date()
keywords = []

# Create placeholders for dynamic content to improve performance
main_placeholder = st.empty()
sidebar_placeholder = st.empty()

def render_web_scraper_sidebar():
    """Render sidebar content for Web Scraper mode"""
    # Web Scraper Controls
    if st.session_state.scraper_mode == "Web Scraper":
        # Date Range Section
        with st.expander("📅 Date Range", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                start_date = st.date_input(
                    "From:",
                    datetime.now().date() - timedelta(days=30),
                    min_value=datetime(2000, 1, 1).date(),
                    key="web_start_date",
                    help="Start date for article search"
                )
            with col2:
                end_date = st.date_input(
                    "To:",
                    datetime.now().date(),
                    max_value=datetime.now().date(),
                    key="web_end_date",
                    help="End date for article search"
                )

        # Keywords Section
        with st.expander("🔎 Keywords", expanded=True):
            keywords_input = st.text_input(
                "Search Keywords:",
                value="",
                placeholder="e.g., ekonomi, pendidikan, kesehatan",
                key="web_keywords",
                help="Comma-separated keywords to filter articles"
            )
            keywords = [k.strip().lower() for k in keywords_input.split(",") if k.strip()]

            if keywords:
                st.caption(f"🔍 Searching for: {', '.join(keywords)}")

        return start_date, end_date, keywords

def process_pdf_file(uploaded_file, keywords=None):
    """Process uploaded PDF file and extract articles"""
    if not LANGCHAIN_AVAILABLE:
        st.error("❌ LangChain extraction not available")
        return []

    # Reset extraction status at start
    st.session_state.pdf_extraction_status = "processing"

    try:
        print(f"[INFO] Starting PDF processing for: {uploaded_file.name}")

        # Save uploaded file to temporary location
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            pdf_path = tmp_file.name

        print(f"[INFO] PDF saved to temporary file: {pdf_path}")

        # Initialize extractor with Azure OpenAI config
        extractor = NewspaperExtractor(
            azure_endpoint=azure_config["endpoint"],
            azure_key=azure_config["api_key"],
            api_version=azure_config["api_version"]
        )

        print(f"[INFO] Extractor initialized with Azure config")

        # Process PDF
        print(f"[INFO] Starting PDF extraction...")
        articles = extractor.process_pdf(pdf_path)
        print(f"[INFO] PDF extraction completed. Found {len(articles)} articles")

        # Clean up temp file
        os.unlink(pdf_path)
        print(f"[INFO] Temporary file cleaned up")

        # Convert to dict format for easier handling
        articles_dict = []
        for article in articles:
            article_dict = {
                'judul': article.judul,
                'konten': article.konten,
                'kategori': article.kategori,
                'halaman': article.halaman,
                'sumber': article.sumber
            }
            articles_dict.append(article_dict)

        print(f"[INFO] Converted {len(articles_dict)} articles to dict format")

        # Apply keyword filtering if specified
        factory = StemmerFactory()
        stemmer = factory.create_stemmer()

        if keywords:
            print(f"[INFO] Applying keyword filtering: {keywords}")
            filtered_articles = []
            keyword_stems = [stemmer.stem(k.lower()) for k in keywords]
            for article in articles_dict:
                text_to_search = (article['judul'] + ' ' + article['konten']).lower()
                cleaned_text = re.sub(r'\s+', ' ', text_to_search) # hapus spasi berlebih
                cleaned_text = re.sub(r'[^\w\s]', ' ', cleaned_text) # hapus tanda baca
                words = cleaned_text.split()
                cleaned_text_stems = [stemmer.stem(w) for w in words]
                if any(k in cleaned_text_stems for k in keyword_stems):
                    filtered_articles.append(article)
            articles_dict = filtered_articles
            print(f"[INFO] After filtering: {len(articles_dict)} articles remain")

        st.session_state.pdf_extraction_status = "completed"
        print(f"[INFO] PDF processing completed successfully")
        return articles_dict

    except Exception as e:
        print(f"[ERROR] PDF processing failed: {e}")
        st.session_state.pdf_extraction_status = "error"
        st.error(f"❌ PDF processing error: {e}")
        return []

def render_pdf_scraper_sidebar():
    """Render sidebar content for PDF Scraper mode"""
    # PDF Scraper Controls
    if st.session_state.scraper_mode == "PDF Scraper":
        # File Upload Section
        with st.expander("📤 Upload Files", expanded=True):
            uploaded_pdfs = st.file_uploader(
                "PDF Newspaper Files:",
                type=['pdf'],
                accept_multiple_files=True,
                help="Upload multiple PDF files of newspapers to extract articles using AI",
                key="pdf_uploader"
            )

            if uploaded_pdfs:
                st.success(f"📄 {len(uploaded_pdfs)} file(s) uploaded")
                for pdf in uploaded_pdfs:
                    st.caption(f"• {pdf.name} ({pdf.size:,} bytes)")

        # Keywords Section
        with st.expander("🔎 Keywords (Optional)", expanded=True):
            pdf_keywords_input = st.text_input(
                "Filter Keywords:",
                value="",
                placeholder="Filter PDF articles by keywords",
                help="Leave empty to extract all articles from PDF",
                key="pdf_keywords"
            )
            pdf_keywords = [k.strip().lower() for k in pdf_keywords_input.split(",") if k.strip()]

            if pdf_keywords:
                st.caption(f"🔍 Filtering by: {', '.join(pdf_keywords)}")

        return uploaded_pdfs, pdf_keywords

# Tools moved to main content area for better organization

# Version info
st.markdown("""
<div style="margin-top:25px; margin-bottom:10px;">
    <span style="color:gray; font-size:14px;">
        📰 News Scraper v2.0
    </span><br>
    <span style="color:#888; font-size:13px;">
        BPS Provinsi Gorontalo
    </span>
</div>
""", unsafe_allow_html=True)

# Sidebar content rendering (optimized with functions)
if st.session_state.scraper_mode == "Web Scraper":
    start_date, end_date, keywords = render_web_scraper_sidebar()

elif st.session_state.scraper_mode == "PDF Scraper":
    uploaded_pdfs, pdf_keywords = render_pdf_scraper_sidebar()

# Clear mode indicator at the top of main content area
st.divider()
if st.session_state.scraper_mode == "Web Scraper":
    st.header("🔍 Web Scraper - Database Query")
    st.markdown("*Search and analyze articles from news database with advanced filtering*")
elif st.session_state.scraper_mode == "PDF Scraper":
    st.header("📄 PDF Scraper - Document Analysis")
    st.markdown("*Extract and analyze articles from PDF newspaper files*")
st.divider()

# PDF Processing - Handle file processing when PDFs are uploaded
if st.session_state.scraper_mode == "PDF Scraper":
    # Process PDF button with enhanced progress tracking
    if uploaded_pdfs and len(uploaded_pdfs) > 0:
        # Show processing info
        st.info(f"📋 Ready to process {len(uploaded_pdfs)} PDF file(s)")

        if st.button("🚀 Start PDF Extraction", type="primary", key="pdf_process_btn"):
            # Pre-processing validation
            if not LANGCHAIN_AVAILABLE:
                st.error("❌ LangChain library is not available. Please install required packages.")
                st.code("pip install langchain langchain-openai langchain-community", language="bash")
                st.stop()

            if not AZURE_OPENAI_AVAILABLE:
                st.error("❌ Azure OpenAI is not configured properly.")
                with st.expander("🔧 Configuration Help", expanded=True):
                    st.write("**Required configuration:**")
                    st.write("1. Update `config.ini` with Azure OpenAI credentials")
                    st.write("2. Or ensure `.env` file has correct AZURE_OPENAI_* variables")
                    st.write("3. Verify Azure OpenAI endpoint is accessible")
                st.stop()

            # Create progress containers
            progress_bar = st.progress(0)
            status_text = st.empty()
            file_status = st.empty()

            all_pdf_results = []
            total_files = len(uploaded_pdfs)

            print(f"[INFO] Starting PDF extraction for {total_files} files")
            print(f"[INFO] Azure OpenAI configured: {AZURE_OPENAI_AVAILABLE}")
            print(f"[INFO] LangChain available: {LANGCHAIN_AVAILABLE}")

            try:
                # Reset PDF session state before processing
                st.session_state.pdf_articles = []
                st.session_state.pdf_filtered_df = None
                st.session_state.pdf_extraction_status = "processing"

                # Process each PDF file with progress tracking
                for i, uploaded_pdf in enumerate(uploaded_pdfs):
                    current_progress = (i / total_files)
                    progress_bar.progress(current_progress)

                    file_status.info(f"📄 Processing file {i+1}/{total_files}: **{uploaded_pdf.name}**")
                    status_text.text(f"🔄 Extracting articles from {uploaded_pdf.name}...")

                    # Process the PDF with error handling
                    try:
                        pdf_results = process_pdf_file(uploaded_pdf, pdf_keywords if pdf_keywords else None)

                        if pdf_results and len(pdf_results) > 0:
                            # Add source information to each article
                            for article in pdf_results:
                                article['source_file'] = uploaded_pdf.name
                            all_pdf_results.extend(pdf_results)

                            status_text.success(f"✅ {uploaded_pdf.name}: {len(pdf_results)} articles extracted")
                            print(f"[SUCCESS] {uploaded_pdf.name}: {len(pdf_results)} articles extracted")
                        else:
                            status_text.warning(f"⚠️ {uploaded_pdf.name}: No articles found")
                            print(f"[WARNING] {uploaded_pdf.name}: No articles found")

                    except Exception as file_error:
                        status_text.error(f"❌ {uploaded_pdf.name}: Processing failed - {str(file_error)}")
                        print(f"[ERROR] {uploaded_pdf.name}: Processing failed - {str(file_error)}")
                        continue  # Continue with next file

                    # Small delay for UI update
                    import time
                    time.sleep(0.5)

                # Complete progress
                progress_bar.progress(1.0)
                file_status.empty()

                # Update session state with results
                if all_pdf_results:
                    st.session_state.pdf_articles = all_pdf_results
                    st.session_state.pdf_filtered_df = pd.DataFrame(all_pdf_results)
                    st.session_state.pdf_extraction_status = "completed"

                    st.success(f"🎉 **Extraction Complete!** Extracted {len(all_pdf_results)} articles from {total_files} PDF file(s)")
                    status_text.success("✅ All files processed successfully!")

                    # Show summary
                    st.info(f"""
                    📊 **Processing Summary:**
                    - Files processed: {total_files}
                    - Total articles: {len(all_pdf_results)}
                    - Average per file: {len(all_pdf_results)/total_files:.1f} articles
                    """)

                    print(f"[SUCCESS] Total extraction complete: {len(all_pdf_results)} articles from {total_files} files")
                else:
                    st.session_state.pdf_articles = []
                    st.session_state.pdf_filtered_df = pd.DataFrame()
                    st.session_state.pdf_extraction_status = "completed"

                    st.warning("⚠️ **No articles found** in any of the uploaded PDF files")
                    status_text.warning("⚠️ No articles were extracted from the uploaded files")

                    print(f"[WARNING] No articles found in any of the {total_files} uploaded files")

            except Exception as e:
                progress_bar.empty()
                status_text.empty()
                file_status.empty()

                # Reset session state on fatal error
                st.session_state.pdf_articles = []
                st.session_state.pdf_filtered_df = None
                st.session_state.pdf_extraction_status = "error"

                print(f"[FATAL ERROR] PDF processing failed: {e}")

                st.error("🚨 **PDF Processing Failed**")
                with st.expander("🐛 **Error Details & Troubleshooting**", expanded=True):
                    st.write("**What went wrong:**")
                    error_str = str(e).lower()
                    if "azure openai" in error_str or "openai" in error_str:
                        st.write("❌ **Azure OpenAI Configuration Issue**")
                        st.write("**Solutions:**")
                        st.write("1. Check Azure OpenAI credentials in `config.ini` and `.env`")
                        st.write("2. Verify Azure OpenAI endpoint is accessible")
                        st.write("3. Check API key validity and quota")
                    elif "langchain" in error_str:
                        st.write("❌ **LangChain Library Issue**")
                        st.write("**Solution:** Install required packages")
                        st.code("pip install langchain langchain-openai langchain-community", language="bash")
                    elif "pdf" in error_str or "pymupdf" in error_str:
                        st.write("❌ **PDF Processing Issue**")
                        st.write("**Solutions:**")
                        st.write("1. Check if PDF files are valid and not corrupted")
                        st.write("2. Ensure PDF is not password-protected")
                        st.write("3. Try with a different PDF file")
                    elif "connection" in error_str or "network" in error_str:
                        st.write("❌ **Network Connectivity Issue**")
                        st.write("**Solutions:**")
                        st.write("1. Check internet connection")
                        st.write("2. Verify Azure OpenAI service is accessible")
                        st.write("3. Check firewall/proxy settings")
                    else:
                        st.write("❌ **Unexpected Processing Error**")
                        st.write("**Error message:**", str(e))

                    st.write("")
                    st.write("**Debug Information:**")
                    st.write(f"- Azure OpenAI Endpoint: {azure_config.get('endpoint', 'Not configured')}")
                    st.write(f"- API Key configured: {'Yes' if azure_config.get('api_key') else 'No'}")
                    st.write(f"- Files uploaded: {len(uploaded_pdfs) if 'uploaded_pdfs' in locals() else 0}")

                    st.code(f"Technical details: {str(e)}")

                st.info("💡 **Try:** Check file format, Azure OpenAI config, or contact administrator")

            # Store results
            st.session_state.pdf_articles = all_pdf_results
            st.session_state.pdf_filtered_df = pd.DataFrame(all_pdf_results) if all_pdf_results else pd.DataFrame()

# Source selection removed - all sources are now included by default


def query_articles_from_db(start_date, end_date, keywords):
    """Query articles from database with filters."""
    conn = get_mysql_conn()
    if not conn:
        st.error("❌ Cannot query database - no connection available")
        return []

    try:
        cursor = conn.cursor()

        # Build query with filters
        query = """
            SELECT id, date, title, contents, reporter, sources, links
            FROM news_articles
            WHERE 1=1
        """
        params = []

        # Date filter
        if start_date:
            query += " AND date >= %s"
            params.append(start_date.strftime('%Y-%m-%d'))

        if end_date:
            query += " AND date <= %s"
            params.append(end_date.strftime('%Y-%m-%d'))

        # Source filter removed - all sources included by default

        # Keyword filter (search in title and contents)
        if keywords:
            keyword_conditions = []
            for keyword in keywords:
                keyword_conditions.append("(title LIKE %s OR contents LIKE %s)")
                params.extend([f'%{keyword}%', f'%{keyword}%'])

            if keyword_conditions:
                query += " AND (" + " OR ".join(keyword_conditions) + ")"

        query += " ORDER BY date DESC, id DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        # DictCursor already returns dictionaries, no need to convert
        results = list(rows) if rows else []

        # Add BPS category classification for each article
        for article in results:
            # Use unified BPS classification function
            content_text = (article.get('title', '') + ' ' + article.get('contents', '')).lower()
            bps_category = classify_bps_category(content_text)

            # Add BPS category to article
            article['bps_category'] = bps_category
            article['bps_category_name'] = BPS_CATEGORIES.get(bps_category, bps_category)

        cursor.close()
        conn.close()

        return results

    except Exception as e:
        st.error(f"Database query error: {e}")
        return []


# Main interface - only show in Web Scraper mode
if st.session_state.scraper_mode == "Web Scraper":
    col1, col2 = st.columns([2, 1])

    with col1:
        # Show current filters summary
        if start_date and end_date:
            st.info(f"📅 Searching: {start_date} to {end_date}")
        if keywords:
            st.info(f"🔍 Keywords: {', '.join(keywords)}")

        if st.button("🔍 Search Articles", type="primary", use_container_width=True):
            # Enhanced search with progress tracking
            progress_bar = st.progress(0)
            status_text = st.empty()

            try:
                status_text.text("🔄 Connecting to database...")
                progress_bar.progress(0.2)

                status_text.text("🔍 Executing search query...")
                progress_bar.progress(0.5)

                # Query database with current filters
                results = query_articles_from_db(start_date, end_date, keywords)
                progress_bar.progress(0.8)

                status_text.text("📊 Processing results...")
                progress_bar.progress(0.9)

                # Store results
                st.session_state.query_results = results
                st.session_state.filtered_df = pd.DataFrame(results) if results else pd.DataFrame()
                st.session_state.last_query = {
                    'start_date': start_date,
                    'end_date': end_date,
                    'keywords': keywords
                }

                # Complete progress
                progress_bar.progress(1.0)
                progress_bar.empty()
                status_text.empty()

                if results:
                    st.success(f"🎉 **Search Complete!** Found {len(results)} articles matching your criteria")

                    # Show quick summary
                    st.info(f"""
                    📊 **Search Summary:**
                    - Date range: {start_date} to {end_date}
                    - Keywords: {', '.join(keywords) if keywords else 'None'}
                    - Results: {len(results)} articles found
                    """)
                else:
                    st.warning("⚠️ No articles found matching your search criteria. Try adjusting the filters.")

            except Exception as e:
                progress_bar.empty()
                status_text.empty()

                st.error("🔍 **Search Failed**")
                with st.expander("🐛 **Search Error Details**", expanded=True):
                    st.write("**What went wrong:**")
                    error_str = str(e).lower()
                    if "not all arguments converted" in error_str:
                        st.write("❌ Database query syntax error")
                        st.write("**Solution:** Check database configuration and table structure")
                    elif "connection" in error_str:
                        st.write("❌ Database connection issue")
                        st.write("**Solution:** Check database server and credentials")
                    elif "table" in error_str or "column" in error_str:
                        st.write("❌ Database schema issue")
                        st.write("**Solution:** Ensure database tables exist and have correct structure")
                    else:
                        st.write("❌ Unexpected search error")

                    st.code(f"Technical details: {str(e)}")

                st.info("💡 **Try:** Adjust search filters, check database connection, or contact administrator")

    with col2:
        # Download button moved to bottom section for consistency
        pass

# Web Scraper Results display - only show in Web Scraper mode
if st.session_state.scraper_mode == "Web Scraper":
    if st.session_state.filtered_df is not None and not st.session_state.filtered_df.empty:
        df = st.session_state.filtered_df

        # Enhanced Results Summary with Cards
        st.subheader("📊 Analysis Results")

        # Summary Cards
        # col1, col2, col3 = st.columns(3)

        # with col1:
        #     st.metric(
        #         label="📄 Total Articles",
        #         value=f"{len(df):,}",
        #         help="Number of articles found matching your search criteria"
        #     )

        # with col2:
        #     # Calculate date range properly
        #     if len(df) > 0 and 'date' in df.columns:
        #         min_date = pd.to_datetime(df['date']).min().strftime('%Y-%m-%d')
        #         max_date = pd.to_datetime(df['date']).max().strftime('%Y-%m-%d')
        #         date_range = f"{min_date} to {max_date}"
        #     else:
        #         date_range = "No data"
        #     st.metric(
        #         label="📅 Date Range",
        #         value=date_range,
        #         help="Date range of articles in results"
        #     )

        # with col3:
        #     # Count unique sources
        #     if 'sources' in df.columns:
        #         unique_sources = df['sources'].dropna().replace('', pd.NA).dropna().nunique()
        #     else:
        #         unique_sources = 0
        #     st.metric(
        #         label="📰 News Sources",
        #         value=unique_sources,
        #         help="Number of unique news sources in results"
        #     )

        col1, col2, col3 = st.columns(3)

        card_style = """
        padding:14px 18px;
        border-radius:12px;
        background:#f0f2f6;
        box-shadow:0 1px 2px rgba(0,0,0,0.04);
        height:100%;
        display:flex;
        flex-direction:column;
        justify-content:center;         
        """

        label_style = "font-size:18px; color:#6c757d; margin-bottom:6px;"
        value_style = """font-size:26px; font-weight:600; color:#111; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;"""

        # --- COL 1 ---
        with col1:
            st.markdown(f"""
            <div style="{card_style}">
                <div style="{label_style}">📄 Total Articles</div>
                <div style="{value_style}">{len(df):,}</div>
            </div>
            """, unsafe_allow_html=True)

        # --- COL 2 ---
        with col2:
            if len(df) > 0 and 'date' in df.columns:
                min_date = pd.to_datetime(df['date']).min().strftime('%Y-%m-%d')
                max_date = pd.to_datetime(df['date']).max().strftime('%Y-%m-%d')
                date_range = f"{min_date} → {max_date}"
            else:
                date_range = "No data"

            st.markdown(f"""
            <div style="{card_style}">
                <div style="{label_style}">📅 Date Range</div>
                <div style="{value_style}">{date_range}</div>
            </div>
            """, unsafe_allow_html=True)

        # --- COL 3 ---
        with col3:
            if 'sources' in df.columns:
                unique_sources = df['sources'].dropna().replace('', pd.NA).dropna().nunique()
            else:
                unique_sources = 0

            st.markdown(f"""
            <div style="{card_style}">
                <div style="{label_style}">📰 News Sources</div>
                <div style="{value_style}">{unique_sources}</div>
            </div>
            """, unsafe_allow_html=True)

        # Additional insights
        if len(df) > 0:
            st.divider()

            # Quick insights row
            insight_col1, = st.columns(1)

            with insight_col1:
                # BPS Category Distribution
                if 'bps_category' in df.columns:
                    bps_counts = df['bps_category'].value_counts()
                    if not bps_counts.empty:
                        dominant_bps = bps_counts.index[0]
                        dominant_name = BPS_CATEGORIES.get(dominant_bps, dominant_bps)
                        st.info(f"🏷️ **Top Category:** {dominant_bps} ({dominant_name})")

        # Data preview
        st.subheader("👀 Article Results")
        st.dataframe(df, width='stretch', height=400)

        # Article details view
        st.subheader("📄 Article Details")
        if not df.empty:
            selected_article = st.selectbox(
                "Select an article to view details:",
                options=df.index,
                format_func=lambda x: f"{df.iloc[x]['date']} - {df.iloc[x]['title'][:50]}..."
            )

            if selected_article is not None:
                article = df.iloc[selected_article]
                st.markdown(f"### {article['title']}")
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**Date:** {article['date']}")
                    st.write(f"**Source:** {article['sources']}")
                    st.write(f"**🏷️ BPS Category:** {article.get('bps_category', 'UMUM')} - {article.get('bps_category_name', 'UMUM')}")
                with col2:
                    st.write(f"**Reporter:** {article.get('reporter', 'N/A')}")
                    if article.get('links'):
                        st.write(f"**Link:** [{article['links']}]({article['links']})")

                if article.get('contents'):
                    st.markdown("**Content:**")
                    # Truncate content if too long
                    content = article['contents']
                    if len(content) > 1000:
                        content = content[:1000] + "..."
                    st.write(content)

        # Data visualization
        if len(df) > 0:
            st.subheader("📊 Data Visualization")

            # Articles by source
            if 'sources' in df.columns:
                st.markdown("**Articles by Source:**")
                source_counts = df['sources'].value_counts().reset_index()
                source_counts.columns = ['Source', 'Count']

                chart = alt.Chart(source_counts).mark_bar().encode(
                    x=alt.X('Source:N', axis=alt.Axis(labelAngle=0)),  # Horizontal labels
                    y='Count:Q',
                    color='Source:N'
                ).properties(height=300)

                st.altair_chart(chart, use_container_width=True)

            # Articles by BPS Category
            if 'bps_category' in df.columns:
                st.markdown("**🏷️ Articles by BPS Category:**")
                bps_counts = df['bps_category'].value_counts().reset_index()
                bps_counts.columns = ['BPS_Category', 'Count']

                # Add category names for better readability
                bps_counts['Category_Name'] = bps_counts['BPS_Category'].map(lambda x: BPS_CATEGORIES.get(x, x))

                chart = alt.Chart(bps_counts).mark_bar().encode(
                    x=alt.X('BPS_Category:N', axis=alt.Axis(labelAngle=0)),  # Horizontal labels
                    y='Count:Q',
                    color='BPS_Category:N',
                    tooltip=['BPS_Category:N', 'Category_Name:N', 'Count:Q']
                ).properties(height=300)

                st.altair_chart(chart, use_container_width=True)

            # Articles by date (timeline)
            if 'date' in df.columns:
                st.markdown("**Articles Timeline:**")
                # Convert date column to datetime and count by date
                df_copy = df.copy()
                df_copy['date'] = pd.to_datetime(df_copy['date'])
                daily_counts = df_copy.groupby(df_copy['date'].dt.date).size().reset_index()
                daily_counts.columns = ['Date', 'Count']

                chart = alt.Chart(daily_counts).mark_line(point=True).encode(
                    x=alt.X('Date:T', axis=alt.Axis(labelAngle=0)),  # Horizontal labels
                    y='Count:Q',
                    tooltip=['Date:T', 'Count:Q']
                ).properties(height=300)

                st.altair_chart(chart, use_container_width=True)

        # Web Scraper Download - consistent with PDF Scraper
        if not df.empty:
            st.subheader("📥 Download Results")
            col1, col2 = st.columns(2)
            with col1:
                csv_data = df.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="📥 Download CSV",
                    data=csv_data,
                    file_name=f"web_articles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            with col2:
                # JSON download
                json_data = df.to_json(orient='records', indent=2, force_ascii=False)
                st.download_button(
                    label="📥 Download JSON",
                    data=json_data,
                    file_name=f"web_articles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json",
                    use_container_width=True
                )

    elif st.session_state.last_query is not None:
        st.info("No articles found matching your current filters. Try adjusting the date range or keywords.")

# PDF Scraper Results Display
if st.session_state.scraper_mode == "PDF Scraper" and st.session_state.pdf_filtered_df is not None and not st.session_state.pdf_filtered_df.empty:
        df_pdf = st.session_state.pdf_filtered_df

        # Enhanced PDF Results Summary
        st.subheader("📊 PDF Extraction Results")

        # Summary Cards
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                label="📄 Total Articles",
                value=f"{len(df_pdf):,}",
                help="Number of articles extracted from PDF files"
            )

        with col2:
            # BPS Categories count
            categories_count = df_pdf['kategori'].nunique() if 'kategori' in df_pdf.columns else 0
            st.metric(
                label="🏷️ BPS Categories",
                value=categories_count,
                help="Number of unique BPS categories identified"
            )

        with col3:
            # Source files count
            source_files = df_pdf['source_file'].nunique() if 'source_file' in df_pdf.columns else 1
            st.metric(
                label="📚 Source Files",
                value=source_files,
                help="Number of PDF files processed"
            )

        # Additional PDF insights
        if len(df_pdf) > 0:
            st.divider()

            # Quick insights row - Top Category wider, Avg per File smaller on right
            insight_col1, insight_col2 = st.columns([3, 1])

            with insight_col1:
                if 'kategori' in df_pdf.columns and not df_pdf['kategori'].empty:
                    # Find most common BPS category
                    top_category_code = df_pdf['kategori'].value_counts().index[0]
                    top_category_name = BPS_CATEGORIES.get(top_category_code, top_category_code)
                    st.info(f"🏷️ **Top Category:** {top_category_code} - {top_category_name}")
                else:
                    st.info("🏷️ **Categories:** Not available")

            with insight_col2:
                if 'source_file' in df_pdf.columns:
                    file_sizes = df_pdf.groupby('source_file').size()
                    avg_articles_per_file = file_sizes.mean()
                    st.info(f"📊 **Avg per File:** {avg_articles_per_file:.1f} articles")

        # PDF Articles Table
        st.subheader("📋 Extracted Articles")
        st.dataframe(df_pdf, width='stretch', height=400)

        # File summary view for PDF
        st.subheader("📄 PDF File Summary")
        if not df_pdf.empty and 'source_file' in df_pdf.columns:
            # Function to generate file description using AI
            def generate_file_description(file_data, file_name=""):
                """Generate contextual description for a PDF file using AI"""
                try:
                    # Convert pandas DataFrame to list of articles for AI processing
                    articles = []
                    for _, row in file_data.iterrows():
                        # Create a simple article object for AI processing
                        class SimpleArticle:
                            def __init__(self, judul, konten, kategori, halaman, sumber):
                                self.judul = judul or "Tanpa Judul"
                                self.konten = konten or ""
                                self.kategori = kategori or "UMUM"
                                self.halaman = halaman or 1
                                self.sumber = sumber or "Unknown"

                        article = SimpleArticle(
                            judul=row.get('judul', ''),
                            konten=row.get('konten', ''),
                            kategori=row.get('kategori', 'UMUM'),
                            halaman=row.get('halaman', 1),
                            sumber=row.get('sumber', 'Unknown')
                        )
                        articles.append(article)

                    # Use AI to generate description if available
                    if LANGCHAIN_AVAILABLE and AZURE_OPENAI_AVAILABLE:
                        try:
                            extractor = NewspaperExtractor(
                                azure_endpoint=azure_config["endpoint"],
                                azure_key=azure_config["api_key"],
                                api_version=azure_config["api_version"]
                            )
                            ai_description = extractor.generate_file_description_ai(articles, file_name)
                            return ai_description.description
                        except Exception as e:
                            st.warning(f"AI description failed: {e}. Using fallback.")
                            return generate_file_description_fallback(file_data)
                    else:
                        # Fallback to rule-based approach if AI not available
                        return generate_file_description_fallback(file_data)

                except Exception as e:
                    st.warning(f"AI description generation failed: {e}. Using fallback method.")
                    return generate_file_description_fallback(file_data)

            def generate_file_description_fallback(file_data):
                """Fallback rule-based description generation"""
                descriptions = []

                # Get dominant BPS category
                if 'kategori' in file_data.columns and not file_data['kategori'].empty:
                    # Map all categories to BPS and find dominant
                    bps_cats = [map_to_bps_category(cat) for cat in file_data['kategori'].dropna()]
                    if bps_cats:
                        dominant_bps = max(set(bps_cats), key=bps_cats.count)
                        category_name = BPS_CATEGORIES.get(dominant_bps, dominant_bps)
                        descriptions.append(f"fokus pada sektor {category_name}")

                # Get title themes (extract common keywords from titles)
                if 'judul' in file_data.columns and not file_data['judul'].empty:
                    titles = file_data['judul'].dropna().str.lower()
                    # Simple keyword extraction from titles
                    common_words = []
                    for title in titles.head(5):  # Check first 5 titles
                        words = title.split()
                        # Look for capitalized words (likely proper nouns/topics)
                        proper_words = [word for word in words if word and word[0].isupper() and len(word) > 3]
                        common_words.extend(proper_words[:2])  # Take max 2 per title

                    if common_words:
                        unique_words = list(set(common_words))[:3]  # Max 3 unique keywords
                        descriptions.append(f"membahas {', '.join(unique_words)}")

                # Content-based themes (from article content if available)
                if 'konten' in file_data.columns and not file_data['konten'].empty:
                    sample_content = file_data['konten'].dropna().head(2)  # First 2 articles
                    content_text = ' '.join(sample_content).lower()[:500]  # Limit text length

                    # Look for contextual keywords
                    context_keywords = []
                    if any(word in content_text for word in ['pembangunan', 'infrastruktur', 'jalan', 'jembatan']):
                        context_keywords.append('pembangunan infrastruktur')
                    if any(word in content_text for word in ['pendidikan', 'sekolah', 'siswa', 'guru']):
                        context_keywords.append('pendidikan')
                    if any(word in content_text for word in ['kesehatan', 'rumah sakit', 'dokter', 'pasien']):
                        context_keywords.append('kesehatan')
                    if any(word in content_text for word in ['pertanian', 'petani', 'tanaman', 'panen']):
                        context_keywords.append('pertanian')
                    if any(word in content_text for word in ['ekonomi', 'usaha', 'wirausaha', 'pasar']):
                        context_keywords.append('ekonomi dan bisnis')

                    if context_keywords:
                        descriptions.append(f"berisi topik tentang {', '.join(context_keywords[:2])}")

                # Create final description
                if descriptions:
                    return f"File koran ini {'. '.join(descriptions)}."
                else:
                    return "File koran berisi berbagai artikel berita lokal."

            # Group by source file and create summary
            file_summaries = []
            for file_name in df_pdf['source_file'].unique():
                file_data = df_pdf[df_pdf['source_file'] == file_name]
                # Map categories to BPS categories for summary
                bps_categories_summary = {}
                if 'kategori' in file_data.columns:
                    for cat in file_data['kategori'].dropna():
                        bps_cat = map_to_bps_category(cat)
                        bps_categories_summary[bps_cat] = bps_categories_summary.get(bps_cat, 0) + 1

                # Count unique pages with articles (simplified)
                unique_pages = set()
                if 'halaman' in file_data.columns and not file_data['halaman'].empty:
                    for halaman_val in file_data['halaman']:
                        try:
                            if isinstance(halaman_val, str) and ',' in halaman_val:
                                # Handle multi-page articles
                                for page in halaman_val.split(','):
                                    unique_pages.add(int(page.strip()))
                            else:
                                unique_pages.add(int(halaman_val))
                        except (ValueError, AttributeError):
                            continue

                page_info = f"{len(unique_pages)} pages with articles" if unique_pages else "N/A"

                # Extract date from filename instead of article data
                file_date = "N/A"
                try:
                    from pathlib import Path
                    import re
                    from datetime import datetime

                    basename = Path(file_name).stem
                    date_pattern = r'(\d{1,2})[.\-](\d{1,2})[.\-](\d{4})'
                    match = re.search(date_pattern, basename)

                    if match:
                        day, month, year = match.groups()
                        date_obj = datetime(int(year), int(month), int(day))
                        file_date = date_obj.strftime('%d %B %Y')
                except:
                    pass

                summary = {
                    'file_name': file_name,
                    'total_articles': len(file_data),
                    'categories': bps_categories_summary,  # BPS mapped categories
                    'page_range': page_info,
                    'date_range': file_date,  # Date extracted from filename
                    'description': generate_file_description(file_data, file_name)
                }
                file_summaries.append(summary)

            # Display summary for each file
            for i, summary in enumerate(file_summaries):
                with st.expander(f"📄 {summary['file_name']}", expanded=(i==0)):
                    col1, col2 = st.columns(2)

                    with col1:
                        st.metric("Total Articles", summary['total_articles'])
                        st.write(f"**Pages with Articles:** {summary['page_range']}")

                    with col2:
                        st.write("**BPS Sectors Found:**")
                        if summary['categories']:
                            for cat_code, count in summary['categories'].items():
                                cat_name = BPS_CATEGORIES.get(cat_code, cat_code)
                                st.write(f"- **{cat_code}**: {cat_name} ({count} articles)")
                        else:
                            st.write("No sectors identified")

                    # Show file description/context
                    st.write("**File Description:**")
                    st.info(summary['description'])

                    # Show sample articles from this file
                    st.write("**Sample Articles:**")
                    file_articles = df_pdf[df_pdf['source_file'] == summary['file_name']]
                    sample_articles = file_articles.head(3)  # Show first 3 articles

                    for _, article in sample_articles.iterrows():
                        st.markdown(f"- **{article.get('judul', 'No Title')[:50]}...** (Page {article.get('halaman', 'N/A')})")

        # PDF Data visualization
        if len(df_pdf) > 0:
            st.subheader("📊 PDF Data Analysis")

            # Articles by category
            if 'kategori' in df_pdf.columns:
                st.markdown("**Articles by Category:**")
                category_counts = df_pdf['kategori'].value_counts().reset_index()
                category_counts.columns = ['Category', 'Count']

                chart = alt.Chart(category_counts).mark_bar().encode(
                    x=alt.X('Category:N', axis=alt.Axis(labelAngle=0)),  # Horizontal labels
                    y='Count:Q',
                    color='Category:N'
                ).properties(height=300)

                st.altair_chart(chart, use_container_width=True)

            # Articles by page
            if 'halaman' in df_pdf.columns:
                st.markdown("**Articles by Page:**")

                # Convert halaman to string for consistent chart display
                df_pdf_copy = df_pdf.copy()
                df_pdf_copy['halaman_str'] = df_pdf_copy['halaman'].astype(str)

                page_counts = df_pdf_copy['halaman_str'].value_counts().reset_index()
                page_counts.columns = ['Page', 'Count']

                # Sort by page number (handle mixed formats)
                def sort_page_key(page_str):
                    try:
                        # Extract first number from formats like "1", "1,3", "2-3"
                        if ',' in page_str:
                            return int(page_str.split(',')[0].strip())
                        elif '-' in page_str:
                            return int(page_str.split('-')[0].strip())
                        else:
                            return int(page_str)
                    except (ValueError, AttributeError):
                        return 999  # Put invalid values at the end

                page_counts['sort_key'] = page_counts['Page'].apply(sort_page_key)
                page_counts = page_counts.sort_values('sort_key').drop('sort_key', axis=1)

                chart = alt.Chart(page_counts).mark_bar().encode(
                    x=alt.X('Page:N', axis=alt.Axis(labelAngle=0)),  # Horizontal labels
                    y='Count:Q',
                    color='Page:N'
                ).properties(height=300)

                st.altair_chart(chart, use_container_width=True)

            # Articles by source file
            if 'source_file' in df_pdf.columns and df_pdf['source_file'].nunique() > 1:
                st.markdown("**Articles by Source File:**")
                file_counts = df_pdf['source_file'].value_counts().reset_index()
                file_counts.columns = ['File', 'Count']

                chart = alt.Chart(file_counts).mark_bar().encode(
                    x=alt.X('File:N', axis=alt.Axis(labelAngle=0)),  # Horizontal labels
                    y='Count:Q',
                    color='File:N'
                ).properties(height=300)

                st.altair_chart(chart, use_container_width=True)

        # PDF Download - consistent with Web Scraper
        if not df_pdf.empty:
            st.subheader("📥 Download Results")
            col1, col2 = st.columns(2)
            with col1:
                csv_pdf_data = df_pdf.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="📥 Download CSV",
                    data=csv_pdf_data,
                    file_name=f"pdf_articles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            with col2:
                # JSON download
                json_pdf_data = df_pdf.to_json(orient='records', indent=2, force_ascii=False)
                st.download_button(
                    label="📥 Download JSON",
                    data=json_pdf_data,
                    file_name=f"pdf_articles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json",
                    use_container_width=True
                )

# PDF Processing Status
elif st.session_state.pdf_extraction_status == "processing" and st.session_state.scraper_mode == "PDF Scraper":
    st.subheader("📄 PDF Processing")
    with st.spinner("🔄 Extracting articles from PDF..."):
        st.info("Please wait while we process the PDF file. This may take several minutes depending on the file size and number of articles.")

elif st.session_state.pdf_extraction_status == "error" and st.session_state.scraper_mode == "PDF Scraper":
    st.subheader("📄 PDF Extraction Error")
    st.error("❌ Failed to extract articles from the uploaded PDF. Please check the file and try again.")


# Footer
st.markdown("---")
st.markdown("*News Scraper for Badan Pusat Statistik Provinsi Gorontalo - Powered by Streamlit*")
