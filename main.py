import flet as ft
import google.generativeai as genai
import PIL.Image
import json
import os
import piexif
from iptcinfo3 import IPTCInfo
import time
import shutil
import tempfile
import re

def main(page: ft.Page):
    page.title = "Stock AI - Strict Mode"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.scroll = ft.ScrollMode.ADAPTIVE
    page.padding = 20
    SUPPORT_URL = "https://wa.me/6281229689225" 

    selected_files = [] 
    
    # --- UI Components ---
    api_key_field = ft.TextField(
        label="Gemini API Key",
        password=True,
        can_reveal_password=True, 
        border_color=ft.Colors.BLUE
    )

    files_table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("File Name")),
            ft.DataColumn(ft.Text("Status")),
        ],
        rows=[],
        visible=False,
        width=float("inf") 
    )
    
    status_text = ft.Text("Siap memilih gambar.", color=ft.Colors.GREY)
    progress_bar = ft.ProgressBar(visible=False, value=0)

    # --- PATH ANDROID ---
    def get_download_path():
        return "/storage/emulated/0/Download"

    # --- JSON PARSER PINTAR ---
    def extract_json(text):
        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
            else:
                return None
        except:
            return None

    # --- FUNGSI PEMBERSIH GAMBAR (KUNCI SUKSES) ---
    def sanitize_image(input_path, output_path):
        """
        Membuka gambar dan menyimpannya ulang untuk memperbaiki header JPG yang rusak.
        Ini membuat iptcinfo3 bekerja 100% lebih stabil.
        """
        try:
            img = PIL.Image.open(input_path)
            # Convert ke RGB untuk jaga-jaga (jika ada file PNG/RGBA)
            img = img.convert('RGB')
            # Simpan ulang dengan kualitas tinggi tanpa metadata sampah
            img.save(output_path, "JPEG", quality=100, optimize=True)
            img.close()
            return True
        except Exception as e:
            print(f"Sanitize Error: {e}")
            return False

    # --- INTI METADATA (STRICT) ---
    def embed_metadata_strict(work_path, title, keywords_str):
        try:
            keyword_list = [k.strip() for k in keywords_str.split(',')]
            
            # ---------------------------------------------------------
            # 1. ISI EXIF (Title + XPKeywords sebagai Backup Kuat)
            # ---------------------------------------------------------
            try:
                exif_dict = piexif.load(work_path)
            except:
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
            
            # Masukkan Title
            exif_dict["0th"][piexif.ImageIFD.ImageDescription] = title.encode('utf-8')
            exif_dict["0th"][piexif.ImageIFD.XPTitle] = title.encode('utf-16le')
            
            # TRICK: Masukkan Keyword juga ke EXIF XPKeywords (Dibaca Adobe)
            # Ini sangat membantu jika IPTC gagal
            xp_keywords = ";".join(keyword_list) # Windows pake pemisah titik koma
            exif_dict["0th"][piexif.ImageIFD.XPKeywords] = xp_keywords.encode('utf-16le')
            
            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, work_path)
            
            # ---------------------------------------------------------
            # 2. ISI IPTC (Standard Adobe Stock)
            # ---------------------------------------------------------
            # Karena gambar sudah di-sanitize, ini harusnya tidak fail lagi
            info = IPTCInfo(work_path, force=True)
            
            info['keywords'] = keyword_list
            info['caption/abstract'] = title 
            info['object name'] = title
            info['headline'] = title
            
            info.save() # Simpan perubahan
            
            # Hapus file backup ~
            if os.path.exists(work_path + "~"):
                os.remove(work_path + "~")

            return True, "Complete"
            
        except Exception as e:
            # Jika ada yang error, kita lempar False agar user tahu
            return False, str(e)

    def process_queue(e):
        if not api_key_field.value:
            page.show_snack_bar(ft.SnackBar(ft.Text("Masukkan API Key!")))
            return
        
        if not selected_files:
            return

        btn_process.disabled = True
        progress_bar.visible = True
        
        # Folder Tujuan Akhir
        download_folder = get_download_path()
        final_output_folder = os.path.join(download_folder, "Stock_AI_Final")
        
        try:
            if not os.path.exists(final_output_folder):
                os.makedirs(final_output_folder)
        except:
            final_output_folder = download_folder

        temp_dir = tempfile.gettempdir() 
        genai.configure(api_key=api_key_field.value)
        model = genai.GenerativeModel('gemini-2.5-flash') 

        total_files = len(selected_files)
        
        for index, file in enumerate(selected_files):
            file_name = file.name
            # Buat nama unik agar tidak bentrok
            work_path = os.path.join(temp_dir, f"TEMP_{int(time.time())}_{file_name}")
            
            # Update UI
            files_table.rows[index].cells[1].content = ft.Text("Cleaning Image...", color=ft.Colors.ORANGE)
            page.update()

            try:
                # LANGKAH 1: SANITASI (Bersihkan Header Gambar)
                # Kita tidak pakai shutil.copy, tapi pakai Pillow save ulang
                # Ini kunci agar IPTC tidak error!
                if not sanitize_image(file.path, work_path):
                    raise Exception("Gagal membersihkan file gambar")

                # LANGKAH 2: AI PROCESS
                files_table.rows[index].cells[1].content = ft.Text("AI Generating...", color=ft.Colors.BLUE)
                page.update()
                
                img = PIL.Image.open(work_path)
                
                prompt = """Act as a professional Stock Photography SEO Expert. Analyze the provided image to generate metadata optimized for Adobe Stock and Shutterstock algorithms.

Your output must be strictly in JSON format with two fields: "title" and "keywords".

Follow these rules:
1. TITLE:
   - Create a descriptive, natural sentence (max 15 words).
   - Focus on the subject, action, and context.
   - Do NOT use ID numbers or filler words.

2. KEYWORDS:
   - Generate exactly 40-50 keywords.
   - Order is CRITICAL: Place the 7 most important visual keywords first (Subject, Action, Main Object), followed by conceptual keywords (Mood, Emotion, Business Concept), and finally technical details (Lighting, Viewpoint).
   - Separate keywords with commas.
   - All text must be in English.
   - STRICTLY NO TRADEMARKS, NO BRAND NAMES, and NO CELEBRITY NAMES.

Output structure example:
{
  "title": "A concise description of the image",
  "keywords": "keyword1, keyword2, keyword3, ..."
}
"""
                
                response = model.generate_content([prompt, img])
                img.close() # Close agar bisa diedit
                
                # Cek Safety
                if not response.parts:
                    raise Exception("Gambar Ditolak AI (Safety)")
                
                # Cek JSON
                data = extract_json(response.text)
                if not data:
                    raise Exception("Format JSON Error")

                title = data.get("title", "")
                keywords = data.get("keywords", "")
                
                if not title or not keywords:
                     raise Exception("AI Output Kosong")

                # LANGKAH 3: EMBEDDING
                files_table.rows[index].cells[1].content = ft.Text("Injecting...", color=ft.Colors.PURPLE)
                page.update()
                
                success, msg = embed_metadata_strict(work_path, title, keywords)
                
                if success:
                    # LANGKAH 4: PINDAHKAN KE PUBLIC
                    final_path = os.path.join(final_output_folder, f"READY_{file_name}")
                    shutil.move(work_path, final_path)
                    
                    files_table.rows[index].cells[1].content = ft.Text("SUCCESS ✅", color=ft.Colors.GREEN)
                else:
                    # Gagal Embed -> Gagal Total
                    files_table.rows[index].cells[1].content = ft.Text(f"Embed Fail ❌", color=ft.Colors.RED)

            except Exception as err:
                print(f"Error: {err}")
                error_msg = str(err)
                if "429" in error_msg:
                    short_err = "Quota Habis ⏳"
                else:
                    short_err = "Failed ❌"
                
                files_table.rows[index].cells[1].content = ft.Text(short_err, color=ft.Colors.RED, tooltip=error_msg)
            
            # Cleanup jika file temp masih ada (karena error)
            if os.path.exists(work_path):
                try: os.remove(work_path)
                except: pass
            
            progress_bar.value = (index + 1) / total_files
            page.update()

        status_text.value = f"Selesai! Cek Folder: Download/Stock_AI_Final"
        progress_bar.visible = False
        btn_process.disabled = False
        page.update()

    def on_files_picked(e: ft.FilePickerResultEvent):
        nonlocal selected_files
        if e.files:
            selected_files = e.files
            files_table.rows.clear()
            for f in selected_files:
                files_table.rows.append(
                    ft.DataRow(cells=[
                        ft.DataCell(ft.Text(f.name[:20])),
                        ft.DataCell(ft.Text("Waiting")),
                    ])
                )
            files_table.visible = True
            btn_process.disabled = False
            status_text.value = f"{len(selected_files)} gambar dipilih."
            page.update()

    file_picker = ft.FilePicker(on_result=on_files_picked)
    page.overlay.append(file_picker)

    # --- UI Elements ---
    btn_pick = ft.ElevatedButton(
        "Pilih Gambar",
        icon=ft.Icons.PHOTO_LIBRARY,
        on_click=lambda _: file_picker.pick_files(allow_multiple=True, file_type=ft.FilePickerFileType.IMAGE)
    )

    btn_process = ft.ElevatedButton(
        "Mulai Proses Strict",
        icon=ft.Icons.ROCKET_LAUNCH,
        style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE),
        disabled=True,
        on_click=process_queue
    )
    
    btn_help = ft.ElevatedButton(
        text="Hubungi Admin (WhatsApp)",
        icon=ft.Icons.CHAT, 
        style=ft.ButtonStyle(color=ft.Colors.WHITE, bgcolor=ft.Colors.GREEN_600),
        width=float("inf"), 
        on_click=lambda _: page.launch_url(SUPPORT_URL)
    )

    # --- Layout ---
    page.add(
        ft.Column([
            ft.Text("Stock AI (Strict Mode)", size=24, weight=ft.FontWeight.BOLD),
            ft.Text("Semua Metadata Wajib Masuk atau Gagal.", size=12, color=ft.Colors.RED),
            ft.Divider(),
            api_key_field,
            ft.Container(height=10),
            btn_pick,
            ft.Container(height=10),
            files_table,
            progress_bar,
            status_text,
            ft.Container(height=10),
            btn_process,
            ft.Divider(),
            ft.Container(height=20), 
            btn_help 
        ])
    )

ft.app(target=main)
