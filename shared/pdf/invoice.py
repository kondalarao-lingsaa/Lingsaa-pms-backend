from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet


client_id = 'L000001'
pdf_file = f'{client_id}invoice.pdf'

image_path = 'logo.jpg'

c = canvas.Canvas(pdf_file, pagesize=A4)


cname = 'LINGSAA Trading And Investments Pvt Ltd'
caddress = '# 6-13-8, 2nd Floor, 13/3 Arundalpet, GUNTUR - 522022.'
ccontact = f"\U0001F4DE 0863 - 4001329, \u2709 accounts@lingsaa.com"
website = f"\U0001F310 www.lingsaa.com"
cin = 'CIN: U32309AP2018PTC108162'

client_details = [
    ['Name', 'ntt data private limited software solutions'],
    ['address', '4th floor, marchon 401, suraksha ace, cillage chakala, j.b. nagar, chakala andheri east , mumbai, suburban, maharastra - 400059'],
    ['Phone', '8657930832'],
    ['GSTN', 'clinet name'],
    ['PAN', 'clinet name'],
    # ['Place','clinet name']
]

invoice_details = [
    ['Invoice No', 'LTPLTI-43'],
    ['Invoice Date', '17-Feb-2024'],
    ['Due Date', '23-Feb-2024'],
    ['Payment Recieved', '0']
]


data = [
    ['Sr. No', 'Name', 'HSN', 'Qty', 'Rate',
        'Taxable Value', 'GST (%)', 'GST Amount', 'Total'],

    ['1', 'Product1 \n vvvvvv',
     '1234', '2', '10', '20', '5%', '1', '21'],

]

total_data = [
    ['Total', '1.00', '', '28,653.53', '', '5,157.64', '33,811.17']
]

total_in_words = [['Total In Words'], [
    'Thirty-Three Thousand eight hundred and eleven rupees only']]

bank_details = [['Name', 'UNION BANK OF INDIA'], ['Branch', 'ACHARYA NAGARJUNA UNIVERSITY CAMPUS'], [
    'Acc. Number', '150811010000044'], ['IFSC', 'UBIN0815080']]


t_and_c = [
    'Goods Once Sold cannot be returned or exchanged at any cost.',
    'One year OEM warranty for manufacturing defects from the date of delivery.',
    'The Article are guaranteed by OEM Company only. We are not responsible in any case after sales.',
    'No Warranty for Adapters, Batteries, Cables, Pins SMPS, Spikes, Furniture product, Fancy product and other Accessories and consumables products.',
    'No warranty for Burn, Tag Cuts, Physical Damage, Pin Bends, Cracks, Pen/Pencil marks, missing Tampered warranty stickers.',
    'Intrest at 24% per annum will be charged, if payment is not made on due date.',
    'subject to guntur jurisdiction only.'
]


max_y = 760


def modify_max_y(value):
    global max_y
    max_y = value


def get_center_x_coords(text):
    text_width = c.stringWidth(text)
    page_width, page_height = A4
    return (page_width-text_width)/2


def get_end_x_coords(text):
    text_width = c.stringWidth(text)
    page_width, page_height = A4
    return (page_width-text_width) - 30


def wrap_text(text, width):
    lines = []
    current_line = ''
    for word in text.split():
        if c.stringWidth(current_line + ' ' + word) < width:
            current_line += ' '+word
        else:
            lines.append(current_line.strip())
            current_line = word
    lines.append(current_line.strip())
    return lines


def client_details_table():
    page_width, page_height = A4
    col_width = [40, (page_width/2)-100]
    y = 670
    for row_idx, row_data in enumerate(client_details):
        for d_index, each in enumerate(row_data):
            lines = wrap_text(each, col_width[d_index])
            x = 0 if d_index == 0 else 100
            for line_ind, line in enumerate(lines):
                if line == '':
                    continue
                else:
                    c.drawString(col_width[d_index]-x, y, line)
                    if d_index == 1:
                        y -= 12
        y -= 5
    if max_y > y:
        modify_max_y(y)


def invoice_details_table():
    page_width, page_height = A4
    col_width = [(page_width/2)+20, (page_width/2)+250]
    y = 670
    for row_idx, row_data in enumerate(invoice_details):
        for d_index, each in enumerate(row_data):
            lines = wrap_text(each, col_width[d_index])
            x = 0 if d_index == 0 else 100
            for line_ind, line in enumerate(lines):
                if line == '':
                    continue
                else:
                    c.drawString(col_width[d_index]-x, y, line)
                    if d_index == 1:
                        y -= 12
        y -= 5
    if max_y > y:
        modify_max_y(y)


def create_desc_table():
    page_width, page_height = A4

    table_data = []
    col_widths = [30, 145, 37, 35, 53, 70, 35, 65, 65]

    # Apply styles to each cell in the table
    for row in data:
        table_row = []
        for cell in row:
            cell_para = Paragraph(cell, getSampleStyleSheet()['BodyText'])
            table_row.append(cell_para)
        table_data.append(table_row)

    # Create the table
    table = Table(table_data, colWidths=col_widths)

    style = TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.white),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                        ('WORDWRAP', (0, 0), (-1, -1), 'WORDWRAP'),
                        ('GRID', (0, 0), (-1, -1), 1, colors.black)])

    table.setStyle(style)

    table.wrapOn(c, page_width-60, page_height)

    ht = table._height
    table.drawOn(c, 30, max_y-(ht-25))

    modify_max_y(max_y-(ht))


def total_table():
    page_width, page_height = A4
    table_data = []
    col_widths = [212, 35, 53, 70, 35, 65, 65]

    for row in total_data:
        table_row = []
        for cell in row:
            cell_para = Paragraph(cell, getSampleStyleSheet()['BodyText'])
            table_row.append(cell_para)
        table_data.append(table_row)

    table = Table(table_data, colWidths=col_widths)
    style = TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.white),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                        ('ALIGN', (0, 0), (-1, 0), 'RIGHT'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                        ('WORDWRAP', (0, 0), (-1, -1), 'WORDWRAP'),
                        ('GRID', (0, 0), (-1, -1), 1, colors.black)])

    table.setStyle(style)
    table.wrapOn(c, page_width-60, page_height)

    ht = table._height
    table.drawOn(c, 30, max_y-(ht-25))

    modify_max_y(max_y-ht)


def right_side_section():
    page_width, page_height = A4
    current_y = max_y-6

    left_start = (page_width/2)+40
    c.setFontSize(12)
    c.rect((page_width/2)+30, 50, (page_width/2)-60, max_y-26)
    c.drawString(left_start, current_y, 'Taxable Amount')


def index():
    page_width, page_height = A4
    c.drawImage(image_path, 30, 730, height=90, width=210)

    c.setFont('Helvetica', 16)
    c.drawString(get_end_x_coords(cname), 800, cname)

    c.setFont('Helvetica', 10)
    c.drawString(get_end_x_coords(caddress), 785, caddress)

    c.setFont('Helvetica', 10)
    c.drawString(get_end_x_coords(ccontact), 770, ccontact)

    c.setFont('Helvetica', 10)
    c.drawString(get_end_x_coords(website), 755, website)

    c.line(30, 730, 560, 730)
    c.setFont('Helvetica', 12)
    c.drawString(get_center_x_coords(cin), 711, cin)
    c.line(30, 700, 560, 700)

    # c.rect(30, 30, 530, 665, fill=0)

    client_details_table()
    invoice_details_table()

    c.rect(x=30, y=max_y, width=page_width/2-30, height=700-max_y, fill=0)
    c.rect(x=page_width/2, y=max_y, width=(page_width/2) -
           30, height=700-max_y, fill=0)

    c.line(30, max_y, 560, max_y)

    modify_max_y(max_y-30)

    create_desc_table()
    total_table()
    # draw_total_inwords()
    right_side_section()


index()


c.save()


# can be used in Further

def show_terms_conditions(a):
    y = a
    lc = 0
    for index, each in enumerate(t_and_c):
        lines = wrap_text(f'{index+1}. {each}', 298)
        for line in lines:
            c.setFont('Helvetica', 8)
            c.drawString(35, y-12, line)
            lc += 1
            y -= 12
    c.rect(30, 85, 298, a-(12*lc)+48)
    c.setFontSize(10)
    c.drawString(40, 68, 'Customer Signature & Stamp')
    c.rect(30, 50, 298, 35)


def bankDetails(A):
    page_width, page_height = A4
    table_data = []
    col_widths = [100, 198]

    c.drawString(140, A-15, 'Bank Details')
    c.rect(30, A-20, 298, 20)

    for row in bank_details:
        table_row = []
        for cell in row:
            cell_para = Paragraph(cell, getSampleStyleSheet()['BodyText'])
            table_row.append(cell_para)
        table_data.append(table_row)

    table = Table(table_data, colWidths=col_widths)
    style = TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTRE'),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('WORDWRAP', (0, 0), (-1, -1), 'WORDWRAP'),
                        ('BOX', (0, 0), (-1, -1), 1, colors.black)])

    table.setStyle(style)
    table.wrapOn(c, page_width-60, page_height)

    ht = table._height
    table.drawOn(c, 30, A-ht-20)
    c.drawString(120, A-ht-20-15, 'Terms and Conditions')
    c.rect(30, A-ht-20-20, 298, 20)
    show_terms_conditions(A-ht-20-20)


def draw_total_inwords():
    page_width, page_height = A4
    table_data = []
    col_widths = [((page_width-60)/2)+30]

    for row in total_in_words:
        table_row = []
        for cell in row:
            cell_para = Paragraph(cell, getSampleStyleSheet()['BodyText'])
            table_row.append(cell_para)
        table_data.append(table_row)

    table = Table(table_data, colWidths=col_widths)
    style = TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.white),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                        ('ALIGN', (0, 0), (-1, -1), 'CENTRE'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                        ('WORDWRAP', (0, 0), (-1, -1), 'WORDWRAP'),
                        ('GRID', (0, 0), (-1, -1), 1, colors.black)])

    table.setStyle(style)
    table.wrapOn(c, page_width-60, page_height)

    ht = table._height
    table.drawOn(c, 30, max_y-(ht-25))
    bankDetails(max_y-(ht-25))
