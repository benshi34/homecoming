__artifacts_v2__ = {
    "corpusWalletPasses": {
        "name": "Apple Wallet - Passes",
        "description": "One row per Wallet pass (boarding pass, event ticket, store card, coupon, generic) with its "
                       "organization, description, dates and visible fields. Reads pass.json in UTF-8, UTF-8 with a "
                       "BOM or UTF-16; the upstream appleWalletPasses module assumes UTF-8, and one UTF-16 pass makes "
                       "it fail for every pass.",
        "author": "q1_user_model",
        "creation_date": "2026-10-07",
        "last_update_date": "2026-10-07",
        "requirements": "none",
        "category": "Apple Wallet",
        "notes": "Barcode payloads and serial numbers are left out on purpose (ticket and confirmation codes).",
        "paths": ('*/Cards/*.pkpass/pass.json',),
        "output_types": "standard",
        "artifact_icon": "credit-card",
    }
}

import json
import os
from datetime import datetime, timezone

from scripts.ilapfuncs import artifact_processor

STYLES = ('boardingPass', 'eventTicket', 'storeCard', 'coupon', 'generic')
SECTIONS = ('headerFields', 'primaryFields', 'secondaryFields', 'auxiliaryFields')


def read_pass(path):
    with open(path, 'rb') as f:
        raw = f.read()
    if raw[:2] in (b'\xfe\xff', b'\xff\xfe'):
        text = raw.decode('utf-16')
    else:
        text = raw.decode('utf-8-sig', errors='replace')
    return json.loads(text)


def to_utc(value):
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def field_text(fields):
    out = []
    for f in fields or []:
        label, value = f.get('label'), f.get('value')
        if value in (None, ''):
            continue
        out.append(f'{label}: {value}' if label else str(value))
    return '; '.join(out)


@artifact_processor
def corpusWalletPasses(context):
    data_list, sources = [], []
    for file_found in context.get_files_found():
        file_found = str(file_found)
        if not file_found.endswith('pass.json'):
            continue
        try:
            p = read_pass(file_found)
        except (ValueError, UnicodeDecodeError):
            continue
        sources.append(file_found)
        style = next((s for s in STYLES if s in p), '')
        body = p.get(style, {}) if style else {}
        front = '; '.join(t for t in (field_text(body.get(s)) for s in SECTIONS) if t)
        relevant = p.get('relevantDate') or next((d.get('startDate') or d.get('date') for d in p.get('relevantDates') or []
                                                  if isinstance(d, dict)), None)
        data_list.append((to_utc(relevant), to_utc(p.get('expirationDate')), style,
                          body.get('transitType', '').replace('PKTransitType', ''), p.get('organizationName'),
                          p.get('description'), p.get('logoText'), front, field_text(body.get('backFields')),
                          'Yes' if p.get('voided') else 'No', p.get('passTypeIdentifier'),
                          os.path.basename(os.path.dirname(file_found)), context.get_relative_path(file_found)))
    data_headers = (('Relevant Date', 'datetime'), ('Expiration Date', 'datetime'), 'Pass Style', 'Transit Type',
                    'Organization', 'Description', 'Logo Text', 'Fields', 'Back Fields', 'Voided',
                    'Pass Type Identifier', 'Pass ID', 'Source File')
    return data_headers, data_list, '\n'.join(sources)
