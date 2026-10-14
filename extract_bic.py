#!/usr/bin/env python3
"""
extract_bic.py  --  Check a Giga-tronics 8650 / 8600A flash dump and cut the
                    firmware image (.bic) out of it.

A .bic file is a raw slice of flash: bus 0x6000 .. 0x6000 + len, where `len`
is the length field of the boot header at image offset 0x414.  There is no
container header, so the extracted file is byte-identical to a .bic.

Flash layout and checksums (verified on 1.55 .bic, 1.58 and 1.61 dumps):

  0x000000  Boot block: copy of image[0x400 : 0x400+N] (the boot/monitor code
            the CPU resets into), field 0x0C patched with the unit ID, then
            trailer  u32 N+4, u32 sum16(block[0 : N+4]).   N = 0x2AB0 so far.
  0x004000  Data block: u32 len (<= 0x2000), data, then u32 CRC at 0x4000+len
            over [0x4000, 0x4000+len).  CRC = CRC-16/XMODEM(bytes) << 16
            | CRC-16/XMODEM(bit-reversed bytes)   (routine at bus 0x875C).
  0x006000  Firmware image: vector table, boot header at 0x6400
            (len @0x6414, checksum @0x6418).  Checksum = sum16(image[0 : len])
            with the checksum field counted as 0.

  sum16 = 32-bit sum of the big-endian 16-bit words, modulo 2**32.

USAGE
  # check a full dump (read with --start 0) and write the image as .bic
  python3 extract_bic.py full_firmware_1_58.bin -o 8600_158.bic

  # dump that starts somewhere else, e.g. at 0x6000
  python3 extract_bic.py firmware.bin --start 0x6000

  # check an existing .bic (detected because file size == length field,
  # or the length field plus less than 4 KiB of zero padding, as in 8650_135)
  python3 extract_bic.py 8600_155.bic

  # strip the padding from a padded .bic
  python3 extract_bic.py 8650_135.bic -o 8650_135_trimmed.bic
"""
import os, sys, struct, argparse

IMAGE_BASE  = 0x6000      # bus address of image byte 0
HDR         = 0x400       # boot header offset inside the image
LEN_OFF     = 0x414       # image length field
CK_OFF      = 0x418       # image checksum field
IMAGE_MAX   = 0x1FA000    # upper limit enforced by the boot code
BOOT_BASE   = 0x000000
BOOT_SIZE   = 0x4000
DATA_BASE   = 0x004000
DATA_MAX    = 0x2000
PAD_MAX     = 0x1000      # zero padding tolerated after the image in a .bic
ID_OFF      = 0x0C        # boot-block field patched with the unit ID

u32 = lambda b, o: struct.unpack_from('>I', b, o)[0]

def sum16(b):
    """32-bit sum of big-endian 16-bit words (odd length padded with 0)."""
    if len(b) & 1:
        b = bytes(b) + b'\0'
    return sum(struct.unpack('>%dH' % (len(b) // 2), b)) & 0xFFFFFFFF

def crc16_xmodem(data):
    crc = 0
    for x in data:
        crc ^= x << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
        crc &= 0xFFFF
    return crc

def data_crc(data):
    """Data-block checksum: two CRC-16/XMODEM, the second over bit-reversed bytes."""
    rev = bytes(int('{:08b}'.format(x)[::-1], 2) for x in data)
    return crc16_xmodem(data) << 16 | crc16_xmodem(rev)

def image_checksum(img, length):
    """Checksum stored at image offset 0x418."""
    b = bytearray(img[:length])
    b[CK_OFF:CK_OFF + 4] = b'\0\0\0\0'
    return sum16(b)

def check_image(img):
    """img starts at the vector table.  Returns (ok, length, msg)."""
    if len(img) < CK_OFF + 4:
        return False, 0, "too short for the boot header"
    length, stored = u32(img, LEN_OFF), u32(img, CK_OFF)
    if not 0x420 <= length <= IMAGE_MAX:
        return False, length, f"implausible length field {length:#x}"
    if length > len(img):
        return False, length, (f"length field {length:#x} but only "
                                f"{len(img):#x} bytes available")
    calc = image_checksum(img, length)
    ok = calc == stored
    return ok, length, (f"length {length:#x}, checksum {stored:#010x} "
                        f"{'OK' if ok else f'MISMATCH (computed {calc:#010x})'}")

def bic_length(data):
    """Image length if data looks like a .bic, else None.  A .bic is exactly
    `len` bytes or, as seen in 8650_135.bic, padded with fewer than PAD_MAX
    zero bytes (that file is rounded up to a 4 KiB multiple)."""
    if len(data) < CK_OFF + 4:
        return None
    length = u32(data, LEN_OFF)
    if not 0x420 <= length <= len(data) < length + PAD_MAX:
        return None
    return length if not any(data[length:]) else None

def check_boot(boot, img=None):
    """boot = flash 0x0000-0x3FFF.  Returns (ok, msg)."""
    for n in range(min(len(boot), BOOT_SIZE) - 8, 0x20, -2):
        if u32(boot, n) == n + 4 and u32(boot, n + 4) == sum16(boot[:n + 4]):
            break
    else:
        return False, "no valid length/checksum trailer found"
    unit = u32(boot, ID_OFF)
    msg = (f"{n:#x} bytes + trailer, checksum {u32(boot, n + 4):#010x} OK, "
           f"ID field {unit:#010x} ({unit})")
    if img is not None and len(img) >= HDR + n:
        ref = bytearray(img[HDR:HDR + n])
        ref[ID_OFF:ID_OFF + 4] = boot[ID_OFF:ID_OFF + 4]
        msg += (", matches image[0x400:]" if ref == boot[:n]
                else ", DIFFERS from image[0x400:] (other firmware version?)")
    return True, msg

def check_data(blk):
    """blk = flash 0x4000-0x5FFF.  Returns (ok, msg)."""
    length = u32(blk, 0)
    if not 4 <= length <= DATA_MAX or length + 4 > len(blk):
        return False, f"implausible length field {length:#x}"
    stored, calc = u32(blk, length), data_crc(blk[:length])
    ok = stored == calc
    return ok, (f"length {length:#x}, CRC {stored:#010x} "
                f"{'OK' if ok else f'MISMATCH (computed {calc:#010x})'}, "
                f"data {blk[4:length].hex(' ')}")

def check_flash(data, start=0, image_base=IMAGE_BASE):
    """Run every check whose region lies inside data (bus address start).
    Returns a list of (name, ok, msg)."""
    end = start + len(data)
    region = lambda a, n: data[a - start:a - start + n]
    img = region(image_base, end) if start <= image_base < end else None
    res = []
    if start <= BOOT_BASE and end >= BOOT_BASE + BOOT_SIZE:
        res.append(("boot block @0x000000",
                    *check_boot(region(BOOT_BASE, BOOT_SIZE), img)))
    if start <= DATA_BASE and end >= DATA_BASE + DATA_MAX:
        res.append(("data block @0x004000", *check_data(region(DATA_BASE, DATA_MAX))))
    if img is not None:
        ok, _, msg = check_image(img)
        res.append((f"firmware image @{image_base:#08x}", ok, msg))
    return res

def main():
    ap = argparse.ArgumentParser(description="Check a GT8650 flash dump and "
                                 "extract the firmware image as .bic")
    ap.add_argument('dump', help="flash dump or .bic file")
    ap.add_argument('--start', type=lambda x: int(x, 0), default=None,
                    help="bus address of the dump's first byte (default 0; "
                         "a .bic is detected automatically)")
    ap.add_argument('-o', '--out', help="write the image here "
                    "(default: <dump>.bic; not written for a .bic input)")
    args = ap.parse_args()
    data = open(args.dump, 'rb').read()

    start, is_bic = args.start, False
    if start is None:
        length = bic_length(data)
        is_bic = length is not None
        start = IMAGE_BASE if is_bic else 0
        if is_bic and length == len(data):
            print(f"[*] {args.dump}: file size equals the length field -> .bic")
        elif is_bic:
            print(f"[*] {args.dump}: length field {length:#x} + "
                  f"{len(data) - length} zero bytes padding -> .bic")

    results = check_flash(data, start)
    if not any(n.startswith('firmware') for n, _, _ in results):
        sys.exit(f"[!] dump {start:#x}..{start + len(data):#x} does not contain "
                 f"the image start {IMAGE_BASE:#x}")
    for name, ok, msg in results:
        print(f"[{'+' if ok else '!'}] {name}: {msg}")
    img_ok = results[-1][1]

    if is_bic and not args.out:
        return 0 if img_ok else 1
    ok, length, _ = check_image(data[IMAGE_BASE - start:])
    if length > len(data) - (IMAGE_BASE - start) or not 0x420 <= length <= IMAGE_MAX:
        sys.exit("[!] cannot extract: image incomplete or header invalid")
    out = args.out or os.path.splitext(args.dump)[0] + '.bic'
    with open(out, 'wb') as f:
        f.write(data[IMAGE_BASE - start:IMAGE_BASE - start + length])
    print(f"[{'+' if ok else '!'}] wrote {length} bytes to {out}"
          + ("" if ok else "  (checksum MISMATCH -- image is suspect)"))
    return 0 if ok else 1

if __name__ == '__main__':
    sys.exit(main())
