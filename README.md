# MTGNP - Magic: The Gathering Network Protocol for CSNETWK

**MTGNP** is a TCP-based client-server implementation of a simplified, two-player *Magic: The Gathering* card game.  
The server acts as the sole authority for all game logic, managing turns, the stack, priority, combat, and state-based actions.  
Clients are thin renderers that send player actions and receive personalised game state updates.

The protocol and implementation follow the [MTGNP RFC v1.0](https://docs.google.com/document/d/1m-INIX8lu9nMxxLh-33n4gP8NxrpAJzgOSODM6hqJyQ/edit?usp=sharing).

---

## Build & Run Instructions

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
| `--verbose` (optional) | prints all sent/received PDUs and internal logs to the console. |

#### Example
```bash
py server.py --verbose
```

---

### Running the Client
```bash
py client.py [--verbose] [--name NAME]
```

| Argument |	Description |
| - | - |
| `--verbose`	(optional) | enables detailed PDU logging on the client side. |
| `--name`	(optional) | sets the player's display ID (default: anonymous). Must be unique per lobby. |

#### Example
```bash
py client.py --name Alice --verbose
py client.py --name Bob
py client.py --verbose
```

> Note: Two clients must connect to the same server to start a game. The server listens on `localhost:4444` by default.
