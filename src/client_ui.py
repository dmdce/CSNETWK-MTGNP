"""Graphical MTGNP player client.

The networking/rules client remains in :mod:`client`; this module is a
presentation and interaction layer only.
"""

import argparse
import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from client import HOST, PORT, MTGNPClient
from console_logger import setup_logging
from ui_theme import *

try:
    from PIL import Image, ImageTk
except ImportError:  # The UI remains usable without the optional artwork.
    Image = ImageTk = None


def card_id(card):
    return card.get("id", "unknown") if isinstance(card, dict) else str(card)


class CardTile(tk.Frame):
    def __init__(self, parent, card, info, command, selected=False, compact=False):
        color = str((info or {}).get("color", "C")).upper()[:1] or "C"
        fill, ink = CARD_COLORS.get(color, CARD_COLORS["C"])
        super().__init__(parent, bg=GOLD_BRIGHT if selected else LINE, padx=2, pady=2,
                         cursor="hand2")
        body = tk.Frame(self, bg=fill, width=116 if compact else 138,
                        height=76 if compact else 112)
        body.pack(fill="both", expand=True)
        body.pack_propagate(False)
        cid = card_id(card)
        name = (info or {}).get("card_name") or cid.rsplit("_", 1)[0].replace("_", " ").title()
        tk.Label(body, text=name, bg=fill, fg=ink, font=(FONT_UI, 9, "bold"),
                 wraplength=108 if compact else 130, justify="left").pack(fill="x", padx=7, pady=(6, 2))
        ctype = (info or {}).get("card_type", "Card")
        tk.Label(body, text=ctype.upper(), bg=fill, fg=ink, font=(FONT_BODY, 7)).pack(anchor="w", padx=7)
        if isinstance(card, dict):
            flags = []
            if card.get("tapped"): flags.append("TAPPED")
            if card.get("attacking"): flags.append("ATTACKING")
            if card.get("blocking"): flags.append("BLOCKING")
            if flags:
                tk.Label(body, text=" • ".join(flags), bg="#0b1220", fg=GOLD_BRIGHT,
                         font=(FONT_UI, 7, "bold")).pack(side="bottom", fill="x")
        pt = (info or {}).get("power"), (info or {}).get("toughness")
        if pt[0] is not None and pt[1] is not None:
            tk.Label(body, text=f"{pt[0]}/{pt[1]}", bg=ink, fg=fill,
                     font=(FONT_UI, 9, "bold"), padx=5).place(relx=1, rely=1, anchor="se")
        for widget in (self, body, *body.winfo_children()):
            widget.bind("<Button-1>", lambda _e, c=cid: command(c))


class GameClientUI:
    def __init__(self, root):
        self.root = root
        self.root.title("MTGNP — Arcane Table")
        self.root.geometry("1440x900")
        self.root.minsize(1080, 700)
        self.root.configure(bg=BG)
        self.client = None
        self.state = {}
        self.events = queue.Queue()
        self.selected_hand = set()
        self.selected_field = set()
        self.mulligan_pending = None
        self.mulligan_kept = False
        self.bg_photo = None
        self._configure_styles()
        self._build_connect_screen()
        self.root.after(50, self._drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _configure_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Game.TButton", background=SURFACE_3, foreground=TEXT,
                        borderwidth=0, padding=(15, 11), font=TYPE_BUTTON)
        style.map("Game.TButton", background=[("active", "#2d4055"), ("disabled", SURFACE)])
        style.configure("Gold.TButton", background=GOLD, foreground="#161109",
                        borderwidth=0, padding=(18, 12), font=TYPE_BUTTON)
        style.map("Gold.TButton", background=[("active", GOLD_BRIGHT)])
        style.configure("Danger.TButton", background="#6f3038", foreground=TEXT,
                        borderwidth=0, padding=(12, 10), font=TYPE_BUTTON)
        style.configure("Dark.TEntry", fieldbackground=SURFACE_2, foreground=TEXT,
                        insertcolor=TEXT, bordercolor=LINE, padding=9,
                        font=TYPE_BODY)

    def _clear(self):
        for child in self.root.winfo_children():
            child.destroy()

    def _build_connect_screen(self):
        self._clear()
        shell = tk.Frame(self.root, bg=BG)
        shell.pack(fill="both", expand=True)
        panel = tk.Frame(shell, bg=SURFACE, highlightbackground=LINE, highlightthickness=1,
                         padx=46, pady=42)
        panel.place(relx=.5, rely=.5, anchor="center", width=510, height=570)
        tk.Label(panel, text="MTGNP", bg=SURFACE, fg=GOLD, font=TYPE_HERO).pack()
        tk.Label(panel, text="ARCANE TABLE", bg=SURFACE, fg=MUTED,
                 font=(FONT_UI, 10, "bold")).pack(pady=(1, 34))
        tk.Label(panel, text="ENTER THE MATCH", bg=SURFACE, fg=TEXT,
                 font=TYPE_TITLE).pack(anchor="w")
        tk.Label(panel, text="Connect to a host and join the next available duel.",
                 bg=SURFACE, fg=MUTED, font=TYPE_BODY).pack(anchor="w", pady=(5, 24))
        self.name_var = tk.StringVar(value="Player")
        self.host_var = tk.StringVar(value=HOST)
        self.port_var = tk.StringVar(value=str(PORT))
        for label, var in (("PLAYER NAME", self.name_var), ("SERVER ADDRESS", self.host_var),
                           ("PORT", self.port_var)):
            tk.Label(panel, text=label, bg=SURFACE, fg=MUTED,
                     font=TYPE_LABEL).pack(anchor="w", pady=(8, 5))
            ttk.Entry(panel, textvariable=var, style="Dark.TEntry").pack(fill="x")
        self.connect_button = ttk.Button(panel, text="JOIN MATCH", style="Gold.TButton",
                                         command=self._connect)
        self.connect_button.pack(fill="x", pady=(28, 12))
        self.connect_status = tk.Label(panel, text="Ready", bg=SURFACE, fg=MUTED,
                                       font=TYPE_BODY_SMALL)
        self.connect_status.pack()

    def _connect(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Player name required", "Choose a player name before joining.")
            return
        try:
            port = int(self.port_var.get())
        except ValueError:
            messagebox.showerror("Invalid port", "The server port must be a number.")
            return
        self.client = MTGNPClient(name)
        self.client.host, self.client.port = self.host_var.get().strip(), port
        self.client.set_event_listener(lambda event, data: self.events.put((event, data)))
        self.connect_button.state(["disabled"])
        self.connect_status.configure(text="Connecting…", fg=GOLD)
        threading.Thread(target=self.client.run, daemon=True).start()

    def _drain_events(self):
        try:
            while True:
                event, data = self.events.get_nowait()
                if event == "connected":
                    self._build_game_screen()
                    self._toast("Connected", f"Joined {data['host']}:{data['port']}", GREEN)
                elif event == "pdu":
                    self._handle_pdu(data)
        except queue.Empty:
            pass
        self.root.after(50, self._drain_events)

    def _build_game_screen(self):
        self._clear()
        self.stage = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        self.stage.pack(fill="both", expand=True)
        asset = os.path.join(os.path.dirname(__file__), "assets", "battlefield.png")
        if Image and os.path.exists(asset):
            image = Image.open(asset).resize((1600, 900), Image.Resampling.LANCZOS)
            self.bg_photo = ImageTk.PhotoImage(image)
            self.stage.create_image(0, 0, image=self.bg_photo, anchor="nw")
        self.app = tk.Frame(self.stage, bg="#0b111c")
        self.stage.create_window(0, 0, anchor="nw", window=self.app, tags="app")
        self.stage.bind("<Configure>", lambda e: (self.stage.itemconfigure("app", width=e.width, height=e.height)))

        top = tk.Frame(self.app, bg="#0b111c", height=62)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text="MTGNP", bg="#0b111c", fg=GOLD, font=(FONT_DISPLAY, 19, "bold")).pack(side="left", padx=22)
        self.turn_label = tk.Label(top, text="WAITING FOR MATCH", bg="#0b111c", fg=TEXT,
                                   font=TYPE_SECTION)
        self.turn_label.pack(side="left", padx=18)
        self.phase_label = tk.Label(top, text="LOBBY", bg=GOLD, fg="#171107",
                                    font=(FONT_UI, 9, "bold"), padx=14, pady=7)
        self.phase_label.pack(side="left")
        self.connection_label = tk.Label(top, text="● ONLINE", bg="#0b111c", fg=GREEN,
                                         font=(FONT_UI, 9, "bold"))
        self.connection_label.pack(side="right", padx=22)

        self.action_banner = tk.Label(self.app, text="WAITING FOR MATCH", bg=SURFACE_2,
                                      fg=MUTED, font=(FONT_DISPLAY, 14, "bold"),
                                      anchor="center", pady=10)
        self.action_banner.pack(fill="x")

        content = tk.Frame(self.app, bg="#0b111c")
        content.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        self.sidebar = tk.Frame(content, bg=SURFACE, width=240, padx=15, pady=14)
        self.sidebar.pack(side="right", fill="y", padx=(12, 0))
        self.sidebar.pack_propagate(False)
        self.board = tk.Frame(content, bg="#101722")
        self.board.pack(side="left", fill="both", expand=True)

        self.opponent_bar = self._player_bar(self.board, "OPPONENT")
        self.opponent_bar.pack(fill="x")
        self.opp_field = self._zone(self.board, "OPPONENT BATTLEFIELD")
        self.opp_field.pack(fill="both", expand=True, padx=12, pady=7)
        self.stack_zone = self._zone(self.board, "THE STACK", 82)
        self.stack_zone.pack(fill="x", padx=12, pady=4)
        self.my_field = self._zone(self.board, "YOUR BATTLEFIELD")
        self.my_field.pack(fill="both", expand=True, padx=12, pady=7)
        self.player_bar = self._player_bar(self.board, "YOU")
        self.player_bar.pack(fill="x")
        self.hand_zone = self._zone(self.board, "YOUR HAND", 150)
        self.hand_zone.pack(fill="x", padx=12, pady=(7, 12))
        self._build_sidebar()
        self._render()

    def _player_bar(self, parent, title):
        frame = tk.Frame(parent, bg="#131d2a", height=48)
        frame.pack_propagate(False)
        frame.title = tk.Label(frame, text=title, bg="#131d2a", fg=TEXT,
                               font=(FONT_UI, 10, "bold"))
        frame.title.pack(side="left", padx=14)
        frame.life = tk.Label(frame, text="20 LIFE", bg="#243446", fg=TEXT,
                              font=(FONT_DISPLAY, 11, "bold"), padx=12, pady=6)
        frame.life.pack(side="right", padx=10)
        frame.meta = tk.Label(frame, text="Library —   Hand —   Grave —", bg="#131d2a", fg=MUTED)
        frame.meta.pack(side="right", padx=8)
        return frame

    def _zone(self, parent, title, height=None):
        frame = tk.Frame(parent, bg="#131a24", highlightbackground="#263549", highlightthickness=1)
        if height:
            frame.configure(height=height)
            frame.pack_propagate(False)
        frame.title = tk.Label(frame, text=title, bg="#131a24", fg=MUTED,
                               font=TYPE_LABEL)
        frame.title.pack(anchor="nw", padx=10, pady=(6, 2))
        frame.cards = tk.Frame(frame, bg="#131a24")
        frame.cards.pack(fill="both", expand=True, padx=8, pady=(0, 7))
        return frame

    def _build_sidebar(self):
        tk.Label(self.sidebar, text="TACTICAL CONTROL", bg=SURFACE, fg=TEXT,
                 font=(FONT_DISPLAY, 12, "bold")).pack(anchor="w")
        self.priority_text = tk.Label(self.sidebar, text="Waiting for priority", bg=SURFACE,
                                      fg=MUTED, font=TYPE_BODY_SMALL)
        self.priority_text.pack(anchor="w", pady=(4, 14))
        self.mulligan_frame = tk.Frame(self.sidebar, bg=SURFACE)
        self.keep_btn = ttk.Button(self.mulligan_frame, text="KEEP HAND", style="Gold.TButton",
                                   command=self._keep_hand)
        self.keep_btn.pack(fill="x", pady=(0, 5))
        self.mulligan_btn = ttk.Button(self.mulligan_frame, text="TAKE MULLIGAN", style="Game.TButton",
                                       command=self._take_mulligan)
        self.mulligan_btn.pack(fill="x")
        self.pass_btn = ttk.Button(self.sidebar, text="PASS PRIORITY", style="Gold.TButton",
                                   command=lambda: self._command("pass"))
        self.pass_btn.pack(fill="x", pady=(0, 10))
        for text, command in (("PLAY / CAST SELECTED", self._play_selected),
                              ("DECLARE ATTACKERS", self._attack),
                              ("ATTACK WITH NONE", self._no_attack),
                              ("DECLARE BLOCKER", self._block),
                              ("BLOCK WITH NONE", self._no_blocks),
                              ("DISCARD SELECTED", self._discard)):
            ttk.Button(self.sidebar, text=text, style="Game.TButton", command=command).pack(fill="x", pady=4)
        ttk.Separator(self.sidebar).pack(fill="x", pady=16)
        tk.Label(self.sidebar, text="CARD INSPECTOR", bg=SURFACE, fg=MUTED,
                 font=TYPE_LABEL).pack(anchor="w")
        self.inspect_name = tk.Label(self.sidebar, text="Select a card", bg=SURFACE, fg=TEXT,
                                     wraplength=205, justify="left", font=(FONT_DISPLAY, 13, "bold"))
        self.inspect_name.pack(anchor="w", pady=(8, 5))
        self.inspect_meta = tk.Label(self.sidebar, text="", bg=SURFACE, fg=GOLD,
                                     wraplength=205, justify="left", font=TYPE_BODY_SMALL)
        self.inspect_meta.pack(anchor="w")
        self.inspect_effect = tk.Label(self.sidebar, text="Card rules and effects appear here.", bg=SURFACE,
                                       fg=MUTED, wraplength=205, justify="left", font=TYPE_BODY_SMALL)
        self.inspect_effect.pack(anchor="w", pady=10)
        ttk.Button(self.sidebar, text="CONCEDE MATCH", style="Danger.TButton",
                   command=self._concede).pack(side="bottom", fill="x")

    def _handle_pdu(self, pdu):
        ptype = pdu.get("type")
        if ptype == "GAME_STATE_UPDATE":
            self.state = pdu.get("state", {})
            if self.state.get("phase") == "MULLIGAN" and self.mulligan_pending == "mulligan":
                self.client.mulligan_count += 1
                self.mulligan_pending = None
                self.selected_hand.clear()
                self._toast("New hand drawn", f"Select {self.client.mulligan_count} card(s) to put on the bottom.", GOLD)
            elif self.state.get("phase") != "MULLIGAN":
                self.mulligan_pending = None
                self.mulligan_kept = False
                self.selected_hand.clear()
            if hasattr(self, "board"): self._render()
        elif ptype == "PHASE_TRANSITION" and hasattr(self, "phase_label"):
            self.phase_label.configure(text=PHASE_LABELS.get(pdu.get("to_phase"), pdu.get("to_phase")))
        elif ptype == "PRIORITY_GRANT" and hasattr(self, "priority_text"):
            if pdu.get("player_id") == self.client.player_id:
                self.priority_text.configure(text="Your priority — choose an action", fg=GREEN)
                self.pass_btn.state(["!disabled"])
        elif ptype == "ERROR":
            self.mulligan_pending = None
            self.mulligan_kept = False
            if hasattr(self, "board"): self._render()
            self._toast(pdu.get("code", "Action rejected"), pdu.get("message", ""), RED)
        elif ptype == "GAME_OVER":
            messagebox.showinfo("Match complete", f"Winner: {pdu.get('winner_id')}\nReason: {pdu.get('reason')}")
        elif ptype == "COMBAT_DAMAGE_RESULT":
            self._toast("Combat resolved", f"{len(pdu.get('damage_events', []))} damage event(s)", GOLD)

    def _render(self):
        if not hasattr(self, "board"): return
        state, me = self.state, self.client.player_id
        life = state.get("life_totals", {})
        opponent = next((pid for pid in life if pid != me), self.client.opponent_id or "Opponent")
        self.client.opponent_id = opponent if opponent != "Opponent" else self.client.opponent_id
        phase = state.get("phase", "LOBBY")
        active = state.get("active_player")
        is_my_turn = active == me
        if phase not in ("LOBBY", "MULLIGAN") and active:
            self.turn_label.configure(
                text=f"{'YOUR TURN' if is_my_turn else str(active).upper() + '’S TURN'}  •  TURN {state.get('turn', '—')}",
                fg=GREEN if is_my_turn else RED)
        else:
            self.turn_label.configure(text=f"TURN {state.get('turn', '—')}  •  {active or 'WAITING'}", fg=TEXT)
        self.phase_label.configure(text=PHASE_LABELS.get(phase, phase))
        counts, libs = state.get("hand_counts", {}), state.get("library_counts", {})
        graves = state.get("graveyard", {})
        for bar, pid, fallback in ((self.player_bar, me, "YOU"), (self.opponent_bar, opponent, "OPPONENT")):
            bar.title.configure(text=fallback if pid == me else str(pid).upper())
            bar.life.configure(text=f"{life.get(pid, 20)} LIFE")
            bar.meta.configure(text=f"Library {libs.get(pid, '—')}   Hand {counts.get(pid, len(state.get('hand', [])) if pid == me else '—')}   Grave {len(graves.get(pid, []))}")
        battlefield = state.get("battlefield", {})
        self._render_cards(self.opp_field, battlefield.get(opponent, []), False, True)
        self._render_cards(self.my_field, battlefield.get(me, []), True, True)
        self._render_cards(self.hand_zone, state.get("hand", []), True, False)
        stack = state.get("stack", [])
        self._render_cards(self.stack_zone, [s.get("source_id", s) if isinstance(s, dict) else s for s in stack], False, True)
        has_priority = state.get("priority_holder") == me or self.client.has_priority
        self.priority_text.configure(text="Your priority — choose an action" if has_priority else "Waiting for opponent",
                                     fg=GREEN if has_priority else MUTED)
        self.pass_btn.state(["!disabled"] if has_priority else ["disabled"])
        if phase == "MULLIGAN":
            self.mulligan_frame.pack(fill="x", before=self.pass_btn, pady=(0, 10))
            required = self.client.mulligan_count
            if self.mulligan_pending == "keep" or self.mulligan_kept:
                banner = "HAND LOCKED IN — WAITING FOR OPPONENT"
                banner_color = BLUE
            elif self.mulligan_pending == "mulligan":
                banner = "DRAWING A NEW HAND…"
                banner_color = GOLD
            elif required:
                banner = f"SELECT {required} CARD{'S' if required != 1 else ''} TO BOTTOM  •  {len(self.selected_hand)}/{required} SELECTED"
                banner_color = GOLD_BRIGHT
            else:
                banner = "OPENING HAND — KEEP OR TAKE A MULLIGAN"
                banner_color = GOLD_BRIGHT
            self.action_banner.configure(text=banner, bg="#2a2114", fg=banner_color)
            waiting = self.mulligan_pending is not None or self.mulligan_kept
            self.keep_btn.state(["disabled"] if waiting else ["!disabled"])
            self.mulligan_btn.state(["disabled"] if waiting else ["!disabled"])
            self.priority_text.configure(
                text="Waiting for opponent to finish" if waiting else
                     (f"Select {required} card(s), then keep" if required else "Choose your opening hand"),
                fg=BLUE if waiting else GOLD_BRIGHT)
        else:
            self.mulligan_frame.pack_forget()
            if phase == "DECLARE_ATTACKERS" and is_my_turn and not state.get("attackers_declared"):
                text, color = "YOUR ACTION — DECLARE ATTACKERS", GOLD_BRIGHT
            elif phase == "DECLARE_BLOCKERS" and not is_my_turn and not state.get("blockers_declared"):
                text, color = "YOUR ACTION — DECLARE BLOCKERS", GOLD_BRIGHT
            elif has_priority:
                text, color = "YOUR PRIORITY — TAKE AN ACTION OR PASS", GREEN
            elif is_my_turn:
                text, color = "YOUR TURN — WAITING FOR PRIORITY", GREEN
            else:
                text, color = f"{str(active).upper() if active else 'OPPONENT'}’S TURN — WAITING", MUTED
            self.action_banner.configure(text=text, bg="#13202b", fg=color)

    def _render_cards(self, zone, cards, selectable, field):
        for child in zone.cards.winfo_children(): child.destroy()
        if not cards:
            tk.Label(zone.cards, text="No cards", bg="#131a24", fg="#536174",
                     font=(FONT_BODY, 9, "italic")).pack(side="left", padx=8)
            return
        selected = self.selected_field if field else self.selected_hand
        for card in cards[:10]:
            cid = card_id(card)
            info = self.client._get_card_info(cid)
            tile = CardTile(zone.cards, card, info,
                            lambda c, f=field, s=selectable: self._select(c, f, s),
                            cid in selected, compact=field)
            tile.pack(side="left", padx=4, pady=2)

    def _select(self, cid, field, selectable):
        self._inspect(cid)
        if selectable:
            chosen = self.selected_field if field else self.selected_hand
            if cid in chosen: chosen.remove(cid)
            else: chosen.add(cid)
            self._render()

    def _inspect(self, cid):
        info = self.client._get_card_info(cid) or {}
        self.inspect_name.configure(text=info.get("card_name") or cid.replace("_", " ").title())
        cost = self._mana_text(info)
        self.inspect_meta.configure(text=f"{info.get('card_type', 'Card')}  •  {cost or 'No mana cost'}")
        self.inspect_effect.configure(text=info.get("simplified_effect") or "No rules text listed in the master card list.")

    @staticmethod
    def _mana_text(info):
        parts = []
        for key in ("generic", "w", "u", "b", "r", "g"):
            value = info.get(key)
            if value not in (None, 0, 0.0, "0"):
                parts.append(f"{key.upper() if key != 'generic' else '◇'}{int(value) if isinstance(value, float) else value}")
        return " ".join(parts)

    def _mana_payment(self, cid):
        info = self.client._get_card_info(cid) or {}
        payment = {}
        for key, symbol in (("w", "W"), ("u", "U"), ("b", "B"), ("r", "R"), ("g", "G")):
            value = info.get(key) or 0
            if value: payment[symbol] = int(value)
        generic = info.get("generic") or 0
        if generic: payment["X"] = int(generic)
        return payment

    def _play_selected(self):
        if len(self.selected_hand) != 1:
            self._toast("Select one card", "Choose exactly one card from your hand.", GOLD)
            return
        cid = next(iter(self.selected_hand))
        info = self.client._get_card_info(cid) or {}
        if "land" in str(info.get("card_type", "")).lower() or cid.startswith(("mountain", "island", "swamp", "forest", "plains")):
            self._command(f"land {cid}")
        else:
            targets = simpledialog.askstring("Spell targets", "Target IDs, separated by spaces. Leave blank if none:", parent=self.root)
            if targets is None: return
            pdu = {"type": "CAST_SPELL", "seq_num": self.client.priority_seq_num,
                   "card_id": cid, "targets": targets.split(), "mana_payment": self._mana_payment(cid)}
            self.client._send_pdu(pdu)
        self.selected_hand.clear()

    def _attack(self):
        if not self.selected_field:
            self._toast("Select attackers", "Choose one or more creatures on your battlefield.", GOLD); return
        self._command("attack " + " ".join(self.selected_field)); self.selected_field.clear()

    def _no_attack(self):
        self.client._send_pdu({"type": "DECLARE_ATTACKERS", "seq_num": self.client.last_phase_transition_seq,
                               "attackers": []})

    def _block(self):
        if len(self.selected_field) != 1:
            self._toast("Select one blocker", "Choose one creature on your battlefield.", GOLD); return
        attacker = simpledialog.askstring("Declare blocker", "Attacking creature ID:", parent=self.root)
        if attacker: self._command(f"block {next(iter(self.selected_field))} {attacker}")
        self.selected_field.clear()

    def _no_blocks(self):
        self.client._send_pdu({"type": "DECLARE_BLOCKERS", "seq_num": self.client.last_phase_transition_seq,
                               "blockers": []})

    def _discard(self):
        if self.selected_hand: self._command("discard " + " ".join(self.selected_hand)); self.selected_hand.clear()

    def _keep_hand(self):
        required = self.client.mulligan_count
        if len(self.selected_hand) != required:
            self._toast("Choose cards to bottom", f"Select exactly {required} card(s) before keeping.", GOLD)
            return
        self.client._send_pdu({
            "type": "MULLIGAN_CHOICE",
            "seq_num": self.client.server_seq_num,
            "keep": True,
            "cards_to_bottom": list(self.selected_hand),
        })
        self.mulligan_pending = "keep"
        self.mulligan_kept = True
        self._render()

    def _take_mulligan(self):
        if self.mulligan_pending or self.mulligan_kept:
            return
        self.client._send_pdu({
            "type": "MULLIGAN_CHOICE",
            "seq_num": self.client.server_seq_num,
            "keep": False,
            "cards_to_bottom": [],
        })
        self.mulligan_pending = "mulligan"
        self._render()

    def _concede(self):
        if messagebox.askyesno("Concede match", "Concede this match and award the win to your opponent?"):
            self._command("concede")

    def _command(self, command):
        if self.client: self.client._handle_user_command(command)

    def _toast(self, title, detail, color):
        if not hasattr(self, "app"): return
        toast = tk.Frame(self.app, bg=SURFACE_3, highlightbackground=color, highlightthickness=2, padx=15, pady=10)
        toast.place(relx=.99, rely=.08, anchor="ne", width=330)
        tk.Label(toast, text=title, bg=SURFACE_3, fg=color, font=(FONT_UI, 10, "bold")).pack(anchor="w")
        tk.Label(toast, text=detail, bg=SURFACE_3, fg=TEXT, font=TYPE_BODY_SMALL,
                 wraplength=290, justify="left").pack(anchor="w")
        self.root.after(4500, toast.destroy)

    def _close(self):
        if self.client:
            self.client.is_running = False
            try: self.client.sock.close()
            except (AttributeError, OSError): pass
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="MTGNP graphical game client")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    setup_logging(verbose=args.verbose)
    root = tk.Tk()
    GameClientUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
