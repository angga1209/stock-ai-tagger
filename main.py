import flet as ft
import json
import os
import time
import shutil
import tempfile
import re
import asyncio
import itertools
import io 

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
    page.title = "Ai Metadata Pro (Final)"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.scroll = ft.ScrollMode.ADAPTIVE
    page.padding = 15 # Padding sedikit dikecilkan agar muat di HP kecil
    page.window_prevent_close = True 

    selected_files = [] 
    is_processing = False 
    processed_count = 0 
    
    # Path Default
    DEFAULT_OUTPUT_DIR = "/storage/emulated/0/Download/Stock_AI_Result"

    # --- UI Components ---
    saved_keys = page.client_storage.get("gemini_api_keys")
    
    api_key_field = ft.TextField(
        label="Gemini API Keys",
        hint_text="Paste Key disini (pisahkan koma)...",
        multiline=True,
        min_lines=1,
        max_lines=3,
        text_size=12,
        value=saved_keys if saved_keys else "",
        border_color=ft.Colors.BLUE,
        on_change=lambda e: page.client_storage.set("gemini_api_keys", api_key_field.value)
    )

    # Input Jumlah Worker (Pengganti Checkbox)
    txt_worker = ft.TextField(
        label="Jml Worker",
        value="1",
        text_align=ft.TextAlign.CENTER,
        width=100,
        keyboard_type=ft.KeyboardType.NUMBER,
        hint_text="Max 2",
        helper_text="Rekomendasi: 1-2"
    )

    files_table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("File")),
            ft.DataColumn(ft.Text("Status")),
        ],
        rows=[],
        visible=False,
        width=float("inf"),
        column_spacing=20,
    )
    
    status_text = ft.Text("Siap.", color=ft.Colors.GREY, size=12)
    progress_bar = ft.ProgressBar(visible=False, value=0, color=ft.Colors.BLUE)

    # --- EXTERNAL LINKS ---
    def open_wa(e):
        page.launch_url("https://wa.me/6281229689225") # Ganti nomor WA Anda
    
    def open_tools(e):
        page.launch_url("https://lynk.id/anggayulianto") # Ganti Link Lynk.id

    # --- UTILS ---
    def show_snack(message, color=ft.Colors.RED):
        page.snack_bar = ft.SnackBar(
            content=ft.Text(message, color=ft.Colors.WHITE),
            bgcolor=color,
            duration=4000,
        )
        page.snack_bar.open = True
        page.update()

    def check_storage_permission():
        test_path = os.path.join(DEFAULT_OUTPUT_DIR, "perm_test.tmp")
        try:
            os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
            with open(test_path, "w") as f: f.write("ok")
            os.remove(test_path)
            return True, "OK"
        except:
            return False, "Izin Penyimpanan Ditolak! Cek Pengaturan HP."

    # --- HELPER FUNCTIONS ---
    def extract_json(text):
        try:
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
            img.save(output_path, "JPEG", quality=100, optimize=True)
            img.close()
            return True
        except Exception as e:
            raise e 

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
            info['keywords'] = keyword_list
            info['caption/abstract'] = title 
            info['object name'] = title
            info['headline'] = title
            info.save() 
            
            if os.path.exists(work_path + "~"): os.remove(work_path + "~")
            return True, "Complete"
        except Exception as e:
            return False, str(e)

    # --- WORKER ---
    async def process_single_image(index, file, key_manager, final_output_folder, temp_dir, semaphore):
        import google.generativeai as genai
        from google.generativeai.types import HarmCategory, HarmBlockThreshold
        import PIL.Image

        nonlocal processed_count
        
        async with semaphore:
            if not is_processing: return

            file_name = file.name
            final_path = os.path.join(final_output_folder, f"READY_{file_name}")

            # Update status awal (Fast UI update)
            files_table.rows[index].cells[1].content = ft.Text("Cleaning...", color=ft.Colors.ORANGE)
            files_table.update()

            if os.path.exists(final_path):
                files_table.rows[index].cells[1].content = ft.Text("Skip (Ada)", color=ft.Colors.GREY)
                files_table.update()
                processed_count += 1
                progress_bar.value = processed_count / len(selected_files)
                progress_bar.update()
                return

            work_path = os.path.join(temp_dir, f"TEMP_{int(time.time())}_{index}_{file_name}")

            try:
                await asyncio.to_thread(sanitize_image_sync, file.path, work_path)

                files_table.rows[index].cells[1].content = ft.Text("Generating...", color=ft.Colors.BLUE)
                files_table.update()

                # In-Memory Image
                img_bytes = None
                def prepare_image():
                    with PIL.Image.open(work_path) as img:
                        img.thumbnail((1024, 1024)) 
                        buf = io.BytesIO()
                        img.save(buf, format='JPEG', quality=80)
                        return buf.getvalue()
                
                img_bytes = await asyncio.to_thread(prepare_image)

                # AI Process
                max_retries = 3
                ai_success = False
                title, keywords = "", ""
                
                for attempt in range(max_retries):
                    if not is_processing: break
                    current_key = key_manager.get_current()
                    
                    try:
                        genai.configure(api_key=current_key)
                        safety = {HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE}
                        model = genai.GenerativeModel('gemini-2.5-flash', safety_settings=safety)
                        
                        prompt = """
                                Act as a professional Stock Photography SEO Expert. Analyze the provided image to generate metadata optimized for Adobe Stock and Shutterstock algorithms.

                                Your output must be strictly in JSON format with two fields: "title" and "keywords".

                                Follow these rules:
                                1. TITLE (Max 200 chars):
                                   - Structure: [Main Subject] + [Action/State] + [Context/Background].
                                   - Example: "Happy business woman using laptop in modern office near window"
                                   - Focus on "Findability". The first 5 words are the most important.
                                
                                2. KEYWORDS (Target 49 words):
                                   - Generate extensive tags separated by commas.
                                   - HIERARCHY IS CRITICAL:
                                     * 1-10: Main Subject, Primary Action, Key Objects (Visuals).
                                     * 11-30: Conceptual, Mood, Lighting, Style (e.g., cinematic, bright, minimalism).
                                     * 31-49: Broader categories and associations.
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
                        
                        response = await asyncio.to_thread(model.generate_content, [prompt, {"mime_type": "image/jpeg", "data": img_bytes}])
                        
                        if not response.parts: raise Exception("Safety Block")
                        data = extract_json(response.text)
                        
                        if data:
                            title = data.get("title", "")
                            keywords = data.get("keywords", "")
                            ai_success = True
                            break 
                        else: raise Exception("JSON Error")

                    except Exception as api_err:
                        err_msg = str(api_err)
                        if "400" in err_msg:
                            show_snack(f"Key Invalid: {current_key[:5]}...")
                            break 
                        if "429" in err_msg or "Resource" in err_msg:
                            key_manager.get_next()
                            await asyncio.sleep(2) 
                        else: raise api_err
                
                if not ai_success: raise Exception("AI Gagal (Limit)")

                files_table.rows[index].cells[1].content = ft.Text("Saving...", color=ft.Colors.PURPLE)
                files_table.update()
                
                success, msg = await asyncio.to_thread(embed_metadata_strict_sync, work_path, title, keywords)
                
                if success:
                    shutil.move(work_path, final_path)
                    files_table.rows[index].cells[1].content = ft.Text("OK ✅", color=ft.Colors.GREEN)
                else:
                    raise Exception(f"Meta: {msg}")

            except Exception as e:
                err_s = str(e)
                if "Permission" in err_s: show_snack("Izin Ditolak!")
                files_table.rows[index].cells[1].content = ft.Text("Gagal ❌", color=ft.Colors.RED)
            
            files_table.update()
            if os.path.exists(work_path): 
                try: os.remove(work_path)
                except: pass
            
            processed_count += 1
            progress_bar.value = processed_count / len(selected_files)
            progress_bar.update()

    # --- ACTIONS ---
    def clear_data(e):
        """Membersihkan list tanpa hapus API Key"""
        nonlocal selected_files
        if is_processing:
            show_snack("Stop proses dulu!")
            return
            
        selected_files = []
        files_table.rows.clear()
        files_table.visible = False
        files_table.update()
        
        status_text.value = "List dibersihkan."
        status_text.update()
        
        progress_bar.value = 0
        progress_bar.visible = False
        progress_bar.update()

        btn_action.disabled = True
        btn_action.text = "MULAI PROSES"
        btn_action.bgcolor = ft.Colors.BLUE_700
        btn_action.update()

    async def toggle_process(e):
        nonlocal is_processing, processed_count
        
        # 1. IMMEDIATE UI FEEDBACK (Agar user tidak merasa lag)
        if not is_processing:
            # STATE: STARTING
            # Matikan tombol langsung agar tidak dipencet 2x
            btn_action.disabled = True 
            btn_action.text = "Menyiapkan..." 
            btn_action.update()
            
            # --- Validasi Awal (Baru dijalankan setelah UI update) ---
            if not selected_files:
                show_snack("Pilih gambar dulu!")
                # Reset tombol
                btn_action.disabled = False
                btn_action.text = "MULAI PROSES"
                btn_action.update()
                return
            
            if not api_key_field.value:
                show_snack("Masukkan API Key!")
                btn_action.disabled = False
                btn_action.text = "MULAI PROSES"
                btn_action.update()
                return

            ok, msg = check_storage_permission()
            if not ok:
                show_snack(msg)
                btn_action.disabled = False
                btn_action.text = "MULAI PROSES"
                btn_action.update()
                return

            # --- SETUP PROCESS ---
            is_processing = True
            processed_count = 0
            
            # Update UI ke mode STOP
            btn_action.text = "STOP PROSES"
            btn_action.bgcolor = ft.Colors.RED_600
            btn_action.icon = ft.Icons.STOP_CIRCLE
            btn_action.disabled = False # Hidupkan lagi agar bisa distop
            btn_action.update()
            
            progress_bar.visible = True
            progress_bar.value = 0
            progress_bar.update()
            
            os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
            key_manager = KeyManager(api_key_field.value)
            temp_dir = tempfile.gettempdir()
            
            # Ambil nilai worker dari textbox
            try:
                worker_limit = int(txt_worker.value)
                if worker_limit < 1: worker_limit = 1
            except: worker_limit = 1
            
            sem = asyncio.Semaphore(worker_limit)
            status_text.value = f"Running ({worker_limit} worker)..."
            status_text.update()
            
            # Execute
            tasks = [process_single_image(i, f, key_manager, DEFAULT_OUTPUT_DIR, temp_dir, sem) for i, f in enumerate(selected_files)]
            await asyncio.gather(*tasks)

            # --- FINISHED ---
            is_processing = False
            status_text.value = "Selesai."
            status_text.update()
            
            btn_action.text = "MULAI PROSES"
            btn_action.bgcolor = ft.Colors.BLUE_700
            btn_action.icon = ft.Icons.ROCKET_LAUNCH
            btn_action.update()

        else:
            # STATE: STOPPING
            is_processing = False
            btn_action.text = "BERHENTI..."
            btn_action.disabled = True # Disable sampai loop benar-benar berhenti
            btn_action.bgcolor = ft.Colors.GREY
            btn_action.update()

    def on_files_picked(e: ft.FilePickerResultEvent):
        nonlocal selected_files
        if e.files:
            selected_files = e.files
            files_table.rows.clear()
            for f in selected_files:
                files_table.rows.append(ft.DataRow(cells=[ft.DataCell(ft.Text(f.name[:12]+"..", size=12)), ft.DataCell(ft.Text("Wait", size=12))]))
            files_table.visible = True
            files_table.update()
            btn_action.disabled = False 
            btn_action.update()
            status_text.value = f"{len(selected_files)} gambar."
            status_text.update()

    file_picker = ft.FilePicker(on_result=on_files_picked)
    page.overlay.append(file_picker)

    # --- LAYOUT CONSTRUCTION ---
    btn_pick = ft.ElevatedButton("Ambil Gambar", icon=ft.Icons.PHOTO_LIBRARY, on_click=lambda _: file_picker.pick_files(allow_multiple=True, file_type=ft.FilePickerFileType.IMAGE), expand=True)
    btn_clear = ft.ElevatedButton("Clear", icon=ft.Icons.CLEAR_ALL, color=ft.Colors.RED, on_click=clear_data)
    
    btn_action = ft.ElevatedButton(
        text="MULAI PROSES", 
        icon=ft.Icons.ROCKET_LAUNCH, 
        style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)), 
        disabled=True,
        height=50,
        on_click=toggle_process
    )
    
    # Menu Bantuan (Baris Bawah)
    btn_help = ft.TextButton("Bantuan (WA)", icon=ft.Icons.CHAT, on_click=open_wa)
    btn_tools = ft.TextButton("Tools Lainnya", icon=ft.Icons.LINK, on_click=open_tools)

    page.add(
        ft.Column([
            ft.Text("Ai Metadata Pro", size=20, weight=ft.FontWeight.BOLD),
            api_key_field,
            ft.Container(height=5),
            
            # Row Setting Worker
            ft.Row([
                txt_worker,
                ft.Text("Set worker ke 2 jika HP RAM > 6GB.\nJika sering crash, set ke 1.", size=10, color=ft.Colors.GREY, expand=True)
            ], alignment=ft.MainAxisAlignment.START),
            
            ft.Divider(),
            
            # Row Tombol Navigasi
            ft.Row([btn_pick, btn_clear]),
            
            ft.Container(height=5),
            ft.Container(content=btn_action, width=float("inf")),
            
            ft.Container(height=10),
            files_table,
            progress_bar,
            status_text,
            
            ft.Divider(),
            # Footer Links
            ft.Row([btn_help, btn_tools], alignment=ft.MainAxisAlignment.CENTER),
            
        ], scroll=ft.ScrollMode.ADAPTIVE)
    )

ft.app(target=main)
