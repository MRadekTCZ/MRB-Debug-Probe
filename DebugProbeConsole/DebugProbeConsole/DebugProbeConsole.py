import serial
import serial.tools.list_ports
import tkinter as tk
from tkinter import ttk
from collections import deque
import threading
import time
import os
import csv

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
# PyQtGraph REAL-TIME PLOT (threaded)
# ============================================================

def live_plot_thread():
    import pyqtgraph as pg
    from PyQt5 import QtWidgets, QtCore

    colors = [
        (255,   0,   0),   # red
        (0,   150,   0),   # green
        (0,   0, 255),     # blue
        (255, 165, 0),     # orange
        (128, 0, 128),     # purple
        (0, 200, 200),     # cyan
        (200, 0, 200),     # magenta
        (128, 64, 0),      # brown
        (80, 80, 80),      # gray
        (255, 255, 0),     # yellow
    ]

    # ----- serial port -----
    try:
        ser = serial.Serial(port_var.get(), int(baud_var.get()), timeout=1)
    except serial.SerialException as e:
        print("Failed to open port:", e)
        return

    n_channels = int(ch_count_var.get())
    gains = [float(ch_gain_vars[i].get()) for i in range(n_channels)]
    ch_names = [ch_name_vars[i].get() or f"ch{i+1}" for i in range(n_channels)]

    # Buffers
    times = deque()
    channels = [deque() for _ in range(n_channels)]
    t0 = None

    # CSV setup
    csv_enabled = csv_var.get() == "Yes"
    if csv_enabled:
        # Find next available filename
        i = 1
        while os.path.exists(f"data{i}.csv"):
            i += 1
        csv_file = open(f"data{i}.csv", "w", newline='')
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["timestamp"] + ch_names)

    # PyQtGraph app
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
        curves.append(plot.plot([], [], pen=pen, name=ch_names[i]))

    # ----- Update function -----
    def update():
        nonlocal t0, gains, ch_names

        # Read line from serial
        line = ser.readline().decode(errors="ignore").strip()
        if not line:
            return
        parts = line.split(",")
        if len(parts) < 2:
            return
        try:
            t_raw = int(parts[0])
            vals = [float(v) for v in parts[1:n_channels+1]]
        except ValueError:
            return

        # Update timer frequency from GUI dynamically
        timer_freq_val = float(timer_freq_var.get())
        if t0 is None:
            t0 = t_raw
        t = (t_raw - t0) / timer_freq_val
        times.append(t)

        # Update gains dynamically
        gains = [float(ch_gain_vars[i].get()) for i in range(n_channels)]
        ch_names = [ch_name_vars[i].get() or f"ch{i+1}" for i in range(n_channels)]

        for ch, v, g in zip(channels, vals, gains):
            ch.append(v * g)

        # Keep sliding window
        window_sec_val = float(window_var.get())
        while times and (times[-1] - times[0] > window_sec_val):
            times.popleft()
            for ch in channels:
                if ch:
                    ch.popleft()

        # Update plots
        t_list = list(times)
        for c, ch in zip(curves, channels):
            c.setData(t_list, list(ch))

        if t_list:
            ylim_min_val = float(ylim_min_var.get())
            ylim_max_val = float(ylim_max_var.get())
            plot.setYRange(ylim_min_val, ylim_max_val)
            plot.setXRange(max(0, t_list[-1] - window_sec_val), t_list[-1])

        # Write CSV if enabled
        if csv_enabled:
            csv_writer.writerow([t] + vals)

    # QTimer for periodic updates
    timer = QtCore.QTimer()
    timer.timeout.connect(update)
    timer.start(10)  # update every 10 ms

    app.exec_()
    ser.close()
    if csv_enabled:
        csv_file.close()

# ============================================================
# Tkinter GUI logic
# ============================================================

def start_plot():
    threading.Thread(target=live_plot_thread, daemon=True).start()

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

# ============================================================
# Tkinter GUI
# ============================================================

root = tk.Tk()
root.title("MRBDebugProbe")

frm = ttk.Frame(root, padding=10)
frm.grid()

# Port
port_var = tk.StringVar()
ttk.Label(frm, text="Port").grid(column=0, row=0)
port_menu = ttk.Combobox(frm, textvariable=port_var, width=10, state="readonly")
port_menu.grid(column=1, row=0)
ttk.Button(frm, text="Scan", command=refresh_ports).grid(column=2, row=0)

# Baud
baud_var = tk.StringVar(value="115200")
baudrates = ["9600", "19200", "38400", "57600", "115200",
             "230400", "460800", "921600"]
ttk.Label(frm, text="Baud").grid(column=0, row=1)
baud_menu = ttk.Combobox(frm, textvariable=baud_var, values=baudrates,
                         width=10, state="readonly")
baud_menu.grid(column=1, row=1)

# Window size
window_var = tk.StringVar(value="10")
ttk.Label(frm, text="Window [s]").grid(column=0, row=2)
ttk.Entry(frm, textvariable=window_var, width=10).grid(column=1, row=2)

# Y limits
ylim_min_var = tk.StringVar(value="-5")
ylim_max_var = tk.StringVar(value="5")
ttk.Label(frm, text="Y min").grid(column=0, row=4)
ttk.Entry(frm, textvariable=ylim_min_var, width=10).grid(column=1, row=4)
ttk.Label(frm, text="Y max").grid(column=0, row=5)
ttk.Entry(frm, textvariable=ylim_max_var, width=10).grid(column=1, row=5)

# Timer frequency
#Frequency of task inside Plecs code (can be 100Hz, 1kHz, 10kHz etc), 
#Recommended frequency for CSV trigger is 10Hz
timer_freq_var = tk.StringVar(value="1000.0")
ttk.Label(frm, text="Timer freq").grid(column=0, row=3)
ttk.Entry(frm, textvariable=timer_freq_var, width=10).grid(column=1, row=3)

# CSV option
csv_var = tk.StringVar(value="No")
ttk.Label(frm, text="Save CSV").grid(column=0, row=19)
csv_menu = ttk.Combobox(frm, textvariable=csv_var, values=["Yes", "No"], width=10, state="readonly")
csv_menu.grid(column=1, row=19)

# Channels
ch_count_var = tk.StringVar(value="3")
ttk.Label(frm, text="Channels").grid(column=0, row=6)
ch_count_spin = ttk.Spinbox(frm, from_=1, to=10, textvariable=ch_count_var,
                            width=5, command=update_channel_fields)
ch_count_spin.grid(column=1, row=6)

ch_name_vars, ch_gain_vars = [], []
ch_widgets = []
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

# Start button
ttk.Button(frm, text="Start Plot", command=start_plot).grid(column=0, row=20, pady=10)

refresh_ports()
root.mainloop()
