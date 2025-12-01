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
# Serial reader thread
# ============================================================

def serial_reader(q, stop_event, port_name, baudrate, n_channels):
    HEADER = b'MRB_'
    NUM_BYTES_AFTER_HEADER = 20  # 10 shorts x 2 bytes
    try:
        global ser
        ser = serial.Serial(port_name, baudrate, timeout=0.01)
    except Exception as e:
        print("Cannot open port:", e)
        return

    buffer = bytearray()
    while not stop_event.is_set():
        if ser.in_waiting > 0:
            buffer.extend(ser.read(ser.in_waiting))

        while True:
            idx = buffer.find(HEADER)
            if idx == -1 or len(buffer) < idx + len(HEADER) + NUM_BYTES_AFTER_HEADER:
                break
            frame_bytes = buffer[idx+len(HEADER):idx+len(HEADER)+NUM_BYTES_AFTER_HEADER]
            buffer = buffer[idx+len(HEADER)+NUM_BYTES_AFTER_HEADER:]
            vals_all = struct.unpack('<10h', frame_bytes)
            vals = vals_all[:n_channels]
            t = time.time()
            q.put((t, vals))

# ============================================================
# Build output frame (10 shorts)
# ============================================================

def build_frame():
    HEADER = b'MRB_'
    NUM_OUTPUTS = 10
    n_outputs = int(out_count_var.get())
    vals = []
    for i in range(NUM_OUTPUTS):
        if i < n_outputs:
            val = int(out_val_vars[i].get())
        else:
            val = 0
        vals.append(val)
    frame = HEADER + struct.pack('<10h', *vals)
    return frame

# ============================================================
# Byte-by-byte output sender thread
# ============================================================

def output_sender(stop_event):
    global ser
    frame = build_frame()
    idx = 0
    while not stop_event.is_set():
        try:
            # refresh frame each cycle so GUI changes are taken into account
            frame = build_frame()
            ser.write(frame[idx:idx+1])
            idx = (idx + 1) % len(frame)
        except Exception as e:
            print("Send error:", e)
        time.sleep(0.001)  # send one byte every 1 ms

# ============================================================
# Real-time plotting thread
# ============================================================

def live_plot_thread(start_btn):
    import pyqtgraph as pg
    from PyQt5 import QtWidgets, QtCore

    colors = [
        (255, 0, 0), (0, 150, 0), (0, 0, 255),
        (255, 165, 0), (128, 0, 128), (0, 200, 200),
        (200, 0, 200), (128, 64, 0), (80, 80, 80), (255, 255, 0)
    ]

    n_channels = int(ch_count_var.get())
    q = Queue()
    stop_event = threading.Event()

    port_name = port_var.get()
    baudrate = int(baud_var.get())

    # start receiver and sender threads
    reader_thread = threading.Thread(target=serial_reader, args=(q, stop_event, port_name, baudrate, n_channels))
    reader_thread.start()
    sender_thread = threading.Thread(target=output_sender, args=(stop_event,))
    sender_thread.start()

    times = deque()
    channels = [deque() for _ in range(n_channels)]

    # CSV setup
    csv_enabled = csv_var.get() == "Yes"
    if csv_enabled:
        i = 1
        while os.path.exists(f"data{i}.csv"):
            i += 1
        csv_file = open(f"data{i}.csv", "w", newline='')
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["timestamp"] + [ch_name_vars[i].get() or f"ch{i+1}" for i in range(n_channels)])

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
        gains = [float(ch_gain_vars[i].get()) for i in range(n_channels)]

        while not q.empty():
            t, vals = q.get()
            if first_timestamp is None:
                first_timestamp = t
            t_rel = t - first_timestamp
            times.append(t_rel)

            for ch, v, g in zip(channels, vals, gains):
                ch.append(v * g)

            # sliding window
            window_sec_val = float(window_var.get())
            while times and (times[-1] - times[0] > window_sec_val):
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
            plot.setYRange(float(ylim_min_var.get()), float(ylim_max_var.get()))
            plot.setXRange(max(0, t_list[-1] - float(window_var.get())), t_list[-1])

    timer = QtCore.QTimer()
    timer.timeout.connect(update)
    timer.start(10)

    def on_close():
        stop_event.set()
        reader_thread.join()
        sender_thread.join()
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
# Tkinter GUI
# ============================================================

def start_plot():
    start_btn.config(state="disabled")
    threading.Thread(target=live_plot_thread, args=(start_btn,), daemon=True).start()

def update_channel_fields(*_):
    n = int(ch_count_var.get())
    for i in range(10):
        widgets = ch_widgets[i]
        if i < n:
            for w in widgets:
                w.grid()
        else:
            for w in widgets:
                w.grid_remove()

def update_output_fields(*_):
    n = int(out_count_var.get())
    for i in range(10):
        widgets = out_widgets[i]
        if i < n:
            for w in widgets:
                w.grid()
        else:
            for w in widgets:
                w.grid_remove()

root = tk.Tk()
root.title("MRBDebugProbe")
frm = ttk.Frame(root, padding=10)
frm.grid()

# Port selection
port_var = tk.StringVar()
ttk.Label(frm, text="Port").grid(column=0, row=0)
port_menu = ttk.Combobox(frm, textvariable=port_var, width=10, state="readonly")
port_menu.grid(column=1, row=0)
ttk.Button(frm, text="Scan", command=refresh_ports).grid(column=2, row=0)

# Baud
baud_var = tk.StringVar(value="115200")
baudrates = ["9600","19200","38400","57600","115200","230400","460800","921600"]
ttk.Label(frm, text="Baud").grid(column=0, row=1)
baud_menu = ttk.Combobox(frm, textvariable=baud_var, values=baudrates, width=10, state="readonly")
baud_menu.grid(column=1, row=1)

# Window size
window_var = tk.StringVar(value="10")
ttk.Label(frm, text="Window [s]").grid(column=0, row=2)
ttk.Entry(frm, textvariable=window_var, width=10).grid(column=1, row=2)

# Y limits
ylim_min_var = tk.StringVar(value="-200")
ylim_max_var = tk.StringVar(value="200")
ttk.Label(frm, text="Y min").grid(column=0, row=4)
ttk.Entry(frm, textvariable=ylim_min_var, width=10).grid(column=1, row=4)
ttk.Label(frm, text="Y max").grid(column=0, row=5)
ttk.Entry(frm, textvariable=ylim_max_var, width=10).grid(column=1, row=5)

# CSV
csv_var = tk.StringVar(value="No")
ttk.Label(frm, text="Save CSV").grid(column=0, row=19)
csv_menu = ttk.Combobox(frm, textvariable=csv_var, values=["Yes","No"], width=10, state="readonly")
csv_menu.grid(column=1, row=19)

# Channels
ch_count_var = tk.StringVar(value="3")
ttk.Label(frm, text="Channels").grid(column=0, row=6)
ch_count_spin = ttk.Spinbox(frm, from_=1, to=10, textvariable=ch_count_var, width=5, command=update_channel_fields)
ch_count_spin.grid(column=1, row=6)

ch_name_vars, ch_gain_vars, ch_widgets = [], [], []
for i in range(10):
    nv = tk.StringVar(value=f"ch{i+1}")
    gv = tk.StringVar(value="1.0")
    ch_name_vars.append(nv)
    ch_gain_vars.append(gv)
    lbl_name = ttk.Label(frm, text=f"Name {i+1}")
    ent_name = ttk.Entry(frm, textvariable=nv, width=8)
    lbl_gain = ttk.Label(frm, text="Gain")
    ent_gain = ttk.Entry(frm, textvariable=gv, width=6)
    lbl_name.grid(column=2, row=7+i)
    ent_name.grid(column=3, row=7+i)
    lbl_gain.grid(column=4, row=7+i)
    ent_gain.grid(column=5, row=7+i)
    ch_widgets.append([lbl_name, ent_name, lbl_gain, ent_gain])

update_channel_fields()

# Outputs
out_count_var = tk.StringVar(value="2")
ttk.Label(frm, text="Outputs").grid(column=0, row=17)
out_count_spin = ttk.Spinbox(frm, from_=1, to=10, textvariable=out_count_var, width=5, command=update_output_fields)
out_count_spin.grid(column=1, row=17)

out_val_vars, out_widgets = [], []
for i in range(10):
    v = tk.StringVar(value="0")
    out_val_vars.append(v)
    lbl = ttk.Label(frm, text=f"Out{i+1}")
    ent = ttk.Entry(frm, textvariable=v, width=6)
    lbl.grid(column=2, row=17+i)
    ent.grid(column=3, row=17+i)
    out_widgets.append([lbl, ent])

update_output_fields()

# Start plot button
start_btn = ttk.Button(frm, text="Start Plot", command=start_plot)
start_btn.grid(column=0, row=30, pady=10)

refresh_ports()
root.mainloop()
