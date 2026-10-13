# gt8650_dump.py

Reads flash and memory from a **Giga-tronics 8650 / 8600A Universal Power Meter**
over its serial port. The tool uses the firmware's built-in service monitor and its
`PEH` ("Peek, Hex") command.

It is based on a static analysis of the firmware image `8600_155.bic`
(Motorola 68340 / CPU32, Nucleus PLUS 1.11.4). The protocol was checked against the
firmware, and the script was tested offline against a simulated device.
It has **not** yet been run on real hardware.

> **Note:** The first editions of the documents and of the script (9 Oct 2026)
> assumed a load address of `0x6010`. The correct value is **`0x6000`**. Everything has
> been corrected; see [Corrections to the first edition](#corrections-to-the-first-edition).

## Files

| File | Contents |
|------|----------|
| `gt8650_dump.py` | The dump tool |
| `GT8650_Firmware_Analysis.md` / `.pdf` | Firmware analysis report (revised 13 Oct 2026) |
| `GT8650_HyperTerminal_Read100.md` / `.pdf` | Guide: reading the first 100 bytes by hand (revised 13 Oct 2026) |
| `tools/md2pdf.py` | Generates the PDFs from the `.md` files (ReportLab) |
| `LICENSE` | MIT license |

The reference firmware `8600_155.bic` is **not** included: it is Giga-tronics'
copyrighted code. If you have a copy, put it next to the script and check it against
the SHA-256 under [Reference firmware](#reference-firmware).

The `.md` files are the source. After a change, regenerate the PDFs like this:

```bash
pip install reportlab
python3 tools/md2pdf.py GT8650_Firmware_Analysis.md
python3 tools/md2pdf.py GT8650_HyperTerminal_Read100.md
```

---

## Requirements

- Python 3.8 or later
- pyserial:
  ```bash
  pip install pyserial
  ```
- A serial (RS-232) cable to the instrument's serial port. On a Mac or on Linux a
  USB-to-serial adapter works, e.g. `/dev/tty.usbserial-*` or `/dev/ttyUSB0`.

## Serial settings

These values come from the monitor's UART initialisation (file offset `0x1774`):

| Parameter    | Value | Evidence                                  |
|--------------|-------|-------------------------------------------|
| Baud rate    | 9600  | CSR = `0xBB`, ACR = `0x80`                |
| Data bits    | 8     | MR1 = `0x93`                              |
| Parity       | none  | MR1 = `0x93`                              |
| Stop bits    | 1     | MR2 = `0x07`                              |
| Flow control | none  | RxRTS is enabled but not required         |

The 9600 baud figure assumes the usual 3.6864 MHz baud-rate crystal is fitted.
If no banner comes back, also try `-b 19200` and `-b 115200`.

---

## Entering the service monitor

At power-on the following sequence runs (reconstructed from the firmware):

1. Boot entry `0x6408` → `0x6854`: hardware initialisation, then a RAM test over `0x200000–0x2FFFFF`
2. Checksum over the data block at `0x4000` (probably calibration or configuration data)
3. The monitor is copied to RAM at `0x2FC000` and started
4. The monitor waits **briefly** for a `*` (timeout loop of `0xFFFFF` iterations,
   estimated at about 1–2 s)
5. If **no** `*` arrives and the self-test passed, the normal instrument
   application starts. The monitor is then gone.
6. If the self-test failed, the monitor stays active and answers with
   `ERR 8600A`.

So the `*` has to arrive **within the first few seconds after power-on**.
The script takes care of this:

1. **Monitor already active?** First the script sends a CR and a test `PEH`.
   If a valid reply comes back, the monitor is already active (e.g. from an
   earlier run) and the handshake is skipped. You can therefore run the script
   several times in a row without power-cycling.
2. **Otherwise it waits for power-on.** The script sends a `*` roughly every
   0.1–0.25 s for up to `--wait` seconds (default 60) until the banner arrives.
   The monitor ignores any further `*` after that.

### Step by step

1. Switch the instrument off and connect the cable.
2. Start the script. It prints `sending '*' for up to 60 s -- switch the instrument on now`.
3. Switch the instrument on. After the self-test, `[*] banner: 'OK 8600A'` appears
   and the dump begins.

If the instrument boots normally and no banner appears, the baud rate or cable is wrong.
You may need a null-modem cable. In that case the instrument application starts, and
the instrument has to be switched off again before the next attempt.

---

## Usage

```
gt8650_dump.py -p PORT [-b BAUD] [--start ADDR] [--length N] [--base ADDR]
               [-o FILE] [--verify REF.bic] [--probe] [--wait SEC]
               [--read-timeout SEC]
```

| Option              | Meaning                                                                                  |
|---------------------|------------------------------------------------------------------------------------------|
| `-p`, `--port`      | Serial port (required)                                                                   |
| `-b`, `--baud`      | Baud rate, default `9600`                                                                |
| `--start`           | Start address (decimal or `0x…`), default = `--base`, i.e. `0x6000`                      |
| `--length`          | Number of bytes. If omitted, reads up to the end of the `--verify` file                  |
| `--base`            | Bus address of byte 0 of the `.bic`, default `0x6000`. Only needed for other firmware versions |
| `-o`, `--out`       | Output file, default `dump.bin`                                                          |
| `--verify REF.bic`  | After reading, compares the part of the dump that overlaps the reference. With `--probe`: checks the mapping |
| `--probe`           | Reads 16 bytes each at `0x0`, `0x4000` and `--base`, checks the mapping, then exits      |
| `--wait`            | How long to keep sending `*` while waiting for power-on, default `60` s                  |
| `--read-timeout`    | Timeout per `read()` in seconds, default `0.25`                                          |

Exit code `2` means no banner and no active monitor was found.

### Examples

Quick check of the link and the mapping:

```bash
python3 gt8650_dump.py -p /dev/tty.usbserial-XXXX --probe --verify 8600_155.bic
```

Expected: `[+] 0x6000 matches .bic byte 0 -> mapping CONFIRMED.`

Read the firmware range and check it against the `.bic`:

```bash
python3 gt8650_dump.py -p /dev/tty.usbserial-XXXX -o firmware.bin --verify 8600_155.bic
```

On success the output ends with
`[+] VERIFY OK: 1080718 bytes at 0x006000..0x10dd8d match 8600_155.bic`.

Read the whole flash (2 MB), i.e. boot block, data block at `0x4000` and firmware.
`--verify` automatically checks the firmware part starting at `0x6000`:

```bash
python3 gt8650_dump.py -p /dev/tty.usbserial-XXXX --start 0 --length 0x200000 -o flash_full.bin --verify 8600_155.bic
```

For an EOL instrument the full dump is the valuable part: the boot block
(`0x0000–0x3FFF`) and the data block (`0x4000–0x5FFF`, probably calibration data)
are **not** contained in the `.bic`.

### Duration

Each `PEH` command returns 40 bytes as 80 hex characters plus CR/LF, and the command
itself is about 10 characters. At 9600 baud that gives at most about 400 bytes/s.
The script shows the remaining time (ETA) while dumping.

| Range                 | Size        | Minimum duration |
|-----------------------|-------------|------------------|
| Firmware image        | 1,080,718 B | about 45 min     |
| Full 2 MB flash       | 2,097,152 B | about 85 min     |

---

## Protocol

```
Host   -> *                          attention character (only in the boot window)
Device -> OK 8600A<CR><LF>           or ERR 8600A if the self-test failed
Host   -> PEH06000<CR>               PEH + count (1 hex digit) + address (hex)
Device -> 002D8FFC00009D2A…<CR><LF>  2×N hex characters, uppercase, no prefix
```

- Count: `1`–`F` reads 1–15 bytes. `0` reads the default of **40 bytes** (`0x28`).
  The script always uses `0`.
- The address is a 32-bit hex value. Spaces are skipped.
- Commands are converted to uppercase, so case does not matter.
- The line reader accepts CR or LF as terminator; ESC discards the line, backspace deletes
  one character. `*` is ignored.
- There is no authentication. The monitor also has `PO*` (Poke) commands, which **write**
  memory. The script uses `PEH` only.

## Memory map

Derived from the chip-select table (file `0x301A`) and the initialisation code:

| Range                       | Contents                                                  |
|-----------------------------|-----------------------------------------------------------|
| `0x000000–0x0FFFFF`         | Flash, CS0                                                |
| ` ├ 0x000000–0x003FFF`      | Boot block (not in the `.bic`, contents unknown)          |
| ` ├ 0x004000–0x005FFF`      | Data block with checksum (not in the `.bic`)              |
| ` └ 0x006000–…`             | Firmware image `8600_155.bic` (VBR = `0x6000`)            |
| `0x100000–0x1FFFFF`         | Flash, CS1 (continued; the image ends at `0x10DD8D`)      |
| `0x200000–0x2FFFFF`         | RAM, CS2. The monitor runs from RAM at `0x2FC000`         |
| `0x800000…`                 | Peripherals, CS3                                          |
| `0xFFFFF000…`               | Internal 68340 registers (MBAR). The serial port is at `0xFFFFF700` |

Conversion: **device address = offset in the `.bic` + `0x6000`**.

---

## Manual test with a terminal program

With HyperTerminal, PuTTY, `screen` or `minicom` (9600 8N1, no flow control,
local echo on, Enter sends CR). Press `*` repeatedly while switching on
until `OK 8600A` appears:

| Input       | Reads address     | `.bic` offset | Expected reply (start)              |
|-------------|-------------------|---------------|-------------------------------------|
| `*`         | –                 | –             | `OK 8600A`                          |
| `PEH06000`  | `0x6000–0x6027`   | `0x00–0x27`   | `002D8FFC00009D2A000095F6…`         |
| `PEH06028`  | `0x6028–0x604F`   | `0x28–0x4F`   | `00009676000096960000913000…`       |
| `PEH06050`  | `0x6050–0x6077`   | `0x50–0x77`   | `0000915000009154000091580000…`     |

Sanity check: the first 8 bytes are `00 2D 8F FC 00 00 9D 2A`, i.e. the firmware's
initial stack pointer and reset PC.

---

## Corrections to the first edition

The first editions (9 Oct 2026, not included) get the protocol right: `PEH`, 40-byte default,
hex reply with CR/LF, `*` and the banner. The following statements were wrong and
have been corrected in the current documents:

| First edition | Correct | Evidence |
|---------------|---------|----------|
| `runtime = file + 0x6010` | `runtime = file + 0x6000` | `movec #$6000, VBR` at file `0x303A`. The reset PC `0x9D2A` points to `movea.l #$2FFFF0, a7`, and the stub table starts at `0x9108` (matching `sub.l #$9108` in the handler) |
| Image size `0x107ECE`, range `0x6010–0x10DEDE` | `0x107D8E`, range `0x6000–0x10DD8D` | File size. The length field in the boot header at `0x6414` also contains `0x107D8E` |
| Handler addresses `0x12B0`, `0x1A88` etc. as "runtime" | These are **file offsets** | In flash they are at +`0x6000`, in RAM at −`0x400` + `0x2FC000` |
| DUART at `0x00F700` | Internal 68340 serial module at `0xFFFFF700` | `$F711.w` is sign-extended, MBAR = `0xFFFFF000` |
| Baud rate cannot be determined | 9600 8N1 | UART initialisation at `0x1774` |
| No caller of the monitor found | Boot path `0x6408` → `0x6854` → `0x6C08` | See [Entering the service monitor](#entering-the-service-monitor) |
| HyperTerminal: `PEH06010` / `PEH06038` / `PEH06060` | `PEH06000` / `PEH06028` / `PEH06050` | The printed replies are correct but belong to these addresses |

## Open points

- The script has not yet been run on real hardware. It has only been tested against
  a simulated device: power-on, boot window, already active monitor, and a full dump
  byte-identical to the `.bic`.
- The length of the `*` window is an estimate. That is why the script sends `*` continuously.
- How the monitor responds to empty or unknown lines has not been analysed.
  The "monitor already active" check sends a CR and discards whatever comes back.
- The checksum in the boot header (`0x6418`) and the one in the data block (`0x4000`)
  have not been analysed: neither the algorithm nor the covered range is known.
- The boot block at `0x0` is not in the `.bic`. That it loads the same monitor layout
  is inferred from the entry-address calculation (`0x71C4 − 0x6400 + 0x2FC000`), not proven.

## Reference firmware

| Property    | Value |
|-------------|-------|
| File        | `8600_155.bic` (the first editions call it `84e2587e-8600_155.bic`) |
| Size        | 1,080,718 bytes (`0x107D8E`) |
| CRC32       | `7414aad0` |
| SHA-256     | `6fe062387758c7e7c2f4313963a99a860be889aed99918fdb81e397de44f26cf` |
| Format      | Raw image of the flash range `0x6000–0x10DD8D`, no file header or trailer |
| Internal checksum | Field at `0x6418` in the boot header; algorithm and covered range not analysed |
| CPU         | Motorola MC68340 (CPU32), big-endian |
| RTOS        | Nucleus PLUS – 68340D Version 1.11.4 |
| Identification | `(C) Giga-tronics, 1999`, `Gigatronics 8650 Universal Power Meter` |

CRC32 and SHA-256 are taken over the whole file. They only identify the file; the
firmware does not check them.

The `.bic` is a byte-for-byte copy of the flash contents from `0x6000` onwards:

- File offset 0 is the exception vector table (initial SP `0x2D8FFC`, reset PC `0x9D2A`),
  and the firmware sets VBR = `0x6000`.
- The file size equals the image length stored in the boot header at `0x6414`, so
  nothing is appended.
- The boot header at file offset `0x400` (flash `0x6400`) belongs to the firmware itself
  (jump table, length, checksum). It is not a container header of the file.

The `.bic` only covers part of the flash. The boot block (`0x0000–0x3FFF`), the data
block (`0x4000–0x5FFF`) and everything after `0x10DD8D` are missing. That the bytes sit
in the instrument exactly like this is derived from the code. It still has to be
confirmed on real hardware with `--probe`.

## Key locations in the firmware

Given as `.bic` offsets. In flash each location is at offset + `0x6000`.
The monitor runs as a RAM copy at offset − `0x400` + `0x2FC000`.

| Offset   | Function |
|----------|----------|
| `0x0000` | Vector table (VBR = `0x6000`, set at `0x303A`) |
| `0x0400` | Boot header with jump table (`0x6408` = boot, `0x641C` = application, `0x6420` = monitor) |
| `0x0C08` | Copies the monitor to RAM and starts it |
| `0x11C4` | Monitor entry. Waits for `*` and prints the banner |
| `0x12B0` | Jump table for commands A–Z |
| `0x1774` | UART initialisation (9600 8N1) |
| `0x1804` | Line reader |
| `0x1A88` | `PEH` handler |
| `0x2328` | Nibble → hex character (uppercase) |
| `0x2D48` | Strings `OK 8600A` / `ERR 8600A` |

## License

The tool, the scripts and the documentation in this repository are released under the
[MIT License](LICENSE). Giga-tronics, the 8650 and the 8600A are names of their
respective owners; this project is not affiliated with Giga-tronics. The instrument
firmware itself is not part of this repository.
