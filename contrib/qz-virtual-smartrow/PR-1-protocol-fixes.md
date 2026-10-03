**Title:** SmartRow: V3.10 protocol fixes (checksum, elapsed time, stop marker)

## Reference

Reference: requested by @cagnulein in a chat on 2026-10-03 ("create a PR on github on the qz repository"). The findings come from a SmartRow → SmartRow app + Peloton (FTMS) bridge I built on a Raspberry Pi, whose protocol knowledge started from `smartrowrower.cpp`.

## Changes

Parsing fixes in `smartrowrower.cpp`, each backed by captures from a SmartRow pulley on firmware **V3.10** (1476 records over a 2½-minute session: easy strokes, hard strokes up to 264 W, steady, then stop).

| Record | Change | Evidence |
|---|---|---|
| all | Validate the checksum: bytes 14-15 are the hex of `sum(raw bytes 0..13) & 0xFF` (raw = before the V3 nibble unscrambling). Corrupted records are ignored. | 1476 of 1476 records match |
| `a` | Elapsed time is `MMMSS` at `[6:11]`, not `HHMMSS`. | The counter goes `00058` → `00101` → … → `00159` → `00200`; the current code reads 1:01 as 0h 10m 1s |
| `f` | `'!'` at `[11]` means the flywheel has stopped → zero watts, speed, and cadence (when cadence comes from the pulley). | After stopping, the pulley keeps repeating the last `c`/`d`/`e` values twice a second, so QZ kept reporting the last stroke (181 W for ~30 s in the capture) |
| `c`, `e` | Comments only: `c` `[9:14]` is the average power ×10 and `[6:9]` stays 0 until the first stroke completes; `e` `[9:12]` is the average split. | Both match `W = 2.8 / (pace/500)^3` within ~2 % from 45 to 264 W |

Also confirmed, no code change needed: the V3 handshake as implemented works (`KEYLOCK=CBFF31C4` → `ca63`, `KEYLOCK=D39F4FBF` → `9177`).

## Testing

- **Not compiled or run in QZ.** I don't have a QZ build environment; the change was written against the source and relies on CI for the build.
- The same logic (checksum, `MMMSS`, stop marker, field offsets) runs in my Python bridge, where it is unit-tested by replaying the 1476-record capture and has been used for real sessions with the SmartRow app and Peloton recording simultaneously.
- This code was drafted with AI assistance (Claude) and reviewed by me against the captures. Please review it with that in mind.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
