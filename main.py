import flet as ft
import json
import os
import time
import shutil
import tempfile
import re
import asyncio
import itertools
import io # Penting untuk In-Memory processing

# --- CLASS MANAGER API KEY ---
class KeyManager:
    def __init__(self, keys_str):
        self.keys = [k.strip() for k in keys_str.split(',') if k.strip()]
        self.iterator = itertools.cycle(self.keys)
        self.current_key = next(self.iterator) if self.keys else None

    def get_next(self):
        if not self.keys: return None
        self.current_key = next(self.iterator)
        return self.current_key
    
    def get_current(self):
        return self.current_key

def main(page: ft.Page):
    page.title = "Ai Metadata Pro (Optimized)"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.scroll = ft.ScrollMode.ADAPTIVE
    page.padding = 20
    page.window_prevent_close = True 

    selected_files = [] 
    is_processing = False 
    
    # Counter untuk progress bar saat parallel
    processed_count = 0 

    # --- UI Components ---
    saved_keys = page.client_storage.get("gemini_api_keys")
    
    api_key_field = ft.TextField(
        label="Gemini API Keys (Pisahkan dengan koma)",
        hint_text="Key1, Key2, Key3...",
        multiline=True,
        min_lines=1,
        max_lines=3,
        value=saved_keys if saved_keys else "",
        border_color=ft.Colors.BLUE,
        on_change=lambda e: page.client_storage.set("gemini_api_keys", api_key_field.value)
    )

    # Checkbox Turbo Mode
    chk_turbo = ft.Checkbox(
        label="Turbo Mode (Parallel Processing)", 
        value=False,
        tooltip="Memproses 2 gambar sekaligus. Butuh RAM lebih besar."
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

    # --- PATH UTILITIES ---
    def get_download_path():
        return "/storage/emulated/0/Download"

    # --- HELPER FUNCTIONS ---
    def extract_json(text):
        try:
            # Bersihkan markdown jika AI bandel
            text = text.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match: return json.loads(match.group())
        except: pass
        return None

    def sanitize_image_sync(input_path, output_path):
        import PIL.Image
        try:
            img = PIL.Image.open(input_path)
            img = img.convert('RGB')
            # Kita simpan full resolution ke disk untuk hasil akhir
            img.save(output_path, "JPEG", quality=100, optimize=True)
            img.close()
            return True
        except Exception as e:
            return False

    def embed_metadata_strict_sync(work_path, title, keywords_str):
        import piexif
        from iptcinfo3 import IPTCInfo
        try:
            keyword_list = [k.strip() for k in keywords_str.split(',')]
            
            # EXIF
            try: exif_dict = piexif.load(work_path)
            except: exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
            
            exif_dict["0th"][piexif.ImageIFD.ImageDescription] = title.encode('utf-8')
            exif_dict["0th"][piexif.ImageIFD.XPTitle] = title.encode('utf-16le')
            xp_keywords = ";".join(keyword_list)
            exif_dict["0th"][piexif.ImageIFD.XPKeywords] = xp_keywords.encode('utf-16le')
            piexif.insert(piexif.dump(exif_dict), work_path)
            
            # IPTC
            info = IPTCInfo(work_path, force=True)
            info.set_encoding('utf-8') 
            info['keywords'] = keyword_list
            info['caption/abstract'] = title 
            info['object name'] = title
            info['headline'] = title
            info.save() 
            
            if os.path.exists(work_path + "~"): os.remove(work_path + "~")
            return True, "Complete"
        except Exception as e:
            return False, str(e)

    # --- CORE WORKER (SINGLE IMAGE PROCESSOR) ---
    async def process_single_image(index, file, key_manager, final_output_folder, temp_dir, semaphore):
        # Lazy Import
        import google.generativeai as genai
        from google.generativeai.types import HarmCategory, HarmBlockThreshold
        import PIL.Image

        nonlocal processed_count
        
        # Gunakan Semaphore untuk membatasi jumlah parallel
        async with semaphore:
            if not is_processing: return # Cek jika user stop

            file_name = file.name
            final_path = os.path.join(final_output_folder, f"READY_{file_name}")

            # 1. Skip jika sudah ada
            if os.path.exists(final_path):
                files_table.rows[index].cells[1].content = ft.Text("Skipped (Done)", color=ft.Colors.GREY)
                files_table.update() # Partial Update
                
                processed_count += 1
                progress_bar.value = processed_count / len(selected_files)
                progress_bar.update() # Partial Update
                return

            # 2. Update Status Cleaning
            files_table.rows[index].cells[1].content = ft.Text("Cleaning...", color=ft.Colors.ORANGE)
            files_table.update()

            work_path = os.path.join(temp_dir, f"TEMP_{int(time.time())}_{index}_{file_name}")

            try:
                # Sanitize (Disk I/O)
                is_clean = await asyncio.to_thread(sanitize_image_sync, file.path, work_path)
                if not is_clean: raise Exception("File Corrupt")

                files_table.rows[index].cells[1].content = ft.Text("AI Generating...", color=ft.Colors.BLUE)
                files_table.update()

                # --- OPTIMASI IN-MEMORY & DOWNSCALE ---
                # Baca file temp, kecilkan di RAM, kirim bytes ke AI
                # Ini menghemat bandwidth upload ke Gemini
                img_bytes = None
                def prepare_image_for_ai():
                    with PIL.Image.open(work_path) as img:
                        img.thumbnail((1024, 1024)) # Resize max 1024px
                        buf = io.BytesIO()
                        img.save(buf, format='JPEG', quality=80)
                        return buf.getvalue()
                
                img_bytes = await asyncio.to_thread(prepare_image_for_ai)

                # AI Process
                max_retries = 3
                ai_success = False
                title, keywords = "", ""
                
                for attempt in range(max_retries):
                    if not is_processing: break # Cek stop di tengah retry

                    current_key = key_manager.get_current()
                    genai.configure(api_key=current_key)
                    
                    safety_config = {
                        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                    }
                    model = genai.GenerativeModel('gemini-2.5-flash', safety_settings=safety_config)
                    
                    try:
                        prompt = """
                                Act as a professional Stock Photography SEO Expert. Analyze the provided image to generate metadata optimized for Adobe Stock and Shutterstock algorithms.

                                Your output must be strictly in JSON format with two fields: "title" and "keywords".

                                Follow these rules:
                                1. TITLE (Max 200 chars):
                                   - Structure: [Main Subject] + [Action/State] + [Context/Background].
                                   - Example: "Happy business woman using laptop in modern office near window"
                                   - Focus on "Findability". The first 5 words are the most important.
                                
                                2. KEYWORDS (Target 50 words):
                                   - Generate extensive tags separated by commas.
                                   - HIERARCHY IS CRITICAL:
                                     * 1-10: Main Subject, Primary Action, Key Objects (Visuals).
                                     * 11-30: Conceptual, Mood, Lighting, Style (e.g., cinematic, bright, minimalism).
                                     * 31-50: Broader categories and associations.
                                   - Use lowercase only.
                                   - Include specific visual descriptors (colors, materials, age, ethnicity if humans).
                                
                                3. RESTRICTIONS:
                                   - NO Trademarked names (e.g., no 'iPhone', use 'smartphone').
                                   - NO Brand logos.
                                   - NO Celebrity names.

                                Output structure example:
                                {
                                  "title": "A concise description of the image",
                                  "keywords": "keyword1, keyword2, keyword3, ..."
                                }
                                """
                        
                        # Kirim BYTES langsung ke model (In-Memory)
                        response = await asyncio.to_thread(
                            model.generate_content, 
                            [prompt, {"mime_type": "image/jpeg", "data": img_bytes}]
                        )
                        
                        if not response.parts: raise Exception("Safety Block")
                        data = extract_json(response.text)
                        
                        if data:
                            title = data.get("title", "")
                            keywords = data.get("keywords", "")
                            ai_success = True
                            break 
                        else:
                            raise Exception("JSON Error")

                    except Exception as api_err:
                        err_msg = str(api_err)
                        if "429" in err_msg or "ResourceExhausted" in err_msg:
                            key_manager.get_next()
                            await asyncio.sleep(1) 
                        else:
                            # Jika error fatal, jangan retry
                            break
                
                if not ai_success: raise Exception("AI Failed/Limit")

                # 3. Embedding (Disk I/O pada work_path)
                files_table.rows[index].cells[1].content = ft.Text("Saving...", color=ft.Colors.PURPLE)
                files_table.update()
                
                success, msg = await asyncio.to_thread(embed_metadata_strict_sync, work_path, title, keywords)
                
                if success:
                    shutil.move(work_path, final_path)
                    files_table.rows[index].cells[1].content = ft.Text("SUCCESS ✅", color=ft.Colors.GREEN)
                else:
                    files_table.rows[index].cells[1].content = ft.Text("FAIL ❌", color=ft.Colors.RED)

            except Exception as e:
                files_table.rows[index].cells[1].content = ft.Text("Error ❌", color=ft.Colors.RED, tooltip=str(e))
            
            files_table.update() # Partial Update akhir
            
            # Cleanup
            if os.path.exists(work_path):
                try: os.remove(work_path)
                except: pass
            
            processed_count += 1
            progress_bar.value = processed_count / len(selected_files)
            progress_bar.update()

    # --- MAIN CONTROLLER ---
    async def toggle_process(e):
        nonlocal is_processing, processed_count
        
        if not selected_files:
            page.show_snack_bar(ft.SnackBar(ft.Text("Pilih gambar dulu!")))
            return
        
        if not api_key_field.value:
            page.show_snack_bar(ft.SnackBar(ft.Text("Masukkan API Key!")))
            return

        # --- TOMBOL START DITEKAN ---
        if not is_processing:
            is_processing = True
            processed_count = 0
            
            # UI Changes
            btn_action.text = "STOP PROSES"
            btn_action.icon = ft.Icons.STOP_CIRCLE_OUTLINED
            btn_action.bgcolor = ft.Colors.RED_600
            btn_action.update() # Partial Update
            
            progress_bar.visible = True
            progress_bar.value = 0
            progress_bar.update()
            
            status_text.value = "Menyiapkan worker..."
            status_text.update()

            # Setup Environment
            download_folder = get_download_path()
            final_output_folder = os.path.join(download_folder, "Stock_AI_Result")
            os.makedirs(final_output_folder, exist_ok=True)
            key_manager = KeyManager(api_key_field.value)
            temp_dir = tempfile.gettempdir()
            
            # --- PARALLEL LOGIC ---
            # Tentukan jumlah worker berdasarkan checkbox
            worker_limit = 2 if chk_turbo.value else 1
            sem = asyncio.Semaphore(worker_limit)
            
            status_text.value = f"Memproses dengan {worker_limit} worker..."
            status_text.update()

            # Buat Task List
            tasks = []
            for index, file in enumerate(selected_files):
                tasks.append(
                    process_single_image(index, file, key_manager, final_output_folder, temp_dir, sem)
                )
            
            # Jalankan semua task (Asyncio Gather)
            await asyncio.gather(*tasks)

            # Selesai Loop
            is_processing = False
            status_text.value = "Proses Selesai."
            
            # Reset UI
            btn_action.text = "MULAI PROSES"
            btn_action.icon = ft.Icons.ROCKET_LAUNCH
            btn_action.bgcolor = ft.Colors.BLUE_700
            btn_action.disabled = False
            progress_bar.visible = False
            
            page.update() # Update final halaman

        # --- TOMBOL STOP DITEKAN ---
        else:
            is_processing = False # Flag dimatikan, worker akan return early
            btn_action.text = "MENGHENTIKAN..."
            btn_action.bgcolor = ft.Colors.GREY
            btn_action.disabled = True
            btn_action.update()
            status_text.value = "Menunggu worker berhenti..."
            status_text.update()
            # Tidak ada logic break manual disini karena asyncio.gather akan selesai 
            # secara alami saat worker mendeteksi is_processing = False

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
            files_table.update()
            
            btn_action.disabled = False 
            btn_action.update()
            
            status_text.value = f"{len(selected_files)} gambar dipilih."
            status_text.update()

    file_picker = ft.FilePicker(on_result=on_files_picked)
    page.overlay.append(file_picker)

    # --- Buttons & UI Construction ---
    btn_pick = ft.ElevatedButton(
        "Pilih Gambar", 
        icon=ft.Icons.PHOTO_LIBRARY, 
        on_click=lambda _: file_picker.pick_files(allow_multiple=True, file_type=ft.FilePickerFileType.IMAGE)
    )
    
    btn_action = ft.ElevatedButton(
        text="MULAI PROSES", 
        icon=ft.Icons.ROCKET_LAUNCH, 
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.BLUE_700, 
            color=ft.Colors.WHITE,
            shape=ft.RoundedRectangleBorder(radius=8),
        ), 
        disabled=True,
        height=50,
        on_click=toggle_process
    )

    page.add(
        ft.Column([
            ft.Text("Ai Metadata Pro (Optimized)", size=24, weight=ft.FontWeight.BOLD),
            ft.Divider(),
            api_key_field,
            ft.Container(height=5),
            chk_turbo, # Checkbox baru
            ft.Container(height=10),
            ft.Row([btn_pick, ft.Container(expand=True)]),
            ft.Container(height=10),
            ft.Container(content=btn_action, width=float("inf")),
            ft.Container(height=10),
            files_table,
            progress_bar,
            status_text,
        ], scroll=ft.ScrollMode.ADAPTIVE)
    )

ft.app(target=main)
