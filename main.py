import flet as ft
import google.generativeai as genai
import PIL.Image
import json
import os
import piexif
from iptcinfo3 import IPTCInfo
import time

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

    # --- FUNGSI INTI ---
    def embed_metadata_hardcore(file_path, title, keywords_str):
        try:
            # 1. EXIF Title
            exif_dict = piexif.load(file_path)
            exif_dict["0th"][piexif.ImageIFD.ImageDescription] = title.encode('utf-8')
            exif_dict["0th"][piexif.ImageIFD.XPTitle] = title.encode('utf-16le')
            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, file_path)
            
            time.sleep(0.5)

            # 2. IPTC Keywords
            info = IPTCInfo(file_path, force=True)
            keyword_list = [k.strip() for k in keywords_str.split(',')]
            info['keywords'] = keyword_list
            info['caption/abstract'] = title 
            info.save()

            # 3. Hapus Backup
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
        
        genai.configure(api_key=api_key_field.value)
        model = genai.GenerativeModel('gemini-2.5-flash') 

        total_files = len(selected_files)
        
        for index, file in enumerate(selected_files):
            file_path = file.path
            file_name = file.name
            
            files_table.rows[index].cells[1].content = ft.Text("AI Generating...", color=ft.Colors.ORANGE)
            status_text.value = f"Processing {index+1}/{total_files}: {file_name}"
            progress_bar.value = index / total_files
            page.update()

            try:
                img = PIL.Image.open(file_path)
                
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
                img.close() # PENTING: Lepas file lock Windows
                
                text_resp = response.text.replace("```json", "").replace("```", "").strip()
                data = json.loads(text_resp)
                
                title = data.get("title", "")
                keywords = data.get("keywords", "")

                files_table.rows[index].cells[1].content = ft.Text("Embedding...", color=ft.Colors.BLUE)
                page.update()
                
                if embed_metadata_hardcore(file_path, title, keywords):
                    files_table.rows[index].cells[1].content = ft.Text("Sukses ✅", color=ft.Colors.GREEN)
                else:
                    files_table.rows[index].cells[1].content = ft.Text("Gagal ❌", color=ft.Colors.RED)

                time.sleep(1.0) 

            except Exception as err:
                print(f"Error: {err}")
                files_table.rows[index].cells[1].content = ft.Text(f"Error ❌", color=ft.Colors.RED)
            
            progress_bar.value = (index + 1) / total_files
            page.update()

        status_text.value = "Selesai! Metadata tersimpan."
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
        "Start Adding Metadata",
        icon=ft.Icons.SAVE_AS,
        style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE),
        disabled=True,
        on_click=process_queue
    )
    
    # --- TOMBOL BANTUAN ---
    btn_help = ft.ElevatedButton(
        text="Butuh Bantuan? Hubungi Kami",
        icon=ft.Icons.HELP_OUTLINE, # Ikon tanda tanya
        style=ft.ButtonStyle(
            color=ft.Colors.WHITE,
            bgcolor=ft.Colors.GREEN_600, # Warna hijau khas chat app
        ),
        width=float("inf"), # Tombol melebar penuh
        on_click=lambda _: page.launch_url(SUPPORT_URL)
    )

    # --- Final Layout ---
    page.add(
        ft.Column([
            ft.Text("Stock AI Metadata Generator", size=24, weight=ft.FontWeight.BOLD),
            ft.Text("Otomatis Menambahkan Judul & Keyword ke Image.", size=12),
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
            ft.Divider(), # Pemisah antara fitur utama dan support
            ft.Container(height=20), # Jarak kosong
            btn_help # Tombol bantuan ditaruh paling bawah
        ])
    )

ft.app(target=main, assets_dir="assets")
