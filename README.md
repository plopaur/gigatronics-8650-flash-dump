# gt8650_dump.py

Reads flash and memory from a **Giga-tronics 8650 / 8600A Universal Power Meter**
over its serial port. The tool uses the firmware's built-in service monitor and its
`PEH` ("Peek, Hex") command.

It is based on a static analysis of the firmware image `8600_155.bic`
(Motorola 68340 / CPU32, Nucleus PLUS 1.11.4). The protocol was checked against the
firmware, and the script has since been used on live units: two complete 2 MB
flash dumps (firmware 1.58 and 1.61) were read with it, and all their checksums match.
A fourth image, `8650_135.bic` (an older 8650 build), also passes the image checksum.

> **Note:** The first editions of the documents and of the script (9 Oct 2026)
> assumed a load address of `0x6010`. The correct value is **`0x6000`**. Everything has
> been corrected; see [Corrections to the first edition](#corrections-to-the-first-edition).

## Files

| File | Contents |
|------|----------|
| `gt8650_dump.py` | The dump tool |
| `extract_bic.py` | Checks a dump offline and cuts out the firmware image as `.bic` (also provides the checksum code for the dump tool) |
| `GT8650_Firmware_Analysis.md` | Firmware analysis report (revised 14 Oct 2026) |
| `GT8650_HyperTerminal_Read100.md` | Guide: reading the first 100 bytes by hand (revised 13 Oct 2026) |
| `md2pdf.py` | Generates PDFs from the `.md` files (ReportLab) |
| `LICENSE` | MIT license |

The reference firmware `8600_155.bic` is **not** included: it is Giga-tronics'
copyrighted code. If you have a copy, put it next to the script and check it against
the SHA-256 under [Reference firmware](#reference-firmware).

The `.md` files are the source. PDFs are not part of the repository (`*.pdf` is in
`.gitignore`); generate them locally if needed:

```bash
pip install reportlab
python3 md2pdf.py GT8650_Firmware_Analysis.md
python3 md2pdf.py GT8650_HyperTerminal_Read100.md
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

1. Boot entry `0x6408` → `0x6854`: hardware initialisation, then a RAM test over `0x200000–0x2FFFFF`.
   The CPU actually runs the identical copy of this code in the boot block at `0x0`.
2. CRC check of the data block at `0x4000` (unit data, see [Flash layout and checksums](#flash-layout-and-checksums))
3. The monitor is copied from the boot block to RAM at `0x2FC000` and started
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
               [--read-timeout SEC] [--restart] [--retries N]
               [--max-recoveries N]
```

| Option              | Meaning                                                                                  |
|---------------------|------------------------------------------------------------------------------------------|
| `-p`, `--port`      | Serial port (required)                                                                   |
| `-b`, `--baud`      | Baud rate, default `9600`                                                                |
| `--start`           | Start address (decimal or `0x…`), default = `--base`, i.e. `0x6000`                      |
| `--length`          | Number of bytes. If omitted, reads up to the end of the firmware image: taken from the `--verify` file, otherwise from the length field in the device's boot header (`0x6414`) |
| `--base`            | Bus address of byte 0 of the `.bic`, default `0x6000`. Only needed for other firmware versions |
| `-o`, `--out`       | Output file, default `dump.bin`                                                          |
| `--verify REF.bic`  | After reading, compares the part of the dump that overlaps the reference (same firmware version only). With `--probe`: checks the mapping |
| `--probe`           | Reads 16 bytes each at `0x0`, `0x4000` and `--base`, shows image length and checksum from the boot header, checks the data-block CRC, then exits |
| `--wait`            | How long to keep sending `*` while waiting for power-on, default `60` s                  |
| `--read-timeout`    | Timeout per `read()` in seconds, default `0.25`                                          |
| `--restart`         | Overwrite an existing output file instead of resuming it                                 |
| `--retries`         | `PEH` retries per block before recovery starts, default `4`                              |
| `--max-recoveries`  | Recovery attempts per failure before giving up, default `6` (from #3 on: power-cycle prompt) |

After every dump the script runs a **self-check**: it verifies the checksums of all
regions the dump fully covers (boot block, data block, firmware image). No reference
`.bic` is needed for that, so it works for any firmware version.

If the link drops, the script resyncs, reopens the port and finally asks for a
power-cycle. If it gives up or you press Ctrl-C, run the same command again: the
existing output file is resumed.

Exit codes: `1` = stopped (resumable), `2` = no banner and no active monitor found,
`3` = a self-check failed.

### Examples

Quick check of the link, plus the image length and checksum of the installed firmware:

```bash
python3 gt8650_dump.py -p /dev/tty.usbserial-XXXX --probe
```

With `--verify 8600_155.bic` it also prints
`[+] 0x6000 matches .bic byte 0 -> mapping CONFIRMED.` (if the unit runs 1.55).

Read the installed firmware image, whatever its version (length from the device,
self-checked):

```bash
python3 gt8650_dump.py -p /dev/tty.usbserial-XXXX -o firmware.bin
```

Expected at the end: `[+] self-check firmware image @0x006000: length 0x…, checksum 0x… OK`.

Read the firmware range and also compare it with a `.bic` of the same version:

```bash
python3 gt8650_dump.py -p /dev/tty.usbserial-XXXX -o firmware.bin --verify 8600_155.bic
```

On success the output ends with
`[+] VERIFY OK: 1080718 bytes at 0x006000..0x10dd8d match 8600_155.bic`.

Read the whole flash (2 MB), i.e. boot block, data block at `0x4000`, firmware and
NV data. The self-check covers all three checksummed regions:

```bash
python3 gt8650_dump.py -p /dev/tty.usbserial-XXXX --start 0 --length 0x200000 -o flash_full.bin
```

For an EOL instrument the full dump is the valuable part: the boot block
(`0x0000–0x3FFF`), the data block (`0x4000–0x5FFF`, unit data) and the NV data at
`0x1E0000` are **not** contained in the `.bic`.

### Extracting a `.bic` from a dump

`extract_bic.py` needs no extra packages. It checks every checksum and writes
`flash[0x6000 : 0x6000 + len]`, which is byte-identical to a `.bic` of that version:

```bash
python3 extract_bic.py flash_full.bin -o 8600_158.bic
```

For a dump that does not start at `0` pass `--start` (e.g. `--start 0x6000`).
Given a `.bic`, the script only checks its checksum. A `.bic` is recognised when its
size equals the length field at `0x414`, or when it has less than 4 KiB of zero
padding after the image (as `8650_135.bic` does). With `-o` the padding is removed:

```bash
python3 extract_bic.py 8650_135.bic -o 8650_135_trimmed.bic
```

`gt8650_dump.py --verify` also ignores this padding.

### Duration

Each `PEH` command returns 40 bytes as 80 hex characters plus CR/LF, and the command
itself is about 10 characters. At 9600 baud that gives at most about 400 bytes/s.
The script shows the remaining time (ETA) while dumping.

| Range                 | Size        | Minimum duration |
|-----------------------|-------------|------------------|
| Firmware image (1.55) | 1,080,718 B | about 45 min     |
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
| ` ├ 0x000000–0x003FFF`      | Boot block: copy of the boot/monitor code; the CPU resets into it (not in the `.bic`) |
| ` ├ 0x004000–0x005FFF`      | Data block with CRC, unit data (not in the `.bic`)        |
| ` └ 0x006000–…`             | Firmware image `8600_155.bic` (VBR = `0x6000`)            |
| `0x100000–0x1FFFFF`         | Flash, CS1 (continued; the 1.55 image ends at `0x10DD8D`) |
| ` └ 0x1E0000–…`             | NV measurement/settings data (not in the `.bic`)          |
| `0x200000–0x2FFFFF`         | RAM, CS2. The monitor runs from RAM at `0x2FC000`         |
| `0x800000…`                 | Peripherals, CS3                                          |
| `0xFFFFF000…`               | Internal 68340 registers (MBAR). The serial port is at `0xFFFFF700` |

Conversion: **device address = offset in the `.bic` + `0x6000`**.

## Flash layout and checksums

Found in the 1.58 and 1.61 full dumps. The image checksum is verified for all four
versions, including the 1.35 `.bic`.
`sum16` is the 32-bit sum (mod 2³²) of the big-endian 16-bit words.

| Region | Format | Checksum |
|--------|--------|----------|
| Firmware image `0x6000` | Vector table, boot header at `0x6400`: length at `0x6414`, checksum at `0x6418` | `sum16(image[0 : len])` with the checksum field counted as 0 |
| Boot block `0x0000` | Copy of image `0x400–0x2EAF` (0x2AB0 bytes so far), field `0x0C` = unit ID, then trailer: u32 `0x2AB4`, u32 checksum | `sum16(block[0 : 0x2AB4])` |
| Data block `0x4000` | u32 length L (≤ `0x2000`, includes the length word), data, u32 CRC at `0x4000 + L` | CRC-16/XMODEM of the bytes in the high word, CRC-16/XMODEM of the bit-reversed bytes in the low word (routine at bus `0x875C`) |

| | 1.35 (`.bic`) | 1.55 (`.bic`) | 1.58 dump | 1.61 dump |
|---|---|---|---|---|
| Image length | `0x10EF88` | `0x107D8E` | `0x108012` | `0x107DCE` |
| Image checksum | `0xECAA2EF6` | `0xF30EEABF` | `0xF2095A84` | `0xF2C7306F` |
| Unit ID (boot `0x0C`, data `0x4010`) | – | – | `0x0083FD8B` = 8650123 | `0x0083FD9D` = 8650141 |

The two dumps carry different unit IDs, so they most likely come from two
different instruments. Details are in the analysis report, section 6.

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

- The script has produced two full dumps on live units. The recovery and resume paths
  were tested only against a simulated device.
- The length of the `*` window is an estimate. That is why the script sends `*` continuously.
- How the monitor responds to empty or unknown lines has not been analysed.
  The "monitor already active" check sends a CR and discards whatever comes back.
- All three checksum algorithms are known, but only the data-block check has been
  located in the code (`0x6BBE`). Where the image checksum and the boot-block trailer
  are checked is still open.
- The meaning of the data-block fields and of the unit ID is a guess.

## Reference firmware

| Property    | Value |
|-------------|-------|
| File        | `8600_155.bic` (the first editions call it `84e2587e-8600_155.bic`) |
| Size        | 1,080,718 bytes (`0x107D8E`) |
| CRC32       | `7414aad0` |
| SHA-256     | `6fe062387758c7e7c2f4313963a99a860be889aed99918fdb81e397de44f26cf` |
| Format      | Raw image of the flash range `0x6000–0x10DD8D`, no file header or trailer |
| Internal checksum | `0xF30EEABF` at `0x6418` in the boot header: `sum16` over the image with the field counted as 0 |
| CPU         | Motorola MC68340 (CPU32), big-endian |
| RTOS        | Nucleus PLUS – 68340D Version 1.11.4 |
| Identification | `(C) Giga-tronics, 1999`, `Gigatronics 8650 Universal Power Meter` |

CRC32 and SHA-256 are taken over the whole file. They only identify the file; the
firmware does not check them.

Two more versions were extracted from full dumps of live units with `extract_bic.py`.
These files contain only the firmware image, no unit-specific data (the unit ID is
in the boot block and the data block), so the same version should give the same hash
on every unit. The full-flash dumps themselves are not listed: they also contain the
unit ID and NV data and are therefore unique to each instrument.

| File | Size | Image checksum | CRC32 | SHA-256 |
|------|------|----------------|-------|---------|
| `8600_155.bic` | 1,080,718 B (`0x107D8E`) | `0xF30EEABF` | `7414aad0` | `6fe062387758c7e7c2f4313963a99a860be889aed99918fdb81e397de44f26cf` |
| `8600_158.bic` | 1,081,362 B (`0x108012`) | `0xF2095A84` | `0e8391e8` | `710b25387d8f3d6c9fb0f31984bfc7dd33d10fcf837889e063e5887f1e63c311` |
| `8600_161.bic` | 1,080,782 B (`0x107DCE`) | `0xF2C7306F` | `bd154108` | `a3ff8a682fee2b0b458a4ebf3c07edb1662087f649c959382265138a6cc06f09` |
| `8650_135.bic` (as found, padded) | 1,110,016 B (`0x10F000`) | `0xECAA2EF6` | `95af342f` | `68450fdf98da42274a459c078d8568d05118bbe41ed66ca0a69459d10972d5b2` |
| `8650_135.bic` trimmed to the length field | 1,109,896 B (`0x10EF88`) | `0xECAA2EF6` | `5d540171` | `635d38f8e8f13b4534f36198e791c1edd93672caf2d297f98bf965c0dd364359` |

`8650_135.bic` was not extracted from a dump but found as a file. It is an older
build: Nucleus PLUS 68340D Version 1.1.G1.2 (1993–1996) instead of 1.11.4, boot header
word `0x410` = `0x00010006` instead of `0x00010007`, reset PC `0x9E2E` instead of
`0x9D2A`, and different boot code. Only 44–47 % of its 16-byte blocks occur in the
8600 images. The file is padded with 120 zero bytes up to a 4 KiB multiple
(bus `0x115000`); the image checksum covers only the first `0x10EF88` bytes.
Details are in the analysis report, section 6.5.

The `.bic` is a byte-for-byte copy of the flash contents from `0x6000` onwards:

- File offset 0 is the exception vector table (initial SP `0x2D8FFC`, reset PC `0x9D2A`),
  and the firmware sets VBR = `0x6000`.
- The file size equals the image length stored in the boot header at `0x6414`, so
  nothing is appended (`8650_135.bic` is the exception: it carries 120 zero bytes of
  padding, which are not part of the image).
- The boot header at file offset `0x400` (flash `0x6400`) belongs to the firmware itself
  (jump table, length, checksum). It is not a container header of the file.

The `.bic` only covers part of the flash. The boot block (`0x0000–0x3FFF`), the data
block (`0x4000–0x5FFF`) and everything after `0x10DD8D` are missing. The 1.58 and
1.61 dumps from live units have exactly this layout at `0x6000`.

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
