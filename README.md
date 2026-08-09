# Magic: The Gathering Network Protocol (MTGNP) for CSNETWK

**MTGNP** is a TCP-based client-server implementation of a simplified, two-player *Magic: The Gathering* card game. The server acts as the sole authority for all game logic, managing turns, the stack, priority, combat, and state-based actions. Clients are thin renderers that send player actions and receive personalized game state updates.

The protocol and implementation follow the [MTGNP RFC v1.0](https://docs.google.com/document/d/1m-INIX8lu9nMxxLh-33n4gP8NxrpAJzgOSODM6hqJyQ/edit?usp=sharing).

---

## A. Build & Run Instructions

### Prerequisites
- Python 3.8 or higher (no external libraries required)
- All source files must be in the same directory:
  - `server.py`
  - `client.py`
  - `engine.py`
  - `turn_manager.py`
  - `protocol.py`
  - `console_logger.py`
  - `logger.py`

---

### Running the Server

```bash
py server.py [--verbose]
```

| Argument |	Description |
| - | - |
| `--verbose` (optional) | Prints all sent/received PDUs and internal logs to the console. |

#### Example
> ```bash
> py server.py --verbose
> ```

---

### Running the Client
```bash
py client.py [--verbose] [--name NAME]
```

| Argument |	Description |
| - | - |
| `--verbose`	(optional) | Enables detailed PDU logging on the client side. |
| `--name`	(optional) | Sets the player's display ID (default: anonymous). Must be unique per lobby. |

#### Example
> ```bash
> py client.py --name Alice --verbose
> py client.py --name Bob
> py client.py --verbose
> ```

> [!NOTE]
> Two clients must connect to the same server to start a game. The server listens on `localhost:4444` by default.

---

## B. Work Distribution Matrix

The contribution matrix disclosed will formalize the contribution of each of the members to the machine project. It is important that the members agree with the figures and remarks imparted here, and it is expected that all have arrived at the same conclusion in good faith.

| TASK / FEATURE | Aya-ay, V. | Barras, A. | Esguerra, D. | Policarpio, R. | SUM |
| --- | --- | --- | --- | --- | --- |
| **TCP Server: connection handling, framing, dispatch** | 13.0000% | 5.0000% | 77.0000% | 5.0000% | 100.0000% |
| **Game lifecycle: LOBBY, GAME_SETUP, MULLIGAN logic** | 90.0000% | 3.3333% | 3.3333% | 3.3333% | 99.9999% |
| **Turn & phase engine (all phases/steps, transitions)** | 5.0000% | 85.0000% | 5.0000% | 5.0000% | 100.0000% |
| **Priority & Stack logic, spell/ability resolution** | 5.0000% | 85.0000% | 5.0000% | 5.0000% | 100.0000% |
| **Combat system (attackers, blockers, damage)** | 5.0000% | 5.0000% | 5.0000% | 85.0000% | 100.0000% |
| **Client implementation & state rendering** | 20.0000% | 5.0000% | 5.0000% | 70.0000% | 100.0000% |
| **PDU serialisation/deserialisation (all 25 PDU types)** | 25.0000% | 25.0000% | 25.0000% | 25.0000% | 100.0000% |
| **Error handling, PING/PONG heartbeat, disconnect logic** | 40.0000% | 10.0000% | 40.0000% | 10.0000% | 100.0000% |
| **Verbose mode (client + server PDU logging, toggle on/off)** | 5.0000% | 5.0000% | 70.0000% | 20.0000% | 100.0000% |
| **Testing & interoperability** | 40.0000% | 20.0000% | 20.0000% | 20.0000% | 100.0000% |
| **README / documentation / AI disclosure** | 25.0000% | 25.0000% | 25.0000% | 25.0000% | 100.0000% |
| **AVERAGE CONTRIBUTION** | **24.8182%** | **24.8485%** | **25.4848%** | **24.8485%** | **100.0000%** |

---

## C. Declaration of AI Usage

* **AI Tools Used:** DeepSeek, Google Gemini
* **Output Explanation:** 
* **Extent of Use:**
* **Contribution to Learning:**

---

## D. Deviations from the RFC

