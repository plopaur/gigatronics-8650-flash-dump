<!-- footer: Giga-tronics 8650 / 8600A - read first 100 bytes via HyperTerminal -->
# Reading the First 100 Bytes over Serial

Giga-tronics 8650 / 8600A service monitor - manual procedure with HyperTerminal (Windows)
Target: the first 100 bytes of `8600_155.bic` - revised 13 Oct 2026

> **Revision 13 Oct 2026.** The first edition used the addresses 0x6010 / 0x6038 / 0x6060. The image actually sits at **0x6000**, so the correct commands are `PEH06000`, `PEH06028` and `PEH06050`. The expected replies are unchanged. This edition also explains the power-on window in which the monitor accepts `*`.

## What this does

The service monitor's `PEH` ("Peek, Hex") command reads bytes from a memory address and returns them as hex text. On the running instrument the firmware image is mapped at **runtime = file offset + 0x6000**, so the start of the `.bic` file is read at address **0x6000**. Each `PEH0` command returns 40 bytes, so three commands cover 120 bytes - you keep the first 100.

## 1. HyperTerminal connection settings

| Setting | Value |
|---|---|
| Connect using | the COM port your serial cable is on (e.g. COM1) |
| Bits per second | 9600 (from the firmware's UART set-up; if no reply, retry at 19200, then 115200) |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Flow control | None |

Then open **File > Properties > Settings > ASCII Setup** and set:

- **Echo typed characters locally**: on. The monitor does not echo, so this lets you see what you type.
- **Send line ends with line feeds**: off. Enter sends a carriage return, which the monitor wants.
- **Append line feeds to incoming line ends**: optional, for tidier display.

## 2. Commands to send

Type each line exactly as shown. The commands are not case-sensitive. Press **Enter** at the end of each `PEH` line; that sends the carriage return the monitor needs. Do *not* press Enter after the `*`.

### Step 1 - wake the monitor during power-on.

The monitor only listens for `*` for a short time (estimated 1-2 s) after the power-on self-test; after that the normal instrument software starts. So:

1. Switch the instrument off and open the HyperTerminal connection.
2. Switch the instrument on and keep pressing `*` (about every half second) until a reply appears.

The instrument should reply:

```
OK 8600A
```

If it replies `ERR 8600A`, a self-test flag is set but reads still work. If nothing comes back and the instrument boots normally, the baud rate or cable is wrong (a null-modem cable may be needed). Switch off and try again. Extra `*` characters typed after the banner are ignored.

### Step 2 - read bytes 1-40. Type this and press Enter:

```
PEH06000
```

Reply (40 bytes = 80 hex characters):

```
002D8FFC00009D2A000095F6000096160000965600009636000091180000911C0000912000009124
```

### Step 3 - read bytes 41-80. Type this and press Enter:

```
PEH06028
```

Reply:

```
00009676000096960000913000009134000091380000913C0000914000009144000091480000914C
```

### Step 4 - read bytes 81-120. Type this and press Enter:

```
PEH06050
```

Reply (you only need the first 40 hex characters = bytes 81-100; the rest is extra):

```
0000915000009154000091580000915C0000916000009528000091680000916C0000917000009174
```

## 3. Command reference

| Type this | Reads address | File offset | Bytes |
|---|---|---|---|
| `PEH06000` | 0x6000 - 0x6027 | 0x00 - 0x27 | 1 - 40 |
| `PEH06028` | 0x6028 - 0x604F | 0x28 - 0x4F | 41 - 80 |
| `PEH06050` | 0x6050 - 0x6077 | 0x50 - 0x77 | 81 - 120 (keep 81-100) |

Command format: `PEH` + one count digit + address. The count digit `0` means the default 40 bytes, and `1`-`F` read 1-15 bytes. The address that follows is in hex. So `PEH06028` = "peek 40 bytes at 0x6028".

## 4. Putting the 100 bytes together

Concatenate the three replies and take the first **200 hex characters** (= 100 bytes). The result is:

```
002D8FFC 00009D2A 000095F6 00009616 00009656 00009636
00009118 0000911C 00009120 00009124 00009676 00009696
00009130 00009134 00009138 0000913C 00009140 00009144
00009148 0000914C 00009150 00009154 00009158 0000915C
00009160
```

> **Quick sanity check:** the very first 8 bytes must be `00 2D 8F FC 00 00 9D 2A` - the initial stack pointer (0x002D8FFC) and reset program counter (0x00009D2A) of the firmware. If you see those, the link, baud and address are all correct. If `PEH06000` returns `0000965600009636...` instead, you are reading 16 bytes too far (address 0x6010).

## 5. Notes

- These bytes are a table of 32-bit big-endian values (the CPU exception vectors; the firmware sets VBR = 0x6000), which is why the first 100 bytes look repetitive.
- To read file offset X of the `.bic`, peek address 0x6000 + X. Address 0x0 holds the boot block, which is not part of the `.bic`. The data block at 0x4000 (probably calibration data) is not part of it either.
- The monitor keeps accepting commands until power-off. You only need the `*` once per power-on.
- For a full automated dump rather than this manual read, use the `gt8650_dump.py` tool. Start it first and then switch the instrument on; it sends `*` by itself.
