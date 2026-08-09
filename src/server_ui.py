"""Graphical host/operations console for the authoritative MTGNP server."""

import argparse
import logging
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from console_logger import setup_logging
from server import HOST, PORT, MTGNPServer
from ui_theme import *


class QueueLogHandler(logging.Handler):
    def __init__(self, output):
        super().__init__()
        self.output = output

    def emit(self, record):
        self.output.put((record.levelname, self.format(record)))


class ServerConsoleUI:
    def __init__(self, root):
        self.root = root
        self.root.title("MTGNP — Host Command")
        self.root.geometry("1220x780")
        self.root.minsize(980, 650)
        self.root.configure(bg=BG)
        self.server = None
        self.running = False
        self.logs = queue.Queue()
        self._style()
        self._build()
        self._attach_logging()
        self.root.after(250, self._refresh)

    def _style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Host.TButton", background=GOLD, foreground="#171107",
                        borderwidth=0, padding=(18, 11), font=TYPE_BUTTON)
        style.map("Host.TButton", background=[("active", GOLD_BRIGHT), ("disabled", SURFACE_3)])
        style.configure("Stop.TButton", background="#71343d", foreground=TEXT,
                        borderwidth=0, padding=(18, 11), font=TYPE_BUTTON)
        style.configure("Host.TEntry", fieldbackground=SURFACE_2, foreground=TEXT,
                        insertcolor=TEXT, bordercolor=LINE, padding=8,
                        font=TYPE_BODY)

    def _build(self):
        header = tk.Frame(self.root, bg="#0b111c", height=74)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="MTGNP", bg="#0b111c", fg=GOLD,
                 font=(FONT_DISPLAY, 23, "bold")).pack(side="left", padx=(24, 9))
        tk.Label(header, text="HOST COMMAND", bg="#0b111c", fg=MUTED,
                 font=(FONT_UI, 10, "bold")).pack(side="left", pady=(8, 0))
        self.status = tk.Label(header, text="●  OFFLINE", bg="#0b111c", fg=MUTED,
                               font=(FONT_UI, 10, "bold"))
        self.status.pack(side="right", padx=25)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        left = tk.Frame(body, bg=BG, width=330)
        left.pack(side="left", fill="y", padx=(0, 14))
        left.pack_propagate(False)
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        self._listener_panel(left).pack(fill="x")
        self._players_panel(left).pack(fill="both", expand=True, pady=(14, 0))
        self._telemetry_panel(right).pack(fill="x")
        self._log_panel(right).pack(fill="both", expand=True, pady=(14, 0))

    def _panel(self, parent, title):
        outer = tk.Frame(parent, bg=SURFACE, highlightbackground=LINE, highlightthickness=1,
                         padx=16, pady=14)
        tk.Label(outer, text=title, bg=SURFACE, fg=TEXT,
                 font=TYPE_SECTION).pack(anchor="w", pady=(0, 14))
        return outer

    def _listener_panel(self, parent):
        panel = self._panel(parent, "LISTENER")
        self.host_var, self.port_var = tk.StringVar(value=HOST), tk.StringVar(value=str(PORT))
        for label, var in (("BIND ADDRESS", self.host_var), ("PORT", self.port_var)):
            tk.Label(panel, text=label, bg=SURFACE, fg=MUTED,
                     font=TYPE_LABEL).pack(anchor="w", pady=(4, 5))
            ttk.Entry(panel, textvariable=var, style="Host.TEntry").pack(fill="x")
        self.start_btn = ttk.Button(panel, text="START SERVER", style="Host.TButton", command=self._start)
        self.start_btn.pack(fill="x", pady=(16, 6))
        self.reset_btn = ttk.Button(panel, text="RESET LOBBY", style="Stop.TButton", command=self._reset)
        self.reset_btn.pack(fill="x")
        self.reset_btn.state(["disabled"])
        return panel

    def _players_panel(self, parent):
        panel = self._panel(parent, "CONNECTED PLAYERS")
        self.player_slots = []
        for index in range(2):
            slot = tk.Frame(panel, bg=SURFACE_2, padx=12, pady=11)
            slot.pack(fill="x", pady=5)
            name = tk.Label(slot, text=f"SLOT {index + 1} — EMPTY", bg=SURFACE_2, fg=MUTED,
                            font=(FONT_UI, 10, "bold"))
            name.pack(anchor="w")
            meta = tk.Label(slot, text="Awaiting player", bg=SURFACE_2, fg="#66768a",
                            font=(FONT_BODY, 8))
            meta.pack(anchor="w", pady=(3, 0))
            self.player_slots.append((slot, name, meta))
        return panel

    def _telemetry_panel(self, parent):
        panel = self._panel(parent, "MATCH TELEMETRY")
        row = tk.Frame(panel, bg=SURFACE)
        row.pack(fill="x")
        self.metrics = {}
        for label in ("SERVER PHASE", "GAME STEP", "TURN", "SEQUENCE"):
            cell = tk.Frame(row, bg=SURFACE_2, padx=14, pady=11)
            cell.pack(side="left", fill="x", expand=True, padx=(0, 7))
            tk.Label(cell, text=label, bg=SURFACE_2, fg=MUTED,
                     font=(FONT_UI, 7, "bold")).pack(anchor="w")
            value = tk.Label(cell, text="—", bg=SURFACE_2, fg=TEXT,
                             font=(FONT_DISPLAY, 12, "bold"))
            value.pack(anchor="w", pady=(4, 0))
            self.metrics[label] = value
        return panel

    def _log_panel(self, parent):
        panel = self._panel(parent, "LIVE EVENT STREAM")
        tools = tk.Frame(panel, bg=SURFACE)
        tools.pack(fill="x", pady=(0, 8))
        tk.Label(tools, text="Authoritative protocol and engine events", bg=SURFACE, fg=MUTED,
                 font=TYPE_BODY_SMALL).pack(side="left")
        tk.Button(tools, text="CLEAR", bg=SURFACE_3, fg=TEXT, relief="flat", cursor="hand2",
                  command=lambda: self.log_text.delete("1.0", "end")).pack(side="right")
        self.log_text = tk.Text(panel, bg="#090f18", fg="#b9c7d8", insertbackground=TEXT,
                                relief="flat", font=(FONT_MONO, 9), padx=14, pady=12,
                                state="disabled", wrap="word")
        scroll = ttk.Scrollbar(panel, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_configure("ERROR", foreground=RED)
        self.log_text.tag_configure("WARNING", foreground=GOLD_BRIGHT)
        self.log_text.tag_configure("INFO", foreground=GREEN)
        return panel

    def _attach_logging(self):
        handler = QueueLogHandler(self.logs)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(handler)

    def _start(self):
        try:
            port = int(self.port_var.get())
        except ValueError:
            messagebox.showerror("Invalid port", "The listener port must be numeric."); return
        self.server = MTGNPServer()
        self.server.host, self.server.port = self.host_var.get().strip(), port
        self.running = True
        self.start_btn.state(["disabled"])
        self.reset_btn.state(["!disabled"])
        self.status.configure(text="●  ONLINE", fg=GREEN)
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        try:
            self.server.start()
        except Exception as exc:
            self.logs.put(("ERROR", f"Server stopped: {exc}"))
            self.root.after(0, self._mark_offline)

    def _mark_offline(self):
        self.running = False
        self.start_btn.state(["!disabled"])
        self.reset_btn.state(["disabled"])
        self.status.configure(text="●  OFFLINE", fg=MUTED)

    def _reset(self):
        if self.server and messagebox.askyesno("Reset lobby", "End the current session and clear both player slots?"):
            self.server.reset_lobby_state()
            self.logs.put(("WARNING", "Lobby reset by host operator."))

    def _refresh(self):
        while True:
            try:
                level, line = self.logs.get_nowait()
                self.log_text.configure(state="normal")
                stamp = datetime.now().strftime("%H:%M:%S")
                self.log_text.insert("end", f"{stamp}  {line}\n", level)
                self.log_text.configure(state="disabled")
                self.log_text.see("end")
            except queue.Empty:
                break
        if self.server:
            players = list(self.server.players.items())
            for index, (slot, name, meta) in enumerate(self.player_slots):
                if index < len(players):
                    pid, info = players[index]
                    connected = info.get("status") == "CONNECTED"
                    name.configure(text=pid, fg=TEXT)
                    meta.configure(text=f"{'● CONNECTED' if connected else '● DISCONNECTED'}  •  {len(info.get('deck', []))} cards",
                                   fg=GREEN if connected else RED)
                    slot.configure(highlightbackground=GREEN if connected else RED, highlightthickness=1)
                else:
                    name.configure(text=f"SLOT {index + 1} — EMPTY", fg=MUTED)
                    meta.configure(text="Awaiting player", fg="#66768a")
                    slot.configure(highlightthickness=0)
            state = self.server.engine.state
            values = (self.server.phase, state.get("phase", "—"), state.get("turn", "—"), self.server.seq_num)
            for key, value in zip(self.metrics, values): self.metrics[key].configure(text=str(value))
        self.root.after(250, self._refresh)


def main():
    parser = argparse.ArgumentParser(description="MTGNP graphical host console")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    setup_logging(verbose=True if args.verbose else False)
    root = tk.Tk()
    ServerConsoleUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
