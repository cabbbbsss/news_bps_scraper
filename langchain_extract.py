import os
import json
import re
from datetime import datetime
from typing import List, Optional
from pathlib import Path

# Optional dotenv loading
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional

# LangChain imports
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
import traceback

# Azure OpenAI imports
from langchain_openai import AzureChatOpenAI

# Pydantic models for structured output
class NewsArticle(BaseModel):
    """Model untuk artikel berita yang terstruktur"""
    judul: str = Field(description="Judul lengkap dari artikel berita")
    konten: str = Field(description="Isi lengkap konten artikel berita")
    kategori: str = Field(description="Kode kategori BPS (KBLI): A1, A2, A3, B, C1, C2, C3, C4, C5, D, E, F, G1, G2, G3, H1, H2, H3, I1, I2, J, K, L, MN, O, P, Q, RSTU, UMUM")
    halaman: int = Field(description="Nomor halaman di mana artikel ditemukan")
    sumber: str = Field(description="Sumber koran")

class NewsArticlesList(BaseModel):
    """Wrapper untuk list of NewsArticle"""
    articles: List[NewsArticle] = Field(description="Daftar artikel berita")

class FileDescription(BaseModel):
    """Model untuk deskripsi file PDF koran"""
    description: str = Field(description="Deskripsi kontekstual file koran dalam bahasa Indonesia")
    main_topics: List[str] = Field(description="Topik utama yang dibahas dalam file")
    dominant_sectors: List[str] = Field(description="Sektor BPS yang dominan dalam file")

class NewspaperExtractor:
    """Kelas untuk mengekstrak artikel berita dari PDF koran menggunakan LangChain dan Azure OpenAI"""

    def __init__(self, azure_endpoint: str = None, azure_key: str = None, api_version: str = "2024-02-01"):
        """
        Inisialisasi extractor dengan Azure OpenAI

        Args:
            azure_endpoint: Azure OpenAI endpoint URL
            azure_key: Azure OpenAI API key
            api_version: API version untuk Azure OpenAI
        """
        self.azure_endpoint = azure_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.azure_key = azure_key or os.getenv("AZURE_OPENAI_API_KEY")
        self.api_version = api_version

        if not self.azure_endpoint or not self.azure_key:
            raise ValueError("Azure OpenAI endpoint dan API key harus disediakan atau di-set sebagai environment variables")

        # Inisialisasi Azure OpenAI model
        self.llm = AzureChatOpenAI(
            azure_endpoint=self.azure_endpoint,
            api_key=self.azure_key,
            api_version=self.api_version,
            deployment_name="grok-4-fast-non-reasoning",  # Ganti dengan deployment name Anda
            temperature=0.1,
            max_tokens=None
        )

        # Setup parser untuk output terstruktur
        self.parser = PydanticOutputParser(pydantic_object=NewsArticlesList)

        # Setup text splitter untuk memecah dokumen panjang
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=4000,
            chunk_overlap=200,
            separators=["\n\n", "\n", " ", ""]
        )

    def extract_metadata_from_filename(self, filename: str) -> dict:
        """Ekstrak metadata dari nama file PDF"""
        basename = Path(filename).stem

        metadata = {
            'filename': basename,
            'full_path': str(filename),
            'source': 'unknown',
            'date': None,
            'date_str': None
        }

        # Pattern untuk tanggal: DD.MM.YYYY atau DD-MM-YYYY
        date_pattern = r'(\d{1,2})[.\-](\d{1,2})[.\-](\d{4})'
        match = re.search(date_pattern, basename)

        if match:
            day, month, year = match.groups()
            try:
                date_obj = datetime(int(year), int(month), int(day))
                metadata['date'] = date_obj.isoformat()
                metadata['date_str'] = date_obj.strftime('%d %B %Y')
            except ValueError:
                pass

        # Deteksi sumber dari filename (fokus koran Gorontalo)
        basename_upper = basename.upper()

        # Gorontalo Post variations
        if any(keyword in basename_upper for keyword in ['GP', 'GORONTALO_POST', 'GORONTALOPOST', 'GO_POST']):
            metadata['source'] = 'Gorontalo Post'
        # GOSULUT variations
        elif any(keyword in basename_upper for keyword in ['GOSULUT', 'GOSULUT_ID', 'SULUT']):
            metadata['source'] = 'GOSULUT.ID'
        # Habari variations
        elif 'HABARI' in basename_upper:
            metadata['source'] = 'Habari.id'
        # CoolTurnesia variations
        elif any(keyword in basename_upper for keyword in ['COOLTURNESIA', 'COOL_TURNESIA', 'COOLTURNESIA_COM']):
            metadata['source'] = 'COOLTURNESIA.COM'
        # Rakyat Gorontalo variations
        elif any(keyword in basename_upper for keyword in ['RAKYATGORONTALO', 'RAKYAT_GORONTALO']):
            metadata['source'] = 'RakyatGorontalo.com'
        # GoPOS variations
        elif any(keyword in basename_upper for keyword in ['GOPOS', 'GO_POS']):
            metadata['source'] = 'GoPOS.id'
        # Antara variations
        elif 'ANTARA' in basename_upper:
            metadata['source'] = 'Antara News'
        # Berita Pemerintah Daerah Gorontalo
        elif any(keyword in basename_upper for keyword in ['PEMERINTAH', 'DAERAH', 'GORONTALOPROV']):
            metadata['source'] = 'Berita Pemerintah Daerah Gorontalo'

        return metadata

    def extract_source_from_pdf_content(self, pdf_path: str) -> str:
        """
        Ekstrak sumber koran dari konten PDF, khususnya dari header halaman pertama
        Fokus pada koran-koran Gorontalo yang ada di sistem scraping

        Returns:
            str: Nama sumber koran atau 'unknown' jika tidak ditemukan
        """
        try:
            loader = PyMuPDFLoader(pdf_path)
            documents = loader.load()

            if not documents:
                return 'unknown'

            # Ambil halaman pertama
            first_page_content = documents[0].page_content

            # Pattern khusus untuk koran Gorontalo (berdasarkan scraper yang ada)
            gorontalo_newspapers = [
                # Exact matches dari scraper files
                r'(GOSULUT\.ID)',
                r'(COOLTURNESIA\.COM)',
                r'(RakyatGorontalo\.com)',
                r'(Habari\.id)',
                r'(Berita Pemerintah Daerah Gorontalo)',
                r'(GoPOS\.id)',
                r'(Antara News)',
                r'(GorontaloPost)',

                # Variations dan pola umum Gorontalo
                r'(Gorontalo Post)',
                r'(Go Post)',
                r'(GO Post)',
                r'(Gorontalo Pos)',
                r'(Pos Gorontalo)',
                r'(Harian Gorontalo)',
                r'(Gorontalo News)',
                r'(Berita Gorontalo)',
                r'(Koran Gorontalo)',
                r'(Media Gorontalo)',
                r'(Suara Gorontalo)',
                r'(Warta Gorontalo)',

                # Pola dengan kata kunci Gorontalo
                r'(\w+\s+GORONTALO)',
                r'(GORONTALO\s+\w+)',
                r'(GOSULUT)',
                r'(GoSulut)',
                r'(Sulut News)',
                r'(Manado Post)',
                r'(Manado Today)',

                # Pola umum untuk koran digital
                r'(Habari)',
                r'(GoPos)',
                r'(Go POS)',
                r'(CoolTurnesia)',
                r'(Cool Turnesia)',
            ]

            # Cari di 600 karakter pertama (biasanya header + subheader)
            header_text = first_page_content[:600].upper()

            for pattern in gorontalo_newspapers:
                match = re.search(pattern.upper(), header_text)
                if match:
                    # Return the matched group, but clean it up
                    source = match.group(1)
                    # Clean up common formatting
                    source = re.sub(r'\s+', ' ', source).strip()

                    # Map to standard names used in scrapers
                    source_mapping = {
                        'GORONTALO POST': 'Gorontalo Post',
                        'GO POST': 'Gorontalo Post',
                        'GORONTALOPOST': 'Gorontalo Post',
                        'GOSULUT.ID': 'GOSULUT.ID',
                        'GOSULUT': 'GOSULUT.ID',
                        'COOLTURNESIA.COM': 'COOLTURNESIA.COM',
                        'COOLTURNESIA': 'COOLTURNESIA.COM',
                        'RAKYATGORONTALO.COM': 'RakyatGorontalo.com',
                        'HABARI.ID': 'Habari.id',
                        'HABARI': 'Habari.id',
                        'GOPOS.ID': 'GoPOS.id',
                        'GOPOS': 'GoPOS.id',
                        'ANTARA NEWS': 'Antara News',
                        'BERITA PEMERINTAH DAERAH GORONTALO': 'Berita Pemerintah Daerah Gorontalo',
                    }

                    # Apply mapping if exists
                    return source_mapping.get(source.upper(), source.title())

            # Jika tidak ditemukan pattern spesifik, coba deteksi berdasarkan kata kunci
            if 'GORONTALO' in header_text and 'POST' in header_text:
                return 'Gorontalo Post'
            elif 'GOSULUT' in header_text:
                return 'GOSULUT.ID'
            elif 'HABARI' in header_text:
                return 'Habari.id'
            elif 'COOLTURNESIA' in header_text or 'COOL TURNESIA' in header_text:
                return 'COOLTURNESIA.COM'
            elif 'RAKYAT GORONTALO' in header_text:
                return 'RakyatGorontalo.com'
            elif 'ANTARA' in header_text:
                return 'Antara News'

        except Exception as e:
            print(f"[WARNING] Error extracting source from PDF content: {e}")

        return 'unknown'

    def load_and_split_pdf(self, pdf_path: str) -> tuple:
        """
        Load PDF dan split menjadi chunks untuk processing

        Returns:
            tuple: (chunks, metadata)
        """
        print(f"[INFO] Loading PDF: {pdf_path}")

        # Load PDF menggunakan PyMuPDFLoader
        loader = PyMuPDFLoader(pdf_path)
        documents = loader.load()

        # Ekstrak metadata dari filename
        metadata = self.extract_metadata_from_filename(pdf_path)

        # Jika source masih 'unknown', coba ekstrak dari konten PDF
        if metadata['source'] == 'unknown':
            content_source = self.extract_source_from_pdf_content(pdf_path)
            if content_source != 'unknown':
                metadata['source'] = content_source
                print(f"[INFO] Source extracted from PDF content: {content_source}")

        # Filter out pages with minimal content (mostly images)
        filtered_documents = []
        for i, doc in enumerate(documents):
            content_length = len(doc.page_content.strip())

            # Skip pages with very little text content (likely image-only pages)
            if content_length < 100:  # Threshold for meaningful text content
                print(f"[INFO] Skipping page {i+1} - minimal text content ({content_length} chars)")
                continue

            filtered_documents.append(doc)

        print(f"[INFO] PDF loaded: {len(documents)} total pages, {len(filtered_documents)} pages with content")

        # Split filtered documents menjadi chunks
        if filtered_documents:
            chunks = self.text_splitter.split_documents(filtered_documents)
            print(f"[INFO] Split into {len(chunks)} chunks")
        else:
            chunks = []

        return chunks, metadata

    def create_extraction_prompt(self) -> ChatPromptTemplate:
        """Buat prompt template untuk ekstraksi artikel"""

        template = """

        PERAN:
        Anda adalah AI yang bertugas mengekstrak artikel berita dari teks koran Indonesia.

        TUGAS:
        Ekstrak semua ARTIKEL BERITA dari teks halaman berikut:

        {text}

        =====================
        1️⃣ IDENTIFIKASI ARTIKEL BERITA
        =====================
        Sebuah teks dianggap artikel berita jika:
        - Memiliki judul di awal artikel yang terpisah dari paragraf konten
        - Diikuti narasi berita (bukan daftar/pengumuman)
        - Konten akhir minimal 50 kata
        - Bukan iklan, pengumuman, ucapan, jadwal, caption foto, kolom opini, atau kotak informasi

        Jika ragu apakah suatu teks adalah artikel berita, abaikan.

        =====================
        2️⃣ ATURAN JUDUL DAN KONTEN
        =====================
        - Judul hanya diambil dari bagian awal artikel, bukan dari dalam paragraf
        - Jangan membuat judul baru
        - Konten dimulai dari paragraf pertama setelah judul
        - Jangan menambahkan opini, ringkasan, atau interpretasi

        =====================
        3️⃣ ARTIKEL BERSAMBUNG ANTAR HALAMAN
        =====================
        Jika ditemukan penanda seperti:
        - "bersambung ke hal.", "bersambung ke halaman" → artikel belum selesai
        - "dari halaman", "lanjutan dari hal." → lanjutan artikel sebelumnya

        Aturan:
        - Gabungkan bagian artikel jika judul sama ATAU konteks peristiwa jelas sama
        - Hapus semua penanda halaman dari konten akhir
        - Jika bagian lanjutan tidak tersedia dalam teks yang diberikan, jangan ekstrak artikel tersebut

        =====================
        4️⃣ DATA YANG DIEKSTRAK
        =====================
        Untuk setiap artikel, hasilkan:

        - judul   : teks judul artikel saja
        - konten  : isi narasi berita lengkap (setelah penggabungan jika bersambung)
        - kategori: PILIH SATU KODE BPS dari daftar klasifikasi di bawah
        - halaman : {page_num} atau format "X,Y" jika artikel muncul di beberapa halaman
        - sumber  : nama koran yang muncul di header halaman

        =====================
        5️⃣ KLASIFIKASI KATEGORI (KODE BPS)
        =====================
        Pilih SATU kode berdasarkan bidang usaha utama yang dibahas:

        SEKTOR PERTANIAN & PERTAMBANGAN:
        - A1: Pertanian (Tanaman Pangan, Hortikultura, Perkebunan), peternakan, perburuan, dan jasa pertanian
        - A2: Kehutanan dan penebangan kayu
        - A3: Perikanan
        - B:  Pertambangan dan penggalian

        SEKTOR INDUSTRI:
        - C1: Industri makanan dan minuman
        - C2: Industri pengolahan
        - C3: Industri tekstil dan pakaian jadi
        - C4: Industri elektronika
        - C5: Industri kertas/barang dari kertas

        SEKTOR INFRASTRUKTUR & UTILITAS:
        - D: Pengadaan listrik, gas
        - E: Pengadaan air
        - F: Konstruksi

        SEKTOR PERDAGANGAN & JASA:
        - G1. Perdagangan, reparasi dan perawatan mobil dan sepeda motor
        - G2. Perdagangan eceran berbagai macam barang di toko, supermkarket/minimarket
        - G3. Perdagangan eceran kaki lima dan los pasar
        - H1: Angkutan darat
        - H2: laut
        - H3: Angkutan udara

        SEKTOR AKOMODASI & MAKANAN:
        - I1: Akomodasi hotel dan pondok wisata
        - I2: Penyediaan Makanan dan Minuman (Kedai, Restoran, dsb)

        SEKTOR JASA LAINNYA:
        - J: Informasi dan komunikasi
        - K: Jasa Keuangan
        - L: Real estate
        - MN: Jasa perusahaan
        - O: Administrasi Pemerintahan, Pertahanan dan Jaminan Sosial Wajib
        - P: Jasa Pendidikan
        - Q: Jasa Kesehatan dan Kegiatan Sosial
        - RSTU: Jasa lainnya

        Jika ragu → pilih UMUM.

        =====================
        6️⃣ ATURAN PENTING
        =====================
        - Jangan mengekstrak artikel yang masih terpotong
        - Jangan menggabungkan artikel berbeda topik
        - Jangan mengubah fakta
        - Jangan membuat artikel baru
        - Jangan menggabungkan dua artikel yang berbeda hanya karena sama topik atau kata kunci, jika judul dan konten berbeda, ekstrak sebagai dua artikel terpisah.
        
        {format_instructions}
        """

        prompt = ChatPromptTemplate.from_template(template)
        return prompt

    def extract_articles_from_chunk(self, chunk_text: str, page_num: int) -> List[NewsArticle]:
        """Ekstrak artikel dari satu chunk teks"""

        # Setup prompt dan parser
        prompt = self.create_extraction_prompt()
        chain = prompt | self.llm | self.parser

        try:
            # Jalankan ekstraksi
            result = chain.invoke({
                "text": chunk_text,
                "page_num": page_num + 1,  # Page numbering starts from 1
                "format_instructions": self.parser.get_format_instructions()
            })

            # Result berupa NewsArticlesList, ambil .articles
            if isinstance(result, NewsArticlesList):
                return result.articles
            elif isinstance(result, list):
                return result
            else:
                return []

        except Exception as e:
            print(f"[WARNING] Error extracting from chunk: {e}")
            return []

    def process_pdf(self, pdf_path: str) -> List[NewsArticle]:
        """Proses PDF lengkap dan ekstrak semua artikel"""

        print(f"[INFO] Starting extraction from: {pdf_path}")

        # Load dan split PDF
        chunks, metadata = self.load_and_split_pdf(pdf_path)

        all_articles = []
        chunk_count = 0

        # Process setiap chunk
        for i, chunk in enumerate(chunks):
            chunk_count += 1
            page_num = getattr(chunk, 'metadata', {}).get('page', i)

            print(f"[INFO] Processing chunk {chunk_count}/{len(chunks)} (page {page_num + 1})")

            # Ekstrak artikel dari chunk ini
            articles = self.extract_articles_from_chunk(
                chunk.page_content,
                page_num
            )

            # Set sumber untuk semua artikel
            for article in articles:
                article.sumber = metadata['source']

            all_articles.extend(articles)
            print(f"[INFO] Found {len(articles)} articles in this chunk")

        # Gabungkan artikel yang bersambung sebelum mengembalikan
        merged_articles = self.merge_continued_articles(all_articles)

        print(f"[SUCCESS] Extraction completed: {len(all_articles)} raw articles, {len(merged_articles)} final articles")
        return merged_articles

    def merge_continued_articles(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        """
        Gabungkan artikel yang bersambung di halaman berbeda

        Returns:
            List[NewsArticle]: Artikel yang telah digabungkan
        """
        if not articles:
            return articles

        # Sort articles by page number
        sorted_articles = sorted(articles, key=lambda x: x.halaman)

        merged = []
        current_article = None

        for article in sorted_articles:
            if current_article is None:
                current_article = article
                continue

            # Check if this article is a continuation of the current one
            if self._is_article_continuation(current_article, article):
                # Merge the articles
                current_article.konten += "\n\n[BERSAMBUNG DARI HALAMAN SEBELUMNYA]\n\n" + article.konten
                current_article.halaman = f"{current_article.halaman},{article.halaman}"
                print(f"[INFO] Merged continuation: '{article.judul}' -> '{current_article.judul}'")
            else:
                # Save current article and start new one
                merged.append(current_article)
                current_article = article

        # Don't forget the last article
        if current_article:
            merged.append(current_article)

        return merged

    def _is_article_continuation(self, article1: NewsArticle, article2: NewsArticle) -> bool:
        """
        Cek apakah article2 adalah kelanjutan dari article1

        Logic (more strict):
        - Halaman HARUS berurutan (page2 = page1 + 1)
        - Judul HARUS sama persis atau article2 judul sangat pendek/singkatan
        - Konten article2 HARUS dimulai dengan indikator kelanjutan
        - Article2 TIDAK boleh memiliki judul lengkap berbeda
        """
        # Check if pages are consecutive (page2 must be exactly page1 + 1)
        try:
            page1 = int(str(article1.halaman).split(',')[-1])  # Get last page if multiple
            page2 = int(str(article2.halaman).split(',')[0])  # Get first page if multiple

            if page2 != page1 + 1:  # Must be exactly next page
                return False
        except (ValueError, IndexError):
            return False

        # Check titles with stricter logic
        title1_lower = article1.judul.lower().strip()
        title2_lower = article2.judul.lower().strip()

        # Exact title match (most reliable)
        if title1_lower == title2_lower and len(title1_lower) > 10:  # Avoid very short titles
            # Additional check: article2 content must start with continuation indicators
            content_indicators = [
                'bersambung',
                'lanjutan',
                '(lanjutan',
                '(bersambung',
                'halaman',
                'baca juga'
            ]
            content2_lower = article2.konten.lower()[:300]  # Check first 300 chars
            has_continuation = any(indicator in content2_lower for indicator in content_indicators)

            if has_continuation:
                return True

        # Title is very short (2-4 words) and doesn't look like a new article title
        # This handles cases where model extracts short phrases as "titles" for continuations
        if (len(title2_lower.split()) <= 4 and
            not title2_lower.endswith('?') and  # Not a question
            not title2_lower.startswith(('dalam', 'dengan', 'untuk', 'pada', 'oleh')) and  # Not starting with common sentence starters
            title2_lower not in ['berita', 'artikel', 'koran', 'halaman']):  # Not generic words

            # Must have strong continuation indicators
            strong_indicators = ['bersambung', 'lanjutan', '(lanjutan', '(bersambung']
            content2_lower = article2.konten.lower()[:200]
            if any(indicator in content2_lower for indicator in strong_indicators):
                return True

        return False

    def save_results(self, articles: List[NewsArticle], output_dir: str = "./output"):
        """Simpan hasil ekstraksi ke berbagai format"""

        # Buat direktori output jika belum ada
        Path(output_dir).mkdir(exist_ok=True)

        # Get metadata from first article
        if not articles:
            print("[WARNING] No articles to save")
            return {}

        first_article = articles[0]
        sumber = first_article.sumber
        tanggal = first_article.tanggal

        # Create safe filename by removing colons and using only date part
        date_part = tanggal.split('T')[0].replace('-', '') if 'T' in tanggal else tanggal.replace('-', '')
        base_filename = f"berita_{sumber.lower().replace(' ', '_')}_{date_part}"

        # Simpan sebagai JSON terstruktur (list of articles)
        json_path = Path(output_dir) / f"{base_filename}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump([article.model_dump() for article in articles], f, ensure_ascii=False, indent=2)

        # Simpan sebagai format sederhana (kompatibel dengan kode existing)
        simple_articles = []
        for article in articles:
            simple_articles.append({
                "judul": article.judul,
                "content": article.konten
            })

        simple_json_path = Path(output_dir) / f"{base_filename}_simple.json"
        with open(simple_json_path, 'w', encoding='utf-8') as f:
            json.dump(simple_articles, f, ensure_ascii=False, indent=2)

        # Simpan sebagai CSV
        csv_path = Path(output_dir) / f"{base_filename}.csv"
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            import csv
            writer = csv.writer(f)

            # Header
            writer.writerow(['Judul', 'Konten', 'Kategori', 'Tanggal', 'Halaman', 'Sumber'])

            # Data
            for article in articles:
                writer.writerow([
                    article.judul,
                    article.konten,
                    article.kategori,
                    article.tanggal,
                    article.halaman,
                    article.sumber
                ])

        print(f"[INFO] Results saved to:")
        print(f"  - {json_path}")
        print(f"  - {simple_json_path}")
        print(f"  - {csv_path}")

        return {
            'structured_json': str(json_path),
            'simple_json': str(simple_json_path),
            'csv': str(csv_path)
        }

    def generate_file_description_ai(self, articles: List[NewsArticle], filename: str = "") -> FileDescription:
        """
        Generate deskripsi file koran menggunakan AI

        Args:
            articles: List artikel yang diekstrak dari PDF
            filename: Nama file PDF (opsional untuk konteks)

        Returns:
            FileDescription: Deskripsi AI-generated untuk file
        """
        if not articles:
            return FileDescription(
                description="File koran tidak berisi artikel yang dapat diekstrak.",
                main_topics=[],
                dominant_sectors=[]
            )

        # Prepare article summaries for AI
        article_summaries = []
        for article in articles[:10]:  # Limit to first 10 articles for context
            summary = f"Judul: {article.judul}\nKategori: {article.kategori}\nKonten singkat: {article.konten[:300]}..."
            article_summaries.append(summary)

        articles_text = "\n\n".join(article_summaries)

        # Create prompt for AI
        prompt = ChatPromptTemplate.from_template("""
        Analisis artikel-artikel dari file koran PDF berikut dan buat deskripsi yang komprehensif dalam bahasa Indonesia.

        NAMA FILE: {filename}
        JUMLAH ARTIKEL: {total_articles}

        ARTIKEL-ARTIKEL:
        {articles_text}

        KATEGORI BPS (KBLI) YANG TERSEDIA:
        - A1: Pertanian, Peternakan, Perburuan, Jasa Pertanian
        - A2: Kehutanan dan Penebangan Kayu
        - A3: Perikanan
        - B: Pertambangan dan Penggalian
        - C1: Industri Makanan dan Minuman
        - C2: Industri Pengolahan
        - C3: Industri Tekstil dan Pakaian Jadi
        - C4: Industri Elektronika
        - C5: Industri Kertas/barang dari Kertas
        - D: Pengadaan Listrik, Gas
        - E: Pengadaan Air
        - F: Konstruksi
        - G1: Perdagangan Mobil dan Sepeda Motor
        - G2: Perdagangan Eceran di Toko/Supermarket
        - G3: Perdagangan Eceran Kaki Lima/Los Pasar
        - H1: Angkutan Darat
        - H2: Angkutan Laut
        - H3: Angkutan Udara
        - I1: Akomodasi Hotel dan Pondok Wisata
        - I2: Penyediaan Makanan dan Minuman
        - J: Informasi dan Komunikasi
        - K: Jasa Keuangan
        - L: Real Estate
        - MN: Jasa Perusahaan
        - O: Administrasi Pemerintah, Pertahanan, Jaminan Sosial
        - P: Jasa Pendidikan
        - Q: Jasa Kesehatan dan Kegiatan Sosial
        - RSTU: Jasa lainnya
        - UMUM: Kategori umum

        TUGAS ANDA:
        1. Buat deskripsi singkat dan natural tentang isi file koran ini (maksimal 2-3 kalimat)
        2. Identifikasi 3-5 topik utama yang dibahas
        3. Identifikasi sektor BPS yang paling dominan

        OUTPUT HARUS DALAM FORMAT JSON:
        {{
            "description": "Deskripsi dalam bahasa Indonesia",
            "main_topics": ["topik1", "topik2", "topik3"],
            "dominant_sectors": ["sektor1", "sektor2"]
        }}

        Pastikan deskripsi informatif, natural, dan fokus pada konten utama file koran.
        """)

        # Setup parser untuk output terstruktur
        parser = PydanticOutputParser(pydantic_object=FileDescription)

        # Create chain
        chain = prompt | self.llm | parser

        try:
            # Invoke AI
            result = chain.invoke({
                "filename": filename,
                "total_articles": len(articles),
                "articles_text": articles_text,
                "format_instructions": parser.get_format_instructions()
            })

            return result

        except Exception as e:
            print(f"[WARNING] AI description generation failed: {e}")
            # Fallback to simple description
            categories = [article.kategori for article in articles if article.kategori]
            unique_categories = list(set(categories))

            return FileDescription(
                description=f"File koran berisi {len(articles)} artikel dengan kategori utama: {', '.join(unique_categories[:3])}. (Deskripsi AI gagal dibuat)",
                main_topics=["berita lokal", "informasi umum"],
                dominant_sectors=unique_categories[:3] if unique_categories else ["UMUM"]
            )

def main():
    """Main function untuk menjalankan ekstraksi"""

    print("LANGCHAIN AZURE OPENAI NEWSPAPER EXTRACTOR")
    print("=" * 60)

    # Inisialisasi extractor
    try:
        extractor = NewspaperExtractor()
    except ValueError as e:
        print(f"[ERROR] Configuration error: {e}")
        print("\nPastikan environment variables sudah di-set:")
        print("- AZURE_OPENAI_ENDPOINT")
        print("- AZURE_OPENAI_API_KEY")
        return

    # File PDF target
    pdf_file = "29.12.2025.GP.pdf"

    # Check if PDF exists
    if not os.path.exists(pdf_file):
        print(f"[ERROR] PDF file not found: {pdf_file}")
        return

    # Proses ekstraksi
    try:
        articles = extractor.process_pdf(pdf_file)

        # Tampilkan summary
        print("\n" + "=" * 60)
        print("EKSTRAKSI SELESAI")
        print(f"Total Artikel: {len(articles)}")
        print("=" * 60)

        # Tampilkan preview artikel
        if articles:
            print("\nPREVIEW ARTIKEL:")
            for i, article in enumerate(articles[:3], 1):
                print(f"\n{i}. {article.judul}")
                print(f"   Kategori: {article.kategori}")
                print(f"   Halaman: {article.halaman}")
                print(f"   Konten: {article.konten[:200]}...")

            if len(articles) > 3:
                print(f"\n... dan {len(articles) - 3} artikel lainnya")
        else:
            print("Tidak ada artikel yang ditemukan")

        # Simpan hasil
        saved_files = extractor.save_results(articles)

        print(f"\nFile output tersimpan di: {saved_files}")

    except Exception as e:
        print(f"[ERROR] Extraction failed: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
