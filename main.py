import flet as ft
import google.generativeai as genai
import PIL.Image
import json
import os
import piexif
from iptcinfo3 import IPTCInfo
import time
import shutil # Library untuk menyalin file

def main(page: ft.Page):
    page.title = "Stock AI Metadata Generator"
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

    # --- FUNGSI SAVE KE DOWNLOADS ---
    def get_download_path():
        """Mencari path folder Download di Android"""
        # Standar path Android
        return "/storage/emulated/0/Download"

    # --- FUNGSI INTI ---
    def embed_metadata_hardcore(file_path, title, keywords_str):
        try:
            # 1. EXIF Title
            try:
                exif_dict = piexif.load(file_path)
            except:
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
            
            exif_dict["0th"][piexif.ImageIFD.ImageDescription] = title.encode('utf-8')
            exif_dict["0th"][piexif.ImageIFD.XPTitle] = title.encode('utf-16le') # Windows Style
            exif_dict["0th"][200] = title.encode('utf-8') # ImageDescription alternative ID
            
            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, file_path)
            
            time.sleep(0.5)

            # 2. IPTC Keywords
            # KITA GUNAKAN LOGIKA BARU DI SINI
            info = IPTCInfo(file_path, force=True)
            
            # Bersihkan list keyword
            keyword_list = [k.strip() for k in keywords_str.split(',')]
            
            # Masukkan ke IPTC Standard
            info['keywords'] = keyword_list
            info['caption/abstract'] = title 
            info['object name'] = title
            
            # Save (iptcinfo3 menyimpan ke file baru/temp lalu rename)
            info.save()

            # Hapus file backup (~) yang dibuat iptcinfo
            backup_file = file_path + "~"
            if os.path.exists(backup_file):
                try: os.remove(backup_file)
                except: pass
                
            return True
        except Exception as e:
            print(f"Error embedding: {e}")
            return False

    def process_queue(e):
        if not api_key_field.value:
            page.show_snack_bar(ft.SnackBar(ft.Text("Masukkan API Key!")))
            return
        
        if not selected_files:
            return

        btn_process.disabled = True
        progress_bar.visible = True
        
        # Buat Folder Khusus di Downloads agar rapi
        download_folder = get_download_path()
        output_folder = os.path.join(download_folder, "Stock_AI_Result")
        
        # Coba buat folder, jika gagal (permission) lanjut saja
        try:
            if not os.path.exists(output_folder):
                os.makedirs(output_folder)
        except:
            # Fallback jika gagal buat folder, pakai folder Download utama
            output_folder = download_folder

        genai.configure(api_key=api_key_field.value)
        # Gunakan model yang Anda pastikan berhasil
        model = genai.GenerativeModel('gemini-2.5-flash') 

        total_files = len(selected_files)
        
        for index, file in enumerate(selected_files):
            # Path file sementara dari Flet
            temp_path = file.path
            file_name = file.name
            
            # Siapkan path tujuan di folder Download
            final_path = os.path.join(output_folder, f"TAGGED_{file_name}")

            files_table.rows[index].cells[1].content = ft.Text("Processing...", color=ft.Colors.ORANGE)
            status_text.value = f"Processing {index+1}/{total_files}: {file_name}"
            progress_bar.value = index / total_files
            page.update()

            try:
                # 1. Salin file dari Temp ke Folder Download DULU
                shutil.copy(temp_path, final_path)
                
                # 2. Analisa Gambar (Baca dari file baru)
                img = PIL.Image.open(final_path)
                
                prompt = """
                Act as a professional Stock Photography SEO Expert. Analyze the provided image to generate metadata optimized for Adobe Stock and Shutterstock algorithms.

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
                img.close() # Lepas lock file
                
                text_resp = response.text.replace("```json", "").replace("```", "").strip()
                data = json.loads(text_resp)
                
                title = data.get("title", "")
                keywords = data.get("keywords", "")

                files_table.rows[index].cells[1].content = ft.Text("Embedding...", color=ft.Colors.BLUE)
                page.update()
                
                # 3. Embed Metadata ke file yang ada di FOLDER DOWNLOAD
                if embed_metadata_hardcore(final_path, title, keywords):
                    files_table.rows[index].cells[1].content = ft.Text("Saved ✅", color=ft.Colors.GREEN)
                else:
                    files_table.rows[index].cells[1].content = ft.Text("Gagal ❌", color=ft.Colors.RED)

                time.sleep(1.0) 

            except Exception as err:
                print(f"Error: {err}")
                files_table.rows[index].cells[1].content = ft.Text(f"Error ❌", color=ft.Colors.RED)
            
            progress_bar.value = (index + 1) / total_files
            page.update()

        status_text.value = f"Selesai! Cek folder: Download/Stock_AI_Result"
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
                        ft.DataCell(ft.Text(f.name)),
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
        "Mulai & Simpan",
        icon=ft.Icons.SAVE_ALT,
        style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE),
        disabled=True,
        on_click=process_queue
    )
    
    btn_help = ft.ElevatedButton(
        text="Butuh Bantuan? Hubungi Kami",
        icon=ft.Icons.HELP_OUTLINE, 
        style=ft.ButtonStyle(color=ft.Colors.WHITE, bgcolor=ft.Colors.GREEN_600),
        width=float("inf"), 
        on_click=lambda _: page.launch_url(SUPPORT_URL)
    )

    # --- Layout ---
    page.add(
        ft.Column([
            ft.Text("Stock AI Metadata Generator", size=24, weight=ft.FontWeight.BOLD),
            ft.Text("Hasil akan disimpan di folder Downloads/Stock_AI_Result", size=12, color=ft.Colors.RED),
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
