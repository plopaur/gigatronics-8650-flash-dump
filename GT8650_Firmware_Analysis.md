<!-- footer: Giga-tronics 8650 / 8600A firmware analysis -->
# Firmware Analysis: Serial Flash Read-out

Giga-tronics 8650 Universal Power Meter (8600A series)
Image: `8600_155.bic` - static reverse-engineering report - 9 Oct 2026, revised 13 and 14 Oct 2026

> **Revision 14 Oct 2026.** Two full 2 MB flash dumps read from live units (firmware 1.58 and 1.61) were compared with the .bic. They confirm that a .bic is a raw slice of flash with no container header. All three checksums (firmware image, boot block, data block) are now decoded, and the boot block at 0x0 turns out to be a copy of the image's boot code. New section 6; all changes are listed in section 9. A fourth image, `8650_135.bic` (an older 8650 build, zero-padded), was compared as well; its image checksum matches (section 6.5).

> **Revision 13 Oct 2026.** The load base is **0x6000**, not 0x6010 as stated in the first edition. The handler addresses there are file offsets, not runtime addresses. This edition also corrects the image size and the serial port address, derives the baud rate, and describes how the monitor is entered. All changes are listed in section 8.

## 1. Summary

**Question:** does the firmware contain a command to read the contents of flash out over the serial port, given that a serial *upload* procedure is already documented?

**Answer: yes.** Alongside the normal SCPI instrument interface the firmware carries a low-level serial **service monitor** with a Peek/Poke memory interface. Its `PEH` ("Peek, Hex") command reads bytes from any address in the CPU address space and returns them as hexadecimal text. Flash is memory-mapped, so `PEH` reads it directly. There is no authentication gate on the command.

The monitor runs at power-on: after the self-test it listens for about 1-2 s for the attention byte `*`, then hands over to the instrument application. A Python dumper (`gt8650_dump.py`) was produced. It was validated offline against the supplied image, including a byte-identical full read-back from a simulated device. It has since read two complete 2 MB flash dumps from live units (firmware 1.58 and 1.61), which confirm the memory map and the .bic format (section 6).

## 2. What the image is

| Property | Finding | Evidence |
|---|---|---|
| Instrument | Giga-tronics 8650 Universal Power Meter (8600A series) | Banner strings "(C) Giga-tronics, 1999", "Gigatronics 8650 Universal Power Meter", "OK 8600A" |
| CPU / arch | Motorola MC68340 (CPU32), big-endian | LINK A6 / UNLK A6 / RTS epilogues; MOVEC, MOVES; MBAR write 0xFFFFF101 |
| RTOS | Nucleus PLUS 68340D v1.11.4 | "Copyright (c) 1993-1999 ATI - Nucleus PLUS - 68340D Version 1.11.4" |
| Image size | 1,080,718 bytes (0x107D8E) | File length; equals the length field at file 0x414 |
| File format | Raw flash image of 0x6000-0x10DD8D; no file header or trailer | File offset 0 is the vector table (SP 0x2D8FFC, PC 0x9D2A, VBR = 0x6000); file size = length field, so nothing is appended |
| File hashes | CRC32 7414aad0; SHA-256 6fe06238...44f26cf (full value in README) | Taken over the whole file; identify the file only, not checked by the firmware |
| Internal checksum | Field at file 0x418 (flash 0x6418) in the boot header: 32-bit sum of the big-endian 16-bit words over file 0 ... len-1, with the checksum field counted as 0 | Matches 1.35 and 1.55 (.bic), 1.58 and 1.61 (dumps); see sections 6.2 and 6.5 |
| Load mapping | runtime = file_offset + 0x6000 | VBR is set to 0x6000; cross-checked 5 ways (see sect. 5) |
| Flash | CS0 0x000000-0x0FFFFF, CS1 0x100000-0x1FFFFF | Chip-select table at file 0x301A |
| RAM | CS2 0x200000-0x2FFFFF (initial SP 0x2D8FFC, reset code sets 0x2FFFF0) | Chip-select table; RAM test 0x200000-0x2FFFFF |
| Serial UART | MC68340 on-chip serial module, channel A at 0xFFFFF700 | Absolute-short `$F711.w` / `$F713.w` sign-extend to 0xFFFFF711 (SRA) / 0xFFFFF713 (RBA/TBA) |
| Monitor line settings | 9600 baud, 8N1 | UART init at file 0x1774: CSR 0xBB, ACR 0x80, MR1 0x93, MR2 0x07 |

## 3. Method

- Classified the image and extracted ASCII / big-endian strings; swept for memory / flash / dump / upload vocabulary.
- Recognised the m68k/CPU32 code and mapped the SCPI command parse-tree (no raw-flash read command there).
- Disassembled with Capstone (M68K, big-endian) to locate and decode the serial service monitor.
- Resolved PC-relative string cross-references (base-independent) to label handlers.
- Pinned the absolute load base from the VBR setup, the reset vector, the exception-vector stub table, the exception vectors and the self-relocation code.
- Followed the boot path from the image header into the monitor, and decoded the chip-select and UART initialisation.
- Decoded the command dispatch and the Peek/Poke handlers; characterised the on-wire framing end to end.
- Wrote a dump tool and validated it against a simulated monitor (power-on window, active monitor, full read-back).

## 4. The serial service monitor

Entered by sending the attention byte `*` during the power-on window (section 6). The monitor replies `OK 8600A`, or `ERR 8600A` if the power-on self-test flagged a fault. Reads still work after `ERR 8600A`.

It then stays in a loop reading CR- or LF-terminated lines (ESC discards the line, backspace edits, `*` is ignored). Each line is upper-cased and dispatched on its first letter through a 26-entry jump table at file offset 0x12B0. The `P` command branches further into Peek (`PE*`) and Poke (`PO*`) families.

Addressing note: all handler locations below are **file offsets** in `8600_155.bic`. The monitor executes from a RAM copy, so add 0x2FBC00 for the RAM address (file - 0x400 + 0x2FC000), or 0x6000 for the flash address.

### 4.1 Memory read (Peek) commands

| Command | Handler (file offset) | Action |
|---|---|---|
| PEH &lt;n&gt;&lt;addr&gt; | 0x1A88 | Read n bytes from addr, return as uppercase hex (the flash-dump command) |
| PEA &lt;n&gt;&lt;addr&gt; | 0x1B48 | Read bytes from addr, return as a null-terminated ASCII string |
| PEU / PES / PED &lt;sz&gt;&lt;addr&gt; | 0x1BE4 / 0x1CD0 / 0x1DBC | Read one value, print as decimal |
| POH / POA / POU / POS / POD | 0x1E60 / 0x1F24 / 0x1FC4 / 0x2090 / ... | Poke - WRITE values into memory (used by the upload/program path) |

`<n>` is a single hex digit (1-F); `0` selects the default of 0x28 = 40 bytes. `<addr>` is a 32-bit hex address; spaces are skipped. The command is dispatched directly - no unlock or password is required.

### 4.2 On-wire exchange for a hex read

```
host -> *                      (attention, during power-on window)
dev  -> OK 8600A<CR><LF>       (banner)
host -> PEH06000<CR>           count '0' = 40 bytes, addr 0x6000
dev  -> 002D8FFC00009D2A...<CR><LF>   80 hex chars = 40 bytes
```

Nibble encoding is uppercase (encoder at file 0x2328). The reply is built in the line buffer and sent with CR+LF appended by the put-string routine at file 0x18D4. Command echo is off by default. `E1` turns it on and `E0` turns it off (handler at file 0x136C).

## 5. Load base and memory map

The image is linked for **0x6000**. Evidence:

- The application start-up code executes `MOVE.L #$6000,D0 / MOVEC D0,VBR` (file 0x303A). The vector table at file offset 0 is therefore the live table at 0x6000.
- The reset vector 0x9D2A maps to file 0x3D2A, which is `MOVEA.L #$2FFFF0,A7 / MOVEA.L #$2C4768,A5 / JSR $8FA6`. 0x8FA6 (file 0x2FA6) is `MOVE.W #$2700,SR / MOVEC ... DFC`, the classic CPU32 cold-start sequence. With base 0x6010 both land in the middle of instructions.
- The 254 BSR.W exception stubs (stride 4) start at file 0x3108 = runtime 0x9108. The common handler they branch to computes the vector number with `SUB.L #$9108,D7`.
- The bus-, address-error, illegal and zero-divide vectors (0x95F6, 0x9616, 0x9656, 0x9636) all land on identical handler prologues (`ORI.W #$700,SR / MOVEM.L D0-D7/A0-A6,-(A7)`).
- The image contains self-relocation code linked at 0x6000 (`MOVEA.L #$6414,A0 / SUBA.L #$6000,A0 ...`).

Consequence for dumping: the bytes of this image appear on the bus at **0x00006000 ... 0x0010DD8D**.

| Range | Contents |
|---|---|
| 0x000000-0x003FFF | Boot block: copy of the image's boot code with a checksum trailer; the CPU resets into it (not part of the .bic; section 6.3) |
| 0x004000-0x005FFF | Data block with length + CRC, checked at boot (unit data; not part of the .bic; section 6.4) |
| 0x006000-0x0063FF | Exception vector table (VBR = 0x6000) |
| 0x006400-0x10DD8D | Boot header from 0x6400 (layout as for 1.55; the end address depends on the version) (SP, jump to boot entry (0x6408), image length 0x107D8E (0x6414), checksum (0x6418), application entry (0x641C), monitor entry (0x6420)), followed by application code and data |
| 0x1E0000-0x1E0FFF | Non-volatile measurement/settings data (seen in the dumps; differs between units) |
| 0x200000-0x2FFFFF | RAM; the monitor runs from a copy at 0x2FC000 |
| 0x800000- | Peripherals (CS3) |
| 0xFFFFF000- | MC68340 on-chip modules (MBAR) |

The boot header is part of the firmware, not a container header of the .bic file. A dump from 0x000000 to 0x1FFFFF captures both flash chip-selects. That includes the boot block and the data block, which are not in the .bic.

## 6. Full flash dumps (firmware 1.58 and 1.61)

Two complete dumps (`--start 0 --length 0x200000`) were read from live units with `gt8650_dump.py`: `full_firmware_1_58.bin` and `full_firmware_1_61.bin`. They were compared with `8600_155.bic`.

### 6.1 Flash layout found

| Range (1.58) | Content |
|---|---|
| 0x000000-0x002AB7 | Boot block (0x2AB0 bytes of code + 8-byte trailer), rest up to 0x3FFF erased (FF) |
| 0x004000-0x004017 | Data block (length 0x14 + CRC), rest up to 0x5FFF erased |
| 0x006000-0x10E011 | Firmware image 1.58 (0x108012 bytes); 1.61 ends at 0x10DDCD (0x107DCE bytes) |
| up to 0x10EFFF | 00 padding, then erased up to 0x1DFFFF |
| 0x1E0000-0x1E0783 | NV measurement/settings data (starts `FFFFFFFE 00AE0300 A5A5 ...`) |
| rest | erased |

### 6.2 Firmware image = .bic

The image at 0x6000 has exactly the .bic structure. Cutting out `flash[0x6000 : 0x6000 + len]` (len from 0x6414) gives a valid .bic for that version; `extract_bic.py` does this. The extracted images hold no unit-specific data, so their hashes identify the version (full values in the README):

| File | Size | SHA-256 |
|---|---|---|
| `8600_158.bic` | 1,081,362 B | 710b2538...1e63c311 |
| `8600_161.bic` | 1,080,782 B | a3ff8a68...6cc06f09 |

- The vector table (0x6000-0x63FF) is byte-identical in 1.55, 1.58 and 1.61.
- The boot header has the same layout. Only the length (0x414), the checksum (0x418) and the target of the `JMP` at 0x42C differ:

| Field | 1.55 (.bic) | 1.58 | 1.61 |
|---|---|---|---|
| Length @0x414 | 0x107D8E (= file size) | 0x108012 | 0x107DCE |
| Checksum @0x418 | 0xF30EEABF | 0xF2095A84 | 0xF2C7306F |

- **Image checksum:** `sum16(image[0 : len])` with the 4 checksum bytes counted as 0, where `sum16` is the 32-bit sum (mod 2^32) of the big-endian 16-bit words. It matches all three versions. The routine that checks it at run time has not been located; the boot path itself only tests the field for zero (0x6D32).
- About 70 % of the 16-byte blocks of 1.58 and 1.61 occur verbatim in 1.55: same toolchain and Nucleus PLUS 1.11.4; the rest is shifted code.
- The CRC tables used for the data block (file 0x2A48-0x2D47) are identical in all three versions.

### 6.3 Boot block at 0x0000

- Bytes 0x0000-0x2AAF are a copy of image offset 0x400-0x2EAF (the boot header and boot/monitor code). The only difference is the field at 0x000C, which is 0 in the image.
- **Field 0x000C:** 0x0083FD8B = 8650123 (1.58 dump) and 0x0083FD9D = 8650141 (1.61 dump). The same value is stored in the data block. It looks like a unit ID or serial number ("8650" + number), so the two dumps most likely come from two different units.
- **Trailer** at 0x2AB0: u32 0x00002AB4 (= offset of the checksum), then u32 `sum16(block[0 : 0x2AB4])`, i.e. a checksum over the code and the length word. Verified in both dumps. The routine that checks it has not been located.
- **The CPU resets into this block.** The vectors at 0x0 are the copied header: SP 0x2F8000, PC 0x0008. The `JMP` at 0x0008 is PC-relative, so it lands at 0x0454, which is the code at 0x6854 in the image. The monitor copy at 0x6C08 also reads from 0x0000 (it uses 0x6400 only when the flag byte 0x213E81 is set, and both boot paths clear it). The boot block therefore carries the monitor that answers `PEH`. Because the code is position-independent, the analysis of the image applies to it unchanged.
- The 1.58 and 1.61 boot blocks differ in 2 code bytes (0x94E-0x94F) besides field 0x0C and the checksum. The boot block therefore follows the installed firmware version; presumably the upload procedure rewrites it.

### 6.4 Data block at 0x4000

Format: u32 length L (at most 0x2000, counted from 0x4000 and including the length word), data, then u32 CRC at 0x4000 + L over `[0x4000, 0x4000 + L)`. The boot code checks it (0x6BBE) via the routine at 0x875C:

- High word: CRC-16/XMODEM (polynomial 0x1021, init 0, not reflected) over the bytes, using the table at 0x8A48.
- Low word: the same CRC over the bit-reversed bytes (substitution table at 0x8C48).

Verified for both dumps (0xF6F981AC and 0x840E6C02). Content in both units, L = 0x14:

| Offset | Value | Possible meaning (not proven) |
|---|---|---|
| 0x4004 | 0x00010000 | format/version |
| 0x4008 | 0x00002198 = 8600 | model family 8600 |
| 0x400C | 0x41000000 | 8.0 as IEEE float |
| 0x4010 | 0x0083FD8B / 0x0083FD9D | unit ID, same as boot block 0x000C |

At boot the block is also copied to RAM 0x200000 (0x6D22).

### 6.5 Firmware 1.35 (`8650_135.bic`)

A further image, `8650_135.bic`, was found as a file (not read from a unit). The version 1.35 is taken from the file name.

- **Checksum:** length field @0x414 = 0x10EF88, checksum @0x418 = 0xECAA2EF6. `sum16(image[0 : 0x10EF88])` with the field counted as 0 gives the same value, so the image is intact and uses the same algorithm as 1.55-1.61.
- **Padding:** the file is 0x10F000 bytes, i.e. the image plus 120 zero bytes up to a 4 KiB multiple (bus 0x115000). The checksum does not cover the padding. `extract_bic.py` accepts such a file as a .bic (less than 4 KiB of zero padding after the length) and removes the padding with `-o`. Trimmed: 1,109,896 B, SHA-256 635d38f8...dd364359.
- **Older build:** Nucleus PLUS "68340D Version 1.1.G1.2" (1993-1996) instead of 1.11.4; the 1.55 string "Engineering Version 0000.00" is missing.
- **Header:** same layout. The word at 0x410 is 0x00010006 (0x00010007 in 1.55-1.61). The `JMP` targets at 0x42C and 0x432 differ (0x19550, 0x18CF8).
- **Vector table:** identical to 1.55 except the reset PC at 0x004 (0x9E2E instead of 0x9D2A).
- **Boot code** 0x430-0x2EAF differs from 1.55. Because the boot block at flash 0x0 is a copy of this range (section 6.3), installing 1.35 on a unit would also need a matching boot block. The CRC tables at 0x2A48-0x2D47 are identical.
- **Similarity:** only 47 % (1.55, 1.58) and 44 % (1.61) of its 16-byte blocks occur verbatim in the 8600 images.

## 7. Entering the monitor

The boot path (addresses from 0x6000 upward lie in the image; subtract 0x6000 for the file offset). After a reset the CPU runs the identical copy in the boot block (section 6.3), where every address below is 0x6400 lower:

1. Boot entry 0x6408 jumps to 0x6854: SIM/chip-select initialisation, then a RAM pattern test over 0x200000-0x2FFFFF.
2. If the RAM test passes, the data block at 0x4000 is checked (length at 0x4000, at most 0x2000; CRC, section 6.4). The result is stored as a fault code: 0x10 = RAM fault, 0x04 = data-block fault.
3. 16 KB of monitor code is copied from the boot block at 0x0 to RAM at 0x2FC000 and entered at 0x71C4 (RAM 0x2FCDC4).
4. The monitor initialises channel A to 9600 8N1 and polls for a received byte with a 0xFFFFF-iteration timeout (estimated 1-2 s).
5. If `*` arrives, it prints the banner and enters the command loop. On a timeout with no fault, it starts the instrument application (0x641C). With a fault it keeps waiting for `*`.

The practical procedure is to send `*` repeatedly while switching the instrument on. Bytes sent before the UART initialisation are discarded, because that initialisation resets the receiver. Once the monitor is in its command loop it ignores further `*` characters, so a host can tell an active monitor apart by sending a `PEH` command.

## 8. Deliverables: gt8650_dump.py and extract_bic.py

A self-contained Python 3 tool (pyserial) that drives the monitor and reassembles a binary:

- Detects an already active monitor via a test `PEH`; otherwise sends `*` repeatedly (up to `--wait`, default 60 s) until the `8600A` banner arrives, so the user can start the script and then power the unit on.
- Reads in 40-byte blocks via `PEH0<addr>`, parses the hex reply, retries on short or garbled lines, and shows progress with an ETA.
- Supports arbitrary `--start` / `--length`. The default start is 0x6000, and `--base` overrides the mapping. Without `--length` (and without `--verify`) the image length is read from the device's boot header at 0x6414, so the installed firmware is dumped exactly, whatever its version.
- Every block is flushed to disk; on link errors it resyncs, reopens the port or asks for a power-cycle, and a re-run resumes an interrupted dump.
- **Self-check:** after the dump it verifies the checksums of every region the dump fully covers (boot block, data block, firmware image). No reference file is needed; a failed check ends with exit code 3.
- `--verify` compares the part of the dump that overlaps a reference .bic placed at the base address. This only makes sense for the same firmware version.
- `--probe` reads 0x0, 0x4000 and 0x6000, shows the image length and checksum from the boot header, checks the data-block CRC, and confirms the mapping against the reference if one is given.

`extract_bic.py` (no dependencies; imported by the dumper for the checksum code) checks a dump offline and writes the firmware image as a .bic. Given a .bic it only checks the image checksum; a .bic with less than 4 KiB of zero padding after the image (such as `8650_135.bic`) is also recognised, and `-o` writes it without the padding.

### Typical use:

```
# start the script, then switch the instrument on
python3 gt8650_dump.py -p /dev/ttyUSB0 --probe

# dump the installed firmware image (length from the device, self-checked)
python3 gt8650_dump.py -p /dev/ttyUSB0 -o firmware.bin

# whole flash incl. boot block and data block, then cut out the .bic
python3 gt8650_dump.py -p /dev/ttyUSB0 --start 0 --length 0x200000 \
        -o flash_full.bin
python3 extract_bic.py flash_full.bin -o 8600_158.bic
```

At 9600 baud one 40-byte block costs about 92 characters on the wire, so throughput is at most about 400 B/s. Even at that rate the image takes about 45 min and the full 2 MB flash about 85 min.

## 9. Changes

### Revision 14 Oct 2026

| Before | Now |
|---|---|
| Image checksum: algorithm unknown | 32-bit sum of 16-bit words over the image, checksum field as 0 |
| Data block checksum: algorithm unknown | Two CRC-16/XMODEM (bytes and bit-reversed bytes), stored after the block |
| Boot block contents unknown | Copy of image 0x400-0x2EAF plus unit ID and sum16 trailer; reset and monitor run from it |
| Dumper needs a .bic for length and verification | Length from the device header; checksum self-check without a reference |
| .bic size always equals the length field | `8650_135.bic` (1.35) carries 120 zero bytes of padding; `extract_bic.py` and `--verify` handle it |

### Revision 13 Oct 2026 (changes from the first edition, 9 Oct 2026)

| First edition | Corrected |
|---|---|
| runtime = file_offset + 0x6010 | runtime = file_offset + 0x6000 (VBR, reset vector, stub table, exception vectors, self-relocation code) |
| Image size 0x107ECE; bus range 0x6010-0x10DEDE | Image size 0x107D8E; bus range 0x6000-0x10DD8D |
| Jump table "at runtime 0x12B0"; handlers 0x1A88 etc. | These are file offsets; RAM copy at +0x2FBC00, flash at +0x6000 |
| DUART at 0x00F700 | MC68340 on-chip serial module at 0xFFFFF700 |
| Baud rate cannot be computed | 9600 8N1 from the UART initialisation (standard 3.6864 MHz clock assumed) |
| Monitor loop has no locatable caller | Boot path 0x6408 -> 0x6854 -> 0x6C08 -> RAM copy; `*` window at power-on |
| PEH0 6010 / dumper default 0x6010 | PEH0 6000 / dumper default 0x6000 |

## 10. Open items and caveats

- **Live confirmation.** The PEH read path, the 0x6000 mapping and the 9600 8N1 settings are confirmed by the two full dumps from live units (section 6), whose checksums all match.
- **Power-on window.** The 1-2 s figure is an estimate from the poll loop; the dumper therefore sends `*` continuously.
- **Checksum consumers.** The algorithms of all three checksums are known and verified. Only the data-block CRC check has been located in the code (0x6BBE); where the image checksum and the boot-block trailer are checked (probably by the application or the upload procedure) is still open.
- **Data block meaning.** The interpretation of the data-block fields and of the unit ID is a guess.
- **Baud clock.** 9600 baud assumes the standard 3.6864 MHz serial clock; if no banner appears, try 19200 and 115200.
