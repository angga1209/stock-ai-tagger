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
    page.title = "Ai Metadata Pro"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.scroll = ft.ScrollMode.ADAPTIVE
    page.padding = 15
    page.window_prevent_close = True 

    selected_files = [] 
    is_processing = False 
    processed_count = 0 
    
    DEFAULT_OUTPUT_DIR = "/storage/emulated/0/Download/Stock_AI_Result"

    # --- UI Components ---
    saved_keys = page.client_storage.get("gemini_api_keys")
    
    api_key_field = ft.TextField(
        label="Gemini API Keys",
        hint_text="Paste disini (pisahkan koma). Key1, Key2, Key3",
        multiline=True,
        min_lines=1,
        max_lines=3,
        text_size=12,
        value=saved_keys if saved_keys else "",
        border_color=ft.Colors.BLUE,
        on_change=lambda e: page.client_storage.set("gemini_api_keys", api_key_field.value)
    )

    txt_worker = ft.TextField(
        label="Jml Worker",
        value="1",
        text_align=ft.TextAlign.CENTER,
        width=100,
        keyboard_type=ft.KeyboardType.NUMBER,
        hint_text="Max 2",
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
    
    # --- DASHBOARD COMPONENTS (Highlight Area) ---
    status_icon = ft.Icon(ft.Icons.INFO_OUTLINE, size=20, color=ft.Colors.BLUE_700)
    status_text = ft.Text("Siap Memproses.", color=ft.Colors.BLUE_GREY_900, size=14, weight=ft.FontWeight.BOLD, expand=True)
    progress_bar = ft.ProgressBar(visible=False, value=0, color=ft.Colors.BLUE_700, bgcolor=ft.Colors.BLUE_100)
    
    # Container Dashboard (Disimpan di variabel agar bisa diubah warnanya)
    dashboard_card = ft.Container(
        content=ft.Column([
            ft.Row([
                status_icon,
                status_text
            ], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            progress_bar,
        ], spacing=5),
        bgcolor=ft.Colors.BLUE_50, 
        padding=15,
        border_radius=10,
        border=ft.border.all(1, ft.Colors.BLUE_200),
        animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT)
    )

    # --- FUNGSI UPDATE STATUS (CORE UPDATE) ---
    def update_dashboard(message, is_error=False):
        """Mengubah teks dan warna dashboard berdasarkan status"""
        status_text.value = message
        
        if is_error:
            # Mode ERROR: Merah
            dashboard_card.bgcolor = ft.Colors.RED_50
            dashboard_card.border = ft.border.all(1, ft.Colors.RED_300)
            status_icon.name = ft.Icons.WARNING_AMBER
            status_icon.color = ft.Colors.RED_700
            status_text.color = ft.Colors.RED_900
            progress_bar.color = ft.Colors.RED
            progress_bar.bgcolor = ft.Colors.RED_100
        else:
            # Mode NORMAL: Biru
            dashboard_card.bgcolor = ft.Colors.BLUE_50
            dashboard_card.border = ft.border.all(1, ft.Colors.BLUE_200)
            status_icon.name = ft.Icons.INFO_OUTLINE
            status_icon.color = ft.Colors.BLUE_700
            status_text.color = ft.Colors.BLUE_GREY_900
            progress_bar.color = ft.Colors.BLUE_700
            progress_bar.bgcolor = ft.Colors.BLUE_100
            
        page.update()

    # --- EXTERNAL LINKS ---
    def open_wa(e):
        page.launch_url("https://wa.me/6281229689225") 
    
    def open_tools(e):
        page.launch_url("https://lynk.id/anggayulianto") 

    # --- UTILS ---
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
            
            try: exif_dict = piexif.load(work_path)
            except: exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
            
            exif_dict["0th"][piexif.ImageIFD.ImageDescription] = title.encode('utf-8')
            exif_dict["0th"][piexif.ImageIFD.XPTitle] = title.encode('utf-16le')
            xp_keywords = ";".join(keyword_list)
            exif_dict["0th"][piexif.ImageIFD.XPKeywords] = xp_keywords.encode('utf-16le')
            piexif.insert(piexif.dump(exif_dict), work_path)
            
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

                img_bytes = None
                def prepare_image():
                    with PIL.Image.open(work_path) as img:
                        img.thumbnail((1024, 1024)) 
                        buf = io.BytesIO()
                        img.save(buf, format='JPEG', quality=80)
                        return buf.getvalue()
                
                img_bytes = await asyncio.to_thread(prepare_image)

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
                            # ERROR FATAL API KEY
                            update_dashboard(f"Key Salah: {current_key[:5]}...", is_error=True)
                            break 
                        if "429" in err_msg or "Resource" in err_msg:
                            key_manager.get_next()
                            await asyncio.sleep(2) 
                        else: raise api_err
                
                if not ai_success: raise Exception("AI Gagal (Limit/Block)")

                files_table.rows[index].cells[1].content = ft.Text("Saving...", color=ft.Colors.PURPLE)
                files_table.update()
                
                success, msg = await asyncio.to_thread(embed_metadata_strict_sync, work_path, title, keywords)
                
                if success:
                    shutil.move(work_path, final_path)
                    files_table.rows[index].cells[1].content = ft.Text("Done ✅", color=ft.Colors.GREEN)
                    # Kembalikan status ke normal jika sebelumnya merah (opsional)
                    # update_dashboard(f"Memproses {index+1}/{len(selected_files)}...", is_error=False) 
                else:
                    raise Exception(f"Meta: {msg}")

            except Exception as e:
                err_s = str(e)
                # TAMPILKAN ERROR KE DASHBOARD
                update_dashboard(f"Gagal: {err_s}", is_error=True)
                
                files_table.rows[index].cells[1].content = ft.Text("Fail ❌", color=ft.Colors.RED)
            
            files_table.update()
            if os.path.exists(work_path): 
                try: os.remove(work_path)
                except: pass
            
            processed_count += 1
            progress_bar.value = processed_count / len(selected_files)
            progress_bar.update()

    # --- ACTIONS ---
    def clear_data(e):
        nonlocal selected_files
        if is_processing:
            update_dashboard("Stop proses dulu!", is_error=True)
            return
            
        selected_files = []
        files_table.rows.clear()
        files_table.visible = False
        files_table.update()
        
        update_dashboard("List dibersihkan.", is_error=False)
        
        progress_bar.value = 0
        progress_bar.visible = False
        progress_bar.update()
        
        reset_start_button()

    def reset_start_button():
        btn_action.text = "MULAI PROSES"
        btn_action.icon = ft.Icons.ROCKET_LAUNCH
        btn_action.bgcolor = ft.Colors.BLUE_700
        btn_action.disabled = False
        btn_action.update()

    async def toggle_process(e):
        nonlocal is_processing, processed_count
        
        if is_processing:
            is_processing = False
            btn_action.text = "MENGHENTIKAN..."
            btn_action.disabled = True
            btn_action.bgcolor = ft.Colors.GREY
            btn_action.update()
            return

        # START ZERO LAG
        is_processing = True 
        btn_action.text = "STOP PROSES"
        btn_action.icon = ft.Icons.STOP_CIRCLE
        btn_action.bgcolor = ft.Colors.RED_600
        btn_action.update()
        await asyncio.sleep(0.1)

        # --- VALIDASI & ERROR REPORTING KE DASHBOARD ---
        
        if not selected_files:
            update_dashboard("ERROR: Pilih gambar dulu!", is_error=True)
            is_processing = False
            reset_start_button()
            return
        
        if not api_key_field.value:
            update_dashboard("ERROR: API Key Kosong!", is_error=True)
            is_processing = False
            reset_start_button()
            return

        ok, msg = check_storage_permission()
        if not ok:
            update_dashboard(f"ERROR: {msg}", is_error=True)
            is_processing = False
            reset_start_button()
            return

        # RESET STATUS KE NORMAL JIKA VALIDASI OK
        processed_count = 0
        progress_bar.visible = True
        progress_bar.value = 0
        progress_bar.update()
        
        try:
            worker_limit = int(txt_worker.value)
            if worker_limit < 1: worker_limit = 1
        except: worker_limit = 1
        
        update_dashboard(f"Memproses {len(selected_files)} gambar ({worker_limit} worker)...", is_error=False)

        os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
        key_manager = KeyManager(api_key_field.value)
        temp_dir = tempfile.gettempdir()
        
        sem = asyncio.Semaphore(worker_limit)
        
        tasks = [process_single_image(i, f, key_manager, DEFAULT_OUTPUT_DIR, temp_dir, sem) for i, f in enumerate(selected_files)]
        await asyncio.gather(*tasks)

        is_processing = False
        update_dashboard("Semua Selesai.", is_error=False)
        reset_start_button()

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
            update_dashboard(f"{len(selected_files)} gambar siap.", is_error=False)

    file_picker = ft.FilePicker(on_result=on_files_picked)
    page.overlay.append(file_picker)

    # --- LAYOUT CONSTRUCTION ---
    btn_pick = ft.ElevatedButton("Pilih Gambar", icon=ft.Icons.PHOTO_LIBRARY, on_click=lambda _: file_picker.pick_files(allow_multiple=True, file_type=ft.FilePickerFileType.IMAGE), expand=True)
    btn_clear = ft.ElevatedButton("Clear", icon=ft.Icons.CLEAR_ALL, color=ft.Colors.RED, on_click=clear_data)
    
    btn_action = ft.ElevatedButton(
        text="MULAI PROSES", 
        icon=ft.Icons.ROCKET_LAUNCH, 
        style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)), 
        disabled=True,
        height=50,
        on_click=toggle_process
    )
    
    btn_help = ft.TextButton("Bantuan (WA)", icon=ft.Icons.CHAT, on_click=open_wa)
    btn_tools = ft.TextButton("Tools Lainnya", icon=ft.Icons.LINK, on_click=open_tools)

    # --- CONTAINER UTAMA ---
    page.add(
        ft.Column([
            ft.Text("Ai Metadata Pro", size=20, weight=ft.FontWeight.BOLD),
            api_key_field,
            ft.Container(height=5),
            
            ft.Row([
                txt_worker,
                ft.Text("Gunakan banyak API\nJika worker lebih dari 1", size=10, color=ft.Colors.GREY, expand=True)
            ], alignment=ft.MainAxisAlignment.START),
            
            ft.Divider(),
            
            ft.Row([btn_pick, btn_clear]),
            ft.Container(height=5),
            
            ft.Container(content=btn_action, width=float("inf")),
            ft.Container(height=10),

            # --- DASHBOARD CARD (DIPANGGIL DISINI) ---
            dashboard_card,
            # ----------------------------------------
            
            ft.Container(height=10),
            files_table,
            
            ft.Divider(),
            ft.Row([btn_help, btn_tools], alignment=ft.MainAxisAlignment.CENTER),
            
        ], scroll=ft.ScrollMode.ADAPTIVE)
    )

ft.app(target=main)

