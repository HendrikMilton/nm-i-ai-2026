"""Generate test PDF and image attachments for testing."""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.join(os.path.dirname(__file__), '..', 'test-tasks')


def make_pdf(path, lines):
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    y = h - 40 * mm
    c.setFont("Helvetica-Bold", 16)
    c.drawString(30 * mm, y, lines[0])
    y -= 15 * mm
    c.setFont("Helvetica", 11)
    for line in lines[1:]:
        if line == '---':
            y -= 5 * mm
            c.line(30 * mm, y, w - 30 * mm, y)
            y -= 5 * mm
        else:
            c.drawString(30 * mm, y, line)
            y -= 7 * mm
    c.save()
    print(f"  PDF: {path}")


def make_receipt_image(path, lines):
    img = Image.new('RGB', (400, 500), 'white')
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
    except Exception:
        font = ImageFont.load_default()
        font_bold = font
    y = 20
    for i, line in enumerate(lines):
        f = font_bold if i == 0 else font
        draw.text((20, y), line, fill='black', font=f)
        y += 28
    # Add a border
    draw.rectangle([5, 5, 395, 495], outline='black', width=2)
    img.save(path)
    print(f"  IMG: {path}")


# === 1-pdf: Supplier invoice ===
d = os.path.join(BASE, 'attachments', '1-pdf')
os.makedirs(d, exist_ok=True)
make_pdf(os.path.join(d, 'faktura-leverandor.pdf'), [
    'FAKTURA',
    '---',
    'Fra: Fjelltopp Utstyr AS',
    'Org.nr: 954321876',
    'Fakturanummer: F-2026-0415',
    'Fakturadato: 2026-03-10',
    'Forfallsdato: 2026-03-24',
    '---',
    'Beskrivelse              Antall    Pris       Sum',
    'Arbeidshansker           20        149 kr     2 980 kr',
    'Vernebriller             15        289 kr     4 335 kr',
    'Hjelm med visir          10        599 kr     5 990 kr',
    '---',
    'Sum eks. mva:                              13 305 kr',
    'MVA 25%:                                    3 326,25 kr',
    'Totalt:                                    16 631,25 kr',
    '---',
    'Kontonummer: 1234.56.78901',
    'Betalingsreferanse: F-2026-0415',
])

with open(os.path.join(d, 'prompt.md'), 'w') as f:
    f.write('Registrer vedlagt leverandørfaktura i Tripletex. Opprett leverandøren hvis den ikke finnes. Sørg for at beløp, leverandørnavn, fakturanummer og dato stemmer.\n')


# === 2-pdfs: Two supplier invoices ===
d = os.path.join(BASE, 'attachments', '2-pdfs')
os.makedirs(d, exist_ok=True)
make_pdf(os.path.join(d, 'faktura-kontorrekvisita.pdf'), [
    'FAKTURA',
    '---',
    'Fra: Kontorservice Bergen AS',
    'Org.nr: 967812345',
    'Fakturanummer: KS-8834',
    'Fakturadato: 2026-03-12',
    'Forfallsdato: 2026-03-26',
    '---',
    'Beskrivelse              Antall    Pris       Sum',
    'Skriverpapir A4          50        89 kr      4 450 kr',
    'Tonerkassett HP          5         890 kr     4 450 kr',
    '---',
    'Sum eks. mva:                               8 900 kr',
    'MVA 25%:                                    2 225 kr',
    'Totalt:                                    11 125 kr',
])
make_pdf(os.path.join(d, 'faktura-renhold.pdf'), [
    'FAKTURA',
    '---',
    'Fra: Rent & Pent AS',
    'Org.nr: 978654321',
    'Fakturanummer: RP-2026-112',
    'Fakturadato: 2026-03-15',
    'Forfallsdato: 2026-04-01',
    '---',
    'Beskrivelse              Antall    Pris       Sum',
    'Renhold kontorlokaler    1         12 500 kr  12 500 kr',
    'Vindusvask               1         3 200 kr    3 200 kr',
    '---',
    'Sum eks. mva:                              15 700 kr',
    'MVA 25%:                                    3 925 kr',
    'Totalt:                                    19 625 kr',
])

with open(os.path.join(d, 'prompt.md'), 'w') as f:
    f.write('Du mottar to vedlagte leverandørfakturaer. Registrer begge i Tripletex. Opprett leverandørene hvis de ikke finnes.\n')


# === 1-image: Receipt photo ===
d = os.path.join(BASE, 'attachments', '1-image')
os.makedirs(d, exist_ok=True)
make_receipt_image(os.path.join(d, 'kvittering-taxi.png'), [
    'KVITTERING',
    '',
    'Bergen Taxi AS',
    'Dato: 2026-03-18',
    'Kl: 14:32',
    '',
    'Tur: Flesland - Sentrum',
    'Beløp: 485 kr',
    'MVA: 58,18 kr',
    '',
    'Betalt med kort',
    'Ref: TX-88421',
])

with open(os.path.join(d, 'prompt.md'), 'w') as f:
    f.write('Vedlagt er et bilde av en taxikvittering. Registrer dette som en utgift på en reiseregning for ansatt Petter Svendsen, reisen heter "Kundemøte Bergen mars 2026".\n')


# === 2-images: Two receipt photos ===
d = os.path.join(BASE, 'attachments', '2-images')
os.makedirs(d, exist_ok=True)
make_receipt_image(os.path.join(d, 'kvittering-restaurant.png'), [
    'KVITTERING',
    '',
    'Bryggen Bistro',
    'Dato: 2026-03-18',
    'Kl: 19:45',
    '',
    'Middag 2 pers',
    'Mat: 890 kr',
    'Drikke: 245 kr',
    'Total: 1 135 kr',
    'MVA: 136,20 kr',
    '',
    'Betalt med kort',
])
make_receipt_image(os.path.join(d, 'kvittering-parkering.png'), [
    'KVITTERING',
    '',
    'Bergen Parkering',
    'Dato: 2026-03-18',
    '',
    'Plass: P3-A22',
    'Tid: 08:00 - 17:30',
    'Beløp: 320 kr',
    'MVA: 38,40 kr',
    '',
    'Automat #14',
])

with open(os.path.join(d, 'prompt.md'), 'w') as f:
    f.write('Vedlagt er to kvitteringsbilder fra en forretningsreise. Registrer begge som utgifter på reiseregningen "Kundemøte Bergen mars 2026" for ansatt Petter Svendsen.\n')


# === mixed: 2 images + 3 pdfs ===
d = os.path.join(BASE, 'attachments', 'mixed')
os.makedirs(d, exist_ok=True)

# Reuse images
make_receipt_image(os.path.join(d, 'kvittering-fly.png'), [
    'E-BILLETT',
    '',
    'Norwegian Air',
    'Oslo - Bergen',
    'Dato: 2026-03-18',
    'Pris: 1 890 kr',
    'MVA: 0 kr (transport)',
    '',
    'Booking: NX8841',
    'Passasjer: Petter Svendsen',
])
make_receipt_image(os.path.join(d, 'kvittering-hotell.png'), [
    'KVITTERING',
    '',
    'Scandic Bergen City',
    'Dato: 18-19 mars 2026',
    '',
    'Rom: Standard enkelt',
    '1 natt: 1 490 kr',
    'MVA: 178,80 kr',
    '',
    'Gjest: Petter Svendsen',
])

make_pdf(os.path.join(d, 'faktura-catering.pdf'), [
    'FAKTURA',
    '---',
    'Fra: Smak Catering AS',
    'Org.nr: 989123456',
    'Fakturanummer: SC-2026-77',
    'Fakturadato: 2026-03-19',
    'Forfallsdato: 2026-04-02',
    '---',
    'Lunsj kundemøte 8 pers   1     4 800 kr    4 800 kr',
    '---',
    'Sum eks. mva:                               4 800 kr',
    'MVA 15%:                                      720 kr',
    'Totalt:                                     5 520 kr',
])
make_pdf(os.path.join(d, 'faktura-trykk.pdf'), [
    'FAKTURA',
    '---',
    'Fra: Grafisk Senter AS',
    'Org.nr: 912876543',
    'Fakturanummer: GS-11042',
    'Fakturadato: 2026-03-17',
    'Forfallsdato: 2026-04-01',
    '---',
    'Presentasjonsmateriell   200     18 kr       3 600 kr',
    'Visittkort               500      3 kr       1 500 kr',
    '---',
    'Sum eks. mva:                               5 100 kr',
    'MVA 25%:                                    1 275 kr',
    'Totalt:                                     6 375 kr',
])
make_pdf(os.path.join(d, 'reiseregning-oppsummering.pdf'), [
    'REISEREGNING - OPPSUMMERING',
    '---',
    'Ansatt: Petter Svendsen',
    'Reise: Kundemøte Bergen mars 2026',
    'Periode: 18-19 mars 2026',
    '---',
    'Utgifter:',
    '  Fly Oslo-Bergen:        1 890 kr',
    '  Hotell 1 natt:          1 490 kr',
    '  Taxi flyplass-sentrum:    485 kr',
    '  Restaurant middag:      1 135 kr',
    '  Parkering:                320 kr',
    '---',
    'Sum reiseutgifter:        5 320 kr',
    '---',
    'Vedlegg: 2 kvitteringsbilder, 2 leverandørfakturaer',
])

with open(os.path.join(d, 'prompt.md'), 'w') as f:
    f.write("""Du mottar en reiseregningsoppsummering (PDF) sammen med tilhørende kvitteringer og fakturaer.

Gjør følgende:
1. Opprett reiseregningen "Kundemøte Bergen mars 2026" for ansatt Petter Svendsen
2. Registrer alle utgifter fra kvitteringene og fakturaene
3. Registrer leverandørfakturaene (Smak Catering AS og Grafisk Senter AS) separat i Tripletex
""")

print("\nAll test attachments generated!")
