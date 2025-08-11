#!/usr/bin/env python
# coding: utf-8

# In[13]:


import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
import requests
import xml.etree.ElementTree as ET
import json
import threading
import queue
import os
from datetime import datetime
from PIL import Image, ImageTk
import concurrent.futures
import time
import math
import keyboard
import pyperclip

SETTINGS_FILE = "settings.json"

def save_settings(settings):
    temp_file = SETTINGS_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    os.replace(temp_file, SETTINGS_FILE)

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

class LineMonitor:
    def __init__(self):
        self.running = False
        self.executed = False

def is_focusable_widget(w):
    return isinstance(w, (tk.Entry, tk.Button, tk.Checkbutton))

def bind_entry_extended_events(entry, mode="timecode"):
    entry._drag_y = None
    entry._drag_in_progress = False
    entry._tc_idx = 2
    entry._tc_positions = [2, 5, 8]
    entry._tc_mode = (mode in ["timecode", "set_time"])

    def select_all(event):
        entry.after(1, lambda: entry.select_range(0, tk.END))
        entry.after(1, lambda: entry.icursor(tk.END))
    entry.bind("<FocusIn>", select_all, add="+")

    if entry._tc_mode:
        entry.bind("<FocusIn>", lambda e: set_tc_cursor(entry), add="+")
        entry.bind("<Shift-Left>", lambda e: tc_shift_move(entry, -1))
        entry.bind("<Shift-Right>", lambda e: tc_shift_move(entry, 1))
        entry.bind("<Shift-Up>", lambda e: tc_shift_incdec(entry, 1))
        entry.bind("<Shift-Down>", lambda e: tc_shift_incdec(entry, -1))
        entry.bind("<Return>", lambda e, en=entry: timecode_zero_autofill(en, app_instance=en.winfo_toplevel().nametowidget(".")))
    elif mode == "button":
        entry.bind("<Shift-Up>", lambda e: button_incdec(entry, 1))
        entry.bind("<Shift-Down>", lambda e: button_incdec(entry, -1))


def set_tc_cursor(entry):
    val = entry.get()
    if not val or len(val) != 8:
        return
    idx = getattr(entry, "_tc_idx", 2)
    pos = [2, 5, 8][idx]
    entry.icursor(pos)

def tc_shift_move(entry, delta):
    if entry.cget("state") in ("readonly", "disabled"):
        return "break"
    idx = getattr(entry, "_tc_idx", 2)
    idx = (idx + delta) % 3
    entry._tc_idx = idx
    set_tc_cursor(entry)
    return "break"

def tc_shift_incdec(entry, delta):
    if entry.cget("state") in ("readonly", "disabled"):
        return "break"
    val = entry.get()
    if not val or len(val) != 8 or val[2] != ":" or val[5] != ":":
        return "break"
    
    idx = getattr(entry, "_tc_idx", 2)
    try:
        h, m, s = map(int, val.split(":"))
    except ValueError:
        return "break"

    if idx == 0:
        h = (h + delta) % 24
    elif idx == 1:
        m = (m + delta) % 60
    else:
        s = (s + delta) % 60
    
    new_tc = f"{h:02d}:{m:02d}:{s:02d}"
    entry.delete(0, tk.END)
    entry.insert(0, new_tc)
    set_tc_cursor(entry)
    return "break"

def button_incdec(entry, delta):
    if entry.cget("state") in ("readonly", "disabled"):
        return "break"
    val = entry.get().strip()
    v = 0
    if val.isdigit():
        v = int(val)
    
    v = max(0, v + delta)
    entry.delete(0, tk.END)
    entry.insert(0, str(v))
    return "break"

def handle_entry_wheel(entry, event, mode="timecode"):
    if entry.cget("state") in ("readonly", "disabled"):
        return "break"
    if event.state & 0x4:
        return
    
    delta = 0
    if hasattr(event, "delta"):
        delta = event.delta // 120
        if delta == 0 and event.delta != 0:
            delta = 1 if event.delta > 0 else -1
    elif hasattr(event, "num"):
        if event.num == 4: delta = 1
        elif event.num == 5: delta = -1
    
    if delta != 0:
        _apply_entry_value(entry, delta, event, mode)
        return "break"

def _apply_entry_value(entry, delta, event=None, mode="timecode"):
    if entry.cget("state") in ("readonly", "disabled"):
        return

    if mode == "button":
        val = entry.get().strip()
        v = 0
        if val.isdigit():
            v = int(val)
        v = max(0, v + delta)
        entry.delete(0, tk.END)
        entry.insert(0, str(v))
    else:
        tc = entry.get().strip()
        if not tc or len(tc) != 8 or tc[2] != ':' or tc[5] != ':':
            if not tc and mode != "button":
                entry.insert(0, "00:00:00")
                tc = "00:00:00"
            else:
                return

        entry_width = entry.winfo_width()
        x_coord = entry_width // 2
        if event and hasattr(event, 'x'):
            x_coord = event.x
        
        third = entry_width // 3
        idx_to_change = 1
        if entry_width > 0 :
            if x_coord < third: idx_to_change = 0
            elif x_coord > 2 * third: idx_to_change = 2
        
        try:
            h, m, s = map(int, tc.split(":"))
        except ValueError:
            return

        if idx_to_change == 0: h = (h + delta) % 24
        elif idx_to_change == 1: m = (m + delta) % 60
        else: s = (s + delta) % 60
        
        new_tc = f"{h:02d}:{m:02d}:{s:02d}"
        entry.delete(0, tk.END)
        entry.insert(0, new_tc)
        
        if idx_to_change == 0: entry.icursor(2)
        elif idx_to_change == 1: entry.icursor(5)
        else: entry.icursor(8)


def timecode_zero_autofill(entry, app_instance=None):
    if entry.cget("state") in ("readonly", "disabled"):
        return "break"
    val = entry.get().strip()

    if len(val) == 6 and val.isdigit():
        try:
            h = int(val[0:2])
            m = int(val[2:4])
            s = int(val[4:6])
            if not (0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59):
                if app_instance and hasattr(app_instance, 'push_error'):
                    app_instance.push_error(f"시간 값 오류: {h:02d}:{m:02d}:{s:02d}")
                return None
            
            formatted_val = f"{val[0:2]}:{val[2:4]}:{val[4:6]}"
            entry.delete(0, tk.END)
            entry.insert(0, formatted_val)
            entry.icursor(tk.END)
            return "break"
        except ValueError:
            return None

    if val == "0":
        entry.delete(0, tk.END)
        entry.insert(0, "00:00:00")
        entry.icursor(tk.END)
        return "break"

    return None

def bind_widget_full_navigation(widget, row_idx, col_idx, app):
    def on_key(event):
        dir_map = {
            "Up":    (-1, 0),
            "Down":  (1, 0),
            "Left":  (0, -1),
            "Right": (0, 1)
        }
        if event.state & 0x1:
            return None
        if event.keysym in dir_map:
            dr, dc = dir_map[event.keysym]
            r_orig, c_orig = row_idx, col_idx
            r, c = r_orig, c_orig

            max_rows = len(app.widget_matrix)
            max_cols = len(app.widget_matrix[0]) if max_rows > 0 else 0

            attempts = 0
            max_attempts = max_rows * max_cols

            while attempts < max_attempts:
                attempts += 1
                r_new, c_new = r + dr, c + dc
                
                if dr != 0:
                    if r_new < 0: r_new = max_rows - 1
                    elif r_new >= max_rows: r_new = 0
                
                if dc != 0:
                    if c_new < 0: c_new = max_cols - 1
                    elif c_new >= max_cols: c_new = 0
                
                if not (0 <= c_new < max_cols) and dc != 0:
                    break
                
                target = app.get_widget_by_rowcol(r_new, c_new)
                
                if target and target.winfo_ismapped() and target.cget('state') != 'disabled' and is_focusable_widget(target) :
                    target.focus_set()
                    if isinstance(target, tk.Entry):
                        target.select_range(0, tk.END)
                        target.icursor(tk.END)
                    return "break"
                
                if (r_new, c_new) == (r_orig, c_orig) and (dr !=0 or dc !=0) :
                    current_widget_is_entry = isinstance(app.get_widget_by_rowcol(r_orig,c_orig), tk.Entry)
                    if current_widget_is_entry and (event.keysym == "Left" or event.keysym == "Right"):
                        return None
                    break
                r, c = r_new, c_new
            return "break"
        return None
    for k in ["<Up>", "<Down>", "<Left>", "<Right>"]:
        widget.bind(k, on_key)

class StatusCircleBar(tk.Frame):
    def __init__(self, master, get_status_callback, status_items, *args, **kwargs):
        super().__init__(master, bg="black", *args, **kwargs)
        self.get_status = get_status_callback
        self.status_items = status_items
        self.labels = []
        self._create_widgets()
        self.update_status()

    def _create_widgets(self):
        for lbl, canvas in self.labels:
            lbl.destroy()
            canvas.destroy()
        self.labels.clear()
        
        for short, _ in self.status_items:
            lbl = tk.Label(self, text=short, fg="white", bg="black", font=("Helvetica", 13), width=2)
            canvas = tk.Canvas(self, width=16, height=16, bg="black", highlightthickness=0)
            lbl.pack(side=tk.LEFT, padx=(2,0))
            canvas.pack(side=tk.LEFT, padx=(0,10))
            self.labels.append((lbl, canvas))

    def update_labels(self, new_status_items):
        self.status_items = new_status_items
        self._create_widgets()

    def update_status(self):
        status = self.get_status()
        colors = {0: "yellow", 1: "red", 2: "lime"}
        for idx, (_, canvas) in enumerate(self.labels):
            if idx < len(status):
                current_status_val = status[idx]
            else:
                current_status_val = 0
            canvas.delete("all")
            color = colors.get(current_status_val, "yellow")
            canvas.create_oval(2, 2, 14, 14, fill=color, outline="gray")
        self.after(1000, self.update_status)

class ActiveTimecodeApp:
    def __init__(self, master):
        self.master = master
        master.title("vMix ACTIVE Input Timecode")
        master.configure(bg="black")
        
        self.settings = load_settings()
        
        saved_geometry = self.settings.get("window_geometry")
        if saved_geometry:
            try:
                self.master.geometry(saved_geometry)
            except tk.TclError:
                self.master.geometry("1280x500")
        else:
            self.master.geometry("1280x500")

        self.main_vmix_name = self.settings.get("main_vmix_name", "M")
        self.main_ip = self.settings.get("main_ip", "127.0.0.1")
        self.main_port = self.settings.get("main_port", "8088")
        
        loaded_sub_vmix = self.settings.get("sub_vmix", [])
        self.sub_vmix = []
        for i in range(3):
            if i < len(loaded_sub_vmix):
                sub_data = loaded_sub_vmix[i]
                self.sub_vmix.append({
                    "name": sub_data.get("name", f"V{i+1}"),
                    "ip": sub_data.get("ip", ""),
                    "port": sub_data.get("port", "8088"),
                    "capture_input": sub_data.get("capture_input", "")
                })
            else:
                self.sub_vmix.append({"name": f"V{i+1}", "ip": "", "port": "8088", "capture_input": ""})

        self.companion_ip = self.settings.get("companion_ip", "127.0.0.1")
        self.companion_port = self.settings.get("companion_port", "8000")
        self.replay_hotkey_ip = self.settings.get("replay_hotkey_ip", "")
        
        self.rail_count = self.settings.get("rail_count", 30)
        self.lines = self.settings.get("lines", [])
        
        self.png_path = self.settings.get("png_path", "")
        self.msg_queue = queue.Queue()
        self.error_message = tk.StringVar(value="")
        self.connection_states = [0,0,0,0,0]
        self._status_lock = threading.Lock()
        
        self.previous_timecode_label_text = "--:--:--"
        
        self.target_header_labels = []
        self.input_changer_labels = {}

        menubar = tk.Menu(master)
        master.config(menu=menubar)
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="설정", menu=settings_menu)
        settings_menu.add_command(label="IP 관리", command=self.open_settings_window)
        settings_menu.add_command(label="vMix 리플레이 가지고오기", command=self.open_replay_hotkey_settings)
        settings_menu.add_command(label="컴페니언 PNG", command=self.open_png_dialog)
        settings_menu.add_command(label="레일 수 옵션", command=self.open_rail_count_settings)

        self.paned_window = tk.PanedWindow(master, orient=tk.HORIZONTAL, bg="#333333", sashwidth=5, sashrelief=tk.RAISED)
        self.paned_window.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.left_frame = tk.Frame(self.paned_window, bg="black")
        self.paned_window.add(self.left_frame, width=485)

        self.right_frame = tk.Frame(self.paned_window, bg="black")
        self.paned_window.add(self.right_frame)
        
        self.timecode_label = tk.Label(self.left_frame, text="--:--:--", font=("Helvetica", 36, "bold"), fg="#39FF14", bg="black", anchor="center")
        self.timecode_label.pack(pady=(5,1), fill=tk.X, padx=5)

        self.statusbar_frame = tk.Frame(self.left_frame, bg="black")
        self.statusbar_frame.pack(pady=(0,3), fill=tk.X)
        
        status_items = [
            (self.main_vmix_name, "Main vMix"), (self.sub_vmix[0]["name"], "서브1"),
            (self.sub_vmix[1]["name"], "서브2"), (self.sub_vmix[2]["name"], "서브3"), ("C", "Companion")
        ]
        self.status_bar = StatusCircleBar(self.statusbar_frame, self.get_connection_status, status_items)
        self.status_bar.pack(anchor="center")

        scroll_container = tk.Frame(self.left_frame, bg="black")
        scroll_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(scroll_container, bg="black", highlightthickness=0)
        v_scrollbar = tk.Scrollbar(scroll_container, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=v_scrollbar.set)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.line_frame = tk.Frame(self.canvas, bg="black")
        self.canvas.create_window((0, 0), window=self.line_frame, anchor="nw")
        self.line_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        def _on_mousewheel(event):
            scroll_val = -1 * (event.delta // 120) if hasattr(event, 'delta') else (-1 if event.num == 4 else 1)
            self.canvas.yview_scroll(scroll_val, "units")

        self.canvas.bind('<Enter>', lambda e: self.master.bind_all('<MouseWheel>', _on_mousewheel, add='+'))
        self.canvas.bind('<Leave>', lambda e: self.master.unbind_all('<MouseWheel>'))
        
        self.rebuild_ui()

        bottom_panel_frame = tk.Frame(self.left_frame, bg="black")
        bottom_panel_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10,0))
        path_changer_controls_row_frame = tk.Frame(bottom_panel_frame, bg="black")
        path_changer_controls_row_frame.pack(side=tk.TOP, fill=tk.X, pady=(0,2))

        self.input_changer_entries = {}
        vmix_keys_for_changer = ["M", "V1", "V2", "V3"]
        vmix_names = [self.main_vmix_name] + [sub['name'] for sub in self.sub_vmix]
        
        for i_col, key in enumerate(vmix_keys_for_changer):
            path_changer_controls_row_frame.grid_columnconfigure(i_col, weight=1)
            group_frame = tk.Frame(path_changer_controls_row_frame, bg="black")
            group_frame.grid(row=0, column=i_col, sticky='ew', padx=2)
            
            name_text = f"{vmix_names[i_col]}:"
            lbl = tk.Label(group_frame, text=name_text, bg="black", fg="white", font=("Helvetica", 9), width=3, anchor='w')
            lbl.pack(side=tk.LEFT, padx=(0,1))
            self.input_changer_labels[key] = lbl

            entry = tk.Entry(group_frame, width=3, bg="#333", fg="white", relief=tk.SOLID, bd=1,
                             insertbackground="white", justify='center', font=("Helvetica", 9))
            entry.pack(side=tk.LEFT, padx=(0,1))
            self.input_changer_entries[key] = entry
            entry.bind("<Return>", lambda e, k=key, en=entry: self.fetch_and_display_single_title(k, en.get().strip()))
            entry.bind("<FocusOut>", lambda e, k=key, en=entry: self.fetch_and_display_single_title(k, en.get().strip()))

            btn = tk.Button(group_frame, text="경로",
                            command=lambda k=key: self.change_input_path(k),
                            bg="#222", fg="white", activebackground="#333", activeforeground="white",
                            relief=tk.RAISED, bd=1, padx=2, font=("Helvetica", 8))
            btn.pack(side=tk.LEFT)
        
        title_display_row_frame = tk.Frame(bottom_panel_frame, bg="black")
        title_display_row_frame.pack(side=tk.TOP, fill=tk.X, expand=True, pady=(2,0))

        self.path_changer_title_displays = {}
        for i_col, key in enumerate(vmix_keys_for_changer):
            title_display_row_frame.grid_columnconfigure(i_col, weight=1)
            title_entry = tk.Entry(title_display_row_frame, bg="#1c1c1c", fg="#a0a0a0", relief=tk.FLAT,
                                   readonlybackground="#1c1c1c", state='readonly',
                                   font=("Helvetica", 8), justify='center')
            title_entry.grid(row=0, column=i_col, sticky='ew', padx=2, ipady=3)
            self.path_changer_title_displays[key] = title_entry
            
        self.error_label = tk.Label(self.right_frame, textvariable=self.error_message,
                                      font=("Helvetica", 10), fg="red", bg="black",
                                      anchor="se", justify=tk.RIGHT, wraplength=480)
        self.error_label.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=(0,5), ipady=2)

        self.png_frame = tk.Frame(self.right_frame, bg="black")
        self.png_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.png_label = tk.Label(self.png_frame, bg="black")
        self.png_label.pack(side=tk.TOP, anchor='n', expand=False, fill=tk.NONE, pady=5)

        self.png_original = None
        self.png_tk = None
        if self.png_path and os.path.exists(self.png_path):
            self.load_png_image(self.png_path)

        self.png_frame.bind("<Configure>", self.on_png_frame_resize)
        self.master.protocol("WM_DELETE_WINDOW", self.on_close)
        self._status_thread_stop_event = threading.Event()
        self._status_thread = threading.Thread(target=self.status_check_worker, daemon=True)
        self._status_thread.start()
        
        self.check_error_message()
        self.title_fetch_queue = queue.Queue()
        self._process_title_queue()
        self.setup_replay_hotkey()
        self.setup_f2_hotkey()
        self.setup_f3_hotkey()  # ✨ F3 단축키 설정 함수 호출
        self.update_timecode()

        self.vmix_volume_map_api_to_xml = {
            0: 0.0, 10: 0.01, 20: 0.16, 30: 0.81, 40: 2.56,
            50: 6.25, 60: 12.96, 70: 24.01, 80: 40.96, 90: 65.61, 100: 100.0
        }
        self.vmix_volume_map_xml_to_api_points = sorted([(v, k) for k, v in self.vmix_volume_map_api_to_xml.items()])

    def rebuild_ui(self):
        for widget in self.line_frame.winfo_children():
            widget.destroy()

        self.line_entries = []
        self.monitor_status = [LineMonitor() for _ in range(self.rail_count)]
        self.previous_line_ui_states = [{} for _ in range(self.rail_count)]
        
        while len(self.lines) < self.rail_count:
            self.lines.append({"timecode": "", "preview": "", "button": "", "set_timecode": "", "set_targets": [1,0,0,0]})
        self.lines = self.lines[:self.rail_count]

        vmix_names = [self.main_vmix_name] + [sub['name'] for sub in self.sub_vmix]
        header_texts_base = ["번호", "Timecode", "Pre", "B", "Run", "Stop", "남은시간"]
        header_texts_end = ["R Set Time"]
        full_header = header_texts_base + vmix_names[:4] + header_texts_end
        
        self.target_header_labels.clear()
        for col, text in enumerate(full_header):
            lbl = tk.Label(self.line_frame, text=text, font=("Helvetica", 9, "bold"), fg="#aaa", bg="black", padx=2)
            lbl.grid(row=0, column=col, sticky='w')
            if text in vmix_names:
                self.target_header_labels.append(lbl)

        self.widget_matrix = [[None for _ in range(len(full_header))] for _ in range(self.rail_count)]

        for i in range(self.rail_count):
            btn_no = tk.Button(self.line_frame, text=str(i+1), width=2, font=("Helvetica", 8), bg="#222", fg="#39FF14", activebackground="#333", activeforeground="#39FF14", relief=tk.RAISED, bd=1, command=lambda r_idx=i: self.clear_row(r_idx))
            btn_no.grid(row=i+1, column=0, padx=(1,1))
            self.widget_matrix[i][0] = btn_no

            e_time = tk.Entry(self.line_frame, width=9, justify='center')
            e_time.insert(0, self.lines[i]["timecode"])
            e_time.grid(row=i+1, column=1, padx=1)
            self.widget_matrix[i][1] = e_time

            e_preview = tk.Entry(self.line_frame, width=3, justify='center')
            e_preview.insert(0, self.lines[i].get("preview", ""))
            e_preview.grid(row=i + 1, column=2, padx=1)
            self.widget_matrix[i][2] = e_preview

            e_btn = tk.Entry(self.line_frame, width=3, justify='center')
            e_btn.insert(0, self.lines[i]["button"])
            e_btn.grid(row=i+1, column=3, padx=1)
            self.widget_matrix[i][3] = e_btn

            run_btn = tk.Button(self.line_frame, text="Run", width=5, bg="#222", fg="#fff", command=lambda idx=i: self.run_line(idx))
            run_btn.grid(row=i+1, column=4, padx=1)
            self.widget_matrix[i][4] = run_btn

            stop_btn = tk.Button(self.line_frame, text="Stop", width=5, bg="#222", fg="#fff", command=lambda idx=i: self.stop_line(idx))
            stop_btn.grid(row=i+1, column=5, padx=1)
            self.widget_matrix[i][5] = stop_btn

            l_diff = tk.Label(self.line_frame, text="00:00", font=("Helvetica", 9), fg="#fff", bg="black", width=6)
            l_diff.grid(row=i+1, column=6, padx=1)
            self.widget_matrix[i][6] = l_diff

            target_vars = []
            for t_idx in range(4):
                cb_col = 7 + t_idx
                var = tk.IntVar(value=self.lines[i].get("set_targets", [1,0,0,0])[t_idx])
                cb = tk.Checkbutton(self.line_frame, variable=var, bg="black", activebackground="black", selectcolor="#555", fg="white", activeforeground="white", highlightthickness=0, bd=0)
                cb.bind("<FocusIn>", lambda e, widget=cb: widget.config(bg="#004D00"))
                cb.bind("<FocusOut>", lambda e, widget=cb: widget.config(bg="black"))
                cb.grid(row=i+1, column=cb_col, sticky='ew')
                self.widget_matrix[i][cb_col] = cb
                target_vars.append(var)
            
            e_set_tc = tk.Entry(self.line_frame, width=9, justify='center')
            e_set_tc.insert(0, self.lines[i]["set_timecode"])
            e_set_tc.grid(row=i+1, column=11, padx=(2,1))
            self.widget_matrix[i][11] = e_set_tc

            bind_entry_extended_events(e_time, mode="timecode")
            bind_entry_extended_events(e_preview, mode="button")
            bind_entry_extended_events(e_btn, mode="button")
            bind_entry_extended_events(e_set_tc, mode="set_time")

            for col_idx, widget in enumerate(self.widget_matrix[i]):
                if widget:
                    bind_widget_full_navigation(widget, i, col_idx, self)
                    if is_focusable_widget(widget):
                        widget.bind("<FocusIn>", lambda e, w=widget: self._scroll_to_widget(w), add="+")

            self.line_entries.append({
                "time": e_time, "preview": e_preview, "button": e_btn, "run": run_btn, 
                "stop": stop_btn, "diff": l_diff,
                "set_tc": e_set_tc, "set_targets": target_vars,
                "no_btn": btn_no
            })
        
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _process_title_queue(self):
        try:
            while True:
                vmix_key, text_to_display, color = self.title_fetch_queue.get_nowait()
                title_entry = self.path_changer_title_displays.get(vmix_key)
                if title_entry:
                    title_entry.config(state='normal', fg=color)
                    title_entry.delete(0, tk.END)
                    title_entry.insert(0, text_to_display)
                    title_entry.config(state='readonly')
        except queue.Empty:
            pass
        finally:
            self.master.after(100, self._process_title_queue)

    def _fetch_title_worker(self, vmix_key, target_ip, target_port, vmix_name, input_num_str):
        try:
            vmix_api_url = f"http://{target_ip}:{target_port}/api/"
            response = requests.get(vmix_api_url, timeout=0.5)
            response.raise_for_status()
            root = ET.fromstring(response.text)
            
            found_title = "Input Not Found"
            for inp_elem in root.findall("./inputs/input"):
                if inp_elem.get("number") == input_num_str:
                    found_title = inp_elem.get("title", "타이틀 없음")
                    break
            self.title_fetch_queue.put((vmix_key, found_title, "#a0a0a0"))

        except requests.exceptions.Timeout:
            self.title_fetch_queue.put((vmix_key, "연결 시간 초과", "orange"))
        except requests.exceptions.RequestException:
            self.title_fetch_queue.put((vmix_key, "연결 실패", "red"))
        except ET.ParseError:
            self.title_fetch_queue.put((vmix_key, "XML 데이터 오류", "red"))
        except Exception as e:
            print(f"Error fetching title for {vmix_key} input {input_num_str}: {e}")
            self.title_fetch_queue.put((vmix_key, "오류 발생", "red"))
    
    def fetch_and_display_single_title(self, vmix_key, input_num_str):
        title_entry = self.path_changer_title_displays.get(vmix_key)
        if not title_entry:
            print(f"[ERROR] No title display widget found for vmix_key: {vmix_key}")
            return

        title_entry.config(state='normal', fg="#a0a0a0")
        title_entry.delete(0, tk.END)

        if not input_num_str.isdigit():
            if input_num_str: title_entry.insert(0, "숫자 입력")
            else: title_entry.insert(0, "")
            title_entry.config(state='readonly')
            return
        
        try:
            num = int(input_num_str)
            if not (0 <= num <= 9999):
                if input_num_str: title_entry.insert(0, "번호 범위 초과")
                title_entry.config(state='readonly')
                return
        except ValueError:
            if input_num_str: title_entry.insert(0, "잘못된 번호")
            title_entry.config(state='readonly')
            return

        target_ip, target_port, vmix_name = "", "", ""
        if vmix_key == "M": target_ip, target_port, vmix_name = self.main_ip, self.main_port, self.main_vmix_name
        elif vmix_key == "V1": target_ip, target_port, vmix_name = self.sub_vmix[0]["ip"], self.sub_vmix[0]["port"], self.sub_vmix[0]["name"]
        elif vmix_key == "V2": target_ip, target_port, vmix_name = self.sub_vmix[1]["ip"], self.sub_vmix[1]["port"], self.sub_vmix[1]["name"]
        elif vmix_key == "V3": target_ip, target_port, vmix_name = self.sub_vmix[2]["ip"], self.sub_vmix[2]["port"], self.sub_vmix[2]["name"]

        if not target_ip or not target_port:
            title_entry.insert(0, f"{vmix_name} IP/Port 미설정")
            title_entry.config(state='readonly')
            return
        
        conn_idx = {"M": 0, "V1": 1, "V2": 2, "V3": 3}.get(vmix_key, -1)
        if conn_idx != -1 and (conn_idx >= len(self.connection_states) or self.connection_states[conn_idx] != 2) :
            title_entry.insert(0, f"{vmix_name} 연결 안됨")
            title_entry.config(state='readonly', fg="orange")
            return

        title_entry.insert(0, "조회 중...")
        title_entry.config(state='readonly')

        threading.Thread(
            target=self._fetch_title_worker,
            args=(vmix_key, target_ip, target_port, vmix_name, input_num_str),
            daemon=True
        ).start()

    def _convert_xml_volume_to_api_value(self, xml_volume_str):
        try:
            target_xml_vol = float(xml_volume_str)
        except ValueError:
            self.push_error(f"경고: 잘못된 볼륨값 '{xml_volume_str}'. 기본값(100) 사용.")
            return "100"

        points = self.vmix_volume_map_xml_to_api_points

        if target_xml_vol <= points[0][0]: return str(points[0][1])
        if target_xml_vol >= points[-1][0]: return str(points[-1][1])

        for i in range(len(points) - 1):
            xml_vol_0, api_val_0 = points[i]
            xml_vol_1, api_val_1 = points[i+1]

            if xml_vol_0 <= target_xml_vol <= xml_vol_1:
                if math.isclose(xml_vol_0, xml_vol_1): return str(int(round(api_val_0)))
                api_val_interpolated = api_val_0 + (target_xml_vol - xml_vol_0) * (api_val_1 - api_val_0) / (xml_vol_1 - xml_vol_0)
                return str(int(round(api_val_interpolated)))
        
        self.push_error(f"경고: 볼륨값({target_xml_vol}) 매핑 실패. 기본값(100) 사용.")
        return "100"


    def _send_vmix_api_request(self, ip, port, vmix_name_for_log, params, action_description=""):
        api_url_base = f"http://{ip}:{port}/api/"
        action_name = params.get("Function", "UnknownAction")
        input_id_param = params.get("Input", "N/A")
        
        log_input_id = params.get('original_input_number', input_id_param)
        log_input_id_display = f"{input_id_param[:8]}..." if isinstance(input_id_param, str) and len(input_id_param) > 12 else input_id_param
        if input_id_param != "N/A" and log_input_id != input_id_param:
            log_input_id_display = f"{log_input_id}({log_input_id_display})"

        full_action_description = f"{action_description} ({action_name}, 인풋 {log_input_id_display})" if action_description else f"{action_name} (인풋 {log_input_id_display})"

        try:
            api_call_params = {k: v for k, v in params.items() if k != 'original_input_number'}
            response = requests.get(api_url_base, params=api_call_params, timeout=0.5)
            response.raise_for_status()
            return True, f"{vmix_name_for_log} {full_action_description} 성공."
        
        except requests.exceptions.HTTPError as e:
            err_text = str(e.response.status_code)
            try:
                root = ET.fromstring(e.response.text)
                err_text_from_vmix = root.text.strip() if root.text else ""
                if err_text_from_vmix: err_text = err_text_from_vmix
            except ET.ParseError: pass
            print(f"[ERROR] API Call ({action_name}) HTTPError for Input {input_id_param}: {err_text} - Full: {e.response.text}")
            return False, f"{vmix_name_for_log} {full_action_description} API 오류: {err_text[:100]}"
        except requests.exceptions.RequestException as e:
            return False, f"{vmix_name_for_log} {full_action_description} 연결 오류: {type(e).__name__}"
        except Exception as e:
            print(f"[ERROR] API Call ({action_name}) Exception for Input {input_id_param}: {type(e).__name__} - {e}")
            return False, f"{vmix_name_for_log} {full_action_description} 알 수 없는 오류: {type(e).__name__}"

    def change_input_path(self, vmix_key):
        target_ip, target_port, vmix_name = "", "", ""
        if vmix_key == "M": target_ip, target_port, vmix_name = self.main_ip, self.main_port, self.main_vmix_name
        elif vmix_key == "V1": target_ip, target_port, vmix_name = self.sub_vmix[0]["ip"], self.sub_vmix[0]["port"], self.sub_vmix[0]["name"]
        elif vmix_key == "V2": target_ip, target_port, vmix_name = self.sub_vmix[1]["ip"], self.sub_vmix[1]["port"], self.sub_vmix[1]["name"]
        elif vmix_key == "V3": target_ip, target_port, vmix_name = self.sub_vmix[2]["ip"], self.sub_vmix[2]["port"], self.sub_vmix[2]["name"]
        
        if not target_ip or not target_port:
            self.push_error(f"{vmix_name} vMix IP/Port 미설정."); return

        original_input_number_for_action = self.input_changer_entries[vmix_key].get().strip()
        if not original_input_number_for_action.isdigit():
            self.push_error(f"{vmix_name} 경로변경 대상 인풋 번호는 숫자여야 합니다."); return
        
        threading.Thread(target=self._path_change_worker, args=(vmix_key, target_ip, target_port, vmix_name, original_input_number_for_action), daemon=True).start()

    def _path_change_worker(self, vmix_key, target_ip, target_port, vmix_name, original_input_number_for_action):
        main_vmix_url = self.get_vmix_api_url(self.main_ip, self.main_port)
        main_active_input_num, _, _ = self.get_active_input_and_timecode(main_vmix_url)

        if vmix_key == "M":
            if original_input_number_for_action == main_active_input_num:
                self.push_error(f"{self.main_vmix_name}의 활성(Active) 인풋은 경로를 변경할 수 없습니다.")
                self.title_fetch_queue.put((vmix_key, "재생중", "red"))
                return

        elif vmix_key in ["V1", "V2", "V3"]:
            sub_index = {"V1": 0, "V2": 1, "V3": 2}[vmix_key]
            sub_vmix_config = self.sub_vmix[sub_index]
            capture_input_num = sub_vmix_config.get("capture_input")
            if capture_input_num and capture_input_num == main_active_input_num:
                sub_ip, sub_port, target_sub_input_num = sub_vmix_config.get("ip"), sub_vmix_config.get("port"), original_input_number_for_action
                if sub_ip and sub_port:
                    sub_vmix_url = self.get_vmix_api_url(sub_ip, sub_port)
                    sub_active_input_num, _, _ = self.get_active_input_and_timecode(sub_vmix_url)
                    if target_sub_input_num == sub_active_input_num:
                        self.push_error(f"{vmix_name}(인풋 {target_sub_input_num})은 현재 활성 상태이므로 변경할 수 없습니다.")
                        self.title_fetch_queue.put((vmix_key, "재생중", "red"))
                        return
        try:
            vmix_api_url = f"http://{target_ip}:{target_port}/api/"
            response = requests.get(vmix_api_url, timeout=1)
            response.raise_for_status()
            root = ET.fromstring(response.text)
            found_old_input = False
            old_input_guid, old_input_title = None, f"Input {original_input_number_for_action}"
            preserved_settings = {"volume": "100", "loop": "False", "muted": "False", "audiobusses": "M"}
            for inp_elem in root.findall("./inputs/input"):
                if inp_elem.get("number") == original_input_number_for_action:
                    old_input_guid, old_input_title = inp_elem.get("key"), inp_elem.get("title", old_input_title)
                    preserved_settings.update({k: inp_elem.get(k, v) for k, v in preserved_settings.items()})
                    found_old_input = True
                    break
            if not found_old_input or not old_input_guid:
                self.push_error(f"{vmix_name}에 인풋 {original_input_number_for_action} 없음."); return
        except Exception as e:
            self.push_error(f"{vmix_name} 기존 인풋 정보 조회 오류: {type(e).__name__}"); return

        _new_file_path_temp = filedialog.askopenfilename(title=f"{vmix_name} 인풋 {original_input_number_for_action} ({old_input_title}) 대체할 새 파일 선택")
        if not _new_file_path_temp: return
        new_file_path = os.path.normpath(_new_file_path_temp)
        new_file_filename = os.path.basename(new_file_path)

        success, msg = self._send_vmix_api_request(target_ip, target_port, vmix_name,
            {"Function": "AddInput", "Value": f"Video|{new_file_path}", "original_input_number": original_input_number_for_action},
            action_description="새 인풋 추가")
        if not success: self.push_error(msg); return
        time.sleep(2.5)

        new_input_guid, new_input_number_vmix = None, None
        try:
            response = requests.get(vmix_api_url, timeout=1.5)
            response.raise_for_status()
            root = ET.fromstring(response.text)
            candidate_inputs = [
                {"guid": i.get("key"), "number": int(i.get("number")), "title": i.get("title")}
                for i in reversed(root.findall("./inputs/input"))
                if i.get("title") == new_file_filename and i.get("type") == "Video"
            ]
            if candidate_inputs:
                candidate_inputs.sort(key=lambda x: x["number"], reverse=True)
                new_input_guid = candidate_inputs[0]["guid"]
                new_input_number_vmix = str(candidate_inputs[0]["number"])
            if not new_input_guid:
                self.push_error(f"{vmix_name}에서 새로 추가된 인풋({new_file_filename}) 식별 실패."); return
        except Exception as e:
            self.push_error(f"{vmix_name} 새 인풋 식별 중 오류: {type(e).__name__}"); return

        apply_settings_success_overall = True
        log_num_for_settings = new_input_number_vmix if new_input_number_vmix else "새 인풋"
        audio_setup_actions = [{"Function": "AudioOff" if preserved_settings["muted"] == "True" else "AudioOn", "Input": new_input_guid, "original_input_number": log_num_for_settings}]
        audio_setup_actions.extend([{"Function": "AudioBusOn", "Input": new_input_guid, "Value": b, "original_input_number": log_num_for_settings} for b in preserved_settings["audiobusses"].split(',') if b])
        
        for params in audio_setup_actions:
            success, msg = self._send_vmix_api_request(target_ip, target_port, vmix_name, params, action_description="오디오 설정")
            if not success: self.push_error(msg); apply_settings_success_overall = False
        
        main_settings_actions = [
            {"Function": "SetVolume", "Input": new_input_guid, "Value": self._convert_xml_volume_to_api_value(preserved_settings["volume"]), "original_input_number": log_num_for_settings},
            {"Function": "LoopOn" if preserved_settings["loop"] == "True" else "LoopOff", "Input": new_input_guid, "original_input_number": log_num_for_settings}
        ]
        for params in main_settings_actions:
            success, msg = self._send_vmix_api_request(target_ip, target_port, vmix_name, params, action_description="볼륨/루프 설정")
            if not success: self.push_error(msg); apply_settings_success_overall = False
        
        if not apply_settings_success_overall: print(f"[WARNING] Failed to apply some settings to {new_input_guid}, but continuing.")

        success, msg = self._send_vmix_api_request(target_ip, target_port, vmix_name,
            {"Function": "RemoveInput", "Input": old_input_guid, "original_input_number": original_input_number_for_action},
            action_description=f"기존 인풋({original_input_number_for_action}) 제거")
        if not success: self.push_error(msg); return
        time.sleep(0.5)

        success, msg = self._send_vmix_api_request(target_ip, target_port, vmix_name,
            {"Function": "MoveInput", "Input": new_input_guid, "Value": original_input_number_for_action, "original_input_number": original_input_number_for_action},
            action_description=f"새 인풋을 {original_input_number_for_action}번으로 이동")
        if not success:
            self.push_error(msg)
            if new_input_number_vmix:
                self.master.after(200, lambda k=vmix_key, num_str=new_input_number_vmix: self.fetch_and_display_single_title(k, num_str))
            return
        
        self.master.after(200, lambda k=vmix_key, num_str=original_input_number_for_action: self.fetch_and_display_single_title(k, num_str))
        self.push_error(f"{vmix_name} 인풋 {original_input_number_for_action}이(가) '{new_file_filename}'(으)로 교체 완료.")

    def clear_row(self, row_index):
        if self.monitor_status[row_index].running:
            self.push_error(f"레일 {row_index + 1}번은 실행 중이라 초기화할 수 없습니다."); return
        if 0 <= row_index < len(self.line_entries):
            line_data = self.line_entries[row_index]
            line_data["time"].delete(0, tk.END)
            line_data["preview"].delete(0, tk.END)
            line_data["button"].delete(0, tk.END)
            line_data["set_tc"].delete(0, tk.END)
            for var in line_data["set_targets"]: var.set(0)
            line_data["diff"].config(text="00:00", fg="#888")
            print(f"레일 {row_index + 1} 데이터 초기화됨.")

    def _scroll_to_widget(self, widget):
        self.master.after(50, lambda: self.__do_scroll(widget))

    def __do_scroll(self, widget):
        try:
            view_top_y, canvas_h = self.canvas.canvasy(0), self.canvas.winfo_height()
            view_bottom_y = view_top_y + canvas_h
            widget_y, widget_h = widget.winfo_y(), widget.winfo_height()
            widget_bottom = widget_y + widget_h
            total_content_height = self.line_frame.winfo_height()
            if total_content_height == 0: return
            if widget_y < view_top_y:
                self.canvas.yview_moveto(widget_y / total_content_height)
            elif widget_bottom > view_bottom_y:
                target_y_fraction = (widget_y - canvas_h + widget_h) / total_content_height
                self.canvas.yview_moveto(max(0, target_y_fraction))
        except (tk.TclError, AttributeError, ZeroDivisionError): pass

    def get_widget_by_rowcol(self, row, col):
        if 0 <= row < len(self.widget_matrix) and 0 <= col < len(self.widget_matrix[row]): return self.widget_matrix[row][col]
        return None
    
    def get_entry_by_rowcol(self, row, col_key):
        if 0 <= row < len(self.line_entries): return self.line_entries[row][col_key]
        return None

    def open_png_dialog(self):
        path = filedialog.askopenfilename(title="컴페니언 버튼 PNG 파일 선택", filetypes=[("PNG Images", "*.png")])
        if path:
            self.png_path = path
            self.load_png_image(path)
            self.save_all_settings()

    def load_png_image(self, path):
        try:
            self.png_original = Image.open(path)
            self.update_png_image()
        except Exception as e:
            self.png_original = None
            self.png_label.config(image='', text="이미지 오류", fg="red")
            print(f"PNG 파일 로드 오류: {e}")

    def update_png_image(self):
        if self.png_original is None:
            self.png_label.config(image='', text="PNG 파일 없음", fg="gray"); return
        frame_width, frame_height = self.png_frame.winfo_width(), self.png_frame.winfo_height()
        if frame_width < 10 or frame_height < 10: return
        img = self.png_original.copy()
        try:
            resample_filter = Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS
            img.thumbnail((frame_width, frame_height), resample_filter)
        except Exception:
             img.thumbnail((frame_width, frame_height))
        self.png_tk = ImageTk.PhotoImage(img)
        self.png_label.config(image=self.png_tk, text="")


    def on_png_frame_resize(self, event):
        if self.png_original is not None:
            if hasattr(self, "_png_resize_timer"): self.png_label.after_cancel(self._png_resize_timer)
            self._png_resize_timer = self.png_label.after(250, self.update_png_image)

    def get_vmix_api_url(self, ip, port): return f"http://{ip}:{port}/api/"

    def get_active_input_and_timecode(self, vmix_url):
        try:
            resp = requests.get(vmix_url, timeout=0.5)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            
            active_num_elem = root.find("active")
            if active_num_elem is None or not active_num_elem.text: return "", "", "--:--:--"
            active_num = active_num_elem.text.strip()

            active_input_element = root.find(f".//input[@number='{active_num}']")
            if active_input_element is None: return active_num, "", "--:--:--"
            
            active_type = active_input_element.get("type", "")

            if active_type == "Replay":
                replay_elem = active_input_element.find("replay")
                if replay_elem is not None and (tcA := replay_elem.find("timecodeA")) is not None and tcA.text:
                    try: return active_num, active_type, tcA.text.split("T")[1].split(".")[0]
                    except IndexError: return active_num, active_type, tcA.text
            elif active_type == "ReplayPreview":
                main_replay_input = root.find(".//input[@type='Replay']")
                if main_replay_input is not None and (replay_elem := main_replay_input.find("replay")) is not None and (tcB := replay_elem.find("timecodeB")) is not None and tcB.text:
                    try: return active_num, active_type, tcB.text.split("T")[1].split(".")[0]
                    except IndexError: return active_num, active_type, tcB.text
            elif active_type == "Video":
                position_str = active_input_element.get("position", "0")
                pos_ms = int(position_str) if position_str.isdigit() else 0
                secs, _ = divmod(pos_ms, 1000)
                h, rem = divmod(secs, 3600)
                m, s_val = divmod(rem, 60)
                return active_num, active_type, f"{h:02d}:{m:02d}:{s_val:02d}"
            
            return active_num, active_type, "--:--:--"

        except (requests.exceptions.RequestException, ET.ParseError, Exception):
            return "", "", "--:--:--"

    def get_current_timecode(self):
        if self.connection_states[0] != 2:
            return f"{self.main_vmix_name} Offline" if self.main_ip else "Set Main IP"
            
        main_url = self.get_vmix_api_url(self.main_ip, self.main_port)
        main_active, _, main_tc_val = self.get_active_input_and_timecode(main_url)

        if not main_active and main_tc_val == "--:--:--": return "--:--:--"

        for idx, sub in enumerate(self.sub_vmix):
            if not sub.get("ip") or not sub.get("port") or not sub.get("capture_input"): continue
            if main_active == sub["capture_input"]:
                sub_vmix_conn_idx = idx + 1
                if self.connection_states[sub_vmix_conn_idx] != 2: return f"{sub['name']} Offline"
                
                sub_url = self.get_vmix_api_url(sub["ip"], sub["port"])
                _, _, sub_tc = self.get_active_input_and_timecode(sub_url)
                return sub_tc if sub_tc and sub_tc != "--:--:--" else main_tc_val or "--:--:--"
        
        return main_tc_val or "--:--:--"

    def update_timecode(self):
        current_tc = self.get_current_timecode()
        if self.previous_timecode_label_text != current_tc:
            self.timecode_label.config(text=current_tc)
            self.previous_timecode_label_text = current_tc

        for idx, line_entry_data in enumerate(self.line_entries):
            user_tc_str = line_entry_data["time"].get().strip()
            diff_lbl_widget = line_entry_data["diff"]
            prev_state = self.previous_line_ui_states[idx]
            current_diff_text, current_fg_color = "00:00", "#888"
            
            is_valid_current_tc = (current_tc and len(current_tc) == 8 and ":" in current_tc)
            is_valid_user_tc = (user_tc_str and len(user_tc_str) == 8 and ":" in user_tc_str)

            seconds_left = None

            if is_valid_current_tc and is_valid_user_tc:
                try:
                    time_diff_delta = self.time_difference(current_tc, user_tc_str)
                    if time_diff_delta is not None:
                        current_diff_text = self.td_str(time_diff_delta)
                        seconds_left = int(time_diff_delta.total_seconds())
                        current_fg_color = "#fff"
                        if 0 <= seconds_left <= 5: current_fg_color = "#ff3030"
                        elif 0 <= seconds_left <= 10: current_fg_color = "#ffe400"
                        elif seconds_left < 0: current_fg_color = "#888"
                except (ValueError, TypeError):
                    current_diff_text, current_fg_color = "Format", "orange"
            
            if prev_state.get("diff_text") != current_diff_text or prev_state.get("diff_fg") != current_fg_color:
                diff_lbl_widget.config(text=current_diff_text, fg=current_fg_color)
                prev_state["diff_text"], prev_state["diff_fg"] = current_diff_text, current_fg_color

            monitor = self.monitor_status[idx]
            is_line_running_pending = monitor.running and not monitor.executed
            target_entry_state = "readonly" if is_line_running_pending else "normal"
            
            for key in ["time", "preview", "button", "set_tc"]:
                entry_widget = line_entry_data[key]
                if prev_state.get(f"{key}_state") != target_entry_state:
                    entry_widget.config(state=target_entry_state)
                    prev_state[f"{key}_state"] = target_entry_state
            
            run_btn_widget = line_entry_data["run"]
            expected_run_btn_bg = "#ff3030" if monitor.executed else ("#28cc28" if monitor.running else "#ffe400")
            if prev_state.get("run_btn_bg") != expected_run_btn_bg:
                run_btn_widget.config(bg=expected_run_btn_bg)
                prev_state["run_btn_bg"] = expected_run_btn_bg

            should_fire = False
            if seconds_left is not None and (seconds_left == 0 or seconds_left == -1):
                should_fire = True
            
            if monitor.running and not monitor.executed and should_fire:
                monitor.executed = True
                
                if (preview_val := line_entry_data["preview"].get().strip()).isdigit() and int(preview_val) > 0:
                    self.set_vmix_preview_input(int(preview_val))
                if (button_val := line_entry_data["button"].get().strip()).isdigit() and int(button_val) > 0:
                    threading.Timer(0.1, self.press_companion_button, args=[int(button_val)]).start()
                if (set_tc_val := line_entry_data["set_tc"].get().strip()) and len(set_tc_val) == 8 and any(var.get() for var in line_entry_data["set_targets"]):
                    threading.Timer(2.0, self.set_replay_timecode_multi, args=(set_tc_val, [v.get() for v in line_entry_data["set_targets"]])).start()
        
        self.master.after(200, self.update_timecode)

    def run_line(self, idx):
        self.monitor_status[idx].running, self.monitor_status[idx].executed = True, False
        self.line_entries[idx]["run"].focus_set()

    def stop_line(self, idx):
        self.monitor_status[idx].running, self.monitor_status[idx].executed = False, False
        self.line_entries[idx]["stop"].focus_set()

    def time_difference(self, cur, target):
        try: return datetime.strptime(target, "%H:%M:%S") - datetime.strptime(cur, "%H:%M:%S")
        except (ValueError, TypeError): return None

    def td_str(self, td):
        total_seconds = int(td.total_seconds())
        sign = "-" if total_seconds < 0 else ""
        m, s_val = divmod(abs(total_seconds), 60)
        return f"{sign}{m:02d}:{s_val:02d}"

    def set_vmix_preview_input(self, input_number):
        params = {"Function": "PreviewInput", "Input": str(input_number)}
        if self.main_ip and self.main_port:
            threading.Thread(target=self._send_vmix_api_request, args=(self.main_ip, self.main_port, self.main_vmix_name, params, f"인풋 {input_number} 프리뷰"), daemon=True).start()
        else:
            self.push_error(f"{self.main_vmix_name} IP/Port가 설정되지 않아 프리뷰 명령을 보내지 못했습니다.")
        
        v1_config = self.sub_vmix[0]
        if (v1_ip := v1_config.get("ip")) and (v1_port := v1_config.get("port")):
            threading.Thread(target=self._send_vmix_api_request, args=(v1_ip, v1_port, v1_config.get('name', '서브 vMix 1'), params, f"인풋 {input_number} 프리뷰"), daemon=True).start()

    def _press_companion_button_worker(self, url, page, button_on_page):
        try:
            requests.get(url, timeout=0.5)
        except requests.exceptions.RequestException as e:
            self.push_error(f"Companion 연결 오류 (P{page}, B{button_on_page}): {type(e).__name__}")
        except Exception as e:
            self.push_error(f"Companion 알 수 없는 오류 (P{page}, B{button_on_page}): {e}")

    def press_companion_button(self, btn_num_overall):
        if not self.companion_ip or not self.companion_port:
            self.push_error("Companion IP/Port 미설정"); return
        if btn_num_overall <= 0:
            self.push_error(f"잘못된 버튼 번호: {btn_num_overall}"); return

        page, button_on_page = divmod(btn_num_overall - 1, 32)
        url = f"http://{self.companion_ip}:{self.companion_port}/press/bank/{page + 1}/{button_on_page + 1}"
        threading.Thread(target=self._press_companion_button_worker, args=(url, page + 1, button_on_page + 1), daemon=True).start()

    def set_replay_timecode_multi(self, set_tc, set_targets):
        vmix_targets = [(self.main_ip, self.main_port, self.main_vmix_name)] + [(s["ip"], s["port"], s["name"]) for s in self.sub_vmix]
        def worker(ip, port, name):
            try:
                url = f"http://{ip}:{port}/api/?Function=ReplaySetTimecode&Value={set_tc}"
                r = requests.get(url, timeout=0.5)
                if r.status_code != 200: self.push_error(f"ReplaySetTC 오류 ({name}): {r.status_code}")
            except requests.exceptions.RequestException as e: self.push_error(f"ReplaySetTC 연결 오류 ({name}): {type(e).__name__}")
            except Exception as e: self.push_error(f"ReplaySetTC 알 수 없는 오류 ({name}): {e}")

        for i, (ip, port, name) in enumerate(vmix_targets):
            if set_targets[i] and ip and port:
                threading.Thread(target=worker, args=(ip, port, name), daemon=True).start()

    def update_vmix_name_labels(self):
        new_names = [self.main_vmix_name] + [sub.get('name', f'V{i+1}') for i, sub in enumerate(self.sub_vmix)]
        new_status_items = [(new_names[0], "Main vMix"),(new_names[1], "서브1"),(new_names[2], "서브2"),(new_names[3], "서브3"),("C", "Companion")]
        self.status_bar.update_labels(new_status_items)
        for i, label in enumerate(self.target_header_labels):
            if i < len(new_names): label.config(text=new_names[i])
        vmix_keys = ["M", "V1", "V2", "V3"]
        for i, key in enumerate(vmix_keys):
            if i < len(new_names) and key in self.input_changer_labels:
                self.input_changer_labels[key].config(text=f"{new_names[i]}:")
                
    def open_settings_window(self):
        window = tk.Toplevel(self.master)
        window.title("IP 및 이름 관리")
        window.configure(bg="black")
        label_options = {"bg": "black", "fg": "white"}
        entry_options = {"bg": "#333", "fg": "white", "insertbackground": "white", "borderwidth": 1, "relief": "solid"}
        
        main_name_entry = tk.Entry(window, **entry_options, width=10)
        main_name_entry.insert(0, self.main_vmix_name)
        main_name_entry.grid(row=0, column=0, padx=5, pady=2, sticky='e')
        tk.Label(window, text="IP:", **label_options).grid(row=0, column=1, sticky='e', padx=5, pady=2)
        main_ip_entry = tk.Entry(window, **entry_options)
        main_ip_entry.insert(0, self.main_ip)
        main_ip_entry.grid(row=0, column=2, padx=5, pady=2)
        tk.Label(window, text="포트:", **label_options).grid(row=0, column=3, sticky='e', padx=5, pady=2)
        main_port_entry = tk.Entry(window, width=6, **entry_options)
        main_port_entry.insert(0, self.main_port)
        main_port_entry.grid(row=0, column=4, padx=5, pady=2)

        sub_entries = []
        for i in range(3):
            name_entry = tk.Entry(window, **entry_options, width=10)
            name_entry.insert(0, self.sub_vmix[i]["name"])
            name_entry.grid(row=i+1, column=0, sticky='e', padx=5, pady=2)
            tk.Label(window, text="IP:", **label_options).grid(row=i+1, column=1, sticky='e', padx=5, pady=2)
            ip_entry = tk.Entry(window, **entry_options)
            ip_entry.insert(0, self.sub_vmix[i]["ip"])
            ip_entry.grid(row=i+1, column=2, padx=5, pady=2)
            tk.Label(window, text="포트:", **label_options).grid(row=i+1, column=3, sticky='e', padx=5, pady=2)
            port_entry = tk.Entry(window, width=6, **entry_options)
            port_entry.insert(0, self.sub_vmix[i]["port"])
            port_entry.grid(row=i+1, column=4, padx=5, pady=2)
            tk.Label(window, text="캡처 인풋:", **label_options).grid(row=i+1, column=5, sticky='e', padx=5, pady=2)
            ci_entry = tk.Entry(window, width=6, **entry_options)
            ci_entry.insert(0, self.sub_vmix[i]["capture_input"])
            ci_entry.grid(row=i+1, column=6, padx=5, pady=2)
            sub_entries.append((name_entry, ip_entry, port_entry, ci_entry))
            
        tk.Label(window, text="Companion IP:", **label_options).grid(row=4, column=1, sticky='e', padx=5, pady=2)
        comp_ip_entry = tk.Entry(window, **entry_options)
        comp_ip_entry.insert(0, self.companion_ip)
        comp_ip_entry.grid(row=4, column=2, padx=5, pady=2)
        tk.Label(window, text="포트:", **label_options).grid(row=4, column=3, sticky='e', padx=5, pady=2)
        comp_port_entry = tk.Entry(window, width=6, **entry_options)
        comp_port_entry.insert(0, self.companion_port)
        comp_port_entry.grid(row=4, column=4, padx=5, pady=2)

        def save():
            self.main_vmix_name, self.main_ip, self.main_port = main_name_entry.get().strip(), main_ip_entry.get().strip(), main_port_entry.get().strip()
            for i, (name_e, ip_e, port_e, ci_e) in enumerate(sub_entries):
                self.sub_vmix[i].update({"name": name_e.get().strip(), "ip": ip_e.get().strip(), "port": port_e.get().strip(), "capture_input": ci_e.get().strip()})
            self.companion_ip, self.companion_port = comp_ip_entry.get().strip(), comp_port_entry.get().strip()
            self.save_all_settings()
            self.update_vmix_name_labels()
            self.push_error("IP 및 이름 설정이 저장되었습니다.")
            window.destroy()

        save_button = tk.Button(window, text="저장", command=save, bg="#28a745", fg="white", padx=10, pady=5, relief="flat")
        save_button.grid(row=5, column=0, columnspan=7, pady=15)
        window.protocol("WM_DELETE_WINDOW", save)
        window.transient(self.master)
        window.grab_set()
        self.master.wait_window(window)

    def open_replay_hotkey_settings(self):
        window = tk.Toplevel(self.master)
        window.title("vMix 리플레이 타임코드 단축키 설정")
        window.configure(bg="black")
        window.geometry("400x120")
        label_options, entry_options = {"bg": "black", "fg": "white"}, {"bg": "#333", "fg": "white", "insertbackground": "white", "borderwidth": 1, "relief": "solid"}
        tk.Label(window, text="vMix 리플레이 IP 주소:", **label_options).pack(pady=(10, 2))
        ip_entry = tk.Entry(window, width=30, **entry_options)
        ip_entry.insert(0, self.replay_hotkey_ip)
        ip_entry.pack(pady=2)
        tk.Label(window, text="(비워두고 저장 시 기능 비활성화)", font=("Helvetica", 8), **label_options).pack(pady=(0, 5))

        def save_hotkey_settings():
            try:
                self.replay_hotkey_ip = ip_entry.get().strip()
                self.save_all_settings()
                self.setup_replay_hotkey() 
                self.push_error(f"단축키 기능 활성화 (IP: {self.replay_hotkey_ip})" if self.replay_hotkey_ip else "단축키 기능 비활성화됨")
                messagebox.showinfo("설정 저장", "리플레이 단축키 설정이 성공적으로 저장되었습니다.", parent=window)
            except Exception as e:
                messagebox.showerror("오류", f"설정 저장 중 오류 발생: {e}", parent=window)
            finally:
                window.destroy()

        save_button = tk.Button(window, text="저장", command=save_hotkey_settings, bg="#28a745", fg="white", padx=10, pady=5, relief="flat")
        save_button.pack(pady=5)
        window.protocol("WM_DELETE_WINDOW", save_hotkey_settings)
        window.transient(self.master)
        window.grab_set()
        self.master.wait_window(window)
        
    def open_rail_count_settings(self):
        new_count_str = simpledialog.askstring("레일 수 설정", "레일 수를 입력하세요 (1-100):", parent=self.master, initialvalue=str(self.rail_count))
        if new_count_str:
            try:
                new_count = int(new_count_str)
                if 1 <= new_count <= 100:
                    if new_count != self.rail_count:
                        self.rail_count = new_count
                        self.rebuild_ui()
                        self.save_all_settings()
                        self.push_error(f"레일 수가 {new_count}개로 변경되었습니다.")
                else:
                    messagebox.showerror("입력 오류", "1에서 100 사이의 숫자를 입력해야 합니다.", parent=self.master)
            except ValueError:
                messagebox.showerror("입력 오류", "유효한 숫자를 입력해야 합니다.", parent=self.master)

    def setup_replay_hotkey(self):
        try: keyboard.remove_hotkey('f11')
        except (KeyError, AttributeError, ValueError): pass 
        if self.replay_hotkey_ip:
            try:
                keyboard.add_hotkey('f11', self.on_replay_hotkey_pressed)
                print(f"리플레이 타임코드 단축키(F11)가 IP {self.replay_hotkey_ip}에 대해 활성화되었습니다.")
            except Exception as e:
                self.push_error(f"단축키 등록 오류: {e}")
                print(f"단축키 등록 오류: {e}")
    
    def setup_f2_hotkey(self):
        try:
            keyboard.remove_hotkey('f2')
        except (KeyError, AttributeError, ValueError):
            pass
        try:
            keyboard.add_hotkey('f2', self.activate_all_prepared_rails)
            print("F2 단축키가 '준비된 모든 레일 활성화' 기능에 할당되었습니다.")
        except Exception as e:
            self.push_error(f"F2 단축키 등록 오류: {e}")
            
    # ✨ F3 단축키 설정 함수 추가
    def setup_f3_hotkey(self):
        try:
            keyboard.remove_hotkey('f3')
        except (KeyError, AttributeError, ValueError):
            pass
        try:
            keyboard.add_hotkey('f3', self.stop_all_rails)
            print("F3 단축키가 '모든 레일 중지' 기능에 할당되었습니다.")
        except Exception as e:
            self.push_error(f"F3 단축키 등록 오류: {e}")

    def on_replay_hotkey_pressed(self): threading.Thread(target=self.execute_replay_hotkey, daemon=True).start()

    def activate_all_prepared_rails(self):
        try:
            activated_count = 0
            for idx, line_entry in enumerate(self.line_entries):
                if line_entry['time'].get().strip():
                    if not self.monitor_status[idx].running:
                        self.run_line(idx)
                        activated_count += 1
            
            if activated_count > 0:
                self.push_error(f"타임코드가 입력된 {activated_count}개의 레일을 활성화했습니다.")
            else:
                self.push_error("활성화할 레일이 없습니다. (타임코드 미입력)")
        except Exception as e:
            self.push_error(f"F2 단축키 실행 중 오류 발생: {e}")
            
    # ✨ F3 단축키 실행 함수 추가
    def stop_all_rails(self):
        """모든 레일의 'Stop' 버튼을 누르는 효과를 냅니다."""
        try:
            for i in range(self.rail_count):
                self.stop_line(i)
            self.push_error(f"{self.rail_count}개의 모든 레일을 중지했습니다.")
        except Exception as e:
            self.push_error(f"F3 단축키 실행 중 오류 발생: {e}")

    def execute_replay_hotkey(self):
        if not self.replay_hotkey_ip: return
        api_url = f"http://{self.replay_hotkey_ip}:8088/api/"
        try:
            response = requests.get(api_url, timeout=0.5)
            response.raise_for_status()
            root = ET.fromstring(response.text)
            if (timecode_element := root.find('.//replay/timecode')) is not None and timecode_element.text:
                hh_mm_ss = timecode_element.text.split('T')[1].split('.')[0]
                pyperclip.copy(hh_mm_ss)
                time.sleep(0.1) 
                keyboard.send('ctrl+v')
                self.push_error(f"성공: 리플레이 타임코드 '{hh_mm_ss}'를 붙여넣었습니다.")
            else:
                self.push_error("단축키 오류: 리플레이 타임코드를 찾을 수 없습니다.")
        except requests.exceptions.RequestException as e:
            self.push_error(f"단축키 오류: vMix 연결 실패 ({type(e).__name__})")
        except Exception as e:
            self.push_error(f"단축키 오류: 알 수 없는 문제 ({type(e).__name__})")

    def save_all_settings(self):
        for i, entry_group in enumerate(self.line_entries):
            if i < len(self.lines):
                self.lines[i]["timecode"] = entry_group["time"].get()
                self.lines[i]["preview"] = entry_group["preview"].get()
                self.lines[i]["button"] = entry_group["button"].get()
                self.lines[i]["set_timecode"] = entry_group["set_tc"].get()
                self.lines[i]["set_targets"] = [var.get() for var in entry_group["set_targets"]]
        
        settings = {
            "main_vmix_name": self.main_vmix_name, "main_ip": self.main_ip, "main_port": self.main_port,
            "sub_vmix": self.sub_vmix, "companion_ip": self.companion_ip, "companion_port": self.companion_port,
            "lines": self.lines, "png_path": self.png_path, "replay_hotkey_ip": self.replay_hotkey_ip,
            "window_geometry": self.master.winfo_geometry(),
            "rail_count": self.rail_count
        }
        save_settings(settings)
        messagebox.showinfo("설정 저장", "모든 설정이 성공적으로 저장되었습니다.", parent=self.master)

    def on_close(self):
        self.save_all_settings()
        if hasattr(self, '_status_thread_stop_event'): self._status_thread_stop_event.set()
        try:
            keyboard.unhook_all()
            print("키보드 훅(hook)이 모두 정리되었습니다.")
        except Exception as e: print(f"키보드 훅 정리 중 오류 발생: {e}")
        self.master.destroy()

    def status_check_worker(self):
        while not hasattr(self, '_status_thread_stop_event') or not self._status_thread_stop_event.is_set():
            targets_to_check = [("vmix", self.main_ip, self.main_port)]
            for sub in self.sub_vmix:
                targets_to_check.append(("vmix", sub["ip"], sub["port"]))
            targets_to_check.append(("companion", self.companion_ip, self.companion_port))

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(targets_to_check)) as executor:
                future_to_idx = {executor.submit(self.ping_target, type_, ip, port): i for i, (type_, ip, port) in enumerate(targets_to_check)}
                current_states = [0] * len(targets_to_check)
                for future in concurrent.futures.as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    try:
                        current_states[idx] = future.result()
                    except Exception:
                        current_states[idx] = 1
            with self._status_lock:
                self.connection_states = current_states[:5]
            if hasattr(self, '_status_thread_stop_event') and self._status_thread_stop_event.wait(3):
                break

    def ping_target(self, conn_type, ip, port):
        if not ip or not port:
            return 0
        if conn_type == "vmix":
            url = f"http://{ip}:{port}/api/"
        elif conn_type == "companion":
            url = f"http://{ip}:{port}/"
        else:
            return 0
        try:
            r = requests.get(url, timeout=0.25)
            return 2 if r.status_code == 200 else 1
        except requests.exceptions.RequestException:
            return 1

    def get_connection_status(self):
        with self._status_lock: return list(self.connection_states)

    def push_error(self, msg): self.msg_queue.put(msg)

    def check_error_message(self):
        try:
            new_messages = [self.msg_queue.get_nowait() for _ in range(self.msg_queue.qsize())]
            if new_messages:
                self.error_message.set(" | ".join(new_messages))
                if hasattr(self, '_error_clear_timer_id'): self.master.after_cancel(self._error_clear_timer_id)
                self._error_clear_timer_id = self.master.after(5000, lambda: self.error_message.set(""))
        except Exception as e: print(f"Error in check_error_message: {e}")
        self.master.after(400, self.check_error_message)

if __name__ == "__main__":
    root = tk.Tk()
    app = ActiveTimecodeApp(root)
    root.mainloop()


# In[ ]:




