#!/usr/bin/env python3

# Copyright 2026 The Sail Authors
# You can use, redistribute, and/or modify this source code under
# the terms of the GPL-3.0 license that can be found in the LICENSE file.
"""Turns a prepared Helium source tree into Sail.

Runs at the end of prepare_sources (devutils/shared.sh), after Helium's
patches, name substitution and resources. It is idempotent, so it can also be
re-run on an existing tree:

    python3 sail/rebrand.py build/src

Everything Sail changes lives under sail/, so merging upstream Helium stays
conflict-free. Every code edit is an exact match: if upstream Helium changes
one of these lines, this script stops and names the line instead of guessing.
Sail's own features are patches in sail/patches/, listed in its series file.
"""

import argparse
import filecmp
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as xml
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAIL_RESOURCES = ROOT / 'sail' / 'resources'
SAIL_PATCHES = ROOT / 'sail' / 'patches'
HELIUM_REPO = ROOT / 'helium-chromium'

sys.path.insert(0, str(HELIUM_REPO / 'utils'))
# pylint: disable=wrong-import-position
import name_substitution  # noqa: E402
import name_substitution_utils as grit_util  # noqa: E402

PRODUCT = 'Sail'
BUNDLE_ID = 'com.manuelmezzanotte.sail'
# Windows app ID (Helium's is {FB68A146-...}).
WINDOWS_APP_GUID = '{BC9170C5-6303-4228-AF17-46D482BEC3FA}'
SOURCE_URL = 'https://github.com/Manuel-Mezzanotte/SailBrowser'
ISSUES_URL = f'{SOURCE_URL}/issues/new'
PRIVACY_URL = f'{SOURCE_URL}/blob/main/sail/PRIVACY.md'
TERMS_URL = f'{SOURCE_URL}/blob/main/LICENSE'

BRANDING = f"""COMPANY_FULLNAME=The {PRODUCT} Authors
COMPANY_SHORTNAME=The {PRODUCT} Authors
PRODUCT_FULLNAME={PRODUCT}
PRODUCT_SHORTNAME={PRODUCT}
PRODUCT_INSTALLER_FULLNAME={PRODUCT} Installer
PRODUCT_INSTALLER_SHORTNAME={PRODUCT} Installer
COPYRIGHT=Copyright @LASTCHANGE_YEAR@ The {PRODUCT} Authors, The Helium Authors and The Chromium Authors.
MAC_BUNDLE_ID={BUNDLE_ID}
MAC_CREATOR_CODE=Cr24
MAC_TEAM_ID=
"""

# (file, exact old text, new text[, times the old text appears]). An empty
# new text deletes the old text.
CODE_EDITS = [
    # sail:// instead of helium:// for the browser's own pages.
    ('content/public/common/url_constants.h',
     'kHeliumUIScheme[] = "helium";', 'kHeliumUIScheme[] = "sail";'),
    ('components/url_formatter/url_fixer.cc',
     'kHeliumUIScheme[] = "helium";', 'kHeliumUIScheme[] = "sail";'),
    ('components/omnibox/browser/builtin_provider.cc',
     'replace(0, 6, u"helium")', 'replace(0, 6, u"sail")'),
    ('chrome/browser/resources/tab_search/tab_search_item.ts',
     "protocol === 'helium:'", "protocol === 'sail:'"),
    ('chrome/browser/resources/tab_search/tab_search_item.ts',
     "createTextNode('helium://')", "createTextNode('sail://')"),

    # Crash reports must never reach Helium's server: no upload URL, and the
    # "send report?" prompt is off by default.
    ('chrome/app/chrome_crash_reporter_client.cc',
     'product_name = "Helium";', f'product_name = "{PRODUCT}";'),
    ('components/crash/core/app/crash_reporter_client.cc',
     'return "https://crash.helium.computer/crash";', 'return "";'),
    ('chrome/browser/prefs/browser_prefs.cc',
     'static_cast<int>(helium::CrashReportingMode::kAsk)',
     'static_cast<int>(helium::CrashReportingMode::kDisabled)'),
    ('chrome/browser/crash_upload_list/helium_crash_reporting.cc',
     'static_cast<int>(CrashReportingMode::kAsk)',
     'static_cast<int>(CrashReportingMode::kDisabled)'),
    ('components/crash/core/browser/resources/crashes.ts',
     "'https://github.com/imputnet/helium/issues/new'", f"'{ISSUES_URL}'"),

    # First-run onboarding: Sail title, and no "Helium Partner" badge, since
    # those purchases support Helium rather than Sail.
    ('components/helium_onboarding/index.html',
     '<title>Helium Setup</title>', f'<title>{PRODUCT} Setup</title>'),
    ('components/helium_onboarding/src/components/PasswordManagerOption.svelte',
     '<HeliumPartner />', ''),
    ('components/helium_onboarding/src/pages/Welcome.svelte',
     'privacyUrl = "https://helium.computer/privacy";', f'privacyUrl = "{PRIVACY_URL}";'),
    ('components/helium_onboarding/src/pages/Welcome.svelte',
     'termsUrl = "https://helium.computer/terms";', f'termsUrl = "{TERMS_URL}";'),
    # The online services page gets a globe instead of the Helium logo.
    ('components/helium_onboarding/src/pages/HeliumServices.svelte',
     'import { CardLink, HeliumLogo } from "@imput/helium-prism";',
     'import { CardLink, IconWorld } from "@imput/helium-prism";'),
    ('components/helium_onboarding/src/pages/HeliumServices.svelte',
     'Icon={HeliumLogo}\n            iconHeight="32px"\n', 'Icon={IconWorld}\n'),
    # Vite does not empty an output folder outside the project, so bundles
    # from earlier builds (some still with the Helium logo) would end up in
    # resources.pak.
    ('components/helium_onboarding/BUILD.gn',
     '    "build",\n    rebase_path("."),\n',
     '    "build",\n    "--emptyOutDir",\n    rebase_path("."),\n'),

    # Flag names shown in sail://flags (#sail-noise, ...).
    ('chrome/browser/helium_flag_choices.h', '"helium-', '"sail-', 7),
    ('chrome/browser/channel_selection.h',
     '"helium-update-channel"', '"sail-update-channel"'),

    # Notice shown when the online services change.
    ('components/helium_services/schema.cc',
     'major changes to Helium services.', 'major changes to online services.'),

    # Chrome Web Store: "Add to Sail" instead of "Add to Chrome".
    ('components/extstore_fixups/chrome-webstore.js',
     "replace(CHROME_NAME_REGEX, 'Helium')", f"replace(CHROME_NAME_REGEX, '{PRODUCT}')"),

    # uBlock Origin: filter list names and its About page.
    ('third_party/ublock/assets/assets.json', '"Helium filters', f'"{PRODUCT} filters', 4),
    ('third_party/ublock/assets/helium/annoyances.txt',
     '! Title: Helium - Annoyances', f'! Title: {PRODUCT} - Annoyances'),
    ('third_party/ublock/assets/helium/unbreak.txt',
     '! Title: Helium - Unbreak', f'! Title: {PRODUCT} - Unbreak'),
    ('third_party/ublock/assets/helium/annoyances.txt',
     'Helium-specific fixes for filterlists used by Helium.',
     f'Fixes for the filter lists used by {PRODUCT}.'),
    ('third_party/ublock/assets/helium/unbreak.txt',
     'Helium-specific fixes for filterlists used by Helium.',
     f'Fixes for the filter lists used by {PRODUCT}.'),
    ('third_party/ublock/about.html',
     '<div class="li">Helium fork:</div>', f'<div class="li">{PRODUCT}:</div>'),
    ('third_party/ublock/about.html',
     'href="https://helium.computer/privacy"', f'href="{PRIVACY_URL}"'),
    ('third_party/ublock/js/about.js', '(Helium)`', f'({PRODUCT})`'),

    # sail://credits must point to Sail's own source code (GPL-3.0). Helium
    # stays listed there as one of the components.
    ('tools/licenses/licenses.py',
     "'opensource_project': 'Helium',", f"'opensource_project': '{PRODUCT}',"),
    ('tools/licenses/licenses.py',
     "'opensource_link': 'https://github.com/imputnet/helium',",
     f"'opensource_link': '{SOURCE_URL}',"),
]

# Edits for one platform only, on top of CODE_EDITS.
PLATFORM_CODE_EDITS = {
    'macos': [
        # Own keychain item and profile folder, so Sail never touches Helium's
        # data.
        ('components/os_crypt/common/keychain_password_mac.mm',
         'kDefaultServiceName[] = "Helium Storage Key";',
         f'kDefaultServiceName[] = "{PRODUCT} Storage Key";'),
        ('components/os_crypt/common/keychain_password_mac.mm',
         'kDefaultAccountName[] = "Helium";', f'kDefaultAccountName[] = "{PRODUCT}";'),
        ('chrome/common/chrome_paths_mac.mm',
         'product_dir_name = "net.imput.helium";', f'product_dir_name = "{BUNDLE_ID}";'),
    ],
    'windows': [
        # Own install folder (%LOCALAPPDATA%\Sail\Sail), registry keys and
        # app ID, so Sail and Helium can be installed side by side. The GUID
        # is also in windows/installer/sail.nsi.
        ('chrome/install_static/chromium_install_modes.h',
         'kCompanyPathName[] = L"imput";', f'kCompanyPathName[] = L"{PRODUCT}";'),
        ('chrome/install_static/chromium_install_modes.h',
         'kProductPathName[] = L"Helium";', f'kProductPathName[] = L"{PRODUCT}";'),
        ('chrome/install_static/chromium_install_modes.h',
         'kSafeBrowsingName[] = "helium";', 'kSafeBrowsingName[] = "sail";'),
        ('chrome/install_static/chromium_install_modes.h',
         'L"{FB68A146-637A-48C2-A0C4-1565DE45FEBD}"',
         f'L"{WINDOWS_APP_GUID}"', 2),
        ('chrome/install_static/chromium_install_modes.h',
         '.base_app_name = L"Helium",', f'.base_app_name = L"{PRODUCT}",'),
        ('chrome/install_static/chromium_install_modes.h',
         '.base_app_id = L"Helium",', f'.base_app_id = L"{PRODUCT}",'),
        ('chrome/install_static/chromium_install_modes.h',
         'L"HeliumHTM"', f'L"{PRODUCT}HTM"'),
        ('chrome/install_static/chromium_install_modes.h',
         'L"Helium HTML Document"', f'L"{PRODUCT} HTML Document"'),
        ('chrome/install_static/chromium_install_modes.h',
         '.direct_launch_url_scheme = "helium",', '.direct_launch_url_scheme = "sail",'),
        ('chrome/install_static/chromium_install_modes.h',
         'L"HeliumPDF"', f'L"{PRODUCT}PDF"'),
        ('chrome/install_static/chromium_install_modes.h',
         'L"Helium PDF Document"', f'L"{PRODUCT} PDF Document"'),
    ],
}

# Flag names and descriptions in sail://flags ("Helium flag.", "Helium Noise").
FLAG_ENTRIES = 'chrome/browser/helium_flag_entries.h'
FLAG_HELIUM = re.compile(r'(?<!The )\bHelium\b')  # but not "The Helium Authors"

# Onboarding pages that show the product logo (not the Helium services logo).
ONBOARDING_LOGO_PAGES = [
    'components/helium_onboarding/src/pages/Welcome.svelte',
    'components/helium_onboarding/src/pages/Finish.svelte',
]
SAIL_LOGO_IMPORT = '    import SailLogo from "../components/SailLogo.svelte";\n'

EXTRA_RESOURCES = [
    ('onboarding/favicon.png', 'components/helium_onboarding/public/favicon.png'),
    ('onboarding/SailLogo.svelte',
     'components/helium_onboarding/src/components/SailLogo.svelte'),
    # Sail's icon in the "import from another browser" animation.
    ('onboarding/browser_icon.avif',
     'components/helium_onboarding/node_modules/nonfree-icons/browsers/helium.avif'),
    # New tab favicon. Helium's other favicons are generic and stay.
    ('favicons/favicon_ntp_16.png', 'chrome/app/theme/default_100_percent/common/favicon_ntp.png'),
    ('favicons/favicon_ntp_32.png', 'chrome/app/theme/default_200_percent/common/favicon_ntp.png'),
]

# UI strings: the product name and its URL scheme become Sail's...
# No word boundaries around the name: many languages attach prefixes and
# suffixes to it (Zulu "kuHelium", Amharic "የHelium", Finnish "Heliumin",
# Korean "Helium을"). UI text never contains Helium inside another word.
NAME = (re.compile(r'Helium'), PRODUCT)
STRING_REGEXES = [
    (re.compile(r'(\b)helium://'), r'\1sail://'),
    # Suffixes that change with the last sound of the name.
    (re.compile(r'Helium으로'), f'{PRODUCT}로'),  # Korean: after "l", 로
    (re.compile(r'Heliummal\b'), f'{PRODUCT}lal'),  # Hungarian: -val assimilates
    NAME,
]
# ...except text about Helium's servers. Sail still uses them, so calling them
# "Sail services" would be misleading: they become "online services". English
# and Italian are rewritten; other languages fall back to English for these
# few strings until someone translates them.
SERVICES_TEXT = re.compile(
    r"Helium(?:'s)? (?:services?|servers?|partner)|development of Helium", re.IGNORECASE)
SERVICES_REGEXES = {
    'en': [
        (re.compile(r'Paying for this service will support the development of Helium\.'),
         'This is a partner service.'),
        (re.compile(r'\bHelium Partner\b'), 'Partner'),
        (re.compile(r'\bHelium servers\b'), 'online services'),
        # grit text starts with the XML indentation, hence the \s*.
        (re.compile(r"(^\s*|[.!?:]\s+|See )Helium(?:'s)? services\b"), r'\1Online services'),
        (re.compile(r"\bHelium(?:'s)? services\b"), 'online services'),
        NAME,
    ],
    'it': [
        (re.compile(r'Pagare per questo servizio sosterrà lo sviluppo di Helium\.'),
         'Questo è un servizio partner.'),
        (re.compile(r'\bPartner di Helium\b'), 'Partner'),
        (re.compile(r'\b([Ss])erver (?:di )?Helium\b'), r'\1ervizi online'),
        (re.compile(r'\b([Ss])ervizi (?:di )?Helium\b'), r'\1ervizi online'),
        NAME,
    ],
}


def _replace(element, regexes):
    grit_util.REPLACEMENT_REGEXES = regexes
    return grit_util.replace_grit_message(element)


class RebrandError(Exception):
    pass


def _patched_files(patch):
    """The files a patch changes, relative to the tree."""
    return {line[len('+++ b/'):].split('\t')[0].strip()
            for line in patch.read_text().splitlines() if line.startswith('+++ b/')}


def _applied_count(patch_bin, tree, patches):
    """How many patches at the start of the series the tree already has.

    Later patches can change lines next to earlier ones, so a single patch
    cannot be checked on its own. Instead, the files are copied aside and the
    patches taken out again, last first: the longest run that comes out
    cleanly is the one in the tree."""
    files = set().union(*(_patched_files(patch) for patch in patches))
    for count in range(len(patches), 0, -1):
        with tempfile.TemporaryDirectory() as copy:
            for relpath in files:
                if (tree / relpath).is_file():
                    (Path(copy) / relpath).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(tree / relpath, Path(copy) / relpath)
            if all(subprocess.run([patch_bin, '-p1', '-R', '-s', '-f', '--no-backup-if-mismatch',
                                   '-d', copy, '-i', str(patch)],
                                  capture_output=True).returncode == 0
                   for patch in reversed(patches[:count])):
                return count
    return 0


def apply_patches(tree):
    """Applies sail/patches/series. The patches are written against the tree
    as it is after Helium's preparation. Patches already in the tree are
    skipped, so the script can run again on a prepared tree."""
    # On Windows there is no patch in PATH; windows/build.py passes the one
    # that comes with Chromium's bundled git.
    patch_bin = os.environ.get('SAIL_PATCH_BIN') or shutil.which('patch')
    if not patch_bin:
        raise RebrandError('the patch command is missing')
    names = [line.strip() for line in (SAIL_PATCHES / 'series').read_text().splitlines()
             if line.strip() and not line.startswith('#')]
    patches = [SAIL_PATCHES / name for name in names]
    done = _applied_count(patch_bin, tree, patches)
    for name, patch in zip(names[done:], patches[done:]):
        command = [patch_bin, '-p1', '-s', '-f', '-d', str(tree), '-i', str(patch)]
        if subprocess.run(command + ['--forward', '--dry-run'],
                          capture_output=True).returncode != 0:
            raise RebrandError(f'sail/patches/{name} does not apply; '
                               'upstream Helium changed the code it patches')
        subprocess.run(command + ['--forward', '--no-backup-if-mismatch'],
                       check=True, capture_output=True)
    print(f'Applied {len(names) - done} of {len(names)} Sail patches')


def apply_code_edits(tree, platform):
    for relpath, old, new, *count in CODE_EDITS + PLATFORM_CODE_EDITS[platform]:
        expected = count[0] if count else 1
        path = tree / relpath
        text = path.read_text(encoding='utf-8')
        if old in text:
            if text.count(old) != expected:
                raise RebrandError(f'{relpath}: expected "{old}" {expected} times, '
                                   f'found {text.count(old)}')
            path.write_text(text.replace(old, new), encoding='utf-8', newline='\n')
        elif new and new not in text:
            raise RebrandError(f'{relpath}: neither "{old}" nor "{new}" found; '
                               'upstream Helium changed this line')

    path = tree / FLAG_ENTRIES
    text = path.read_text(encoding='utf-8')
    if FLAG_HELIUM.search(text):
        path.write_text(FLAG_HELIUM.sub(PRODUCT, text), encoding='utf-8', newline='\n')
    elif f'{PRODUCT} flag' not in text:
        raise RebrandError(f'{FLAG_ENTRIES}: no "Helium flag" descriptions found; '
                           'upstream Helium changed the flag list')

    for relpath in ONBOARDING_LOGO_PAGES:
        path = tree / relpath
        text = path.read_text(encoding='utf-8')
        if SAIL_LOGO_IMPORT in text:
            continue
        if '<HeliumLogo ' not in text or '<script lang="ts">\n' not in text:
            raise RebrandError(f'{relpath}: Helium logo markup not found')
        text = text.replace('<script lang="ts">\n', '<script lang="ts">\n' + SAIL_LOGO_IMPORT, 1)
        path.write_text(text.replace('<HeliumLogo ', '<SailLogo '), encoding='utf-8', newline='\n')

    branding = tree / 'chrome' / 'app' / 'theme' / 'chromium' / 'BRANDING'
    if branding.read_text(encoding='utf-8') != BRANDING:
        branding.write_text(BRANDING, encoding='utf-8', newline='\n')


def _read_grit(path):
    text = path.read_text(encoding='utf-8')
    if 'Helium' not in text and 'helium://' not in text:
        return None
    return xml.fromstring(text.replace('&#36;', '!!dollar-sign-literal!!'),
                         grit_util.get_parser())


def _write_grit(path, root):
    # Keep the file's own prolog: some readers (the onboarding's i18n script)
    # expect the root element first and fail on an added XML declaration.
    declaration = path.read_text(encoding='utf-8').lstrip().startswith('<?xml')
    text = xml.tostring(root, encoding='unicode', xml_declaration=declaration)
    path.write_text(text.replace('!!dollar-sign-literal!!', '&#36;'), encoding='utf-8', newline='\n')


def _rebrand_grd(args):
    path, tree = args
    if str(tree / 'tools' / 'grit') not in sys.path:
        grit_util.add_grit_to_path(tree)
    root = _read_grit(path)
    if root is None:
        return {}, set()

    fp_map, services, changed = {}, set(), False
    for message in root.findall('.//message'):
        old_fp = grit_util.compute_fp(message)
        is_service = bool(SERVICES_TEXT.search(''.join(message.itertext())))
        if _replace(message, SERVICES_REGEXES['en'] if is_service else STRING_REGEXES):
            changed = True
            new_fp = grit_util.compute_fp(message)
            if new_fp != old_fp:
                fp_map[old_fp] = new_fp
                if is_service:
                    services.add(old_fp)
    if changed:
        _write_grit(path, root)
    return fp_map, services


def _rebrand_xtb(args):
    path, fp_map, services = args
    root = _read_grit(path)
    if root is None:
        return False

    service_regexes = SERVICES_REGEXES.get(root.get('lang', '').split('-')[0])
    changed, seen = False, set()
    for translation in root.findall('.//translation'):
        old_id = translation.get('id')
        if old_id in services and service_regexes is None:
            # No rewrite for this language: the old translation stays under
            # its old id, unused, so the English text is shown instead.
            changed |= _replace(translation, STRING_REGEXES)
        else:
            regexes = service_regexes if old_id in services else STRING_REGEXES
            changed |= _replace(translation, regexes)
            # Re-key even when the translated text has no "Helium" in it,
            # otherwise the translation would be orphaned.
            if old_id in fp_map:
                translation.set('id', fp_map[old_id])
                changed = True
        grit_util.dedup_translations_in_place(translation, seen)
    if changed:
        _write_grit(path, root)
    return changed


def rebrand_strings(tree):
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as pool:
        grd_files = name_substitution.get_substitutable_files(tree, ['grd', 'grdp'])
        fp_map, services = {}, set()
        for file_map, file_services in pool.map(_rebrand_grd, ((p, tree) for p in grd_files)):
            fp_map.update(file_map)
            services |= file_services

        xtb_files = name_substitution.get_substitutable_files(tree, ['xtb'])
        changed = sum(pool.map(_rebrand_xtb, ((p, fp_map, services) for p in xtb_files),
                               chunksize=16))
    print(f'Rebranded {len(fp_map)} strings ({len(services)} about online services), '
          f'updated {changed} translation files')


def copy_resources(tree, platform):
    mappings = []
    listings = [(HELIUM_REPO / 'resources' / 'helium_resources.txt', ('branding/', 'generated/'))]
    if platform == 'macos':
        listings.append(
            (ROOT / 'macos' / 'resources' / 'platform_resources.txt', ('assets/',)))
    # On Windows the app icon comes from windows/resources/generate_resources.txt.
    for listing, prefixes in listings:
        for line in listing.read_text().splitlines():
            parts = line.split()
            if len(parts) == 2 and not line.startswith('#') and parts[0].startswith(prefixes):
                mappings.append(tuple(parts))
    mappings += EXTRA_RESOURCES

    copied = 0
    for source, destination in mappings:
        source_path = SAIL_RESOURCES / source
        if not source_path.exists():
            raise RebrandError(f'missing Sail resource {source_path}; '
                               'run sail/branding/generate_assets.py')
        destination_path = tree / destination
        # Leave identical files alone so incremental builds stay incremental.
        if destination_path.exists() and filecmp.cmp(source_path, destination_path, shallow=False):
            continue
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, destination_path)
        copied += 1
    print(f'Copied {copied} of {len(mappings)} Sail resources')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('tree', type=Path, help='the prepared Chromium source tree')
    parser.add_argument('--platform', choices=sorted(PLATFORM_CODE_EDITS), default='macos',
                        help='the platform the tree is prepared for (default: macos)')
    args = parser.parse_args()
    tree = args.tree.resolve()
    if not (tree / 'OWNERS').exists():
        raise SystemExit(f'{tree} is not a Chromium source tree')

    try:
        apply_patches(tree)
        apply_code_edits(tree, args.platform)
        rebrand_strings(tree)
        copy_resources(tree, args.platform)
    except RebrandError as error:
        raise SystemExit(f'sail/rebrand.py: {error}') from None
    print('Sail branding applied')


if __name__ == '__main__':
    main()
