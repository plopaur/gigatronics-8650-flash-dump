#!/usr/bin/env python3
"""
gt8650_dump.py  --  Dump memory/flash from a Giga-tronics 8650 / 8600A-series
                    power meter over its serial SERVICE MONITOR, using the
                    built-in PEH ("Peek, Hex") command.

Reverse-engineered from firmware 8600_155.bic (Motorola 68340 / CPU32, m68k).
See README.md for details.

PROTOCOL (verified in the firmware):
  * The monitor speaks 9600 8N1 (CSR=0xBB, ACR=0x80, MR1=0x93, MR2=0x07).
  * The monitor only listens for its attention char right after power-on:
    after the RAM self-test it waits ~1-2 s for '*', otherwise the normal
    instrument application starts.  '*' -> "OK 8600A\r\n"
    (or "ERR 8600A" if the self-test flagged a fault; dumping still works).
  * After that it stays in a command loop reading CR/LF-terminated lines and
    ignores any further '*'.  Commands are case-insensitive.
  * Memory read:   PEH <count><addr>
        - <count> is ONE hex digit (1..F). '0' selects the default of
          0x28 = 40 bytes. So "PEH0<ADDR>" returns 40 bytes.
        - <addr>  is a hex address in the CPU address space.
        - Reply:  <2*N uppercase hex chars>\r\n   (no "OK" prefix, no spaces)
  * Memory map:
        runtime_address = file_offset + 0x6000   (firmware sets VBR = 0x6000)
        Flash CS0 0x000000-0x0FFFFF, CS1 0x100000-0x1FFFFF, RAM 0x200000-0x2FFFFF.
        0x0000-0x3FFF boot block, 0x4000-0x5FFF data block (not in the .bic).
  * Boot header at runtime 0x6400: image length @0x6414, checksum @0x6418
    (see extract_bic.py for the checksum algorithms).

USAGE EXAMPLES
  # Start the script, THEN switch the instrument on (it keeps sending '*').
  # Without --length the image length is read from the device's boot header,
  # so this dumps exactly the installed firmware, whatever its version:
  python3 gt8650_dump.py -p /dev/ttyUSB0 -o firmware.bin

  # Same, and also compare against a reference .bic of the same version:
  python3 gt8650_dump.py -p /dev/ttyUSB0 -o firmware.bin --verify 8600_155.bic

  # Quick probe: confirm link + mapping before a long dump
  python3 gt8650_dump.py -p /dev/ttyUSB0 --probe --verify 8600_155.bic

  # Whole 2 MB flash including boot block and data block:
  python3 gt8650_dump.py -p /dev/ttyUSB0 --start 0 --length 0x200000 \
        -o flash_full.bin

SELF-CHECK
  After every dump the checksums of all regions the dump fully covers are
  checked (boot block, data block, firmware image), so no reference .bic is
  needed.  extract_bic.py cuts the firmware image out of a full dump.

RESUME / RECOVERY
  Every block is flushed to disk.  If the monitor stops answering, the script
  escalates automatically: soft resync -> reopen the serial port -> re-handshake
  with a power-cycle prompt, then continues at the same address.  If it gives up
  (or you press Ctrl-C), just run the SAME command again: an existing output file
  is resumed (its tail is checked against the device first).  --restart overwrites.

If the monitor is already active (e.g. after an earlier run without power
cycling), the script detects that and skips the '*' handshake.
Needs: pip install pyserial, and extract_bic.py next to this script.
"""
import os, sys, time, argparse, binascii

from extract_bic import (check_flash, check_data, u32, HDR, LEN_OFF, CK_OFF,
                         DATA_BASE)

try:
    import serial  # pyserial
except ImportError:
    sys.exit("pyserial not installed.  Run:  pip install pyserial")

DEFAULT_BYTES = 0x28          # 40 bytes per PEH when count digit = '0'
BASE_OFFSET   = 0x6000        # runtime = file_offset + 0x6000
STAR_INTERVAL = 0.1           # seconds between '*' while waiting for power-on

def open_port(port, baud, rtimeout):
    return serial.Serial(port=port, baudrate=baud, bytesize=8,
                         parity='N', stopbits=1, timeout=rtimeout)

def read_line(ser, deadline):
    """Read until CR or LF; return the stripped line (bytes)."""
    buf = bytearray()
    while time.time() < deadline:
        c = ser.read(1)
        if not c:
            continue
        if c in (b'\r', b'\n'):
            if buf:
                return bytes(buf)
            # swallow a lone CR/LF (CRLF pair) and keep going
            continue
        buf += c
    return bytes(buf)  # whatever we got (may be partial/empty on timeout)

def monitor_active(ser, base):
    """True if the monitor is already in its command loop (answers PEH)."""
    ser.write(b'\r')                  # terminate any partial line on the device
    ser.flush()
    time.sleep(0.3)
    ser.reset_input_buffer()
    try:
        peek(ser, base, retries=1)
        return True
    except IOError:
        return False

def handshake(ser, wait, base):
    """Get the monitor into its command loop. Returns True on success."""
    if monitor_active(ser, base):
        print("[*] monitor already active, skipping '*' handshake",
              file=sys.stderr)
        return True
    print(f"[*] sending '*' for up to {wait:.0f} s -- switch the instrument "
          "on now", file=sys.stderr)
    ser.reset_input_buffer()
    buf = bytearray()
    deadline = time.time() + wait
    while time.time() < deadline:
        ser.write(b'*')
        ser.flush()
        t_next = time.time() + STAR_INTERVAL
        while time.time() < t_next:
            buf += ser.read(ser.in_waiting or 1)
        if b'8600A' in buf:
            break
    else:
        print("[!] No '... 8600A' banner. Wrong baud, cable, or the '*' did not "
              "reach the monitor within its power-on window.", file=sys.stderr)
        return False
    time.sleep(0.2)                   # let the banner's CR/LF arrive
    buf += ser.read(ser.in_waiting)
    txt = buf.decode('latin1', 'replace')
    banner = next(l for l in txt.splitlines() if '8600A' in l).strip()
    print(f"[*] banner: {banner!r}", file=sys.stderr)
    if 'ERR' in banner:
        print("[!] Self-test flagged a fault (ERR 8600A); reads still work.",
              file=sys.stderr)
    ser.reset_input_buffer()
    return True

def peek(ser, addr, retries=4):
    """Read DEFAULT_BYTES (40) bytes at addr via PEH0<addr>. Returns bytes."""
    cmd = b'PEH0%X\r' % addr          # count '0' -> 40 bytes
    line = b''
    for attempt in range(retries):
        ser.reset_input_buffer()
        ser.write(cmd)
        ser.flush()
        line = read_line(ser, time.time() + 2.0)
        s = line.strip()
        # strip anything non-hex the device might have echoed
        s = bytes(ch for ch in s if ch in b'0123456789ABCDEFabcdef')
        if len(s) == DEFAULT_BYTES * 2:
            try:
                return binascii.unhexlify(s)
            except binascii.Error:
                pass
        time.sleep(0.03 * (attempt + 1))
    raise IOError(f"bad/short reply at {addr:#08x}: {line!r}")

def soft_resync(ser, addr):
    """Flush the monitor's line buffer (ESC discards the line, CR ends it)
    and check that it answers PEH again.  Returns the block or raises IOError."""
    ser.reset_output_buffer()
    ser.write(b'\x1b\r\r')
    ser.flush()
    time.sleep(0.5)
    ser.reset_input_buffer()
    return peek(ser, addr, retries=2)

def reopen_port(ser, timeout=30.0):
    """Close and reopen the serial port (cures USB-serial adapter hiccups).
    Waits up to `timeout` s if the adapter has temporarily disappeared."""
    try:
        ser.close()
    except Exception:
        pass
    time.sleep(1.0)
    deadline = time.time() + timeout
    while True:
        try:
            ser.open()
            return
        except (OSError, serial.SerialException):
            if time.time() > deadline:
                raise
            time.sleep(1.0)

def recover(ser, addr, args, err):
    """The monitor stopped answering at `addr`.  Escalate until it talks again:
         1. soft resync (ESC/CR, flush buffers)
         2. close + reopen the serial port
         3. re-handshake: send '*' and ask the user to power-cycle the unit
    Returns the 40-byte block at `addr`; raises RuntimeError when giving up."""
    print(f"\n[!] {err}", file=sys.stderr)
    for n in range(1, args.max_recoveries + 1):
        try:
            if n == 1:
                print(f"[*] recovery {n}: soft resync ...", file=sys.stderr)
            elif n == 2:
                print(f"[*] recovery {n}: reopening serial port ...",
                      file=sys.stderr)
                reopen_port(ser)
            else:
                print(f"[*] recovery {n}: monitor not responding -- POWER-CYCLE "
                      f"the instrument now (waiting up to {args.wait:.0f} s)\a",
                      file=sys.stderr)
                if not ser.is_open:
                    reopen_port(ser)
                if not handshake(ser, args.wait, args.base):
                    continue
            block = soft_resync(ser, addr)
            print(f"[+] link restored, continuing at {addr:#08x}", file=sys.stderr)
            return block
        except (IOError, OSError) as e:      # SerialException is an IOError
            print(f"[!] recovery {n} failed: {e}", file=sys.stderr)
    raise RuntimeError(f"giving up at {addr:#08x} after "
                       f"{args.max_recoveries} recovery attempts")

def prepare_resume(ser, start, length, out_path, restart):
    """Decide where to (re)start.  Returns number of bytes already on disk."""
    if restart or not os.path.exists(out_path):
        return 0
    have = os.path.getsize(out_path)
    if have == 0:
        return 0
    if have > length:
        sys.exit(f"{out_path} is already {have} bytes, larger than the requested "
                 f"{length}.  Use --restart to overwrite it.")
    # sanity check: re-read the tail of the existing file from the device
    tail_len = min(DEFAULT_BYTES, have)
    tail_addr = start + have - tail_len
    with open(out_path, 'rb') as f:
        f.seek(have - tail_len)
        old = f.read(tail_len)
    new = peek(ser, tail_addr)[:tail_len]
    if new != old:
        sys.exit(f"[!] {out_path} does not match the device at {tail_addr:#08x} "
                 "(different instrument/start address?).  Use --restart to "
                 "overwrite it.")
    print(f"[*] RESUMING: {have} bytes already in {out_path} "
          f"(tail verified against device)", file=sys.stderr)
    return have

def dump(ser, start, length, out_path, args):
    end = start + length
    have = prepare_resume(ser, start, length, out_path, args.restart)
    addr = start + have
    t0, done0, blocks, recoveries = time.time(), have, 0, 0
    with open(out_path, 'r+b' if have else 'wb') as f:
        f.seek(have)
        f.truncate()
        while addr < end:
            try:
                block = peek(ser, addr, retries=args.retries)   # 40 bytes
            except IOError as e:
                recoveries += 1
                block = recover(ser, addr, args, e)
            take = min(DEFAULT_BYTES, end - addr)
            f.write(block[:take])
            f.flush()                       # every block is safe on disk
            addr += take
            blocks += 1
            done = addr - start
            if blocks % 25 == 0 or addr >= end:
                elapsed = max(1e-3, time.time() - t0)
                rate = (done - done0) / elapsed
                pct = 100.0 * done / length
                eta = (length - done) / max(rate, 1e-3)
                print(f"\r[+] {done}/{length} bytes ({pct:5.1f}%)  "
                      f"{rate:6.0f} B/s  ETA {eta/60:5.1f} min  @ {addr:#08x}",
                      end='', file=sys.stderr)
    print(file=sys.stderr)
    if recoveries:
        print(f"[*] {recoveries} link recoveries during this run", file=sys.stderr)
    with open(out_path, 'rb') as f:
        return f.read()

def verify(data, start, ref_path, base):
    """Compare the part of the dump that overlaps the reference image.
    The reference occupies [base, base + len(ref)) on the bus."""
    ref = open(ref_path, 'rb').read()
    lo = max(start, base)
    hi = min(start + len(data), base + len(ref))
    if lo >= hi:
        print(f"[!] dump {start:#08x}..{start+len(data):#08x} does not overlap "
              f"{ref_path} at {base:#08x}; nothing verified.", file=sys.stderr)
        return
    d = data[lo - start:hi - start]
    r = ref[lo - base:hi - base]
    if d == r:
        print(f"[+] VERIFY OK: {hi-lo} bytes at {lo:#08x}..{hi-1:#08x} match "
              f"{ref_path}", file=sys.stderr)
    else:
        i = next(i for i in range(len(d)) if d[i] != r[i])
        print(f"[!] VERIFY MISMATCH: first diff at bus address {lo+i:#08x} "
              f"(ref offset {lo-base+i:#x})", file=sys.stderr)

def self_check(data, start, base):
    """Check the checksums of every flash region the dump fully covers."""
    results = check_flash(data, start, base)
    if not results:
        print("[*] self-check: dump covers no complete boot block, data block "
              "or firmware image", file=sys.stderr)
    for name, ok, msg in results:
        print(f"[{'+' if ok else '!'}] self-check {name}: {msg}", file=sys.stderr)
    return all(ok for _, ok, _ in results)

def image_length(ser, base):
    """Image length from the boot header on the device (bus base + 0x414)."""
    hdr = peek(ser, base + HDR)
    return u32(hdr, LEN_OFF - HDR), u32(hdr, CK_OFF - HDR)

def do_probe(ser, ref, base):
    for a in (0x00000000, DATA_BASE, base):
        try:
            b = peek(ser, a)[:16]
            print(f"  {a:#08x}: {b.hex(' ')}", file=sys.stderr)
        except IOError as e:
            print(f"  {a:#08x}: {e}", file=sys.stderr)
    try:
        length, ck = image_length(ser, base)
        print(f"[*] boot header @{base + HDR:#x}: image length {length:#x} "
              f"(bus {base:#x}..{base + length - 1:#x}), checksum {ck:#010x}",
              file=sys.stderr)
        blk = peek(ser, DATA_BASE)
        if u32(blk, 0) + 4 <= len(blk):
            ok, msg = check_data(blk)
            print(f"[{'+' if ok else '!'}] data block @{DATA_BASE:#x}: {msg}",
                  file=sys.stderr)
    except IOError as e:
        print(f"[!] header read failed: {e}", file=sys.stderr)
    if ref:
        data = open(ref, 'rb').read()
        live = peek(ser, base)
        if live == data[:DEFAULT_BYTES]:
            print(f"[+] {base:#x} matches .bic byte 0 -> mapping CONFIRMED.",
                  file=sys.stderr)
        else:
            print(f"[!] {base:#x} live {live[:16].hex()} != .bic {data[:16].hex()} "
                  "-- different firmware or base; try --base.", file=sys.stderr)

def main():
    ap = argparse.ArgumentParser(description="Dump 8650/8600A flash via serial PEH")
    auto = lambda x: int(x, 0)
    ap.add_argument('-p', '--port', required=True)
    ap.add_argument('-b', '--baud', type=int, default=9600)
    ap.add_argument('--start', type=auto, default=None,
                    help="start address (default: --base)")
    ap.add_argument('--length', type=auto, default=0,
                    help="bytes to read (default: up to the end of the "
                         "firmware image, from --verify or the device header)")
    ap.add_argument('--base', type=auto, default=BASE_OFFSET,
                    help="bus address of .bic byte 0 (default 0x6000)")
    ap.add_argument('-o', '--out', default='dump.bin')
    ap.add_argument('--verify', metavar='REF.bic',
                    help="compare dump (or probe) against a reference image")
    ap.add_argument('--probe', action='store_true',
                    help="read a few bytes and confirm link/mapping, then exit")
    ap.add_argument('--wait', type=float, default=60.0,
                    help="seconds to keep sending '*' while waiting for "
                         "power-on (default 60)")
    ap.add_argument('--read-timeout', type=float, default=0.25)
    ap.add_argument('--restart', action='store_true',
                    help="overwrite an existing output file instead of resuming it")
    ap.add_argument('--retries', type=int, default=4,
                    help="PEH retries per block before recovery starts (default 4)")
    ap.add_argument('--max-recoveries', type=int, default=6,
                    help="recovery attempts per failure before giving up "
                         "(default 6; #3 and later ask for a power-cycle)")
    args = ap.parse_args()
    start = args.base if args.start is None else args.start

    ser = open_port(args.port, args.baud, args.read_timeout)
    try:
        if not handshake(ser, args.wait, args.base):
            sys.exit(2)
        if args.probe:
            do_probe(ser, args.verify, args.base)
            return
        length = args.length
        if length == 0:
            if args.verify:
                length = args.base + len(open(args.verify, 'rb').read()) - start
                if length <= 0:
                    sys.exit("--start lies beyond the reference image; "
                             "specify --length.")
                print(f"[*] --length from {args.verify}: {length} bytes",
                      file=sys.stderr)
            else:
                img_len, _ = image_length(ser, args.base)
                length = args.base + img_len - start
                if not 0x420 <= img_len <= 0x1FA000 or length <= 0:
                    sys.exit(f"implausible image length {img_len:#x} in the "
                             "device's boot header (or --start beyond it); "
                             "specify --length.")
                print(f"[*] --length from the device's boot header: image "
                      f"{img_len:#x} bytes -> {length} bytes to read",
                      file=sys.stderr)
        print(f"[*] dumping {length} bytes from {start:#08x} -> {args.out}",
              file=sys.stderr)
        try:
            data = dump(ser, start, length, args.out, args)
        except (KeyboardInterrupt, RuntimeError) as e:
            have = os.path.getsize(args.out) if os.path.exists(args.out) else 0
            print(f"\n[!] stopped ({e or 'Ctrl-C'}) -- {have} bytes saved in "
                  f"{args.out}.\n    Re-run the same command to resume at "
                  f"{start + have:#08x}.", file=sys.stderr)
            sys.exit(1)
        ok = self_check(data, start, args.base)
        if args.verify:
            verify(data, start, args.verify, args.base)
        if not ok:
            sys.exit(3)
    finally:
        ser.close()

if __name__ == '__main__':
    main()
