#!/usr/bin/env python3
# Copyright 2026 The Sail Authors
# You can use, redistribute, and/or modify this source code under
# the terms of the GPL-3.0 license that can be found in the LICENSE file.
"""Copies the accounts you are signed in to (the cookies) from Zen to Sail.

Sail's own import brings bookmarks and history over from Zen, but not
cookies. This script writes Zen's cookies into Sail's cookie database,
encrypted with the "Sail Storage Key" from the keychain, the way Sail stores
them itself.

Close Zen and Sail first. macOS asks once for permission to read the
"Sail Storage Key" from the keychain.

    python3 sail/tools/import_zen_accounts.py            # copy the cookies
    python3 sail/tools/import_zen_accounts.py --dry-run  # only count them

Before writing, the script makes a copy of Sail's cookie database next to it
(Cookies.before-zen-<date>), so you can go back.
"""

import argparse
import configparser
import hashlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

APP_SUPPORT = Path.home() / 'Library' / 'Application Support'
ZEN_DIR = APP_SUPPORT / 'zen'
SAIL_PROFILE = APP_SUPPORT / 'com.manuelmezzanotte.sail' / 'Default'
KEYCHAIN_SERVICE = 'Sail Storage Key'
KEYCHAIN_ACCOUNT = 'Sail'

# Chromium counts microseconds from 1601, Firefox from 1970.
WINDOWS_EPOCH_US = 11644473600 * 1_000_000
# Chromium keeps cookies for at most 400 days (RFC 6265bis).
MAX_AGE_US = 400 * 24 * 3600 * 1_000_000

# Firefox's sameSite (0 none, 1 lax, 2 strict, 256 not set) to Chromium's
# CookieSameSite (0 none, 1 lax, 2 strict, -1 not set).
SAME_SITE = {0: 0, 1: 1, 2: 2}


# AES-128-CBC ------------------------------------------------------------------
#
# Chromium on macOS encrypts cookies with AES-128-CBC. Python has no AES of
# its own, and passing the key to the openssl command would show it to every
# other process, so here is a small implementation.


def _xtime(a):
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _make_sbox():
    def rotl(x, n):
        return ((x << n) | (x >> (8 - n))) & 0xFF

    sbox = [0] * 256
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        sbox[p] = q ^ rotl(q, 1) ^ rotl(q, 2) ^ rotl(q, 3) ^ rotl(q, 4) ^ 0x63
        if p == 1:
            break
    sbox[0] = 0x63
    return sbox


SBOX = _make_sbox()
INV_SBOX = [0] * 256
for _i, _v in enumerate(SBOX):
    INV_SBOX[_v] = _i


def _round_keys(key):
    words = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        word = list(words[i - 1])
        if i % 4 == 0:
            word = [SBOX[b] for b in word[1:] + word[:1]]
            word[0] ^= rcon
            rcon = _xtime(rcon)
        words.append([a ^ b for a, b in zip(words[i - 4], word)])
    return [sum(words[r * 4:r * 4 + 4], []) for r in range(11)]


def _mix_columns(state):
    out = []
    for c in range(4):
        a = state[4 * c:4 * c + 4]
        t = a[0] ^ a[1] ^ a[2] ^ a[3]
        out += [a[i] ^ t ^ _xtime(a[i] ^ a[(i + 1) % 4]) for i in range(4)]
    return out


def _encrypt_block(block, keys):
    state = [b ^ k for b, k in zip(block, keys[0])]
    for rnd in range(1, 11):
        state = [SBOX[b] for b in state]
        state = [state[4 * ((c + r) % 4) + r] for c in range(4) for r in range(4)]
        if rnd != 10:
            state = _mix_columns(state)
        state = [b ^ k for b, k in zip(state, keys[rnd])]
    return bytes(state)


def _decrypt_block(block, keys):
    state = [b ^ k for b, k in zip(block, keys[10])]
    for rnd in range(9, -1, -1):
        state = [state[4 * ((c - r) % 4) + r] for c in range(4) for r in range(4)]
        state = [INV_SBOX[b] for b in state]
        state = [b ^ k for b, k in zip(state, keys[rnd])]
        if rnd:
            pre = []
            for c in range(4):
                a = state[4 * c:4 * c + 4]
                u = _xtime(_xtime(a[0] ^ a[2]))
                v = _xtime(_xtime(a[1] ^ a[3]))
                pre += [a[0] ^ u, a[1] ^ v, a[2] ^ u, a[3] ^ v]
            state = _mix_columns(pre)
    return bytes(state)


# Chromium uses a fixed IV of 16 spaces (components/os_crypt).
IV = b' ' * 16


def cbc_encrypt(key, data):
    keys = _round_keys(key)
    pad = 16 - len(data) % 16
    data += bytes([pad]) * pad
    out, previous = bytearray(), IV
    for i in range(0, len(data), 16):
        previous = _encrypt_block(
            bytes(a ^ b for a, b in zip(data[i:i + 16], previous)), keys)
        out += previous
    return bytes(out)


def cbc_decrypt(key, data):
    if not data or len(data) % 16:
        raise ValueError('not a whole number of blocks')
    keys = _round_keys(key)
    out, previous = bytearray(), IV
    for i in range(0, len(data), 16):
        block = data[i:i + 16]
        out += bytes(a ^ b for a, b in zip(_decrypt_block(block, keys), previous))
        previous = block
    pad = out[-1]
    if not 1 <= pad <= 16 or out[-pad:] != bytes([pad]) * pad:
        raise ValueError('bad padding')
    return bytes(out[:-pad])


# Sail's cookie encryption ------------------------------------------------------


def sail_key(password):
    # components/os_crypt/async/browser/keychain_key_provider.mm
    return hashlib.pbkdf2_hmac('sha1', password, b'saltysalt', 1003, 16)


def encrypt_cookie(key, host, value):
    # Version 24 of the cookie database puts a SHA-256 of the domain in front
    # of the value (net/extras/sqlite/sqlite_persistent_cookie_store.cc).
    plain = hashlib.sha256(host.encode()).digest() + value.encode()
    return b'v10' + cbc_encrypt(key, plain)


def decrypt_cookie(key, host, encrypted):
    if not encrypted.startswith(b'v10'):
        raise ValueError('not v10')
    plain = cbc_decrypt(key, encrypted[3:])
    if plain[:32] != hashlib.sha256(host.encode()).digest():
        raise ValueError('domain hash does not match')
    return plain[32:]


def keychain_password():
    result = subprocess.run(
        ['security', 'find-generic-password', '-w', '-s', KEYCHAIN_SERVICE,
         '-a', KEYCHAIN_ACCOUNT],
        capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f'Non riesco a leggere "{KEYCHAIN_SERVICE}" dal portachiavi '
                 '(permesso negato, o Sail non è mai stata aperta).')
    return result.stdout.rstrip('\n').encode()


# Zen ------------------------------------------------------------------------------


def zen_profile():
    """The profile Zen opens, from installs.ini, else the default one."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(ZEN_DIR / 'installs.ini')
    for section in parser.sections():
        path = parser[section].get('Default')
        if path and (ZEN_DIR / path / 'cookies.sqlite').is_file():
            return ZEN_DIR / path
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(ZEN_DIR / 'profiles.ini')
    found = []
    for section in parser.sections():
        options = parser[section]
        if 'path' not in options:
            continue
        relative = options.get('IsRelative', '1') == '1'
        path = ZEN_DIR / options['Path'] if relative else Path(options['Path'])
        if (path / 'cookies.sqlite').is_file():
            found.append((options.get('Default') != '1', str(path)))
    if not found:
        sys.exit(f'Nessun profilo di Zen con dei cookie in {ZEN_DIR}.')
    return Path(sorted(found)[0][1])


def read_zen_cookies(profile):
    # Copy the database with its write-ahead log, so that the latest cookies
    # are included and Zen's own files are never opened.
    with tempfile.TemporaryDirectory() as tmp:
        for suffix in ('', '-wal'):
            source = profile / f'cookies.sqlite{suffix}'
            if source.is_file():
                shutil.copyfile(source, Path(tmp) / f'cookies.sqlite{suffix}')
        db = sqlite3.connect(Path(tmp) / 'cookies.sqlite')
        db.row_factory = sqlite3.Row
        rows = [dict(row) for row in db.execute('SELECT * FROM moz_cookies')]
        db.close()
    return rows


def convert(rows, now_us):
    """Zen's cookies as rows of Sail's cookie table, and what was left out."""
    cookies, skipped = {}, Counter()
    for row in rows:
        if row['originAttributes']:
            # Cookies of a site embedded in another one (Firefox partitions
            # them by top-level site) or of a container. As normal cookies
            # they could replace the site's own ones and sign you out.
            skipped['partitioned'] += 1
            continue
        expiry = row['expiry'] or 0
        # Firefox writes the expiry in milliseconds, older versions in seconds.
        expires_us = expiry * 1000 if expiry > 10**11 else expiry * 1_000_000
        if expires_us <= now_us:
            skipped['expired'] += 1
            continue
        expires_us = min(expires_us, now_us + MAX_AGE_US)

        secure = bool(row['isSecure'])
        same_site = SAME_SITE.get(row['sameSite'], -1)
        if same_site == 0 and not secure:
            # Chromium does not keep SameSite=None cookies that are not
            # secure; Firefox writes "none" for cookies that did not say.
            same_site = -1
        scheme_map = row.get('schemeMap') or 0
        if secure or scheme_map & 2:
            scheme, port = 2, 443
        elif scheme_map & 1:
            scheme, port = 1, 80
        else:
            scheme, port = 0, -1
        created = row['creationTime'] or now_us
        accessed = row['lastAccessed'] or created
        updated = row.get('updateTime') or created
        cookies[(row['host'], row['name'], row['path'])] = {
            'creation_utc': created + WINDOWS_EPOCH_US,
            'host_key': row['host'],
            'name': row['name'],
            'value': row['value'] or '',
            'path': row['path'],
            'expires_utc': expires_us + WINDOWS_EPOCH_US,
            'is_secure': int(secure),
            'is_httponly': int(bool(row['isHttpOnly'])),
            'last_access_utc': accessed + WINDOWS_EPOCH_US,
            'samesite': same_site,
            'source_scheme': scheme,
            'source_port': port,
            'last_update_utc': updated + WINDOWS_EPOCH_US,
        }
    return list(cookies.values()), skipped


# Sail -------------------------------------------------------------------------------


def running(name):
    return subprocess.run(['pgrep', '-x', name], capture_output=True).returncode == 0


def existing(db, cookie):
    return db.execute(
        "SELECT COUNT(*) FROM cookies WHERE host_key = ? AND "
        "top_frame_site_key = '' AND name = ? AND path = ?",
        (cookie['host_key'], cookie['name'], cookie['path'])).fetchone()[0]


def check_key(db, key):
    """Decrypts a cookie Sail wrote itself, to be sure the key is right."""
    rows = db.execute(
        "SELECT host_key, encrypted_value FROM cookies "
        "WHERE length(encrypted_value) > 3 LIMIT 20").fetchall()
    if not rows:
        return None
    for host, encrypted in rows:
        try:
            decrypt_cookie(key, host, encrypted)
            return True
        except ValueError:
            pass
    return False


def write(db, cookies, key):
    replaced = 0
    with db:
        for cookie in cookies:
            replaced += db.execute(
                "DELETE FROM cookies WHERE host_key = ? AND "
                "top_frame_site_key = '' AND name = ? AND path = ?",
                (cookie['host_key'], cookie['name'], cookie['path'])).rowcount
            db.execute(
                'INSERT INTO cookies (creation_utc, host_key, '
                'top_frame_site_key, name, value, encrypted_value, path, '
                'expires_utc, is_secure, is_httponly, last_access_utc, '
                'has_expires, is_persistent, priority, samesite, '
                'source_scheme, source_port, last_update_utc, source_type, '
                'has_cross_site_ancestor) '
                "VALUES (?, ?, '', ?, '', ?, ?, ?, ?, ?, ?, 1, 1, 1, ?, ?, ?, "
                '?, 0, 1)',
                (cookie['creation_utc'], cookie['host_key'], cookie['name'],
                 encrypt_cookie(key, cookie['host_key'], cookie['value']),
                 cookie['path'], cookie['expires_utc'], cookie['is_secure'],
                 cookie['is_httponly'], cookie['last_access_utc'],
                 cookie['samesite'], cookie['source_scheme'],
                 cookie['source_port'], cookie['last_update_utc']))
    return replaced


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--zen-profile', type=Path,
                        help='cartella del profilo di Zen (di solito si trova da sola)')
    parser.add_argument('--sail-profile', type=Path, default=SAIL_PROFILE,
                        help=f'cartella del profilo di Sail (predefinita: {SAIL_PROFILE})')
    parser.add_argument('--dry-run', action='store_true',
                        help='conta soltanto, senza leggere la chiave né scrivere')
    args = parser.parse_args()

    zen = args.zen_profile or zen_profile()
    sail_db = args.sail_profile / 'Cookies'
    if not sail_db.is_file():
        sys.exit(f'Non trovo i cookie di Sail in {sail_db}. Apri Sail una volta e richiudila.')
    if not args.dry_run:
        for name, app in (('zen', 'Zen'), ('Sail', 'Sail')):
            if running(name):
                sys.exit(f'Chiudi {app} (⌘Q) e rilancia lo script.')

    cookies, skipped = convert(read_zen_cookies(zen), int(time.time() * 1_000_000))
    print(f'Profilo di Zen: {zen.name}')
    print(f'Da copiare: {len(cookies)} cookie di '
          f'{len({c["host_key"].lstrip(".") for c in cookies})} siti')
    print(f'Lasciati fuori: {skipped["expired"]} scaduti, '
          f'{skipped["partitioned"]} di siti incorporati in altri')

    if args.dry_run:
        db = sqlite3.connect(f'file:{sail_db}?mode=ro', uri=True)
        clashes = sum(1 for cookie in cookies if existing(db, cookie))
        db.close()
        print(f'Già presenti in Sail, da sostituire: {clashes}')
        print('Prova senza modifiche: non ho scritto niente.')
        return

    key = sail_key(keychain_password())
    db = sqlite3.connect(sail_db)
    verified = check_key(db, key)
    if verified is False:
        db.close()
        sys.exit('La chiave del portachiavi non apre i cookie che Sail ha già: '
                 'non scrivo niente.')

    backup_path = sail_db.with_name(
        f'Cookies.before-zen-{datetime.now():%Y%m%d-%H%M%S}')
    backup = sqlite3.connect(backup_path)
    db.backup(backup)
    backup.close()

    replaced = write(db, cookies, key)
    # Read back what was written, with the same key.
    sample = db.execute(
        "SELECT host_key, encrypted_value FROM cookies ORDER BY rowid DESC "
        "LIMIT 1").fetchone()
    decrypt_cookie(key, *sample)
    db.close()

    print(f'Copiati {len(cookies)} cookie ({replaced} sostituiti).')
    if verified is None:
        print('Sail non aveva cookie suoi da usare come prova della chiave.')
    print(f'Copia di prima: {backup_path.name}')
    print('Ora apri Sail.')


if __name__ == '__main__':
    main()
