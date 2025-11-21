import serial
import serial.tools.list_ports
import tkinter as tk
from tkinter import ttk
import time
from collections import deque


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
# PyQtGraph REAL-TIME PLOT (replaces matplotlib)
# ============================================================

def live_plot_after_tkinter(port, baud, window_sec, ch_names,
                            gains, ylim_min, ylim_max, n_channels):

    import pyqtgraph as pg
    from PyQt5 import QtWidgets, QtCore
    colors = [
    (255,   0,   0),   # red
    (  0, 150,   0),   # green
    (  0,   0, 255),   # blue
    (255, 165,   0),   # orange
    (128,   0, 128),   # purple
    (  0, 200, 200),   # cyan
    (200,   0, 200),   # magenta
    (128,  64,   0),   # brown
    ( 80,  80,  80),   # gray
    (255, 255,   0),   # yellow
]

    # ----- serial port -----
    try:
        ser = serial.Serial(port, baud, timeout=1)
    except serial.SerialException as e:
        print("Failed to open port:", e)
        return

    timer_freq = 100.0*2

    # Buffers
    times = deque()
    channels = [deque() for _ in range(n_channels)]
    t0 = None

    # ----- PyQtGraph window -----
    app = QtWidgets.QApplication([])

    win = pg.GraphicsLayoutWidget(show=True, title="Live UART Plot")
    win.resize(1000, 600)

    plot = win.addPlot()
    plot.setLabel('bottom', 'Time [s]')
    plot.setLabel('left', 'Value')
    plot.setYRange(ylim_min, ylim_max)
    plot.addLegend()

    curves = []
    for i in range(n_channels):
        color = colors[i % len(colors)]
        pen = pg.mkPen(color=color, width=2)
        curves.append(plot.plot([], [], pen=pen, name=ch_names[i]))


    # ----- Update loop -----
    def update():
        nonlocal t0

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

        if t0 is None:
            t0 = t_raw

        t = (t_raw - t0) / timer_freq
        times.append(t)

        for ch, v, g in zip(channels, vals, gains):
            ch.append(v * g)

        # keep sliding window
        while times and (times[-1] - times[0] > window_sec):
            times.popleft()
            for ch in channels:
                if ch:
                    ch.popleft()

        # update plots
        t_list = list(times)
        for c, ch in zip(curves, channels):
            c.setData(t_list, list(ch))

        if t_list:
            plot.setXRange(max(0, t_list[-1] - window_sec), t_list[-1])

    timer = QtCore.QTimer()
    timer.timeout.connect(update)
    timer.start(5)

    app.exec_()
    ser.close()


# ============================================================
# GUI logic (unchanged)
# ============================================================

def start_plot():
    port = port_var.get()
    baud = int(baud_var.get())
    window_sec = float(window_var.get())
    n_channels = int(ch_count_var.get())

    ch_names = [ch_name_vars[i].get() or f"ch{i+1}" for i in range(n_channels)]
    gains = [float(ch_gain_vars[i].get()) for i in range(n_channels)]

    ylim_min = float(ylim_min_var.get())
    ylim_max = float(ylim_max_var.get())

    root.destroy()

    live_plot_after_tkinter(port, baud, window_sec,
                            ch_names, gains,
                            ylim_min, ylim_max, n_channels)


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
# Tkinter GUI  (unchanged from your code)
# ============================================================

root = tk.Tk()
root.title("MRBDebugProbe")

frm = ttk.Frame(root, padding=10)
frm.grid()

# Port
port_var = tk.StringVar()
lbl_port = ttk.Label(frm, text="Port")
lbl_port.grid(column=0, row=0)
port_menu = ttk.Combobox(frm, textvariable=port_var, width=10, state="readonly")
port_menu.grid(column=1, row=0)
btn_scan = ttk.Button(frm, text="Scan", command=refresh_ports)
btn_scan.grid(column=2, row=0)

# Baud
baud_var = tk.StringVar(value="115200")
baudrates = ["9600", "19200", "38400", "57600", "115200",
             "230400", "460800", "921600"]
lbl_baud = ttk.Label(frm, text="Baud")
lbl_baud.grid(column=0, row=1)
baud_menu = ttk.Combobox(frm, textvariable=baud_var,
                         values=baudrates, width=10, state="readonly")
baud_menu.grid(column=1, row=1)

# Window size
window_var = tk.StringVar(value="10")
refresh_var = tk.StringVar(value="1.0")
lbl_window = ttk.Label(frm, text="Window [s]")
lbl_window.grid(column=0, row=2)
ent_window = ttk.Entry(frm, textvariable=window_var, width=10)
ent_window.grid(column=1, row=2)
lbl_refresh = ttk.Label(frm, text="Refresh [s]")
lbl_refresh.grid(column=0, row=3)
ent_refresh = ttk.Entry(frm, textvariable=refresh_var, width=10)
ent_refresh.grid(column=1, row=3)

# Y limits
ylim_min_var = tk.StringVar(value="-100")
ylim_max_var = tk.StringVar(value="500")
lbl_ymin = ttk.Label(frm, text="Y min")
lbl_ymin.grid(column=0, row=4)
ent_ymin = ttk.Entry(frm, textvariable=ylim_min_var, width=10)
ent_ymin.grid(column=1, row=4)
lbl_ymax = ttk.Label(frm, text="Y max")
lbl_ymax.grid(column=0, row=5)
ent_ymax = ttk.Entry(frm, textvariable=ylim_max_var, width=10)
ent_ymax.grid(column=1, row=5)

# Channels
ch_count_var = tk.StringVar(value="3")
lbl_channels = ttk.Label(frm, text="Channels")
lbl_channels.grid(column=0, row=6)
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
ttk.Button(frm, text="Start", command=start_plot).grid(column=0, row=18, pady=10)

refresh_ports()

root.mainloop()
