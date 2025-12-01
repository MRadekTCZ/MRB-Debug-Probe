import serial
import serial.tools.list_ports
import tkinter as tk
from tkinter import ttk
from collections import deque
import threading
import os
import csv
import struct
from queue import Queue
import time
import sys

# ============================================================
# Helper to handle resource path (for PyInstaller)
# ============================================================
def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return relative_path

# ============================================================
# Safe parsing helpers
# ============================================================
def safe_int(value, default=0):
    try:
        return int(value)
    except:
        return default

def safe_float(value, default=1.0):
    try:
        return float(value)
    except:
        return default

# ============================================================
# Tkinter helpers
# ============================================================
def list_serial_ports():
    return [p.device for p in serial.tools.list_ports.comports()]

def refresh_ports():
    ports = list_serial_ports()
    port_menu["values"] = ports
    if ports:
        port_var.set(ports[0])

# ============================================================
# GLOBAL for "applied" input values
# ============================================================
applied_input_values = [0] * 8

# ============================================================
# Serial reader thread
# ============================================================
def serial_reader(q, stop_event, port_name, baudrate, n_channels):
    HEADER = b'MRB_'
    NUM_BYTES_AFTER_HEADER = 16  # 8 shorts x 2 bytes
    try:
        global ser
        ser = serial.Serial(port_name, baudrate, timeout=0.01)
    except Exception as e:
        print("Cannot open port:", e)
        return

    buffer = bytearray()
    while not stop_event.is_set():
        try:
            if ser.in_waiting > 0:
                buffer.extend(ser.read(ser.in_waiting))
        except Exception as e:
            print("Serial read error:", e)
            break

        while True:
            idx = buffer.find(HEADER)
            if idx == -1 or len(buffer) < idx + len(HEADER) + NUM_BYTES_AFTER_HEADER:
                break
            frame_bytes = buffer[idx + len(HEADER): idx + len(HEADER) + NUM_BYTES_AFTER_HEADER]
            buffer = buffer[idx + len(HEADER) + NUM_BYTES_AFTER_HEADER:]
            try:
                vals_all = struct.unpack('<8h', frame_bytes)
            except Exception:
                continue
            vals = vals_all[:n_channels]
            t = time.time()
            q.put((t, vals))

# ============================================================
# Build frame from applied values
# ============================================================
def build_frame():
    HEADER = b'MRB_'
    NUM_INPUTS = 8
    n = safe_int(input_count_var.get(), 0)
    vals = []
    for i in range(NUM_INPUTS):
        if i < n:
            vals.append(applied_input_values[i])
        else:
            vals.append(0)
    return HEADER + struct.pack('<8h', *vals)

# ============================================================
# Byte-by-byte input sender
# ============================================================
def input_sender(stop_event):
    global ser
    idx = 0
    while not stop_event.is_set():
        try:
            frame = build_frame()
            ser.write(frame[idx:idx+1])
            idx = (idx + 1) % len(frame)
        except Exception as e:
            print("Send error:", e)
        time.sleep(0.001)

# ============================================================
# Real-time plot thread
# ============================================================
def live_plot_thread(start_btn):
    import pyqtgraph as pg
    from PyQt5 import QtWidgets, QtCore

    colors = [
        (255, 0, 0), (0, 150, 0), (0, 0, 255),
        (255, 165, 0), (128, 0, 128), (0, 200, 200),
        (200, 0, 200), (128, 64, 0)
    ]

    n_channels = max(1, safe_int(ch_count_var.get(), 1))
    q = Queue()
    stop_event = threading.Event()

    port_name = port_var.get()
    baudrate = safe_int(baud_var.get(), 115200)

    reader_thread = threading.Thread(target=serial_reader, args=(q, stop_event, port_name, baudrate, n_channels))
    reader_thread.start()
    sender_thread = threading.Thread(target=input_sender, args=(stop_event,))
    sender_thread.start()

    times = deque()
    channels = [deque() for _ in range(n_channels)]

    csv_enabled = csv_var.get() == "Yes"
    if csv_enabled:
        i = 1
        while os.path.exists(f"data{i}.csv"):
            i += 1
        csv_file = open(f"data{i}.csv", "w", newline='')
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["timestamp"] + [ch_name_vars[j].get() or f"ch{j+1}" for j in range(n_channels)])

    app = QtWidgets.QApplication([])
    win = pg.GraphicsLayoutWidget(show=True, title="MRB Live Plot")
    win.resize(1000, 600)
    plot = win.addPlot()
    plot.setLabel('bottom', 'Time [s]')
    plot.setLabel('left', 'Value')
    plot.addLegend()

    curves = []
    for i in range(n_channels):
        pen = pg.mkPen(color=colors[i % len(colors)], width=2)
        curves.append(plot.plot([], [], pen=pen, name=ch_name_vars[i].get() or f"ch{i+1}"))

    first_timestamp = None

    def update():
        nonlocal curves, channels, times, first_timestamp
        gains = [safe_float(ch_gain_vars[i].get(), 1.0) for i in range(n_channels)]

        while not q.empty():
            t, vals = q.get()
            if first_timestamp is None:
                first_timestamp = t
            t_rel = t - first_timestamp
            times.append(t_rel)

            for ch, v, g in zip(channels, vals, gains):
                ch.append(v * g)

            window_sec = safe_float(window_var.get(), 10.0)
            while times and (times[-1] - times[0] > window_sec):
                times.popleft()
                for ch in channels:
                    if ch:
                        ch.popleft()

            if csv_enabled:
                csv_writer.writerow([t_rel] + list(vals))

        t_list = list(times)
        for c, ch in zip(curves, channels):
            c.setData(t_list, list(ch))

        if t_list:
            plot.setYRange(safe_float(ylim_min_var.get(), -200), safe_float(ylim_max_var.get(), 200))
            plot.setXRange(max(0, t_list[-1] - safe_float(window_var.get(), 10)), t_list[-1])

    timer = QtCore.QTimer()
    timer.timeout.connect(update)
    timer.start(10)

    def on_close():
        stop_event.set()
        reader_thread.join(timeout=1.0)
        sender_thread.join(timeout=1.0)
        try:
            ser.close()
        except:
            pass
        if csv_enabled:
            csv_file.close()
        start_btn.config(state="normal")
        app.quit()

    win.closeEvent = lambda event: on_close()
    app.exec_()

# ============================================================
# Tkinter GUI Layout
# ============================================================
root = tk.Tk()
root.title("MRBDebugProbe")

main = ttk.Frame(root, padding=10)
main.grid(row=0, column=0, sticky="nsew")

# ==== LEFT FRAME: Controls ====
left = ttk.Frame(main)
left.grid(row=0, column=0, sticky="nw")

# ==== RIGHT FRAME: Image ====
right = ttk.Frame(main)
right.grid(row=0, column=1, padx=20, sticky="n")

# Load the image
try:
    original = tk.PhotoImage(file=resource_path("chalmers_logo.png"))
    tk_img = original.subsample(3, 3)
    img_label = ttk.Label(right, image=tk_img)
    img_label.image = tk_img
    img_label.grid(row=0, column=0, pady=10)
except:
    img_label = ttk.Label(right, text="Cannot load image", width=40)
    img_label.grid(row=0, column=0, pady=10)

# Version label at top-right corner of right frame
version_label = ttk.Label(right, text="v2.0 Release", font=("Arial", 8))
version_label.grid(row=1, column=0, sticky="e", padx=5, pady=(0,10))

# ------------------------------------------------------------
# Serial Settings
# ------------------------------------------------------------
row = 0
ttk.Label(left, text="Serial Settings", font=("Arial", 11, "bold")).grid(column=0, row=row, columnspan=3, pady=(0,5))

row += 1
ttk.Label(left, text="Port").grid(column=0, row=row, sticky="w")
port_var = tk.StringVar()
port_menu = ttk.Combobox(left, textvariable=port_var, width=12, state="readonly")
port_menu.grid(column=1, row=row)
ttk.Button(left, text="Scan", command=refresh_ports).grid(column=2, row=row)

row += 1
ttk.Label(left, text="Baud").grid(column=0, row=row, sticky="w")
baud_var = tk.StringVar(value="115200")
baud_menu = ttk.Combobox(left, textvariable=baud_var,
                         values=["9600","19200","38400","57600","115200","230400","460800","921600"],
                         width=12, state="readonly")
baud_menu.grid(column=1, row=row)

row += 1
ttk.Label(left, text="Window [s]").grid(column=0, row=row, sticky="w")
window_var = tk.StringVar(value="10")
ttk.Entry(left, textvariable=window_var, width=12).grid(column=1, row=row)

row += 1
ttk.Label(left, text="Y min").grid(column=0, row=row, sticky="w")
ylim_min_var = tk.StringVar(value="-200")
ttk.Entry(left, textvariable=ylim_min_var, width=12).grid(column=1, row=row)

row += 1
ttk.Label(left, text="Y max").grid(column=0, row=row, sticky="w")
ylim_max_var = tk.StringVar(value="200")
ttk.Entry(left, textvariable=ylim_max_var, width=12).grid(column=1, row=row)

row += 1
ttk.Label(left, text="Save CSV").grid(column=0, row=row, sticky="w")
csv_var = tk.StringVar(value="No")
csv_menu = ttk.Combobox(left, textvariable=csv_var, values=["Yes","No"], width=12, state="readonly")
csv_menu.grid(column=1, row=row)

# ------------------------------------------------------------
# Channels
# ------------------------------------------------------------
row += 2
ttk.Label(left, text="Channels", font=("Arial", 11, "bold")).grid(column=0, row=row, columnspan=3, pady=(10,5))
row += 1
ttk.Label(left, text="Count").grid(column=0, row=row, sticky="w")
ch_count_var = tk.StringVar(value="3")
ch_count_spin = ttk.Spinbox(left, from_=1, to=8, textvariable=ch_count_var, width=5, command=lambda: update_channel_fields())
ch_count_spin.grid(column=1, row=row)

ch_name_vars, ch_gain_vars, ch_widgets = [], [], []

for i in range(8):
    row_i = row + 1 + i
    name_var = tk.StringVar(value=f"ch{i+1}")
    gain_var = tk.StringVar(value="1.0")
    ch_name_vars.append(name_var)
    ch_gain_vars.append(gain_var)

    lbl_name = ttk.Label(left, text=f"Name {i+1}")
    ent_name = ttk.Entry(left, textvariable=name_var, width=10)
    lbl_gain = ttk.Label(left, text="Gain")
    ent_gain = ttk.Entry(left, textvariable=gain_var, width=6)

    lbl_name.grid(column=0, row=row_i, sticky="w")
    ent_name.grid(column=1, row=row_i, sticky="w")
    lbl_gain.grid(column=2, row=row_i, sticky="w")
    ent_gain.grid(column=3, row=row_i, sticky="w")

    ch_widgets.append([lbl_name, ent_name, lbl_gain, ent_gain])

def update_channel_fields():
    n = max(1, safe_int(ch_count_var.get(), 1))
    for i in range(8):
        widgets = ch_widgets[i]
        if i < n:
            for w in widgets:
                w.grid()
        else:
            for w in widgets:
                w.grid_remove()

update_channel_fields()

# ------------------------------------------------------------
# Inputs
# ------------------------------------------------------------
inputs_start_row = row + 10
ttk.Label(left, text="Inputs", font=("Arial", 11, "bold")).grid(column=0, row=inputs_start_row, columnspan=3, pady=(10,5))

inputs_start_row += 1
ttk.Label(left, text="Count").grid(column=0, row=inputs_start_row, sticky="w")
input_count_var = tk.StringVar(value="2")
input_count_spin = ttk.Spinbox(left, from_=1, to=8, textvariable=input_count_var, width=5)
input_count_spin.grid(column=1, row=inputs_start_row)

input_val_vars, input_widgets = [], []

for i in range(8):
    row_i = inputs_start_row + 1 + i
    var = tk.StringVar(value="0")
    input_val_vars.append(var)

    lbl = ttk.Label(left, text=f"Input {i+1}")
    ent = ttk.Entry(left, textvariable=var, width=10)

    lbl.grid(column=0, row=row_i, sticky="w")
    ent.grid(column=1, row=row_i, sticky="w")

    input_widgets.append([lbl, ent])

def update_input_fields():
    n = max(1, safe_int(input_count_var.get(), 1))

    # show/hide input fields
    for i in range(8):
        widgets = input_widgets[i]
        if i < n:
            for w in widgets:
                w.grid()
        else:
            for w in widgets:
                w.grid_remove()

    # APPLY VALUES (only now)
    for i in range(n):
        applied_input_values[i] = safe_int(input_val_vars[i].get(), 0)

update_input_fields()

# Update Inputs button
ttk.Button(left, text="Update Inputs", command=update_input_fields).grid(column=0, row=inputs_start_row + 10, pady=10, sticky="w")

# Start Plot button - bigger and centered
start_btn = ttk.Button(left, text="Start Plot", command=lambda: (
    start_btn.config(state="disabled"),
    threading.Thread(target=live_plot_thread, args=(start_btn,), daemon=True).start()
))
start_btn.grid(column=0, row=inputs_start_row + 12, columnspan=5, pady=20, sticky="ew")
start_btn.configure(width=20)  # make the button wider

refresh_ports()
root.mainloop()
