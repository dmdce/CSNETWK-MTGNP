import struct
import sys
import socket
import json
import time
import threading

HOST = socket.gethostbyname(socket.gethostname())
PORT = 4444

class MTGNPCLient:
    def __init__(self, player_id):
        self.player_id = player_id
        self.host = HOST
        self.port = PORT
        self.sock = None
        self.seq_num = 0
        self.last_ping_seq = -1
        self.pong_timer = None
        self.is_running = True
        self.deck = ["mountain_001", "shock_001", "goblin_guide_001"] # Temporary

    def _start_heartbeat(self):
        thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        thread.start()

    def _heartbeat_loop(self):
        while self.is_running:
            time.sleep(30)
            if self.sock:
                self.seq_num += 1
                self.last_ping_seq = self.seq_num

                ping_pdu = {
                    "type": "PING",
                    "seq_num": self.seq_num,
                    "timestamp": time.time()
                }

                self.pong_timer = threading.Timer(10.0, self._on_pong_timeout)
                self.pong_timer.start()

                print(f"[PING] Sending heartbeat (seq: {self.seq_num}). Waiting for PONG...")
                self._send_pdu(ping_pdu)

    def _on_pong_timeout(self):
        print(f"[client] TIMEOUT: No PONG received for seq {self.last_ping_seq} within 10s.")
        print("[client] Closing connection due to no response from server...")

        if self.sock:
            try:
                # Force close to trigger reconnection
                self.sock.shutdown(socket.SHUT_RDWR)
                self.sock.close()
            except:
                pass

    def _send_pdu(self, pdu):
        try:
            payload = json.dumps(pdu).encode('utf-8')
            header = struct.pack('>I', len(payload))
            self.sock.sendall(header + payload)
        except (socket.error, AttributeError):
            print("[client] Failed to send PDU: Socket not connected.")

    def _recv_pdu(self):
        try:
            header = self.sock.recv(4)

            if not header: return None

            length = struct.unpack('>I', header)[0]
            chunks = []
            bytes_received = 0

            while bytes_received < length:
                chunk = self.sock.recv(min(length - bytes_received, 4096))
                if not chunk: break
                chunks.append(chunk)
                bytes_received += len(chunk)

            return json.loads(b"".join(chunks).decode('utf-8'))
        except (socket.error, json.JSONDecodeError):
            return None

    def connect_and_identify(self):
        while self.is_running:
            try:
                print(f"[client] Attempting to connect to {self.host}:{self.port}...")
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                # Ensures client doesn't hang on dead link:
                self.sock.settimeout(15.0)
                self.sock.connect((self.host, self.port))

                print(f"[client] Connected. Sending PLAYER_READY for '{self.player_id}'...")
                self.seq_num += 1
                ready_pdu = {
                    "type": "PLAYER_READY",
                    "seq_num": self.seq_num,
                    "player_id": self.player_id,
                    "deck_list": self.deck
                }
                self._send_pdu(ready_pdu)
                return True

            except (socket.error, ConnectionRefusedError):
                print("[client] Connection failed. Retrying in 5 seconds...")
                time.sleep(5)
        return False

    def run(self):
        if not self.connect_and_identify():
            return

        self._start_heartbeat()

        while self.is_running:
            pdu = self._recv_pdu()

            if pdu is None:
                print("\n[client] TCP Disconnect detected by Peer!")
                # Try to reconnect immediately
                if self.connect_and_identify():
                    continue
                else:
                    break

            self.handle_pdu(pdu)

    def handle_pdu(self, pdu):
        p_type = pdu.get("type")

        if p_type == "PONG":
            # timestamp = pdu.get("timestamp")
            # seqnum = pdu.get("seq_num")
            # latency = round((time.time() - timestamp) * 1000, 2)
            # print(f"[PONG] Heartbeat acknowledged. (seq: {seqnum}, latency: {latency} ms)")
            if pdu.get("seq_num") == self.last_ping_seq:
                if self.pong_timer:
                    self.pong_timer.cancel()

                latency = round((time.time() - pdu.get("timestamp")) * 1000, 2)
                print(f"[PONG] Received. Latency: {latency}ms, ping timer cancelled")
            else:
                print(f"[client] ??? Received stale PONG (expected {self.last_ping_seq}, got {pdu.get('seq_num')})")

        elif p_type == "GAME_STATE_UPDATE":
            state = pdu.get("state", {})
            print(f"\n--- STATE UPDATE (Seq: {pdu.get('seq_num')}) ---")
            print(f"Phase: {state.get('phase')}")
            print(f"Players Ready: {state.get('players_ready')}")
            if state.get('waiting_for'):
                print(f"Waiting for: {state.get('waiting_for')}")

        elif p_type == "ERROR":
            print(f"\n[server] ERROR {pdu.get('code')}: {pdu.get('message')}")

        elif p_type == "GAME_OVER":
            print(f"\n--- GAME OVER ---")
            print(f"Winner: {pdu.get('winner_id')} | Loser: {pdu.get('loser_id')}")
            print(f"Reason: {pdu.get('reason')}")

            print("[client] Returning to lobby. Waiting for next game.")
            self.seq_num = 0

        elif p_type == "PING":
            self._send_pdu({"type": "PONG", "seq_num": pdu.get("seq_num")})

if __name__ == '__main__':
    if len(sys.argv) > 1:
        player = sys.argv[1]
    else:
        player = "anonymous"

    client = MTGNPCLient(player_id = player)

    try:
        client.run()
    except KeyboardInterrupt:
        print("\n[client] Exiting...")
        client.is_running = False