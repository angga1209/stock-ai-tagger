import flet as ft
import json
import os
import time
import shutil
import tempfile
import re
import asyncio
import itertools

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
    page.title = "Ai Metadata Generator Pro"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.scroll = ft.ScrollMode.ADAPTIVE
    page.padding = 20
    page.window_prevent_close = True 

    selected_files = [] 
    is_processing = False 

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
        # Android path fallback
        return "/storage/emulated/0/Download"

    # --- HELPER FUNCTIONS ---
    def extract_json(text):
        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match: return json.loads(match.group())
        except: pass
        return None

    def sanitize_image_sync(input_path, output_path):
        # LAZY IMPORT: Hanya diload saat membersihkan gambar
        import PIL.Image
        try:
            img = PIL.Image.open(input_path)
            img = img.convert('RGB')
            img.save(output_path, "JPEG", quality=100, optimize=True)
            img.close()
            return True
        except Exception as e:
            return False

    def embed_metadata_strict_sync(work_path, title, keywords_str):
        # LAZY IMPORT: Hanya diload saat menyimpan metadata
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
            # Fix Encoding issue
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

    # --- CORE PROCESS (ASYNC) ---
    async def process_queue(e):
        # LAZY IMPORT: Library TERBERAT ditaruh di sini
        # Agar aplikasi cepat terbuka di awal
        import google.generativeai as genai
        from google.generativeai.types import HarmCategory, HarmBlockThreshold
        import PIL.Image

        nonlocal is_processing
        
        if not api_key_field.value:
            page.show_snack_bar(ft.SnackBar(ft.Text("Masukkan API Key!")))
            return
        
        if not selected_files:
            return

        is_processing = True
        btn_process.disabled = True
        btn_stop.disabled = False
        progress_bar.visible = True
        page.update()
        
        download_folder = get_download_path()
        final_output_folder = os.path.join(download_folder, "Stock_AI_Result")
        os.makedirs(final_output_folder, exist_ok=True)
        
        key_manager = KeyManager(api_key_field.value)
        temp_dir = tempfile.gettempdir()
        total_files = len(selected_files)
        
        for index, file in enumerate(selected_files):
            if not is_processing: 
                break

            file_name = file.name
            final_path = os.path.join(final_output_folder, f"READY_{file_name}")

            if os.path.exists(final_path):
                files_table.rows[index].cells[1].content = ft.Text("Skipped (Done)", color=ft.Colors.GREY)
                progress_bar.value = (index + 1) / total_files
                page.update()
                continue

            files_table.rows[index].cells[1].content = ft.Text("Cleaning...", color=ft.Colors.ORANGE)
            page.update()
            
            await asyncio.sleep(0.1)

            work_path = os.path.join(temp_dir, f"TEMP_{int(time.time())}_{file_name}")

            try:
                is_clean = await asyncio.to_thread(sanitize_image_sync, file.path, work_path)
                if not is_clean: raise Exception("File Corrupt")

                files_table.rows[index].cells[1].content = ft.Text("AI Generating...", color=ft.Colors.BLUE)
                page.update()

                img = PIL.Image.open(work_path)
                
                max_retries = 3
                ai_success = False
                
                for attempt in range(max_retries):
                    current_key = key_manager.get_current()
                    genai.configure(api_key=current_key)
                    
                    # SAFETY SETTINGS: Agar gambar orang/kulit tidak diblokir
                    safety_config = {
                        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                    }

                    # MODEL FIX: Menggunakan 1.5-flash (2.5 belum stabil/publik)
                    model = genai.GenerativeModel(
                        'gemini-2.5-flash', 
                        safety_settings=safety_config
                    )
                    
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
                        
                        response = await asyncio.to_thread(model.generate_content, [prompt, img])
                        
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
                            new_key = key_manager.get_next()
                            print(f"Switching Key due to limit...")
                            await asyncio.sleep(1) 
                        else:
                            raise api_err
                
                img.close()

                if not ai_success:
                    raise Exception("AI Failed/Limit")

                files_table.rows[index].cells[1].content = ft.Text("Saving...", color=ft.Colors.PURPLE)
                page.update()
                
                success, msg = await asyncio.to_thread(embed_metadata_strict_sync, work_path, title, keywords)
                
                if success:
                    shutil.move(work_path, final_path)
                    files_table.rows[index].cells[1].content = ft.Text("SUCCESS ✅", color=ft.Colors.GREEN)
                else:
                    files_table.rows[index].cells[1].content = ft.Text("FAIL ❌", color=ft.Colors.RED)

            except Exception as e:
                files_table.rows[index].cells[1].content = ft.Text("Error ❌", color=ft.Colors.RED, tooltip=str(e))
            
            if os.path.exists(work_path):
                try: os.remove(work_path)
                except: pass
            
            progress_bar.value = (index + 1) / total_files
            page.update()

        status_text.value = "Proses Selesai." if is_processing else "Proses Dihentikan."
        progress_bar.visible = False
        btn_process.disabled = False
        btn_stop.disabled = True
        is_processing = False
        page.update()

    def stop_process(e):
        nonlocal is_processing
        is_processing = False
        status_text.value = "Menghentikan proses..."
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

    # --- Buttons ---
    btn_pick = ft.ElevatedButton("Pilih Gambar", icon=ft.Icons.PHOTO_LIBRARY, on_click=lambda _: file_picker.pick_files(allow_multiple=True, file_type=ft.FilePickerFileType.IMAGE))
    
    btn_process = ft.ElevatedButton("Mulai Proses (Pro Worker)", icon=ft.Icons.ROCKET_LAUNCH, style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE), disabled=True, on_click=process_queue)
    
    btn_stop = ft.ElevatedButton("Stop", icon=ft.Icons.STOP, bgcolor=ft.Colors.RED, color=ft.Colors.WHITE, disabled=True, on_click=stop_process)

    # --- Layout ---
    page.add(
        ft.Column([
            ft.Text("Ai Metadata Pro (Worker Mode)", size=24, weight=ft.FontWeight.BOLD),
            ft.Text("Supports Multiple Keys & Resume Mode", size=12, color=ft.Colors.GREY),
            ft.Divider(),
            api_key_field,
            ft.Container(height=10),
            ft.Row([btn_pick, btn_stop]),
            ft.Container(height=10),
            files_table,
            progress_bar,
            status_text,
            ft.Container(height=10),
            btn_process,
        ], scroll=ft.ScrollMode.ADAPTIVE)
    )

ft.app(target=main)
