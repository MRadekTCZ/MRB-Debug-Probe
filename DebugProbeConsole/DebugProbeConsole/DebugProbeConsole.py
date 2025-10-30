import serial
import serial.tools.list_ports
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from collections import deque
import tkinter as tk
from tkinter import ttk
import threading
import traceback

# ---------- plotting thread ----------
def run_plot(port, baud, window_sec, refresh, ch_names, gains, control_flags,
             ch_gain_vars, ch_name_vars, ylim_min_var, ylim_max_var,
             ch_count_var, window_var, refresh_var, plot_frame,
             widgets_to_disable, widgets_to_hide, root):
    try:
        ser = serial.Serial(port, baud, timeout=1)
    except serial.SerialException as e:
        print("Error opening serial port:", e)
        control_flags["running"] = False
        return

    timer_freq = 10000.0

    def get_channel_count():
        try:
            return max(1, min(10, int(ch_count_var.get())))
        except ValueError:
            return 1

    n_channels = get_channel_count()
    times = deque()
    channels = [deque() for _ in range(n_channels)]
    t0 = None

    # create embedded figure inside Tkinter frame
    fig, ax = plt.subplots(figsize=(6, 4))
    lines = [ax.plot([], [], label=ch_names[i])[0] for i in range(n_channels)]
    ax.set_xlabel("Time [s]")
    ax.set_ylabel("Value")
    ax.set_xlim(0, window_sec)
    ax.set_ylim(-100, 500)
    ax.grid(True)
    legend = ax.legend()

    # embed matplotlib figure in Tkinter
    canvas = FigureCanvasTkAgg(fig, master=plot_frame)
    root.after_idle(lambda: canvas.get_tk_widget().grid(row=0, column=0, columnspan=6, pady=5))
    root.after_idle(canvas.draw)

    # ---- update helpers ----
    def update_y_limits():
        try:
            ymin = float(ylim_min_var.get())
            ymax = float(ylim_max_var.get())
            if ymin < ymax:
                ax.set_ylim(ymin, ymax)
        except ValueError:
            pass

    def update_channel_names():
        for i, var in enumerate(ch_name_vars[:n_channels]):
            lines[i].set_label(var.get() or "ch{}".format(i + 1))
        try:
            legend.remove()
        except Exception:
            pass
        ax.legend()

    def update_gains_local():
        try:
            for i in range(n_channels):
                gains[i] = float(ch_gain_vars[i].get())
        except ValueError:
            pass

    def update_window_refresh():
        try:
            return float(window_var.get()), float(refresh_var.get())
        except ValueError:
            return window_sec, refresh

    # hide port, baud, and channel controls (done safely in main thread)
    root.after(0, lambda: [w.grid_remove() for w in widgets_to_hide])
    root.after(0, lambda: [w.configure(state="disabled") for w in widgets_to_disable])

    try:
        while control_flags["running"]:
            if control_flags["reset"]:
                times.clear()
                for ch in channels:
                    ch.clear()
                t0 = None
                control_flags["reset"] = False

            if control_flags.get("update_all"):
                update_gains_local()
                update_y_limits()
                update_channel_names()
                window_sec, refresh = update_window_refresh()
                control_flags["update_all"] = False

            try:
                line = ser.readline().decode(errors="ignore").strip()
                if not line:
                    continue
                parts = line.split(",")
                if len(parts) < 2:
                    continue
                t_raw = int(parts[0])
                vals = [float(v) for v in parts[1:]]
            except Exception:
                continue

            if t0 is None:
                t0 = t_raw
            t = (t_raw - t0) / timer_freq
            used_channels = min(len(vals), n_channels)
            vals = vals[:used_channels]

            if not control_flags["paused"]:
                times.append(t)
                for ch, v, g in zip(channels[:used_channels], vals, gains[:used_channels]):
                    ch.append(v * g)
                while times and (times[-1] - times[0] > window_sec):
                    times.popleft()
                    for ch in channels:
                        if ch:
                            ch.popleft()
                for ln, ch in zip(lines[:used_channels], channels[:used_channels]):
                    ln.set_data(times, ch)
                ax.set_xlim(max(0, times[-1] - window_sec), times[-1])
                ax.relim()
                ax.autoscale_view(True, True, False)
                root.after_idle(canvas.draw_idle)
            else:
                root.after_idle(canvas.draw_idle)
    except Exception as e:
        print("Fatal error in plotting thread:", e)
        traceback.print_exc()
    finally:
        try:
            ser.close()
        except Exception:
            pass

        def restore_gui():
            for w in widgets_to_hide:
                w.grid()
            for w in widgets_to_disable:
                w.configure(state="normal")
        root.after(0, restore_gui)


# ---------- helper functions ----------
def list_serial_ports():
    return [p.device for p in serial.tools.list_ports.comports()]


# ---------- GUI logic ----------
def refresh_ports():
    ports = list_serial_ports()
    port_menu["values"] = ports
    if ports:
        port_var.set(ports[0])


def start_plot():
    if control_flags["running"]:
        return
    port = port_var.get()
    baud = int(baud_var.get())
    window_sec = float(window_var.get())
    refresh = float(refresh_var.get())
    n_channels = int(ch_count_var.get())
    ch_names = [ch_name_vars[i].get() or "ch{}".format(i + 1) for i in range(n_channels)]
    gains = [float(ch_gain_vars[i].get()) for i in range(n_channels)]
    control_flags.update({
        "running": True,
        "paused": False,
        "reset": False,
        "update_all": False
    })

    threading.Thread(
        target=run_plot,
        args=(port, baud, window_sec, refresh, ch_names, gains, control_flags,
              ch_gain_vars, ch_name_vars, ylim_min_var, ylim_max_var,
              ch_count_var, window_var, refresh_var, plot_frame,
              widgets_to_disable, widgets_to_hide, root),
        daemon=True,
    ).start()


def pause_resume():
    if not control_flags["running"]:
        return
    if control_flags["paused"]:
        control_flags["update_all"] = True
        for w in widgets_to_disable:
            w.configure(state="disabled")
    else:
        for w in widgets_to_disable:
            w.configure(state="normal")
    control_flags["paused"] = not control_flags["paused"]
    btn_pause.config(text="Resume" if control_flags["paused"] else "Pause")


def reset_plot():
    if control_flags["running"]:
        control_flags["reset"] = True


def stop_plot():
    control_flags["running"] = False


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


# ---------- GUI ----------
root = tk.Tk()
root.title("MRBDebugProbe")

# Frame for embedded plot
plot_frame = ttk.Frame(root, padding=5, borderwidth=2, relief="groove")
plot_frame.grid(column=0, row=0, columnspan=6, pady=5)

frm = ttk.Frame(root, padding=10)
frm.grid()

# --- COM port selection ---
port_var = tk.StringVar()
lbl_port = ttk.Label(frm, text="Port")
lbl_port.grid(column=0, row=0)
port_menu = ttk.Combobox(frm, textvariable=port_var, width=10, state="readonly")
port_menu.grid(column=1, row=0)
btn_scan = ttk.Button(frm, text="Scan", command=refresh_ports)
btn_scan.grid(column=2, row=0)

# --- Baud rate selection ---
baud_var = tk.StringVar(value="115200")
baudrates = ["9600", "19200", "38400", "57600",
             "115200", "230400", "460800", "921600"]
lbl_baud = ttk.Label(frm, text="Baud")
lbl_baud.grid(column=0, row=1)
baud_menu = ttk.Combobox(frm, textvariable=baud_var, values=baudrates,
                         width=10, state="readonly")
baud_menu.grid(column=1, row=1)

# --- Other parameters ---
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

# --- Y limits manual controls ---
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

# --- Channel settings ---
ch_count_var = tk.StringVar(value="3")
lbl_channels = ttk.Label(frm, text="Channels")
lbl_channels.grid(column=0, row=6)
ch_count_spin = ttk.Spinbox(frm, from_=1, to=10, textvariable=ch_count_var,
                            width=5, command=update_channel_fields)
ch_count_spin.grid(column=1, row=6)

ch_name_vars, ch_gain_vars = [], []
ch_widgets = []
for i in range(10):
    nv = tk.StringVar(value="ch{}".format(i + 1))
    gv = tk.StringVar(value="1.0")
    ch_name_vars.append(nv)
    ch_gain_vars.append(gv)
    lbl_name = ttk.Label(frm, text="Name {}".format(i + 1))
    ent_name = ttk.Entry(frm, textvariable=nv, width=8)
    lbl_gain = ttk.Label(frm, text="Gain")
    ent_gain = ttk.Entry(frm, textvariable=gv, width=6)
    lbl_name.grid(column=2, row=7 + i)
    ent_name.grid(column=3, row=7 + i)
    lbl_gain.grid(column=4, row=7 + i)
    ent_gain.grid(column=5, row=7 + i)
    ch_widgets.append([lbl_name, ent_name, lbl_gain, ent_gain])

update_channel_fields()

# --- Control buttons ---
control_flags = {
    "running": False,
    "paused": False,
    "reset": False,
    "update_all": False
}
ttk.Button(frm, text="Start", command=start_plot).grid(column=0, row=18, pady=10)
btn_pause = ttk.Button(frm, text="Pause", command=pause_resume)
btn_pause.grid(column=1, row=18, pady=10)
ttk.Button(frm, text="Reset", command=reset_plot).grid(column=2, row=18, pady=10)
ttk.Button(frm, text="Stop", command=stop_plot).grid(column=3, row=18, pady=10)

# group of widgets to disable and hide dynamically
widgets_to_disable = [
    ent_window, ent_refresh, ent_ymin, ent_ymax,
    *[w for widgets in ch_widgets for w in widgets]
]
widgets_to_hide = [lbl_port, port_menu, btn_scan, lbl_baud, baud_menu,
                   lbl_channels, ch_count_spin]

refresh_ports()
root.mainloop()
